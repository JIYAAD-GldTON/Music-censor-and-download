"""
Profanity Detector module.
Takes transcribed words with timestamps and identifies intervals that require censorship.
Supports single-word and multi-word Hinglish/Hindi/English matches and merges adjacent intervals.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from core.filter.profanity_db import ProfanityDB, normalize_text


@dataclass
class WordTimestamp:
    word: str
    start: float
    end: float
    confidence: float = 1.0


@dataclass
class CensorInterval:
    start: float
    end: float
    matched_word: str
    reason: str = "profanity"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def merge_intervals(intervals: List[CensorInterval], min_gap: float = 0.15) -> List[CensorInterval]:
    """Merge overlapping or closely adjacent intervals."""
    if not intervals:
        return []

    # Sort intervals by start time
    sorted_intervals = sorted(intervals, key=lambda x: x.start)
    merged: List[CensorInterval] = [sorted_intervals[0]]

    for current in sorted_intervals[1:]:
        prev = merged[-1]
        # Check if current overlaps or is close enough to previous
        if current.start <= prev.end + min_gap:
            prev.end = max(prev.end, current.end)
            prev.matched_word = f"{prev.matched_word}, {current.matched_word}"
        else:
            merged.append(current)

    return merged


class ProfanityDetector:
    def __init__(
        self,
        db: Optional[ProfanityDB] = None,
        padding: float = 0.20,
        pre_padding: Optional[float] = None,
        post_padding: Optional[float] = None,
        time_offset: float = 0.0
    ):
        self.db = db or ProfanityDB()
        self.padding = padding
        self.pre_padding = pre_padding if pre_padding is not None else padding
        self.post_padding = post_padding if post_padding is not None else padding
        self.time_offset = time_offset

    def detect_in_words(
        self,
        words: List[WordTimestamp],
        lang: str = "all",
        padding: Optional[float] = None,
        pre_padding: Optional[float] = None,
        post_padding: Optional[float] = None,
        time_offset: Optional[float] = None
    ) -> List[CensorInterval]:
        """
        Analyze a list of WordTimestamp objects and return merged CensorIntervals.
        Handles both individual profane words and multi-word profane phrases.
        Applies pre_padding (lead-in) and post_padding (tail), plus optional time_offset shift.
        """
        if not words:
            return []

        pad = self.padding if padding is None else padding
        pre_pad = padding if padding is not None else (self.pre_padding if pre_padding is None else pre_padding)
        post_pad = padding if padding is not None else (self.post_padding if post_padding is None else post_padding)
        offset = self.time_offset if time_offset is None else time_offset

        detected_intervals: List[CensorInterval] = []

        # 1. Multi-word phrase matching
        n_words = len(words)
        matched_indices = set()

        for phrase in self.db.phrases:
            phrase_parts = phrase.split()
            p_len = len(phrase_parts)
            if p_len > n_words:
                continue

            for i in range(n_words - p_len + 1):
                window_words = [normalize_text(w.word) for w in words[i:i + p_len]]
                match = True
                if window_words != phrase_parts:
                    for ww, pp in zip(window_words, phrase_parts):
                        if ww == pp:
                            continue
                        if ('*' in ww or '#' in ww) and self.db._matches_masked_pattern(ww, lang=lang):
                            continue
                        match = False
                        break

                if match:
                    start_time = max(0.0, words[i].start + offset - pre_pad)
                    end_time = max(0.0, words[i + p_len - 1].end + offset + post_pad)
                    detected_intervals.append(
                        CensorInterval(
                            start=start_time,
                            end=end_time,
                            matched_word=phrase
                        )
                    )
                    for idx in range(i, i + p_len):
                        matched_indices.add(idx)

        # 2. Single word matching for remaining words
        for idx, w in enumerate(words):
            if idx in matched_indices:
                continue
            if self.db.is_profane_word(w.word, lang=lang):
                start_time = max(0.0, w.start + offset - pre_pad)
                end_time = max(0.0, w.end + offset + post_pad)
                detected_intervals.append(
                    CensorInterval(
                        start=start_time,
                        end=end_time,
                        matched_word=w.word.strip()
                    )
                )

        return merge_intervals(detected_intervals)

    def detect_in_text(self, text: str, lang: str = "all") -> List[str]:
        """Return list of profane words/phrases found in plain text."""
        matches = []
        norm_text = normalize_text(text)
        
        # Check phrases
        for phrase in self.db.phrases:
            if phrase in norm_text:
                matches.append(phrase)

        # Check tokens
        tokens = norm_text.split()
        for token in tokens:
            if self.db.is_profane_word(token, lang=lang):
                matches.append(token)

        return list(set(matches))
