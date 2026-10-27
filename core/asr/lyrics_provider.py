"""
Online and Local Synced Lyrics Provider (.LRC).
Supports:
1. Local .lrc file (e.g. song.lrc alongside song.mp3 or custom pasted lyrics)
2. Online query with validation (LRCLIB, Musixmatch, NetEase, Spotify via syncedlyrics)
3. OpenAI Whisper fallback when lyrics are absent or ambiguous.
"""

import re
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple, Any
from core.filter.detector import WordTimestamp
from core.logger import get_logger

logger = get_logger("lyrics_provider")

try:
    import syncedlyrics
    SYNCEDLYRICS_AVAILABLE = True
except ImportError:
    SYNCEDLYRICS_AVAILABLE = False


def parse_lrc_timestamp(ts_str: str) -> float:
    """Convert mm:ss.xx or mm:ss.xxx into float seconds."""
    ts_str = ts_str.strip("[]")
    parts = ts_str.split(":")
    if len(parts) == 2:
        minutes = float(parts[0])
        seconds = float(parts[1])
        return minutes * 60.0 + seconds
    return 0.0


def parse_lrc_lines(lrc_text: str) -> List[Tuple[float, str]]:
    """Parse LRC text into sorted list of (timestamp_seconds, line_text), applying [offset:...] if present."""
    if not lrc_text:
        return []
    lines = lrc_text.strip().splitlines()
    timed_lines: List[Tuple[float, str]] = []
    lrc_pattern = re.compile(r'\[(\d{2}:\d{2}\.\d{2,3})\](.*)')
    offset_pattern = re.compile(r'\[offset:\s*([+-]?\d+)\]', re.IGNORECASE)

    offset_sec = 0.0
    for line in lines:
        off_match = offset_pattern.match(line.strip())
        if off_match:
            try:
                # LRC spec: [offset:+/-ms]. Positive = shifts lyrics later / delays lyrics
                offset_sec = float(off_match.group(1)) / 1000.0
            except Exception:
                pass

    for line in lines:
        match = lrc_pattern.match(line.strip())
        if match:
            ts = parse_lrc_timestamp(match.group(1)) + offset_sec
            text = match.group(2).strip()
            # Ignore metadata tags like [by:...] or [ar:...]
            if text and not text.startswith(("[", ":")):
                timed_lines.append((max(0.0, ts), text))

    timed_lines.sort(key=lambda x: x[0])
    return timed_lines


def parse_lrc_content(lrc_text: str) -> List[WordTimestamp]:
    """
    Parse LRC lines into timestamped words with realistic speech/rap tempo modeling.
    Prevents words from stretching across empty instrumental breaks and trailing silence.
    """
    timed_lines = parse_lrc_lines(lrc_text)
    if not timed_lines:
        return []

    words_output: List[WordTimestamp] = []
    for idx, (start_sec, line_text) in enumerate(timed_lines):
        tokens = line_text.split()
        if not tokens:
            continue

        num_words = len(tokens)
        # In natural rap/singing, words average 0.22s - 0.35s each.
        # Don't stretch words across long pauses or instrumental gaps before next line!
        if idx + 1 < len(timed_lines):
            gap_to_next = timed_lines[idx + 1][0] - start_sec
            estimated_active_duration = num_words * 0.30
            line_duration = max(0.4, min(gap_to_next, max(estimated_active_duration, gap_to_next * 0.60)))
        else:
            line_duration = max(0.5, num_words * 0.30)

        w_dur = line_duration / num_words
        for w_idx, token in enumerate(tokens):
            w_start = start_sec + (w_idx * w_dur)
            w_end = w_start + w_dur
            words_output.append(
                WordTimestamp(
                    word=token,
                    start=w_start,
                    end=w_end,
                    confidence=1.0  # Human-verified lyrics
                )
            )

    return words_output


def _get_tag_str(tags: Any, *keys: str) -> str:
    """Helper to safely extract string value from mutagen tags dict, object, or list."""
    if not tags:
        return ""
    for k in keys:
        val = None
        if hasattr(tags, "get"):
            try:
                val = tags.get(k)
            except Exception:
                val = None
            if not val and hasattr(tags, "keys"):
                try:
                    for tag_key in tags.keys():
                        if str(tag_key).lower() == k.lower():
                            val = tags.get(tag_key)
                            break
                except Exception:
                    pass
        elif hasattr(tags, "__getitem__"):
            try:
                val = tags[k]
            except Exception:
                val = None

        if val is not None:
            try:
                if isinstance(val, (list, tuple)) and len(val) > 0:
                    s = str(val[0]).strip()
                elif hasattr(val, "text") and isinstance(val.text, (list, tuple)) and len(val.text) > 0:
                    s = str(val.text[0]).strip()
                else:
                    s = str(val).strip()

                s = s.strip("[]'\"")
                if s and s.lower() != "none":
                    return s
            except Exception as e:
                logger.debug("Error parsing tag %s: %s", k, e)
    return ""


