import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import threading

from downloader import (
    QUALITY_PROFILES,
    get_profile,
    download_song_or_playlist,
    download_high_quality
)


class TestDownloader(unittest.TestCase):
    def test_get_profile_exact_match(self):
        flac_key = "FLAC (Lossless Studio Quality, ~1411 kbps)"
        profile = get_profile(flac_key)
        self.assertEqual(profile["ext"], "flac")
        self.assertEqual(profile["ytdl_format"], "flac")

    def test_get_profile_by_extension(self):
        profile = get_profile("opus")
        self.assertEqual(profile["ext"], "opus")
        self.assertEqual(profile["ytdl_format"], "opus")

    def test_get_profile_by_partial_string(self):
        profile = get_profile("320")
        self.assertEqual(profile["ext"], "mp3")
        self.assertEqual(profile["ytdl_quality"], "320k")

    def test_get_profile_fallback(self):
        profile = get_profile("non_existent_quality_preset_12345")
        self.assertEqual(profile["ext"], "mp3")
        self.assertEqual(profile["ytdl_quality"], "320k")

    @patch("downloader._run_process_with_progress")
    def test_download_spotify_command_construction(self, mock_run):
        mock_run.return_value = (0, "Done", "")
        spotify_url = "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"

        with patch("pathlib.Path.glob", return_value=[]):
            success, target, msg = download_song_or_playlist(
                spotify_url,
                output_dir="./test_downloads",
                quality="mp3_320",
                is_single=True
            )

        self.assertTrue(success)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("-m", cmd)
        self.assertIn("spotdl", cmd)
        self.assertIn(spotify_url, cmd)
        self.assertIn("--format", cmd)
        self.assertIn("mp3", cmd)

    @patch("downloader._run_process_with_progress")
    def test_download_youtube_command_construction(self, mock_run):
        mock_run.return_value = (0, "Done", "")
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        with patch("pathlib.Path.glob", return_value=[]):
            success, target, msg = download_song_or_playlist(
                yt_url,
                output_dir="./test_downloads",
                quality="flac",
                is_single=True
            )

        self.assertTrue(success)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "yt-dlp")
        self.assertIn("--audio-format", cmd)
        self.assertIn("flac", cmd)
        self.assertIn("--no-playlist", cmd)
        self.assertIn(yt_url, cmd)

    @patch("downloader._run_process_with_progress")
    def test_download_error_handling(self, mock_run):
        mock_run.return_value = (1, "", "ERROR: Video unavailable")
        yt_url = "https://www.youtube.com/watch?v=broken"

        success, target, msg = download_song_or_playlist(
            yt_url,
            output_dir="./test_downloads"
        )
        self.assertFalse(success)
        self.assertIsNone(target)
        self.assertIn("Video unavailable", msg)

    @patch("downloader._run_process_with_progress")
    def test_download_cancellation(self, mock_run):
        cancel_ev = threading.Event()
        cancel_ev.set()
        mock_run.return_value = (-1, "", "Operation cancelled by user.")

        success, target, msg = download_song_or_playlist(
            "https://www.youtube.com/watch?v=test",
            cancel_event=cancel_ev
        )
        self.assertFalse(success)
        self.assertIsNone(target)
        self.assertIn("cancelled", msg.lower())

    @patch("downloader.download_song_or_playlist")
    def test_download_high_quality_alias(self, mock_dl):
        mock_dl.return_value = (True, "/path/to/song.flac", "Success")
        result = download_high_quality("https://example.com/audio")
        self.assertTrue(result)
        mock_dl.assert_called_once_with(
            "https://example.com/audio",
            output_dir="./downloads",
            quality="flac"
        )


if __name__ == "__main__":
    unittest.main()
