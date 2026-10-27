"""
Playlist Mode for batch censoring downloaded playlists, folders, and media files.
"""

import os
import json
import subprocess
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from core.filter.detector import ProfanityDetector, CensorInterval
from core.asr.whisper_engine import WhisperEngine
from core.censor.ffmpeg_censor import FFmpegCensor
from core.rea.format_inspector import REAFormatInspector, PlaylistManifest, TrackInfo
from core.logger import get_logger

logger = get_logger("modes.playlist")
console = Console(legacy_windows=False)


class PlaylistCensorRunner:
    def __init__(
        self,
        whisper_model: str = "base",
        mode: str = "beep",  # "beep" or "mute"
        lang: str = "all",   # "all", "en", "hi"
        output_dir: Optional[str] = None,
        padding: float = 0.20,
        pre_padding: float = 0.25,
        post_padding: float = 0.18,
        time_offset: float = 0.0,
        beep_freq: int = 1000,
        intro_offset: Optional[float] = None,
        dry_run: bool = False,
        cancel_event: Optional[threading.Event] = None
    ):
        self.whisper_model = whisper_model
        self.mode = mode
        self.lang = lang
        self.output_dir = output_dir
        self.padding = padding
        self.pre_padding = pre_padding
        self.post_padding = post_padding
        self.time_offset = time_offset
        self.intro_offset = intro_offset
        self.dry_run = dry_run
        self.cancel_event = cancel_event

        self.inspector = REAFormatInspector()
        self.detector = ProfanityDetector(
            padding=padding,
            pre_padding=pre_padding,
            post_padding=post_padding,
            time_offset=time_offset
        )
        self.asr = WhisperEngine(model_name=whisper_model)
        self.censor = FFmpegCensor()

    def process_playlist(self, target_input: str) -> Dict[str, Any]:
        """
        Process a playlist folder, M3U file, or remote URL.
        """
        console.print(f"[bold cyan][SCAN] Inspecting input target:[/bold cyan] {target_input}")
        manifest = self.inspector.inspect_target(target_input)

        console.print(
            f"[green][OK] Target format identified:[/green] [bold]{manifest.format_type}[/bold] "
            f"({len(manifest.tracks)} tracks found)"
        )

        out_dir = Path(self.output_dir or "./censored_output")
        out_dir.mkdir(parents=True, exist_ok=True)

        report = {
            "playlist_name": manifest.name,
            "format": manifest.format_type,
            "total_tracks": len(manifest.tracks),
            "processed_tracks": [],
            "summary": {"total_cuss_words_censored": 0, "clean_tracks": 0, "censored_tracks": 0}
        }

        with Progress(
            SpinnerColumn(spinner_name="line"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            overall_task = progress.add_task("[yellow]Processing tracks...", total=len(manifest.tracks))

            for track in manifest.tracks:
                if self.cancel_event and self.cancel_event.is_set():
                    console.print("[yellow]Operation cancelled by user.[/yellow]")
                    report["summary"]["cancelled"] = True
                    break

                progress.update(overall_task, description=f"[cyan]Processing: {track.title[:30]}")
                track_result = self._process_single_track(track, out_dir)
                report["processed_tracks"].append(track_result)

                if track_result["cuss_words_count"] > 0:
                    report["summary"]["censored_tracks"] += 1
                    report["summary"]["total_cuss_words_censored"] += track_result["cuss_words_count"]
                else:
                    report["summary"]["clean_tracks"] += 1

                progress.advance(overall_task)

        # Save report
        report_file = out_dir / "censored_report.json"
        with open(report_file, "w", encoding="utf-8") as rf:
            json.dump(report, rf, indent=2, ensure_ascii=False)

        console.print(f"\n[bold green][DONE] Batch Censoring Complete![/bold green]")
        console.print(f"Total Tracks Processed: {report['total_tracks']}")
        console.print(f"Clean Tracks: {report['summary']['clean_tracks']}")
        console.print(f"Censored Tracks: {report['summary']['censored_tracks']}")
        console.print(f"Total Cuss Words Censored: {report['summary']['total_cuss_words_censored']}")
        console.print(f"Output Directory: [underline]{out_dir.resolve()}[/underline]")
        console.print(f"Detailed Report: [underline]{report_file.resolve()}[/underline]\n")

        return report

    def _process_single_track(self, track: TrackInfo, out_dir: Path) -> Dict[str, Any]:
        track_path = track.url_or_path

        # If it's a remote URL, download audio using yt-dlp first
        if track_path.startswith(("http://", "https://")):
            downloaded = self._download_track(track_path, out_dir)
            if not downloaded:
                return {
                    "title": track.title,
                    "status": "failed_download",
                    "cuss_words_count": 0,
                    "output_file": None
                }
            track_path = downloaded

        in_p = Path(track_path)
        out_filename = f"{in_p.stem}_censored{in_p.suffix}"
        out_filepath = str((out_dir / out_filename).resolve())

        try:
            # 1. Transcribe with Whisper
            words = self.asr.transcribe(track_path, language=self.lang, intro_offset=self.intro_offset)

            # 2. Detect profanities
            intervals = self.detector.detect_in_words(words, lang=self.lang)

            # 3. Apply censorship (unless in dry-run preview mode)
            if not self.dry_run:
                self.censor.censor_media(
                    input_path=track_path,
                    output_path=out_filepath,
                    intervals=intervals,
                    mode=self.mode
                )
                status = "success"
                final_out = out_filepath
            else:
                status = "dry_run"
                final_out = None

            flagged_words = [i.matched_word for i in intervals]

            return {
                "title": track.title,
                "input_file": track_path,
                "output_file": final_out,
                "status": status,
                "cuss_words_count": len(intervals),
                "flagged_words": flagged_words,
                "intervals": [{"start": i.start, "end": i.end, "word": i.matched_word} for i in intervals]
            }

        except Exception as e:
            return {
                "title": track.title,
                "input_file": track_path,
                "output_file": None,
                "status": f"error: {str(e)}",
                "cuss_words_count": 0,
                "flagged_words": [],
                "intervals": []
            }

    def _download_track(self, url: str, target_dir: Path) -> Optional[str]:
        cmd = [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "-o", str(target_dir / "%(title)s.%(ext)s"),
            url
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                # Find newest file created in target_dir
                files = list(target_dir.glob("*.mp3"))
                if files:
                    return str(max(files, key=os.path.getctime))
        except Exception:
            pass
        return None