def extract_song_and_artist(media_path: str) -> Tuple[str, str]:
    """
    Extract (song_title, artist_name) from ID3/metadata tags or filename.
    Safely handles ID3, Vorbis, and MP4 tags without crashing on malformed tags.
    """
    artist = ""
    title = ""
    try:
        import mutagen
        f = mutagen.File(media_path)
        if f:
            tags = getattr(f, "tags", None) or f
            # Check Artist: ID3 (TPE1, TPE2), Vorbis/FLAC (artist), MP4 (©ART, aART)
            artist = _get_tag_str(tags, "TPE1", "TPE2", "artist", "ARTIST", "\xa9ART", "©ART", "aART")
            # Check Title: ID3 (TIT2), Vorbis/FLAC (title), MP4 (©nam)
            title = _get_tag_str(tags, "TIT2", "title", "TITLE", "\xa9nam", "©nam")
    except Exception as e:
        logger.debug("Mutagen extraction fallback for %s: %s", media_path, e)

    stem = Path(media_path).stem
    cleaned = re.sub(r'(_clean|_censored)+$', '', stem, flags=re.I)
    cleaned = re.sub(r'\(.*?\)|\[.*?\]|official audio|lyrics|official video', '', cleaned, flags=re.I)
    cleaned = re.sub(r'[:：|｜_\-–—]+', ' ', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)

    if not title and not artist:
        if " - " in cleaned:
            parts = cleaned.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
        else:
            title = cleaned
    elif not title:
        title = cleaned

    primary_artist = artist.split(',')[0].split(';')[0].strip() if artist else ""
    return title.strip(), primary_artist.strip()


def get_audio_duration(media_path: str) -> float:
    """Extract audio duration in seconds using mutagen or ffprobe."""
    if not media_path or not os.path.exists(media_path):
        return 0.0
    try:
        import mutagen
        f = mutagen.File(media_path)
        if f and hasattr(f, 'info') and hasattr(f.info, 'length') and f.info.length:
            return float(f.info.length)
    except Exception as e:
        logger.debug("Mutagen length lookup failed for %s: %s", media_path, e)

    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            media_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception as e:
        logger.debug("ffprobe duration lookup failed for %s: %s", media_path, e)
    return 0.0


def is_youtube_url(url: str) -> bool:
    """Check if string is a YouTube URL."""
    if not url:
        return False
    u = url.strip().lower()
    return "youtube.com" in u or "youtu.be" in u


def fetch_youtube_description_from_url(url: str) -> Optional[str]:
    """Fetch video description directly from a YouTube URL via yt-dlp."""
    if not is_youtube_url(url):
        return None
    try:
        cmd = ["yt-dlp", "--print", "description", "--skip-download", url.strip()]
        res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="ignore", timeout=20)
        if res.returncode == 0 and res.stdout and res.stdout.strip():
            return res.stdout.strip()
    except Exception as e:
        logger.warning("yt-dlp failed to fetch description for URL %s: %s", url, e)
    return None


def fetch_youtube_description_from_query(query: str) -> Optional[str]:
    """Fetch video description by searching YouTube via yt-dlp ytsearch1:<query>."""
    if not query or not query.strip():
        return None
    try:
        cmd = ["yt-dlp", "--print", "description", "--skip-download", f"ytsearch1:{query.strip()}"]
        res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="ignore", timeout=20)
        if res.returncode == 0 and res.stdout and res.stdout.strip():
            return res.stdout.strip()
    except Exception as e:
        logger.debug("yt-dlp query '%s' failed: %s", query, e)
    return None


class TimedLyricsList(list):
    """List of (timestamp, line) tuples with metadata on whether timestamps were estimated."""
    def __init__(self, items, is_untimed: bool = False):
        super().__init__(items)
        self.is_untimed = is_untimed


# Unified phonetic transliteration maps for cross-script alignment
URDU_MAP = {
    'ا': 'a', 'آ': 'a', 'ب': 'b', 'پ': 'p', 'ت': 't', 'ٹ': 't', 'ث': 's',
    'ج': 'j', 'چ': 'ch', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ڈ': 'd', 'ذ': 'z',
    'ر': 'r', 'ڑ': 'd', 'ز': 'z', 'ژ': 'zh', 'س': 's', 'ش': 'sh', 'ص': 's',
    'ض': 'z', 'ط': 't', 'ظ': 'z', 'ع': 'a', 'غ': 'gh', 'ف': 'f', 'ق': 'q',
    'ک': 'k', 'گ': 'g', 'ل': 'l', 'म': 'm', 'ن': 'n', 'ں': 'n', 'و': 'o',
    'ہ': 'h', 'ھ': 'h', 'ء': '', 'ی': 'i', 'ے': 'e', 'ئ': 'i', 'ؤ': 'o',
    'ُ': 'u', 'ِ': 'i', 'َ': 'a', 'ً': 'an', 'ّ': ''
}

DEV_MAP = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
    'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v',
    'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
    'ड़': 'd', 'ढ़': 'dh', 'ज़': 'z', 'फ़': 'f', 'क़': 'q', 'ख़': 'kh', 'ग़': 'gh',
    'अ': 'a', 'आ': 'a', 'इ': 'i', 'ई': 'i', 'उ': 'u', 'ऊ': 'u', 'ऋ': 'ri',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'an', 'अः': 'ah',
    'ा': 'a', 'ि': 'i', 'ी': 'i', 'ु': 'u', 'ू': 'u', 'ृ': 'ri',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n', 'ः': 'h', '्': '', '़': ''
}


