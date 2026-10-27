"""
CLI Module for Cuss-Censor using Click and Rich.
Provides subcommands: gui, file, playlist, download, rea-probe, and devices.
"""

import click
import sounddevice as sd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from modes.playlist_mode import PlaylistCensorRunner
from core.censor.ffmpeg_censor import FFmpegCensor
from core.asr.whisper_engine import WhisperEngine
from core.filter.detector import ProfanityDetector
from core.rea.protocol_probe import REAProtocolProbe
from core.devices import get_windows_output_devices
from ui.gui import launch_gui
from downloader import QUALITY_PROFILES, download_song_or_playlist, download_high_quality

console = Console(legacy_windows=False)


@click.group()
def cli():
    """Hindi and English Audio Cuss Word Censoring Application (with REA)."""
    pass


@cli.command(name="gui")
def run_gui():
    """Launch the modern desktop GUI (Lite Mode) with all features."""
    launch_gui()


@cli.command(name="devices")
def list_devices():
    """List clean Windows sound output playback devices (matching Windows Sound Settings)."""
    devices = get_windows_output_devices()
    table = Table(title="🎧 Windows Audio Output Devices (Sound Playback)", show_lines=True)
    table.add_column("Index / ID", style="cyan", justify="right")
    table.add_column("Playback Device Name", style="bold white")
    table.add_column("Channels", justify="center")
    table.add_column("Default Sample Rate", justify="center")
    table.add_column("Windows Status", justify="center")

    if not devices:
        console.print("[yellow]No audio output devices found.[/yellow]")
        return

    for d in devices:
        status = "[bold green]★ Default Output[/bold green]" if d["is_default"] else "[dim]Ready[/dim]"
        ch_str = f"{d['channels']} (Stereo)" if d["channels"] == 2 else f"{d['channels']} ch"
        table.add_row(
            str(d["id"]),
            d["name"],
            ch_str,
            f"{d['default_samplerate']} Hz",
            status
        )
    console.print(table)


@cli.command(name="download")
@click.option("--url", "-u", required=True, help="Single track or playlist URL (Spotify, YouTube, JioSaavn, etc.)")
@click.option(
    "--quality", "-q",
    type=click.Choice(["flac", "mp3_320", "aac_256", "opus", "wav", "mp3_192"], case_sensitive=False),
    default="mp3_320",
    help="Explicit audio quality: flac (lossless), mp3_320 (320k), aac_256 (256k), opus, wav."
)
@click.option("--output-dir", "-o", default="./downloads", help="Directory to save downloaded tracks.")
@click.option("--single/--playlist", default=True, help="Download as single track or full playlist.")
def run_download(url, quality, output_dir, single):
    """Download single songs or playlists with explicit audio quality (FLAC / 320k MP3) & metadata."""
    console.print(f"[bold cyan]📥 Fetching:[/bold cyan] {url}")
    console.print(f"[bold green]Selected Quality:[/bold green] {quality.upper()} -> Destination: {output_dir}")
    success, target_path, msg = download_song_or_playlist(
        url, output_dir=output_dir, quality=quality, is_single=single
    )
    if success:
        console.print(f"[bold green]✔ {msg}[/bold green]")
        if target_path:
            console.print(f"Path: [underline]{target_path}[/underline]")
    else:
        console.print(f"[bold red]❌ {msg}[/bold red]")


@cli.command(name="playlist")
@click.option("--input", "-i", "target_input", required=True, help="Folder path, M3U8 file, or streaming playlist URL.")
@click.option("--mode", "-m", type=click.Choice(["beep", "mute"], case_sensitive=False), default="beep", help="Censoring effect: beep tone or mute.")
@click.option("--lang", "-l", type=click.Choice(["all", "hi", "en"], case_sensitive=False), default="all", help="Target language filter.")
@click.option("--output-dir", "-o", default="./censored_output", help="Directory to save censored tracks.")
@click.option("--model", default="base", help="Whisper model size (tiny, base, small, medium).")
@click.option("--offset", "-off", default=0.0, type=float, help="Timing offset in seconds (e.g. -0.5 to play censors 0.5s earlier).")
@click.option("--intro-offset", "-intro", default=None, type=float, help="Manual intro vocal start offset in seconds (skips instrumental intro noise).")
@click.option("--dry-run", is_flag=True, default=False, help="Preview detected profanities without generating output files.")
def run_playlist(target_input, mode, lang, output_dir, model, offset, intro_offset, dry_run):
    """Batch-censor downloaded playlists, directories of songs/videos, or streaming URLs."""
    if dry_run:
        console.print("[yellow][DRY-RUN] Mode active: files will be scanned but not modified.[/yellow]")
    runner = PlaylistCensorRunner(
        whisper_model=model,
        mode=mode,
        lang=lang,
        output_dir=output_dir,
        time_offset=offset,
        intro_offset=intro_offset,
        dry_run=dry_run
    )
    runner.process_playlist(target_input)


