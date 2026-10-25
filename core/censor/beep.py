"""
Beep and Mute audio segment replacement module using pydub and numpy.
"""

import os
from pathlib import Path
from typing import List
import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine
from core.filter.detector import CensorInterval


def copy_media_tags(src_path: str, dst_path: str) -> None:
    """Copy audio metadata and ID3 tags from source to destination."""
    if not os.path.exists(src_path) or not os.path.exists(dst_path):
        return
    try:
        import mutagen
        src = mutagen.File(src_path)
        dst = mutagen.File(dst_path)
        if src and dst and hasattr(src, 'tags') and src.tags:
            if hasattr(dst, 'tags') and dst.tags is not None:
                for k, v in src.tags.items():
                    try:
                        dst.tags[k] = v
                    except Exception:
                        pass
                dst.save()
            elif hasattr(dst, 'add_tags'):
                try:
                    dst.add_tags()
                    for k, v in src.tags.items():
                        try:
                            dst.tags[k] = v
                        except Exception:
                            pass
                    dst.save()
                except Exception:
                    pass
    except Exception:
        pass


class AudioCensor:
    def __init__(self, beep_wav_path: str = None, beep_freq: int = 1000):
        self.beep_freq = beep_freq
        if beep_wav_path and os.path.exists(beep_wav_path):
            self.beep_segment = AudioSegment.from_file(beep_wav_path)
        else:
            # Fallback to generating a 1kHz sine wave segment
            self.beep_segment = Sine(beep_freq).to_audio_segment(duration=1000)

    def censor_audio_file(
        self,
        input_path: str,
        output_path: str,
        intervals: List[CensorInterval],
        mode: str = "beep"  # "beep" or "mute"
    ) -> str:
        """
        Censor an audio file by replacing intervals with beeps or silence.
        Saves output to output_path.
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")

        audio = AudioSegment.from_file(input_path)
        total_len_ms = len(audio)

        if not intervals:
            # No profanity detected, just export copy
            audio.export(output_path)
            copy_media_tags(input_path, output_path)
            return output_path

        # Sort intervals
        sorted_intervals = sorted(intervals, key=lambda x: x.start)

        # Build censored audio piece by piece
        censored = AudioSegment.empty()
        last_end_ms = 0

        for interval in sorted_intervals:
            start_ms = max(0, int(interval.start * 1000))
            end_ms = min(total_len_ms, int(interval.end * 1000))

            if start_ms > last_end_ms:
                censored += audio[last_end_ms:start_ms]

            duration_ms = max(1, end_ms - start_ms)

            if mode == "mute":
                replacement = AudioSegment.silent(duration=duration_ms)
            else:  # beep
                # Repeat or slice beep segment to match duration
                if len(self.beep_segment) < duration_ms:
                    repeats = (duration_ms // len(self.beep_segment)) + 1
                    full_beep = self.beep_segment * repeats
                else:
                    full_beep = self.beep_segment
                replacement = full_beep[:duration_ms]
                # Match volume/channels
                replacement = replacement.set_channels(audio.channels).set_frame_rate(audio.frame_rate)
                # Attenuate beep slightly so it doesn't clip
                replacement = replacement - 6

            censored += replacement
            last_end_ms = end_ms

        if last_end_ms < total_len_ms:
            censored += audio[last_end_ms:]

        out_fmt = Path(output_path).suffix.lstrip(".").lower() or "mp3"
        censored.export(output_path, format=out_fmt)
        copy_media_tags(input_path, output_path)
        return output_path


def apply_realtime_censor(
    audio_buffer: np.ndarray,
    censor_mask: np.ndarray,
    sample_rate: int = 16000,
    mode: str = "beep",
    freq: float = 1000.0
) -> np.ndarray:
    """
    Apply real-time censor to numpy audio buffer.
    censor_mask is a boolean array of same length as audio_buffer (True = censor).
    """
    output = np.copy(audio_buffer)
    if not np.any(censor_mask):
        return output

    if mode == "mute":
        output[censor_mask] = 0.0
    else:  # beep
        num_samples = len(audio_buffer)
        t = np.arange(num_samples) / sample_rate
        beep_signal = (0.3 * np.sin(2 * np.pi * freq * t)).astype(output.dtype)
        output[censor_mask] = beep_signal[censor_mask]

    return output
