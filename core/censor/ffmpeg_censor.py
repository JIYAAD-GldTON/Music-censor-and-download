"""
FFmpeg-based audio/video censor module.
Handles media files (video & audio) preserving video stream via '-c:v copy'.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import List
from core.filter.detector import CensorInterval
from core.censor.beep import AudioCensor
from core.system_checks import check_binary
from core.logger import get_logger

logger = get_logger("censor.ffmpeg")


class FFmpegCensor:
    def __init__(self, beep_wav_path: str = None):
        self.beep_censor = AudioCensor(beep_wav_path=beep_wav_path)

    def is_video(self, file_path: str) -> bool:
        """Check if file has video stream extension."""
        video_exts = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".ts"}
        return Path(file_path).suffix.lower() in video_exts

    def censor_media(
        self,
        input_path: str,
        output_path: str,
        intervals: List[CensorInterval],
        mode: str = "beep"
    ) -> str:
        """
        Censor audio or video media. If video, video stream is copied without re-encoding.
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")

        # If it's a pure audio file, AudioCensor is direct and fast
        if not self.is_video(input_path):
            return self.beep_censor.censor_audio_file(
                input_path, output_path, intervals, mode=mode
            )

        if not check_binary("ffmpeg"):
            raise RuntimeError(
                "FFmpeg executable not found in system PATH. "
                "Please install FFmpeg to process and remux video files."
            )

        if not intervals:
            # No censorship needed; copy streams
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-c", "copy", output_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                logger.error("FFmpeg stream copy failed: %s", res.stderr)
                raise RuntimeError(f"FFmpeg stream copy failed: {res.stderr[:200]}")
            return output_path

        # For video: extract audio track to temporary WAV, censor it with AudioCensor, then remux
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_audio_in = os.path.join(tmpdir, "extracted_audio.wav")
            temp_audio_clean = os.path.join(tmpdir, "censored_audio.wav")

            # 1. Extract audio stream
            cmd_extract = [
                "ffmpeg", "-y", "-i", input_path,
                "-vn", "-acodec", "pcm_s16le", temp_audio_in
            ]
            res_ext = subprocess.run(cmd_extract, capture_output=True, text=True)
            if res_ext.returncode != 0:
                logger.error("FFmpeg audio extraction failed: %s", res_ext.stderr)
                raise RuntimeError(f"FFmpeg audio extraction failed: {res_ext.stderr[:200]}")

            # 2. Censor audio track
            self.beep_censor.censor_audio_file(
                temp_audio_in, temp_audio_clean, intervals, mode=mode
            )

            # 3. Remux: copy original video stream and replace audio stream
            cmd_remux = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-i", temp_audio_clean,
                "-map_metadata", "0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                output_path
            ]
            res_mux = subprocess.run(cmd_remux, capture_output=True, text=True)
            if res_mux.returncode != 0:
                logger.error("FFmpeg remuxing failed: %s", res_mux.stderr)
                raise RuntimeError(f"FFmpeg remuxing failed: {res_mux.stderr[:200]}")

        logger.info("Successfully censored video: %s -> %s", input_path, output_path)
        return output_path
