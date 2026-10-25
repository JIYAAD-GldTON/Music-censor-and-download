import unittest
import os
import tempfile
from pathlib import Path
from core.asr.lyrics_provider import (
    extract_lyrics_from_youtube_description,
    parse_timestamp_str,
    OnlineLyricsProvider,
    parse_lrc_content
)
from core.filter.detector import ProfanityDetector


class TestYouTubeDescriptionLyrics(unittest.TestCase):
    def test_parse_timestamp_str(self):
        self.assertEqual(parse_timestamp_str("0:15 hello"), (15.0, "hello"))
        self.assertEqual(parse_timestamp_str("00:25.50 - world"), (25.5, "world"))
        self.assertEqual(parse_timestamp_str("[01:10] test"), (70.0, "test"))
        self.assertEqual(parse_timestamp_str("(0:05) intro"), (5.0, "intro"))
        self.assertEqual(parse_timestamp_str("1:02:15 long track"), (3735.0, "long track"))
        self.assertIsNone(parse_timestamp_str("Just a normal text line"))

    def test_direct_timestamped_lines(self):
        desc = """
Track: Nanchaku
0:15 I needed some shit with some bop in it
0:18 I flew past the whip with that blunt in my mouth
0:21 My ***** got good *****, fly her 'cross the country
0:27 I'm still with the shits, I'm a hot nigga
0:31 What's your name? Get the **** out the spot, nigga
Stream on Spotify
"""
        timed = extract_lyrics_from_youtube_description(desc)
        self.assertEqual(len(timed), 5)
        self.assertEqual(timed[0][0], 15.0)
        self.assertIn("shit", timed[0][1])
        self.assertEqual(timed[2][0], 21.0)
        self.assertIn("*****", timed[2][1])
        self.assertEqual(timed[4][0], 31.0)

    def test_section_chapters_with_lyrics(self):
        desc = """
0:15 - Verse 1
I needed some shit with some bop in it
I flew past the whip with that blunt in my mouth
Watch the swervin', that whip had a cop in it

0:30 - Chorus
My bitch got good pussy, fly her 'cross the country
I finish the show and I hop in it

0:45 - Outro
Yeah yeah
"""
        timed = extract_lyrics_from_youtube_description(desc, total_duration=60.0)
        self.assertGreaterEqual(len(timed), 5)
        # Verify timestamps are monotonically increasing
        for i in range(len(timed) - 1):
            self.assertLess(timed[i][0], timed[i+1][0])
        # First verse lines should start around 15s - 30s
        self.assertGreaterEqual(timed[0][0], 15.0)
        self.assertLess(timed[0][0], 30.0)

    def test_untimed_lyrics_block(self):
        desc = """
Seedhe Maut - Nanchaku

Lyrics:
I needed some shit with some bop in it
I flew past the whip with that blunt in my mouth
Watch the swervin', that whip had a cop in it
My bitch got good pussy, fly her 'cross the country
I finish the show and I hop in it
I got me a milli', I did it legit-ly
I'm still with the shits, I'm a hot nigga

Audio Credits:
Music by Sez on the Beat
Follow on Instagram: https://instagram.com/
"""
        timed = extract_lyrics_from_youtube_description(desc, total_duration=180.0)
        self.assertEqual(len(timed), 7)
        self.assertIn("shit", timed[0][1])
        self.assertIn("nigga", timed[-1][1])
        # Timestamps should be distributed reasonably
        self.assertGreaterEqual(timed[0][0], 10.0)
        self.assertLessEqual(timed[-1][0], 180.0)

    def test_non_lyrics_description(self):
        desc = """
Official music video by Artist.
Produced by Producer.
(C) 2024 Record Label.
Subscribe to the channel for more updates!
https://youtube.com/...
"""
        timed = extract_lyrics_from_youtube_description(desc)
        self.assertEqual(timed, [])

    def test_lyrics_extraction_with_typo_header_lyircs(self):
        desc = """
Dop/Edit-Vazeer_Art 

Special Thanks : Shakir Bhai (Vazeer_Art) 

Lyircs

Mai bhi changa mera pio bhi changa
meri maa bhi changi, ristedar bench*d

ex bhi changi meri next bhi changi
Meri crush bhi changi
Ristedar bench*d

Follow on Instagram: https://instagram.com/
"""
        timed = extract_lyrics_from_youtube_description(desc, total_duration=180.0)
        self.assertGreaterEqual(len(timed), 5)
        self.assertTrue(timed.is_untimed)
        self.assertIn("bench*d", timed[1][1])

    def test_integration_with_censor_detector(self):
        desc = """
0:15 I needed some shit with some bop in it
0:21 My ***** got good *****, fly her 'cross the country
0:31 What's your name? Get the **** out the spot, nigga
"""
        timed = extract_lyrics_from_youtube_description(desc)
        lrc_lines = [f"[{int(ts // 60):02d}:{ts % 60:05.2f}] {text}" for ts, text in timed]
        lrc_text = "\n".join(lrc_lines)

        words = parse_lrc_content(lrc_text)
        detector = ProfanityDetector()
        intervals = detector.detect_in_words(words)
        self.assertGreaterEqual(len(intervals), 3)

        detected_words = [i.matched_word for i in intervals]
        # Should detect the swear words and the starred words
        self.assertTrue(any("shit" in w for w in detected_words))
        self.assertTrue(any("*****" in w for w in detected_words))
        self.assertTrue(any("****" in w or "nigga" in w for w in detected_words))

    def test_ai_audio_alignment_untimed_lyrics(self):
        from core.asr.lyrics_provider import align_lyrics_with_whisper_segments

        untimed_lyrics = [
            "I needed some shit with some bop in it",
            "I flew past the whip with that blunt in my mouth",
            "Watch the swervin', that whip had a cop in it",
            "My bitch got good pussy, fly her 'cross the country",
            "I finish the show and I hop in it",
        ]
        whisper_segments = [
            {"start": 15.0, "end": 17.5, "text": "I needed some shit with some bop in it"},
            {"start": 18.0, "end": 20.2, "text": "I flew past the whip with that blunt in my mouth"},
            {"start": 20.8, "end": 23.0, "text": "Watch the swervin that whip had a cop in it"},
            {"start": 23.5, "end": 26.0, "text": "My bitch got good pussy fly her cross the country"},
            {"start": 45.0, "end": 48.0, "text": "I finish the show and I hop in it"},
        ]

        aligned = align_lyrics_with_whisper_segments(untimed_lyrics, whisper_segments)
        self.assertEqual(len(aligned), 5)
        # Verify timestamps match real vocal speech start
        self.assertAlmostEqual(aligned[0][0], 15.0, places=1)
        self.assertAlmostEqual(aligned[1][0], 18.0, places=1)
        self.assertAlmostEqual(aligned[2][0], 20.8, places=1)
        self.assertAlmostEqual(aligned[3][0], 23.5, places=1)
        self.assertAlmostEqual(aligned[4][0], 45.0, places=1)

    def test_phonetic_roman_transliteration(self):
        from core.asr.lyrics_provider import to_phonetic_roman

        # Devanagari Hindi
        dev = to_phonetic_roman("मैं भी चंगा मेरा पियो भी चंगा")
        self.assertIn("chnga", dev)
        self.assertIn("piyo", dev)

        # Perso-Arabic Urdu
        urdu = to_phonetic_roman("چھڑھ رشتے دار بھین چھوڑھ")
        self.assertIn("rshte", urdu)
        self.assertIn("dar", urdu)
        self.assertIn("chhodh", urdu)

    def test_alignment_with_manual_intro_offset(self):
        from core.asr.lyrics_provider import align_lyrics_with_whisper_segments

        lyrics = [
            "Mai bhi changa mera pio bhi changa",
            "meri maa bhi changi, ristedar benchod",
            "kher chhod ristedar bc"
        ]
        segments = [
            {"start": 0.0, "end": 0.5, "text": "Intro DJ tag"},
            {"start": 5.0, "end": 7.0, "text": "Beats and scratching"},
            {"start": 59.0, "end": 62.0, "text": "چھڑھ رشتے دار بھین چھوڑھ"}
        ]
        # Pass manual intro_offset=28.0 (skips 0s and 5s noise)
        aligned = align_lyrics_with_whisper_segments(lyrics, segments, intro_offset=28.0)
        self.assertEqual(len(aligned), 3)
        self.assertGreaterEqual(aligned[0][0], 27.9)
        self.assertLess(aligned[0][0], 35.0)

    def test_alignment_auto_intro_noise_skip_and_back_projection(self):
        from core.asr.lyrics_provider import align_lyrics_with_whisper_segments

        lyrics = [
            "Mai bhi changa mera pio bhi changa",
            "meri maa bhi changi, ristedar benchod",
            "kher chhod ristedar bc"
        ]
        segments = [
            {"start": 0.0, "end": 0.4, "text": "Blip"}, # isolated noise < 3.5s followed by > 4s gap
            {"start": 59.0, "end": 62.0, "text": "چھڑھ رشتے دار بھین چھوڑھ"} # Anchor for line 2
        ]
        # In Auto mode (intro_offset=None), back-projection should not pin Line 0 to 0.0s!
        aligned = align_lyrics_with_whisper_segments(lyrics, segments)
        self.assertEqual(len(aligned), 3)
        # Line 0 should be back-projected near 50-55s, not at 0.0s!
        self.assertGreater(aligned[0][0], 20.0)


    def test_clean_filename_resolves_base_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_desc = Path(tmpdir) / "MySong.description"
            base_desc.write_text("Lyircs\nLine 1 bench*d\nLine 2 test\nLine 3 here\n", encoding="utf-8")
            clean_audio = Path(tmpdir) / "MySong_clean.mp3"
            clean_audio.touch()

            prov = OnlineLyricsProvider()
            desc_text = prov._get_youtube_description_text(str(clean_audio))
            self.assertIsNotNone(desc_text)
            self.assertIn("bench*d", desc_text)

    def test_candidate_queries_fullwidth_punctuation(self):
        prov = OnlineLyricsProvider()
        test_file = "downloads/Ristedaar BC ： Mai Bhi Changa Mera Pio Bhi Changa ｜ Viral Song ｜ terabhaipaul (Original Song) 2024_clean.mp3"
        candidates = prov.get_candidate_queries(test_file)
        # Verify fullwidth delimiters were stripped cleanly
        self.assertTrue(any("Ristedaar BC" in c for c in candidates))
        self.assertFalse(any("：" in c for c in candidates))
        self.assertFalse(any("｜" in c for c in candidates))

    def test_copy_media_tags(self):
        from core.censor.beep import copy_media_tags
        import mutagen
        import shutil

        src_real = Path("downloads/3 DRAGS.mp3")
        dst_real = Path("downloads/3 DRAGS_clean.mp3")
        if not src_real.exists() or not dst_real.exists():
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src.mp3"
            dst = Path(tmpdir) / "dst.mp3"
            shutil.copyfile(src_real, src)
            shutil.copyfile(dst_real, dst)

            copy_media_tags(str(src), str(dst))
            dst_res = mutagen.File(str(dst))
            self.assertIsNotNone(dst_res.tags)
            self.assertIn("TIT2", dst_res.tags)
            self.assertIn("TPE1", dst_res.tags)


if __name__ == '__main__':
    unittest.main()
