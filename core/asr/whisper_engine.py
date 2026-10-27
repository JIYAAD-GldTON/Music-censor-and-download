"""
Whisper Speech-to-Text Engine.
Wraps OpenAI Whisper to extract word-level timestamps from audio and video files.
"""

from typing import List, Optional, Tuple
import os
import whisper
from core.filter.detector import WordTimestamp
from core.asr.lyrics_provider import OnlineLyricsProvider
from core.logger import get_logger

logger = get_logger("asr.whisper")


class WhisperEngine:
    def __init__(self, model_name: str = "base", device: Optional[str] = None):
        """
        Initialize Whisper model and Online Lyrics Provider.
        model_name: 'tiny', 'base', 'small', 'medium', 'large'
        device: 'cuda', 'cpu', or None (auto-selected by torch/whisper)
        """
        self.model_name = model_name
        self.device = device
        self._model = None
        self.lyrics_provider = OnlineLyricsProvider()

    @property
    def model(self):
        if self._model is None:
            # Lazy load model on first use
            logger.info("Loading Whisper '%s' model...", self.model_name)
            self._model = whisper.load_model(self.model_name, device=self.device)
        return self._model

    def transcribe(
        self,
        media_path: str,
        language: Optional[str] = None,
        task: str = "transcribe",
        prefer_online_lyrics: bool = True,
        custom_query: Optional[str] = None,
        custom_lrc_text: Optional[str] = None,
        song_title: Optional[str] = None,
        artist_name: Optional[str] = None,
        youtube_desc: Optional[str] = None,
        intro_offset: Optional[float] = None
    ) -> List[WordTimestamp]:
        """
        Transcribe audio/video file and return a list of WordTimestamp objects with word-level timestamps.
        If prefer_online_lyrics=True: checks local .lrc file, YouTube description lyrics, or online synced lyrics first (Song Name with Artist).
        Falls back to local OpenAI Whisper if not found or if query is ambiguous.
        """
        if not os.path.exists(media_path):
            raise FileNotFoundError(f"Media file not found: {media_path}")

        self.last_source = None

        # Step 2A: Check local .lrc, YouTube description, or online synced lyrics
        if prefer_online_lyrics or (custom_lrc_text and custom_lrc_text.strip()) or youtube_desc:
            synced_words = self.lyrics_provider.fetch_synced_words(
                media_path,
                custom_query=custom_query,
                custom_lrc_text=custom_lrc_text,
                song_title=song_title,
                artist_name=artist_name,
                youtube_desc=youtube_desc
            )
            if synced_words:
                if getattr(self.lyrics_provider, "is_untimed", False):
                    try:
                        logger.info("Untimed lyrics detected (%d lines). Running AI Audio Alignment with Whisper...", len(self.lyrics_provider.last_timed_lines))
                        align_kwargs = {
                            "task": task,
                            "initial_prompt": "Hindi, Hinglish, English rap songs, hip hop lyrics, slang, profanity, cuss words."
                        }
                        if language and language.lower() not in ("auto", "all"):
                            align_kwargs["language"] = language.lower()
                        w_res = self.model.transcribe(media_path, **align_kwargs)
                        segs = w_res.get("segments", [])
                        if segs:
                            from core.asr.lyrics_provider import align_lyrics_with_whisper_segments, parse_lrc_content, get_audio_duration
                            raw_lines = [line for _, line in self.lyrics_provider.last_timed_lines]
                            aligned = align_lyrics_with_whisper_segments(
                                raw_lines,
                                segs,
                                total_duration=get_audio_duration(media_path),
                                intro_offset=intro_offset
                            )
                            lrc_lines = [f"[{int(ts // 60):02d}:{ts % 60:05.2f}] {text}" for ts, text in aligned]
                            formatted_lrc = "\n".join(lrc_lines)
                            aligned_words = parse_lrc_content(formatted_lrc)
                            if aligned_words:
                                synced_words = aligned_words
                                self.lyrics_provider.last_timed_lines = aligned
                                self.lyrics_provider.last_raw_lyrics = formatted_lrc
                                self.lyrics_provider.last_source = f"{self.lyrics_provider.last_source} (AI Aligned)"
                                self.lyrics_provider.is_untimed = False
                                logger.info("AI Audio Alignment complete: %d lines synchronized to vocals.", len(aligned))
                    except Exception as e:
                        logger.warning("AI Audio Alignment fallback warning: %s", e)

                self.last_source = self.lyrics_provider.last_source or "lyrics"
                logger.info("Using synchronized lyrics for '%s' (%d words).", os.path.basename(media_path), len(synced_words))
                return synced_words
            else:
                logger.info("Running local OpenAI Whisper (%s)...", self.model_name)

        self.last_source = "whisper"
        kwargs = {
            "word_timestamps": True,
            "task": task,
            "initial_prompt": "Hindi, Hinglish, English rap songs, hip hop lyrics, slang, profanity, cuss words.",
        }
        if language and language.lower() not in ("auto", "all"):
            kwargs["language"] = language.lower()

        result = self.model.transcribe(media_path, **kwargs)
        
        words: List[WordTimestamp] = []
        for segment in result.get("segments", []):
            # Check for word-level timestamps
            seg_words = segment.get("words", [])
            if seg_words:
                for w in seg_words:
                    word_str = w.get("word", "").strip()
                    if word_str:
                        words.append(
                            WordTimestamp(
                                word=word_str,
                                start=float(w.get("start", segment.get("start", 0.0))),
                                end=float(w.get("end", segment.get("end", 0.0))),
                                confidence=float(w.get("probability", 1.0))
                            )
                        )
            else:
                # Fallback: estimate or use segment boundaries
                text = segment.get("text", "").strip()
                if text:
                    sub_words = text.split()
                    seg_start = float(segment.get("start", 0.0))
                    seg_end = float(segment.get("end", 0.0))
                    duration = max(0.01, seg_end - seg_start)
                    w_dur = duration / max(1, len(sub_words))
                    for i, sw in enumerate(sub_words):
                        words.append(
                            WordTimestamp(
                                word=sw,
                                start=seg_start + i * w_dur,
                                end=seg_start + (i + 1) * w_dur,
                                confidence=1.0
                            )
                        )
        return words

    @property
    def last_raw_lyrics(self) -> Optional[str]:
        return self.lyrics_provider.last_raw_lyrics

    @property
    def last_timed_lines(self) -> List[Tuple[float, str]]:
        return self.lyrics_provider.last_timed_lines

    def get_annotated_lyrics_lines(self, profanity_detector=None):
        return self.lyrics_provider.get_annotated_lyrics_lines(profanity_detector=profanity_detector)
