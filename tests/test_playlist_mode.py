import unittest
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

from modes.playlist_mode import PlaylistCensorRunner
from core.rea.format_inspector import PlaylistManifest, TrackInfo
from core.filter.detector import WordTimestamp


class TestPlaylistMode(unittest.TestCase):
    def test_runner_initialization_defaults(self):
        runner = PlaylistCensorRunner(
            whisper_model="tiny",
            mode="mute",
            lang="en",
            dry_run=True
        )
        self.assertEqual(runner.whisper_model, "tiny")
        self.assertEqual(runner.mode, "mute")
        self.assertEqual(runner.lang, "en")
        self.assertTrue(runner.dry_run)

    @patch("modes.playlist_mode.WhisperEngine.transcribe")
    @patch("modes.playlist_mode.FFmpegCensor.censor_media")
    def test_process_playlist_dry_run(self, mock_censor, mock_transcribe):
        mock_transcribe.return_value = [
            WordTimestamp(word="hello", start=0.0, end=0.5),
            WordTimestamp(word="fuck", start=1.0, end=1.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a dummy audio file
            dummy_file = os.path.join(tmpdir, "track1.mp3")
            Path(dummy_file).touch()

            runner = PlaylistCensorRunner(
                output_dir=tmpdir,
                dry_run=True
            )

            mock_manifest = PlaylistManifest(
                name="Test Album",
                tracks=[TrackInfo(title="track1", url_or_path=dummy_file)],
                format_type="local_dir"
            )

            with patch.object(runner.inspector, "inspect_target", return_value=mock_manifest):
                report = runner.process_playlist(tmpdir)

            self.assertEqual(report["total_tracks"], 1)
            self.assertEqual(report["summary"]["censored_tracks"], 1)
            self.assertEqual(report["summary"]["total_cuss_words_censored"], 1)
            # In dry-run mode, censor_media should NOT be invoked
            mock_censor.assert_not_called()
            self.assertEqual(report["processed_tracks"][0]["status"], "dry_run")

    @patch("modes.playlist_mode.WhisperEngine.transcribe")
    def test_process_playlist_cancellation(self, mock_transcribe):
        mock_transcribe.return_value = []
        cancel_ev = threading.Event()

        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_file1 = os.path.join(tmpdir, "track1.mp3")
            dummy_file2 = os.path.join(tmpdir, "track2.mp3")
            Path(dummy_file1).touch()
            Path(dummy_file2).touch()

            runner = PlaylistCensorRunner(
                output_dir=tmpdir,
                cancel_event=cancel_ev,
                dry_run=True
            )

            # Set cancellation before second track
            cancel_ev.set()

            mock_manifest = PlaylistManifest(
                name="Cancelled Album",
                tracks=[
                    TrackInfo(title="track1", url_or_path=dummy_file1),
                    TrackInfo(title="track2", url_or_path=dummy_file2),
                ],
                format_type="local_dir"
            )

            with patch.object(runner.inspector, "inspect_target", return_value=mock_manifest):
                report = runner.process_playlist(tmpdir)

            self.assertTrue(report["summary"].get("cancelled", False))
            self.assertEqual(len(report["processed_tracks"]), 0)


if __name__ == "__main__":
    unittest.main()
