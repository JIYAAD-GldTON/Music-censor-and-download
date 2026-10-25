import unittest
from unittest.mock import patch
from core.devices import get_windows_output_devices


class TestDevices(unittest.TestCase):
    def test_get_windows_output_devices_structure(self):
        devices = get_windows_output_devices()
        # Even if run on systems with no soundcards, it should return a list
        self.assertIsInstance(devices, list)
        for d in devices:
            self.assertIn("id", d)
            self.assertIn("name", d)
            self.assertIn("channels", d)
            self.assertIn("default_samplerate", d)
            self.assertIn("is_default", d)
            self.assertGreater(d["channels"], 0)
            # Ensure internal driver paths or mapper dummies are filtered out
            self.assertNotIn("@system32", d["name"].lower())
            self.assertNotIn("bthhfenum", d["name"].lower())
            self.assertNotIn("microsoft sound mapper", d["name"].lower())

    @patch("sounddevice.query_devices")
    @patch("sounddevice.query_hostapis")
    def test_device_filtering_and_default_sorting(self, mock_apis, mock_devs):
        mock_apis.return_value = [
            {"name": "MME", "default_output_device": 0},
            {"name": "Windows DirectSound", "default_output_device": 1},
            {"name": "Windows WASAPI", "default_output_device": 3},
        ]
        mock_devs.return_value = [
            {"name": "Microsoft Sound Mapper - Output", "max_output_channels": 2, "hostapi": 0, "default_samplerate": 44100},
            {"name": "Primary Sound Driver", "max_output_channels": 2, "hostapi": 1, "default_samplerate": 44100},
            {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 2, "default_samplerate": 48000},
            {"name": "Headphones (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 2, "default_samplerate": 48000},
            {"name": "Headphones (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 2, "default_samplerate": 48000},  # duplicate
            {"name": r"@System32\drivers\bthhfenum.sys,#2;Bluetooth Hands-Free (JBL)", "max_output_channels": 1, "hostapi": 2, "default_samplerate": 16000},
            {"name": "Microphone (Realtek)", "max_output_channels": 0, "hostapi": 2, "default_samplerate": 48000},  # input only
        ]

        with patch("sounddevice.default") as mock_default:
            mock_default.device = [0, 0]
            devs = get_windows_output_devices()

        names = [d["name"] for d in devs]
        # Mapper and input-only should be filtered
        self.assertNotIn("Microsoft Sound Mapper - Output", names)
        self.assertNotIn("Primary Sound Driver", names)
        self.assertNotIn("Microphone (Realtek)", names)
        # Driver path should be cleaned to friendly name
        self.assertIn("JBL", names)
        # Duplicate should be deduplicated
        self.assertEqual(names.count("Headphones (Realtek(R) Audio)"), 1)
        # WASAPI default output (index 3: Headphones) should have is_default True and be first
        self.assertTrue(devs[0]["is_default"])
        self.assertEqual(devs[0]["name"], "Headphones (Realtek(R) Audio)")


if __name__ == "__main__":
    unittest.main()