@cli.command(name="file")
@click.option("--input", "-i", "input_file", required=True, help="Path to single audio or video file.")
@click.option("--output", "-o", "output_file", default=None, help="Path for cleaned output file.")
@click.option("--song", "-s", default=None, help="Song title (e.g. 'Khatta Flow').")
@click.option("--artist", "-a", default=None, help="Artist name (e.g. 'Seedhe Maut').")
@click.option("--lrc", default=None, help="Path to custom .lrc synced lyrics file.")
@click.option("--query", "-q", default=None, help="Custom search query hint for online synced lyrics.")
@click.option("--mode", "-m", type=click.Choice(["beep", "mute"], case_sensitive=False), default="beep", help="Censoring effect.")
@click.option("--lang", "-l", type=click.Choice(["all", "hi", "en"], case_sensitive=False), default="all", help="Target language filter.")
@click.option("--model", default="base", help="Whisper model size.")
@click.option("--offset", "-off", default=0.0, type=float, help="Timing offset in seconds (e.g. -0.5 to play censors 0.5s earlier).")
@click.option("--intro-offset", "-intro", default=None, type=float, help="Manual intro vocal start offset in seconds (skips instrumental intro noise).")
@click.option("--desc", default=None, help="Path to YouTube .description file or YouTube URL to extract lyrics from.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview detected profanities without modifying or saving files.")
def run_single_file(input_file, output_file, song, artist, lrc, query, mode, lang, model, offset, intro_offset, desc, dry_run):
    """Censor a single audio or video file."""
    from pathlib import Path
    in_p = Path(input_file)
    if not output_file:
        output_file = str(in_p.parent / f"{in_p.stem}_clean{in_p.suffix}")

    custom_lrc_text = None
    if lrc and Path(lrc).exists():
        with open(lrc, "r", encoding="utf-8", errors="ignore") as lf:
            custom_lrc_text = lf.read()

    console.print(f"[bold cyan]Transcribing file:[/bold cyan] {input_file} (model: {model})")
    asr = WhisperEngine(model_name=model)
    words = asr.transcribe(
        input_file,
        language=lang,
        custom_query=query,
        custom_lrc_text=custom_lrc_text,
        song_title=song,
        artist_name=artist,
        youtube_desc=desc,
        intro_offset=intro_offset
    )

    detector = ProfanityDetector(pre_padding=0.25, post_padding=0.18, time_offset=offset)
    intervals = detector.detect_in_words(words, lang=lang)

    # Display found lyrics in the meantime!
    if asr.last_timed_lines:
        console.print(Panel(
            f"[bold green]✔ Synchronized Lyrics Found ({len(asr.last_timed_lines)} lines | {len(words)} words)[/bold green]\n"
            f"[dim]Source: {asr.last_source} | Query: {asr.lyrics_provider.last_matched_query}[/dim]",
            title="📜 Lyrics Preview",
            expand=False
        ))
        annotated_lines = asr.get_annotated_lyrics_lines(profanity_detector=detector)
        for ts, line, has_cuss in annotated_lines:
            if has_cuss:
                console.print(f"  [bold red]●[/bold red] [bold yellow]{line}[/bold yellow]")
            else:
                console.print(f"    [dim]{line}[/dim]")
        console.print("")

    console.print(f"[green]Profanities detected:[/green] {len(intervals)}")
    for i in intervals:
        console.print(f"  • [{i.start:.2f}s - {i.end:.2f}s]: [bold red]{i.matched_word}[/bold red]")

    if dry_run:
        console.print("\n[bold yellow][DRY-RUN] Mode: media censoring skipped. No files written.[/bold yellow]")
        return

    censor = FFmpegCensor()
    censor.censor_media(input_file, output_file, intervals, mode=mode)
    console.print(f"[bold green]✔ Output saved successfully to:[/bold green] {output_file}")


@cli.command(name="rea-probe")
@click.option("--target", "-t", required=True, help="URL, binary, or application directory to reverse engineer.")
def run_rea_probe(target):
    """Reverse-engineer an unknown streaming protocol, playlist schema, or desktop media app using REA."""
    console.print(Panel(f"[bold yellow]Reverse Engineering Target:[/bold yellow] {target}\n[dim]Invoking REA (Reverse Engineer Anything)...[/dim]"))
    probe = REAProtocolProbe()

    if target.startswith(("http://", "https://", "rtsp://", "rtmp://")):
        result = probe.probe_stream_protocol(target)
    else:
        result = probe.inspect_binary_or_app(target)

    import json
    console.print_json(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    cli()
