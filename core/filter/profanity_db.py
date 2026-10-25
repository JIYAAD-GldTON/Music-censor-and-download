"""
Profanity Database module.
Loads English, Hindi (Devanagari), and Hindi (Romanized/Hinglish) wordlists.
Provides normalization and lookup functionality.
"""

import os
import re
from pathlib import Path
from typing import Set, List, Dict, Tuple


# Leetspeak and symbol substitutions mapping to potential vowels/consonants
LEET_CANDIDATES = {
    '@': ['a', 'u'],
    '*': ['a', 'e', 'i', 'o', 'u'],
    '4': ['a'],
    '8': ['b'],
    '3': ['e'],
    '1': ['i', 'l'],
    '!': ['i', 'l'],
    '0': ['o'],
    '$': ['s'],
    '5': ['s'],
    '7': ['t'],
    '+': ['t'],
}


def normalize_text(text: str) -> str:
    """Basic normalization: lowercase, remove special symbols except alphanumeric, space, devanagari."""
    if not text:
        return ""
    text = text.lower().strip()
    
    # Normalize Devanagari candrabindu (ँ) to anusvara (ं) for unified matching (e.g. माँ -> मां)
    text = text.replace('\u0901', '\u0902')
    # Normalize Devanagari nukta (़) so words with or without nukta match (e.g. ड़ -> ड, ज़ -> ज)
    text = text.replace('\u093c', '')

    # Remove non-alphanumeric except space, devanagari characters, and common leet chars
    text = re.sub(r'[^\w\s\u0900-\u097F@*!$431057+]', '', text)
    
    # Collapse character repetitions (> 2 of the same char down to 1 or 2)
    text = re.sub(r'(.)\1{2,}', r'\1\1', text)
    
    return text.strip()


def generate_variations(text: str) -> List[str]:
    """Generate potential normalized words from leetspeak / masked symbols."""
    text = normalize_text(text)
    if not text:
        return []

    # If pure word already
    results = {re.sub(r'[^\w\s\u0900-\u097F]', '', text)}

    # Generate substitutions
    chars = list(text)
    branches = [[""]]
    for ch in chars:
        replacements = LEET_CANDIDATES.get(ch, [ch])
        new_branches = []
        for b in branches:
            for r in replacements:
                new_branches.append(b + [r])
        # Limit explosion
        if len(new_branches) > 32:
            new_branches = new_branches[:32]
        branches = new_branches

    for b in branches:
        cand = "".join(b)
        clean_cand = re.sub(r'[^\w\s\u0900-\u097F]', '', cand)
        results.add(clean_cand)
        results.add(re.sub(r'(.)\1+', r'\1', clean_cand))

    return [r for r in results if r]


class ProfanityDB:
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            # Default to ../../data/wordlists
            current_dir = Path(__file__).resolve().parent
            data_dir = current_dir.parent.parent / "data" / "wordlists"
        self.data_dir = Path(data_dir)
        
        self.english_words: Set[str] = set()
        self.hindi_devanagari_words: Set[str] = set()
        self.hindi_roman_words: Set[str] = set()
        self.phrases: List[str] = []
        
        self.load_all()

    def _load_file(self, filepath: Path) -> List[str]:
        words = []
        if not filepath.exists():
            return words
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    words.append(line.lower())
        return words

    def load_all(self):
        eng_file = self.data_dir / "english_cuss.txt"
        hin_dev_file = self.data_dir / "hindi_devanagari.txt"
        hin_rom_file = self.data_dir / "hindi_roman.txt"

        for w in self._load_file(eng_file):
            normalized = normalize_text(w)
            if " " in normalized:
                self.phrases.append(normalized)
            else:
                self.english_words.add(normalized)

        for w in self._load_file(hin_dev_file):
            normalized = normalize_text(w)
            if " " in normalized:
                self.phrases.append(normalized)
            else:
                self.hindi_devanagari_words.add(normalized)

        for w in self._load_file(hin_rom_file):
            normalized = normalize_text(w)
            if " " in normalized:
                self.phrases.append(normalized)
            else:
                self.hindi_roman_words.add(normalized)
                
        # Sort phrases by length descending to match longest phrases first
        self.phrases.sort(key=lambda p: len(p.split()), reverse=True)

    @property
    def all_single_words(self) -> Set[str]:
        return self.english_words | self.hindi_devanagari_words | self.hindi_roman_words

    def is_profane_word(self, word: str, lang: str = "all") -> bool:
        """
        Check if a single word is profane.
        Supports:
        - Plain words (English, Hindi Devanagari, Hinglish/Romanized)
        - Leetspeak substitutions (@, $, 0, 1, 3, etc.)
        - Purely masked/censored tokens (***, ****, *****, ####, [beep], [censored])
        - Wildcard/masked words (f***, f**k, b****, m****chod, b****chod, ch***ya, etc.)
        - Surrounding punctuation (e.g. '*****,', '(****)', 'f***ing!')
        """
        if not word:
            return False

        w_raw = word.strip().lower()
        if w_raw in {'[beep]', '[censored]', '[explicit]', '[muted]'}:
            return True

        # Clean leading/trailing punctuation while preserving * and #
        w = re.sub(r'^[^\w*#\u0900-\u097F]+|[^\w*#\u0900-\u097F]+$', '', w_raw)
        if not w:
            return False

        # 1. Purely masked or explicit placeholders in lyrics
        clean_symbols = re.sub(r'[\*\#\_~\-]', '', w)
        if len(clean_symbols) == 0 and len(w) >= 2:
            return True

        # 2. Check standard variations & leetspeak
        candidates = set(generate_variations(w))
        if candidates:
            if lang == "en":
                if any(c in self.english_words for c in candidates):
                    return True
            elif lang == "hi":
                if any(c in (self.hindi_devanagari_words | self.hindi_roman_words) for c in candidates):
                    return True
            else:
                if any(c in self.all_single_words for c in candidates):
                    return True

        # 3. Masked words with asterisks or hashes (e.g. f***, f**k, b****, m****chod, ch***ya)
        if '*' in w or '#' in w:
            return self._matches_masked_pattern(w, lang=lang)

        return False

    def _matches_masked_pattern(self, word: str, lang: str = "all") -> bool:
        """Match partially masked words (e.g. f***, f**k, b****, m****chod) against the profanity dictionary."""
        parts = re.split(r'[\*\#]+', word)
        escaped_parts = [re.escape(p) for p in parts if p]
        if not escaped_parts:
            return True

        prefix = '.*' if word.startswith(('*', '#')) else ''
        suffix = '.*' if word.endswith(('*', '#')) else ''
        pattern_str = f"^{prefix}{'.*'.join(escaped_parts)}{suffix}$"

        if lang == "en":
            vocab = self.english_words
        elif lang == "hi":
            vocab = self.hindi_devanagari_words | self.hindi_roman_words
        else:
            vocab = self.all_single_words

        try:
            pat = re.compile(pattern_str)
            for target in vocab:
                if pat.match(target):
                    return True
        except Exception:
            pass

        return False
