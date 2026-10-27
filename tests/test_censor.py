import unittest
import os
import tempfile
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.censor.beep import (
    AudioCensor,
    apply_realtime_censor,
    get_pydub_export_format,
    FORMAT_EXPORT_MAP
)
from core.censor.ffmpeg_censor import FFmpegCensor
from core.filter.detector import CensorInterval
from pydub import AudioSegment
from pydub.generators import Sine


class TestCensorEngine(unittest.TestCase):
    def test_format_mappings(self):
        self.assertEqual(get_pydub_export_format(".m4a"), "ipod")
        self.assertEqual(get_pydub_export_format(".aac"), "adts")
        self.assertEqual(get_pydub_export_format(".mp3"), "mp3")
        self.assertEqual(get_pydub_export_format(".wav"), "wav")
        self.assertEqual(get_pydub_export_format(".flac"), "flac")
        self.assertEqual(get_pydub_export_format(".opus"), "opus")
        self.assertEqual(get_pydub_export_format("file.ogg"), "ogg")
        self.assertEqual(get_pydub_export_format("unknown_ext"), "unknown_ext")

    def test_is_video_extensions(self):
        censor = FFmpegCensor()
        self.assertTrue(censor.is_video("movie.mp4"))
        self.assertTrue(censor.is_video("clip.mkv"))
        self.assertTrue(censor.is_video("video.webm"))
        self.assertTrue(censor.is_video("stream.mov"))
        self.assertTrue(censor.is_video("recording.avi"))

        self.assertFalse(censor.is_video("track.mp3"))
        self.assertFalse(censor.is_video("song.wav"))
        self.assertFalse(censor.is_video("audio.flac"))
        self.assertFalse(censor.is_video("master.m4a"))
        self.assertFalse(censor.is_video("voice.opus"))

    def test_audio_censor_with_beep(self):
        # Generate 2 seconds of pure 440Hz sine wave
        audio = Sine(440).to_audio_segment(duration=2000)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_wav = os.path.join(tmpdir, "test_in.wav")
            output_wav = os.path.join(tmpdir, "test_out.wav")
            audio.export(input_wav, format="wav")

            censor = AudioCensor()
            # Censor interval between 0.5s and 1.0s
            intervals = [CensorInterval(start=0.5, end=1.0, matched_word="test_cuss")]
            res = censor.censor_audio_file(input_wav, output_wav, intervals, mode="beep")

            self.assertTrue(os.path.exists(output_wav))
            censored_audio = AudioSegment.from_file(output_wav)
            # Duration should be preserved (~2000ms)
            self.assertAlmostEqual(len(censored_audio), 2000, delta=50)

    def test_audio_censor_with_mute(self):
        audio = Sine(440).to_audio_segment(duration=1500)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_wav = os.path.join(tmpdir, "test_in.wav")
            output_wav = os.path.join(tmpdir, "test_out.wav")
            audio.export(input_wav, format="wav")

            censor = AudioCensor()
            intervals = [CensorInterval(start=0.3, end=0.8, matched_word="test_cuss")]
            censor.censor_audio_file(input_wav, output_wav, intervals, mode="mute")

            self.assertTrue(os.path.exists(output_wav))
            censored_audio = AudioSegment.from_file(output_wav)
            self.assertAlmostEqual(len(censored_audio), 1500, delta=50)

    def test_audio_censor_no_intervals(self):
        audio = Sine(440).to_audio_segment(duration=1000)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_wav = os.path.join(tmpdir, "test_in.wav")
            output_wav = os.path.join(tmpdir, "test_out.wav")
            audio.export(input_wav, format="wav")

            censor = AudioCensor()
            censor.censor_audio_file(input_wav, output_wav, [], mode="beep")
            self.assertTrue(os.path.exists(output_wav))

    def test_apply_realtime_censor_beep_and_mute(self):
        # 16000 samples (1 second at 16kHz)
        buffer = np.ones(16000, dtype=np.float32) * 0.5
        mask = np.zeros(16000, dtype=bool)
        # Mark samples 4000 to 8000 as profane
        mask[4000:8000] = True

        # Test mute mode
        muted = apply_realtime_censor(buffer, mask, sample_rate=16000, mode="mute")
        self.assertEqual(muted[0], 0.5)
        self.assertEqual(muted[4500], 0.0)
        self.assertEqual(muted[10000], 0.5)

        # Test beep mode
        beeped = apply_realtime_censor(buffer, mask, sample_rate=16000, mode="beep", freq=1000.0)
        self.assertEqual(beeped[0], 0.5)
        # In beep region, values should not be 0.5 (they should be sine values)
        self.assertNotEqual(beeped[4500], 0.5)
        self.assertEqual(beeped[10000], 0.5)

    @patch("core.censor.ffmpeg_censor.check_binary", return_value=True)
    @patch("subprocess.run")
    def test_ffmpeg_censor_video_stream_copy_when_clean(self, mock_subproc, mock_bin):
        mock_subproc.return_value = MagicMock(returncode=0)
        censor = FFmpegCensor()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            dummy_in = f.name

        try:
            out_file = dummy_in.replace(".mp4", "_out.mp4")
            censor.censor_media(dummy_in, out_file, intervals=[])
            mock_subproc.assert_called_once()
            cmd = mock_subproc.call_args[0][0]
            self.assertIn("-c", cmd)
            self.assertIn("copy", cmd)
        finally:
            if os.path.exists(dummy_in):
                os.remove(dummy_in)


if __name__ == "__main__":
    unittest.main()