def to_phonetic_roman(text: str) -> str:
    """Normalize text (Devanagari, Urdu/Perso-Arabic, English/Hinglish) to unified phonetic Roman."""
    if not text:
        return ""
    t = re.sub(r'\(.*?\)|\[.*?\]', '', text)
    out = []
    for ch in t:
        if ch in URDU_MAP:
            out.append(URDU_MAP[ch])
        elif ch in DEV_MAP:
            out.append(DEV_MAP[ch])
        elif ('a' <= ch.lower() <= 'z') or ch.isdigit():
            out.append(ch.lower())
        elif ch.isspace():
            out.append(" ")
    res = "".join(out)
    return re.sub(r'\s+', ' ', res).strip()


def clean_for_match(text: str) -> str:
    """Normalize text for alignment matching across scripts."""
    return to_phonetic_roman(text)


def align_lyrics_with_whisper_segments(
    lyrics_lines: List[str],
    segments: List[dict],
    total_duration: Optional[float] = None,
    intro_offset: Optional[float] = None
) -> List[Tuple[float, str]]:
    """
    Align untimed lyrics lines with audio speech segments detected by Whisper.
    Assigns real vocal audio start timestamps to each lyric line, preserving
    instrumental pauses, solos, and speech cadence with strictly monotonic interpolation.

    Supports:
    - intro_offset: Manual or pre-calculated start seconds (skips instrumental intro noise).
    - Auto intro-sound detection: Ignores isolated DJ tags, scratches, and beat drops before singing.
    - Multi-script matching: Accurately matches Roman Hinglish, Devanagari, and Perso-Arabic Urdu.
    - Anchor back-projection: Auto-aligns intro when early lines are instrumental or missing in Whisper.
    """
    import difflib

    n_lyrics = len(lyrics_lines)
    if not lyrics_lines:
        return []

    valid_segs = [s for s in (segments or []) if s.get('text', '').strip() and float(s.get('end', 0.0)) > float(s.get('start', 0.0))]
    fallback_dur = total_duration or (n_lyrics * 3.5 + 20.0)

    # 1. Handle Intro Offset & Spurious Intro Noise Detection
    if intro_offset is not None and intro_offset >= 0.0:
        vocal_start = float(intro_offset)
        # Filter segments strictly to after intro_offset (with 1.5s tolerance)
        active_segs = [s for s in valid_segs if float(s.get('start', 0.0)) >= max(0.0, intro_offset - 1.5)]
    else:
        # Auto: Skip isolated short blips at song beginning (< 3.5s duration followed by >= 4.0s silence)
        idx = 0
        while idx < len(valid_segs) - 1:
            s_curr = valid_segs[idx]
            s_next = valid_segs[idx + 1]
            dur = float(s_curr.get('end', 0.0)) - float(s_curr.get('start', 0.0))
            gap = float(s_next.get('start', 0.0)) - float(s_curr.get('end', 0.0))
            if dur <= 3.5 and gap >= 4.0 and float(s_curr.get('start', 0.0)) < 35.0:
                idx += 1
            else:
                break
        active_segs = valid_segs[idx:]
        if active_segs:
            vocal_start = max(0.0, float(active_segs[0].get('start', 0.0)))
        elif valid_segs:
            vocal_start = max(0.0, float(valid_segs[0].get('start', 0.0)))
        else:
            vocal_start = min(12.0, fallback_dur * 0.08)

    if valid_segs:
        vocal_end = min(fallback_dur, float(valid_segs[-1].get('end', fallback_dur)))
        if vocal_end <= vocal_start + 10.0:
            vocal_end = max(vocal_start + 15.0, fallback_dur - min(10.0, fallback_dur * 0.06))
    else:
        vocal_end = max(vocal_start + 15.0, fallback_dur - min(10.0, fallback_dur * 0.06))

    # 2. Match anchors across scripts (Roman Hinglish, Urdu, Devanagari) with Tempo Consistency
    cleaned_lyrics = [clean_for_match(l) for l in lyrics_lines]
    cleaned_segs = [clean_for_match(s.get('text', '')) for s in active_segs]

    nominal_tempo = (vocal_end - vocal_start) / max(1, n_lyrics)
    max_slack = max(14.0, (vocal_end - vocal_start) * 0.20)

    anchors = {}  # lyric_idx -> timestamp
    last_seg_idx = 0
    n_segs = len(active_segs)

    for l_idx, l_text in enumerate(cleaned_lyrics):
        if len(l_text) < 4 or not active_segs:
            continue
        expected_ts = vocal_start + l_idx * nominal_tempo
        best_r = 0.0
        best_s = None

        search_window = range(last_seg_idx, min(n_segs, last_seg_idx + 12))
        for s_i in search_window:
            seg_ts = float(active_segs[s_i].get('start', 0.0))
            # Tempo gating: prevent matching a chorus to an occurrence 30s away
            if abs(seg_ts - expected_ts) > max_slack:
                continue

            s_text = cleaned_segs[s_i]
            t_l = set(l_text.split())
            t_s = set(s_text.split())

            # Semantic anchor requirement: must share at least one word or sub-word stem
            overlap_words = t_l & t_s
            if not overlap_words:
                has_stem = any(len(w1) >= 4 and (w1 in s_text or any(w1 in w2 or w2 in w1 for w2 in t_s)) for w1 in t_l)
                if not has_stem:
                    continue

            r = difflib.SequenceMatcher(None, l_text, s_text).ratio()
            if overlap_words:
                overlap = len(overlap_words) / min(len(t_l), len(t_s))
                r = max(r, overlap * 0.85)
            if l_text in s_text or s_text in l_text:
                r = max(r, 0.70)
            if r > best_r:
                best_r = r
                best_s = s_i

        # Accept matches with similarity >= 0.45
        if best_s is not None and best_r >= 0.45:
            anchors[l_idx] = float(active_segs[best_s].get('start', 0.0))
            last_seg_idx = best_s

    anchor_indices = sorted(anchors.keys())

    # 3. Anchor Back-Projection for Intro (if Line 0 not directly matched)
    if anchor_indices and intro_offset is None:
        first_a_idx = anchor_indices[0]
        first_a_ts = anchors[first_a_idx]
        if first_a_idx > 0:
            if len(anchor_indices) >= 2:
                idx_span = anchor_indices[-1] - anchor_indices[0]
                time_span = anchors[anchor_indices[-1]] - anchors[anchor_indices[0]]
                avg_line_dur = max(1.5, min(3.5, time_span / max(1, idx_span)))
            else:
                avg_line_dur = 2.4
            proj_start = max(0.0, first_a_ts - first_a_idx * avg_line_dur)
            # Align vocal_start to the back-projected tempo start of Line 0
            if vocal_start < proj_start - 3.0 or vocal_start > proj_start + 1.0:
                vocal_start = proj_start

    # If fewer than 2 high-confidence anchors:
    if len(anchor_indices) < 2:
        step = (vocal_end - vocal_start) / max(1, n_lyrics)
        return [(vocal_start + i * step, line) for i, line in enumerate(lyrics_lines)]

    # Build full anchors from boundary 0 to N-1
    full_anchors = [(0, vocal_start if 0 not in anchors else min(vocal_start, anchors[0]))]
    for idx in anchor_indices:
        if idx != 0 and idx != n_lyrics - 1:
            full_anchors.append((idx, anchors[idx]))
    full_anchors.append((n_lyrics - 1, vocal_end if (n_lyrics - 1) not in anchors else max(vocal_end, anchors[n_lyrics - 1])))

    # Ensure strictly increasing timestamps between anchors
    clean_anchors = [full_anchors[0]]
    for idx, ts in full_anchors[1:]:
        if idx > clean_anchors[-1][0]:
            clean_ts = max(ts, clean_anchors[-1][1] + 0.5)
            clean_anchors.append((idx, clean_ts))

    # Proportional, monotonic interpolation between consecutive anchors
    aligned_lines = []
    for a_i in range(len(clean_anchors) - 1):
        idx_a, ts_a = clean_anchors[a_i]
        idx_b, ts_b = clean_anchors[a_i + 1]
        span = idx_b - idx_a
        time_span = ts_b - ts_a
        for k in range(span):
            curr_idx = idx_a + k
            frac = k / span
            curr_ts = ts_a + frac * time_span
            aligned_lines.append((curr_ts, lyrics_lines[curr_idx]))

    # Append the last line
    last_idx, last_ts = clean_anchors[-1]
    aligned_lines.append((last_ts, lyrics_lines[last_idx]))

    aligned_lines.sort(key=lambda x: x[0])
    return aligned_lines


