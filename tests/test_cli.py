import unittest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from ui.cli import cli
from core.filter.detector import WordTimestamp


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_cli_help(self):
        result = self.runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Hindi and English Audio Cuss Word Censoring", result.output)

    @patch("ui.cli.get_windows_output_devices")
    def test_devices_command(self, mock_devices):
        mock_devices.return_value = [
            {
                "id": 1,
                "name": "Headphones (Test Device)",
                "channels": 2,
                "default_samplerate": 48000,
                "is_default": True
            }
        ]
        result = self.runner.invoke(cli, ["devices"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Headphones", result.output)
        self.assertIn("Test Device", result.output)
        self.assertIn("Default", result.output)
        self.assertIn("Output", result.output)

    def test_download_help(self):
        result = self.runner.invoke(cli, ["download", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--url", result.output)
        self.assertIn("--quality", result.output)

    @patch("ui.cli.download_song_or_playlist")
    def test_download_command(self, mock_dl):
        mock_dl.return_value = (True, "/path/clean.mp3", "Downloaded OK")
        result = self.runner.invoke(cli, ["download", "--url", "https://example.com/test", "--quality", "flac"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Downloaded OK", result.output)
        mock_dl.assert_called_once()

    @patch("ui.cli.WhisperEngine.transcribe")
    @patch("ui.cli.FFmpegCensor.censor_media")
    def test_file_dry_run_command(self, mock_censor, mock_transcribe):
        mock_transcribe.return_value = [
            WordTimestamp(word="clean", start=0.0, end=0.4),
            WordTimestamp(word="bitch", start=0.5, end=0.9),
        ]

        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.mp3")
            with open(test_file, "w") as f:
                f.write("dummy audio content")

            result = self.runner.invoke(cli, [
                "file",
                "--input", test_file,
                "--dry-run"
            ])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Profanities detected", result.output)
        self.assertIn("bitch", result.output)
        self.assertIn("[DRY-RUN] Mode: media censoring skipped", result.output)
        # Verify censor_media was skipped
        mock_censor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
