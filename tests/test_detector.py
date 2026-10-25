import unittest
from core.filter.profanity_db import ProfanityDB, normalize_text
from core.filter.detector import ProfanityDetector, WordTimestamp


class TestProfanityDetector(unittest.TestCase):
    def setUp(self):
        self.db = ProfanityDB()
        self.detector = ProfanityDetector(self.db, padding=0.1)

    def test_english_words(self):
        self.assertTrue(self.db.is_profane_word("fuck"))
        self.assertTrue(self.db.is_profane_word("bitch"))
        self.assertTrue(self.db.is_profane_word("fuuuck"))
        self.assertTrue(self.db.is_profane_word("f@ck"))
        self.assertFalse(self.db.is_profane_word("hello"))

    def test_hindi_devanagari(self):
        self.assertTrue(self.db.is_profane_word("चूतिया"))
        self.assertTrue(self.db.is_profane_word("मादरचोद"))
        self.assertTrue(self.db.is_profane_word("गांडू"))
        self.assertTrue(self.db.is_profane_word("चुथ"))
        self.assertTrue(self.db.is_profane_word("चूथ"))
        self.assertTrue(self.db.is_profane_word("चुत"))
        self.assertTrue(self.db.is_profane_word("चोद"))
        self.assertTrue(self.db.is_profane_word("भोसडीके"))
        self.assertTrue(self.db.is_profane_word("गाँडू"))
        self.assertTrue(self.db.is_profane_word("लौडे"))
        self.assertFalse(self.db.is_profane_word("नमस्ते"))

    def test_devanagari_phrases_and_typos(self):
        words = [
            WordTimestamp(word="मां", start=10.0, end=10.3),
            WordTimestamp(word="की", start=10.3, end=10.5),
            WordTimestamp(word="चुथ", start=10.5, end=10.9),
        ]
        hits = self.detector.detect_in_words(words)
        self.assertEqual(len(hits), 1)
        self.assertIn("मां की चुथ", hits[0].matched_word)

        # Candrabindu variation
        words_candra = [
            WordTimestamp(word="माँ", start=20.0, end=20.3),
            WordTimestamp(word="की", start=20.3, end=20.5),
            WordTimestamp(word="चुथ", start=20.5, end=20.9),
        ]
        hits_candra = self.detector.detect_in_words(words_candra)
        self.assertEqual(len(hits_candra), 1)

    def test_hindi_romanized(self):
        self.assertTrue(self.db.is_profane_word("bhosdike"))
        self.assertTrue(self.db.is_profane_word("chutiya"))
        self.assertTrue(self.db.is_profane_word("madarchod"))
        self.assertTrue(self.db.is_profane_word("bkl"))
        self.assertTrue(self.db.is_profane_word("mc"))
        self.assertTrue(self.db.is_profane_word("bc"))
        self.assertFalse(self.db.is_profane_word("shukriya"))

    def test_intervals_and_padding(self):
        words = [
            WordTimestamp(word="Hello", start=0.0, end=0.5),
            WordTimestamp(word="bhosdike", start=1.0, end=1.5),
            WordTimestamp(word="how", start=2.0, end=2.3),
            WordTimestamp(word="are", start=2.4, end=2.6),
            WordTimestamp(word="you", start=2.7, end=3.0),
        ]
        intervals = self.detector.detect_in_words(words)
        self.assertEqual(len(intervals), 1)
        # Check padding: start 1.0 - 0.1 = 0.9, end 1.5 + 0.1 = 1.6
        self.assertAlmostEqual(intervals[0].start, 0.9, places=2)
        self.assertAlmostEqual(intervals[0].end, 1.6, places=2)

    def test_merging_adjacent(self):
        words = [
            WordTimestamp(word="fuck", start=1.0, end=1.3),
            WordTimestamp(word="shit", start=1.35, end=1.6),
        ]
        intervals = self.detector.detect_in_words(words)
        # Should be merged into 1 interval
        self.assertEqual(len(intervals), 1)
        self.assertAlmostEqual(intervals[0].start, 0.9, places=2)
        self.assertAlmostEqual(intervals[0].end, 1.7, places=2)

    def test_offset_and_asymmetric_padding(self):
        words = [
            WordTimestamp(word="bitch", start=3.0, end=3.4),
        ]
        # Shift 0.5s earlier (-0.5s offset) with 0.25s pre-pad and 0.15s post-pad
        intervals = self.detector.detect_in_words(
            words,
            pre_padding=0.25,
            post_padding=0.15,
            time_offset=-0.5
        )
        self.assertEqual(len(intervals), 1)
        # Expected start: 3.0 - 0.5 - 0.25 = 2.25s
        # Expected end: 3.4 - 0.5 + 0.15 = 3.05s
        self.assertAlmostEqual(intervals[0].start, 2.25, places=2)
        self.assertAlmostEqual(intervals[0].end, 3.05, places=2)

    def test_masked_and_starred_words(self):
        # Purely masked tokens (including punctuation)
        self.assertTrue(self.db.is_profane_word("*****"))
        self.assertTrue(self.db.is_profane_word("*****, "))
        self.assertTrue(self.db.is_profane_word("(****)"))
        self.assertTrue(self.db.is_profane_word("****"))
        self.assertTrue(self.db.is_profane_word("***"))
        self.assertTrue(self.db.is_profane_word("[beep]"))
        self.assertTrue(self.db.is_profane_word("[censored]"))

        # Partially masked English words (including punctuation)
        self.assertTrue(self.db.is_profane_word("f***"))
        self.assertTrue(self.db.is_profane_word("f***,"))
        self.assertTrue(self.db.is_profane_word("f**k"))
        self.assertTrue(self.db.is_profane_word("b****"))
        self.assertTrue(self.db.is_profane_word("f***ing"))

        # Partially masked Hindi / Hinglish words
        self.assertTrue(self.db.is_profane_word("m****chod"))
        self.assertTrue(self.db.is_profane_word("b****chod"))
        self.assertTrue(self.db.is_profane_word("ch***ya"))

        # Normal clean words should NEVER match
        self.assertFalse(self.db.is_profane_word("hello"))
        self.assertFalse(self.db.is_profane_word("music"))
        self.assertFalse(self.db.is_profane_word("star"))

    def test_masked_words_in_intervals(self):
        words = [
            WordTimestamp(word="He", start=0.0, end=0.4),
            WordTimestamp(word="said", start=0.5, end=0.8),
            WordTimestamp(word="f***", start=1.0, end=1.4),
            WordTimestamp(word="and", start=1.5, end=1.8),
            WordTimestamp(word="*****", start=2.0, end=2.5),
        ]
        intervals = self.detector.detect_in_words(words)
        self.assertEqual(len(intervals), 2)
        self.assertEqual(intervals[0].matched_word, "f***")
        self.assertEqual(intervals[1].matched_word, "*****")


if __name__ == '__main__':
    unittest.main()