def parse_timestamp_str(line: str) -> Optional[Tuple[float, str]]:
    """Parse timestamps like 0:15, 00:15, [0:15], (0:15), 1:02:15, etc."""
    m = re.match(r'^[\(\[]?(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?[\)\]]?\s*[-:–—|]?\s*(.*)$', line.strip())
    if m:
        hrs = int(m.group(1)) if m.group(1) else 0
        mins = int(m.group(2))
        secs = int(m.group(3))
        ms = float('.' + m.group(4)) if m.group(4) else 0.0
        total_sec = float(hrs * 3600 + mins * 60 + secs + ms)
        text = m.group(5).strip()
        return total_sec, text
    return None


def extract_lyrics_from_youtube_description(
    desc: str,
    total_duration: Optional[float] = None
) -> List[Tuple[float, str]]:
    """
    Extract lyrics and compute timestamps from a YouTube video description.
    Supports:
    1. Direct timestamped lyric lines (e.g. 0:15 I needed some shit...)
    2. Section/chapter timestamps with lyrics underneath (e.g. 0:15 Verse 1...)
    3. Untimed lyrics blocks under headers like 'Lyrics:', 'LYRICS:', 'बोल:'
       interpolated smoothly across the audio duration.
    """
    if not desc or not desc.strip():
        return []

    lines = [l.strip() for l in desc.splitlines()]

    # Check for lines starting with timestamps
    raw_timed: List[Tuple[int, float, str]] = []
    for idx, l in enumerate(lines):
        ts_res = parse_timestamp_str(l)
        if ts_res:
            raw_timed.append((idx, ts_res[0], ts_res[1]))

    # Scenario A: Timestamped lines (direct lyrics lines or section chapters)
    if len(raw_timed) >= 2:
        has_sub_lines = False
        for i in range(len(raw_timed) - 1):
            if raw_timed[i+1][0] - raw_timed[i][0] > 1:
                has_sub_lines = True
                break

        timed_lines: List[Tuple[float, str]] = []
        if has_sub_lines:
            for i, (line_idx, start_ts, header_text) in enumerate(raw_timed):
                next_ts = raw_timed[i+1][1] if i + 1 < len(raw_timed) else (total_duration or (start_ts + 30.0))
                next_line_idx = raw_timed[i+1][0] if i + 1 < len(raw_timed) else len(lines)

                sub_lines = [l for l in lines[line_idx+1:next_line_idx] if l and not l.startswith(('http', 'Follow', 'Stream', 'Subscribe'))]
                if header_text and not re.match(r'^(verse|chorus|hook|intro|outro|bridge|part)\b', header_text, re.I):
                    timed_lines.append((start_ts, header_text))

                if sub_lines:
                    interval = max(1.0, next_ts - start_ts)
                    step = interval / (len(sub_lines) + 1)
                    for s_i, sl in enumerate(sub_lines):
                        timed_lines.append((start_ts + (s_i + 1) * step, sl))
        else:
            for _, ts, text in raw_timed:
                if text:
                    timed_lines.append((ts, text))

        if timed_lines:
            timed_lines.sort(key=lambda x: x[0])
            return TimedLyricsList(timed_lines, is_untimed=False)

    # Scenario B: Untimed lyrics under 'Lyrics:' or similar headers
    header_pattern = re.compile(
        r'(?:^|\n)\s*(?:[-*#=~_\s]*\b(?:lyrics?|lyircs?|lirics?|lirycs?|गीत|बोल|sahitya|tracklist)\b[-*#=~_\s]*:?|\[.*?lyrics?.*?\])\s*\n',
        re.I
    )
    m = header_pattern.search(desc)
    if m:
        start_pos = m.end()
        remaining = desc[start_pos:]
        footer_pattern = re.compile(
            r'\n\s*(?:(?:follow|stream|listen|connect|subscribe|copyright|audio credits|video credits|socials?|special thanks|booking|business queries|for business|contact|management)\b|https?://)',
            re.I
        )
        fm = footer_pattern.search(remaining)
        block = remaining[:fm.start()] if fm else remaining
        raw_lines = [l.strip() for l in block.splitlines() if l.strip() and not l.startswith(('[', 'http', '#'))]
        if len(raw_lines) >= 3:
            dur = total_duration or (len(raw_lines) * 3.5 + 20.0)
            start_off = min(12.0, dur * 0.08)
            end_off = max(start_off + 10.0, dur - min(10.0, dur * 0.06))
            span = end_off - start_off
            step = span / len(raw_lines)
            return TimedLyricsList([(start_off + i * step, line) for i, line in enumerate(raw_lines)], is_untimed=True)

    return TimedLyricsList([], is_untimed=False)


class OnlineLyricsProvider:
    def __init__(self):
        self.available = SYNCEDLYRICS_AVAILABLE
        self.last_source: Optional[str] = None
        self.last_matched_query: Optional[str] = None
        self.last_raw_lyrics: Optional[str] = None
        self.last_timed_lines: List[Tuple[float, str]] = []
        self.is_untimed: bool = False

    def _get_youtube_description_text(self, media_path: str, youtube_desc: Optional[str] = None) -> Optional[str]:
        # 1. Direct explicit description string, file path, or URL
        if youtube_desc and youtube_desc.strip():
            if os.path.exists(youtube_desc):
                try:
                    with open(youtube_desc, "r", encoding="utf-8", errors="ignore") as f:
                        return f.read()
                except Exception:
                    pass
            elif is_youtube_url(youtube_desc):
                text = fetch_youtube_description_from_url(youtube_desc)
                if text:
                    return text
            else:
                return youtube_desc.strip()

        # 2. Local .description file alongside media_path or base media file
        if media_path and not is_youtube_url(media_path):
            p = Path(media_path)
            local_desc = p.with_suffix(".description")
            if local_desc.exists():
                try:
                    with open(local_desc, "r", encoding="utf-8", errors="ignore") as df:
                        return df.read()
                except Exception:
                    pass

            # Check if file has _clean / _censored suffix and look for base .description
            base_stem = re.sub(r'(_clean|_censored)+$', '', p.stem, flags=re.I)
            if base_stem != p.stem:
                base_desc = p.parent / f"{base_stem}.description"
                if base_desc.exists():
                    try:
                        with open(base_desc, "r", encoding="utf-8", errors="ignore") as df:
                            return df.read()
                    except Exception:
                        pass

            # 3. EMBEDDED METADATA TAGS INSIDE AUDIO/VIDEO FILE!
            # yt-dlp embeds full description into ID3 / Vorbis tags (TXXX:description, TXXX:synopsis)
            candidate_files = []
            if os.path.exists(media_path):
                candidate_files.append(media_path)
            if base_stem != p.stem:
                for ext in [p.suffix, ".mp3", ".m4a", ".opus", ".webm", ".wav"]:
                    bf = p.parent / f"{base_stem}{ext}"
                    if bf.exists() and str(bf) not in candidate_files:
                        candidate_files.append(str(bf))

            for cf in candidate_files:
                try:
                    import mutagen
                    f = mutagen.File(cf)
                    if f and hasattr(f, 'tags') and f.tags:
                        for tag_key in [
                            'TXXX:description', 'TXXX:synopsis', 'description',
                            'TXXX:comment', 'comment'
                        ]:
                            val = f.tags.get(tag_key)
                            if val:
                                s_val = str(val).strip()
                                if len(s_val) > 40 and not s_val.startswith('http'):
                                    return s_val
                                elif is_youtube_url(s_val):
                                    text = fetch_youtube_description_from_url(s_val)
                                    if text:
                                        return text

                        for url_key in ['TXXX:purl', 'WOAR', 'WXXX']:
                            val = f.tags.get(url_key)
                            if val:
                                s_url = str(val).strip()
                                if is_youtube_url(s_url):
                                    text = fetch_youtube_description_from_url(s_url)
                                    if text:
                                        return text
                except Exception:
                    pass

        # 4. If media_path itself is a YouTube URL
        if is_youtube_url(media_path):
            return fetch_youtube_description_from_url(media_path)

        return None

    def _search_youtube_for_description(
        self,
        media_path: str,
        song_title: Optional[str] = None,
        artist_name: Optional[str] = None
    ) -> Optional[str]:
        """
        On-the-fly YouTube search fallback using yt-dlp ytsearch1:<query>.
        Searches YouTube when local tags and .description are absent, parses the description
        for lyrics, and caches it to disk if lyrics are found.
        """
        search_queries = []
        p = Path(media_path) if media_path and not is_youtube_url(media_path) else None
        base_stem = re.sub(r'(_clean|_censored)+$', '', p.stem, flags=re.I) if p else ""

        s_title = (song_title or "").strip()
        a_name = (artist_name or "").strip()
        if a_name.lower() == "none":
            a_name = ""
        if s_title.lower() == "none":
            s_title = ""

        # Query from user-provided title/artist
        if s_title and a_name:
            search_queries.append(f"{s_title} {a_name}")
            clean_short = re.sub(r'\(.*?\)|\[.*?\]|[:：|｜\-–—].*', '', s_title).strip()
            if clean_short and clean_short != s_title:
                search_queries.append(f"{clean_short} {a_name}")
        elif s_title:
            clean_short = re.sub(r'\(.*?\)|\[.*?\]|[:：|｜\-–—].*', '', s_title).strip()
            if clean_short and clean_short != s_title:
                search_queries.append(clean_short)
            search_queries.append(s_title)

        # Query from file stem
        if base_stem:
            stem_clean = re.sub(r'\(.*?\)|\[.*?\]', '', base_stem)
            stem_clean = re.sub(r'official audio|official video|lyrics|video', '', stem_clean, flags=re.I).strip()
            parts = [pt.strip() for pt in re.split(r'[:：|｜\-–—]', stem_clean) if pt.strip()]
            if len(parts) >= 2:
                search_queries.append(f"{parts[0]} {parts[1]}")
                search_queries.append(f"{parts[0]} {parts[-1]}")
            full_clean = re.sub(r'\s+', ' ', re.sub(r'[:：|｜_\-–—]+', ' ', stem_clean)).strip()
            if full_clean and full_clean not in search_queries:
                search_queries.append(full_clean)
            if parts and parts[0] not in search_queries:
                search_queries.append(parts[0])

        unique_queries = []
        for q in search_queries:
            q_clean = q.strip()
            if len(q_clean) >= 3 and q_clean not in unique_queries:
                unique_queries.append(q_clean)

        for query in unique_queries[:3]:
            try:
                desc = fetch_youtube_description_from_query(query)
                if desc and desc.strip():
                    yt_res = extract_lyrics_from_youtube_description(desc)
                    if yt_res and len(yt_res) >= 2:
                        if p:
                            try:
                                cache_file = p.parent / f"{base_stem}.description"
                                with open(cache_file, "w", encoding="utf-8") as cf:
                                    cf.write(desc)
                                if base_stem != p.stem:
                                    cache_file_clean = p.with_suffix(".description")
                                    with open(cache_file_clean, "w", encoding="utf-8") as cf:
                                        cf.write(desc)
                            except Exception:
                                pass
                        return desc
            except Exception:
                continue

        return None


    def extract_search_query(self, media_path: str) -> str:
        """Derive primary search query: Song Name with Artist."""
        title, artist = extract_song_and_artist(media_path)
        if title and artist:
            return f"{title} {artist}"
        return title or Path(media_path).stem

    def get_candidate_queries(
        self,
        media_path: str,
        custom_query: Optional[str] = None,
        song_title: Optional[str] = None,
        artist_name: Optional[str] = None
    ) -> List[str]:
        """
        Derive prioritized search candidates:
        Prioritizes: Song Name with Artist (Highest hit-rate on LRCLIB / Musixmatch / NetEase).
        """
        candidates: List[str] = []

        # 1. Custom user query (if provided)
        if custom_query and custom_query.strip():
            candidates.append(custom_query.strip())

        # 2. User-provided explicit song_title and/or artist_name
        s_title = (song_title or "").strip()
        a_name = (artist_name or "").strip()
        if s_title and a_name:
            candidates.append(f"{s_title} {a_name}")
            candidates.append(f"{a_name} {s_title}")
            candidates.append(s_title)
            # Add cleaned short title variants (strip YouTube noise like : | Viral Song)
            clean_short = re.sub(r'\(.*?\)|\[.*?\]|[:：|｜\-–—].*', '', s_title).strip()
            if clean_short and len(clean_short) >= 3 and clean_short != s_title:
                candidates.append(f"{clean_short} {a_name}")
                candidates.append(clean_short)
        elif s_title:
            candidates.append(s_title)
            clean_short = re.sub(r'\(.*?\)|\[.*?\]|[:：|｜\-–—].*', '', s_title).strip()
            if clean_short and len(clean_short) >= 3 and clean_short != s_title:
                candidates.append(clean_short)
        elif a_name:
            candidates.append(a_name)

        # 3. Metadata tags (mutagen)
        meta_title, meta_artist = extract_song_and_artist(media_path)
        clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', meta_title).strip()
        if clean_title and meta_artist:
            cand_song_art = f"{clean_title} {meta_artist}".strip()
            if cand_song_art not in candidates:
                candidates.append(cand_song_art)  # Song Name with Artist
            cand_art_song = f"{meta_artist} {clean_title}".strip()
            if cand_art_song not in candidates:
                candidates.append(cand_art_song)  # Artist with Song Name
            if clean_title not in candidates:
                candidates.append(clean_title)     # Song Name alone
        elif clean_title and clean_title not in candidates:
            candidates.append(clean_title)

        # 4. Filename stem fallback
        stem = Path(media_path).stem
        cleaned = re.sub(r'(_clean|_censored)+$', '', stem, flags=re.I)
        cleaned = re.sub(r'\(.*?\)|\[.*?\]|official audio|lyrics|official video', '', cleaned, flags=re.I)
        cleaned = re.sub(r'[:：|｜_\-–—]+', ' ', cleaned).strip()
        if cleaned and cleaned not in candidates:
            if " - " in cleaned:
                parts = cleaned.split(" - ", 1)
                part_art, part_tit = parts[0].strip(), parts[1].strip()
                if f"{part_tit} {part_art}" not in candidates:
                    candidates.append(f"{part_tit} {part_art}")  # Song Name with Artist
                if f"{part_art} {part_tit}" not in candidates:
                    candidates.append(f"{part_art} {part_tit}")  # Artist with Song Name
                if part_tit and part_tit not in candidates:
                    candidates.append(part_tit)
            candidates.append(cleaned)

        # Filter out empty or extremely short candidates (< 3 chars)
        final_candidates: List[str] = []
        for c in candidates:
            c = c.strip()
            if len(c) >= 3 and c not in final_candidates:
                final_candidates.append(c)

        return final_candidates

    def fetch_synced_words(
        self,
        media_path: str,
        custom_query: Optional[str] = None,
        custom_lrc_text: Optional[str] = None,
        song_title: Optional[str] = None,
        artist_name: Optional[str] = None,
        youtube_desc: Optional[str] = None
    ) -> Optional[List[WordTimestamp]]:
        """
        Fetch synchronized lyrics in strict 3-Phase Priority:
        PHASE 1 (100% Pre-Timed):
          1A. Custom pasted [mm:ss] lyrics
          1B. Local .lrc file
          1C. YouTube Description with explicit timestamps (0:15 ..., chapters)
          1D. Online Synced Databases (LRCLIB, Musixmatch, NetEase)
        PHASE 2 (Untimed Ground-Truth Lyrics -> AI Audio Alignment):
          2A. Untimed lyrics block from YouTube description
          2B. Custom pasted untimed lyrics
        PHASE 3:
          Return None -> Fallback to pure OpenAI Whisper AI speech recognition
        """
        self.last_source = None
        self.last_matched_query = None
        self.last_raw_lyrics = None
        self.last_timed_lines = []
        self.is_untimed = False

        p = Path(media_path)
        local_lrc = p.with_suffix(".lrc")

        # =====================================================================
        # PHASE 1: Exhaust 100% Pre-Timed Lyrics Sources First
        # =====================================================================

        # 1A. Custom pasted [mm:ss] lyrics
        if custom_lrc_text and custom_lrc_text.strip():
            parsed_timed = parse_lrc_lines(custom_lrc_text)
            if parsed_timed:
                words = parse_lrc_content(custom_lrc_text)
                if words:
                    self.last_source = "custom"
                    self.is_untimed = False
                    self.last_raw_lyrics = custom_lrc_text
                    self.last_timed_lines = parsed_timed
                    return words

        # 1B. Local .lrc file
        if local_lrc.exists():
            try:
                with open(local_lrc, "r", encoding="utf-8", errors="ignore") as f:
                    content_lrc = f.read()
                words = parse_lrc_content(content_lrc)
                if words:
                    self.last_source = "local"
                    self.is_untimed = False
                    self.last_matched_query = local_lrc.name
                    self.last_raw_lyrics = content_lrc
                    self.last_timed_lines = parse_lrc_lines(content_lrc)
                    return words
            except Exception:
                pass

        # 1C. YouTube description with EXPLICIT timestamps
        yt_desc_text = self._get_youtube_description_text(media_path, youtube_desc)
        yt_untimed_result = None
        if yt_desc_text:
            duration = get_audio_duration(media_path)
            yt_res = extract_lyrics_from_youtube_description(yt_desc_text, total_duration=duration)
            if yt_res and len(yt_res) >= 2:
                if not getattr(yt_res, "is_untimed", False):
                    # Pre-timed lyrics in YouTube description!
                    lrc_lines = [f"[{int(ts // 60):02d}:{ts % 60:05.2f}] {text}" for ts, text in yt_res]
                    formatted_lrc = "\n".join(lrc_lines)
                    words = parse_lrc_content(formatted_lrc)
                    if words:
                        self.last_source = "youtube_description (timed)"
                        self.is_untimed = False
                        self.last_matched_query = "YouTube Description"
                        self.last_raw_lyrics = formatted_lrc
                        self.last_timed_lines = yt_res
                        return words
                else:
                    yt_untimed_result = yt_res

        # 1D. Online Synced Databases (LRCLIB, Musixmatch, NetEase)
        if self.available:
            candidates = self.get_candidate_queries(
                media_path,
                custom_query=custom_query,
                song_title=song_title,
                artist_name=artist_name
            )
            for query in candidates:
                tokens = query.strip().split()
                if len(tokens) < 2 and not custom_query and not song_title:
                    continue
                try:
                    lrc = syncedlyrics.search(query)
                    if lrc:
                        words = parse_lrc_content(lrc)
                        if words and len(words) >= 5:
                            self.last_source = "online"
                            self.is_untimed = False
                            self.last_matched_query = query
                            self.last_raw_lyrics = lrc
                            self.last_timed_lines = parse_lrc_lines(lrc)
                            if not local_lrc.exists():
                                try:
                                    with open(local_lrc, "w", encoding="utf-8") as lf:
                                        lf.write(lrc)
                                except Exception:
                                    pass
                            return words
                except Exception:
                    continue

        # =====================================================================
        # PHASE 2: No Pre-Timed Lyrics Found! Check for Ground-Truth UNTIMED Lyrics
        # =====================================================================

        # 2A. Untimed lyrics from YouTube description (local file or embedded tags)
        if yt_untimed_result and len(yt_untimed_result) >= 2:
            lrc_lines = [f"[{int(ts // 60):02d}:{ts % 60:05.2f}] {text}" for ts, text in yt_untimed_result]
            formatted_lrc = "\n".join(lrc_lines)
            words = parse_lrc_content(formatted_lrc)
            if words:
                self.last_source = "youtube_description (untimed)"
                self.is_untimed = True
                self.last_matched_query = "YouTube Description"
                self.last_raw_lyrics = formatted_lrc
                self.last_timed_lines = yt_untimed_result
                return words

        # 2B. On-the-fly YouTube Description Search (fallback when local description is absent)
        search_desc_text = self._search_youtube_for_description(
            media_path,
            song_title=song_title,
            artist_name=artist_name
        )
        if search_desc_text:
            duration = get_audio_duration(media_path)
            yt_res = extract_lyrics_from_youtube_description(search_desc_text, total_duration=duration)
            if yt_res and len(yt_res) >= 2:
                lrc_lines = [f"[{int(ts // 60):02d}:{ts % 60:05.2f}] {text}" for ts, text in yt_res]
                formatted_lrc = "\n".join(lrc_lines)
                words = parse_lrc_content(formatted_lrc)
                if words:
                    self.last_source = "youtube_description (untimed)" if yt_res.is_untimed else "youtube_description (timed)"
                    self.is_untimed = yt_res.is_untimed
                    self.last_matched_query = "YouTube Description (Search)"
                    self.last_raw_lyrics = formatted_lrc
                    self.last_timed_lines = yt_res
                    return words

        # 2C. Custom pasted untimed lyrics
        if custom_lrc_text and custom_lrc_text.strip():
            raw_lines = [l.strip() for l in custom_lrc_text.splitlines() if l.strip()]
            if raw_lines:
                duration = get_audio_duration(media_path)
                dur = duration or (len(raw_lines) * 3.5 + 20.0)
                start_off = min(12.0, dur * 0.08)
                end_off = max(start_off + 10.0, dur - min(10.0, dur * 0.06))
                step = (end_off - start_off) / len(raw_lines)
                timed_lines = [(start_off + i * step, l) for i, l in enumerate(raw_lines)]
                lrc_lines = [f"[{int(ts // 60):02d}:{ts % 60:05.2f}] {text}" for ts, text in timed_lines]
                formatted_lrc = "\n".join(lrc_lines)
                self.last_source = "custom (untimed)"
                self.is_untimed = True
                self.last_raw_lyrics = formatted_lrc
                self.last_timed_lines = timed_lines
                return parse_lrc_content(formatted_lrc)

        # =====================================================================
        # PHASE 3: No lyrics anywhere -> Returns None (Triggers Whisper AI Fallback)
        # =====================================================================
        return None

    def get_annotated_lyrics_lines(self, profanity_detector=None) -> List[Tuple[float, str, bool]]:
        """
        Return list of (timestamp_seconds, annotated_line, has_cuss).
        Highlights detected cuss words with '>> word <<'.
        """
        if not self.last_timed_lines:
            return []

        results: List[Tuple[float, str, bool]] = []
        for ts, line in self.last_timed_lines:
            mins = int(ts // 60)
            secs = ts % 60
            ts_str = f"[{mins:02d}:{secs:05.2f}]"

            if not profanity_detector:
                results.append((ts, f"{ts_str} {line}", False))
                continue

            has_cuss = False
            annotated_line_text = line

            # 1. Multi-word phrase highlighting
            for phrase in profanity_detector.db.phrases:
                if phrase in line.lower():
                    pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                    annotated_line_text = pattern.sub(f">> {phrase} <<", annotated_line_text)
                    has_cuss = True
                    break

            # 2. Single token highlighting if no phrase matched
            if not has_cuss:
                tokens = line.split()
                annotated_tokens = []
                for t in tokens:
                    cleaned_token = re.sub(r'^[^\w*#\u0900-\u097F]+|[^\w*#\u0900-\u097F]+$', '', t)
                    if cleaned_token and profanity_detector.db.is_profane_word(cleaned_token):
                        annotated_tokens.append(f">> {t} <<")
                        has_cuss = True
                    else:
                        annotated_tokens.append(t)
                annotated_line = f"{ts_str} {' '.join(annotated_tokens)}"
            else:
                annotated_line = f"{ts_str} {annotated_line_text}"

            results.append((ts, annotated_line, has_cuss))

        return results
