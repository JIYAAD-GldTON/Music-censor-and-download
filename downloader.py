"""
High-Quality Music Downloader with Explicit Bitrate & Quality Control.
Supports YouTube, YouTube Music, Spotify, JioSaavn, SoundCloud, and direct stream links.
Downloads single songs or entire playlists in user-selected audio qualities.
"""

import os
import sys
import glob
import subprocess
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

# Explicit Quality Profiles with Bitrates and Codecs
QUALITY_PROFILES: Dict[str, Dict[str, Any]] = {
    "FLAC (Lossless Studio Quality, ~1411 kbps)": {
        "ext": "flac",
        "ytdl_format": "flac",
        "ytdl_quality": "0",
        "spotdl_format": "flac",
        "spotdl_bitrate": "auto",
        "bitrate_label": "1411 kbps (Lossless)",
        "desc": "Bit-perfect lossless compression. Highest fidelity audio."
    },
    "MP3 320 kbps (Extreme Quality)": {
        "ext": "mp3",
        "ytdl_format": "mp3",
        "ytdl_quality": "320k",
        "spotdl_format": "mp3",
        "spotdl_bitrate": "320k",
        "bitrate_label": "320 kbps (CBR/VBR0)",
        "desc": "Industry maximum MP3 bitrate. Rich low-end and crystal clear highs."
    },
    "AAC 256 kbps (High Quality M4A)": {
        "ext": "m4a",
        "ytdl_format": "m4a",
        "ytdl_quality": "256k",
        "spotdl_format": "m4a",
        "spotdl_bitrate": "256k",
        "bitrate_label": "256 kbps AAC",
        "desc": "High-efficiency Apple/YouTube standard. Excellent transparency."
    },
    "Opus (Native Best Stream, 0 Re-encode Loss)": {
        "ext": "opus",
        "ytdl_format": "opus",
        "ytdl_quality": "0",
        "spotdl_format": "opus",
        "spotdl_bitrate": "auto",
        "bitrate_label": "160 kbps Native Opus",
        "desc": "Untouched original server audio stream without generation loss."
    },
    "WAV (Uncompressed Studio PCM, 1411 kbps)": {
        "ext": "wav",
        "ytdl_format": "wav",
        "ytdl_quality": "0",
        "spotdl_format": "wav",
        "spotdl_bitrate": "auto",
        "bitrate_label": "1411 kbps Linear PCM",
        "desc": "Raw uncompressed studio wave format."
    },
    "MP3 192 kbps (Standard Quality)": {
        "ext": "mp3",
        "ytdl_format": "mp3",
        "ytdl_quality": "192k",
        "spotdl_format": "mp3",
        "spotdl_bitrate": "192k",
        "bitrate_label": "192 kbps",
        "desc": "Smaller file size with balanced sound reproduction."
    }
}


def get_profile(quality_key: str) -> Dict[str, Any]:
    """Retrieve profile by full key, short key, or fallback to 320kbps MP3."""
    if quality_key in QUALITY_PROFILES:
        return QUALITY_PROFILES[quality_key]

    k_lower = quality_key.lower()
    for full_key, profile in QUALITY_PROFILES.items():
        if k_lower in full_key.lower() or k_lower == profile["ext"]:
            return profile

    # Default fallback
    return QUALITY_PROFILES["MP3 320 kbps (Extreme Quality)"]


def download_song_or_playlist(
    url: str,
    output_dir: str = "./downloads",
    quality: str = "MP3 320 kbps (Extreme Quality)",
    is_single: bool = True
) -> Tuple[bool, Optional[str], str]:
    """
    Download a single song or playlist in the specified audio quality.
    Returns: (success: bool, target_path: Optional[str], status_message: str)
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    profile = get_profile(quality)
    ext = profile["ext"]
    bitrate_label = profile["bitrate_label"]

    # Pre-snapshot files in target folder to identify newly created file
    existing_files = set(out_path.glob("*.*"))

    if "spotify.com" in url:
        # Spotify link via spotDL
        spot_cmd = [
            sys.executable, "-m", "spotdl",
            url,
            "--output", str(out_path / "{artist} - {title}.{output-ext}"),
            "--format", profile["spotdl_format"],
        ]
        if profile["spotdl_bitrate"] != "auto":
            spot_cmd.extend(["--bitrate", profile["spotdl_bitrate"]])

        try:
            res = subprocess.run(spot_cmd, capture_output=True, text=True, timeout=300)
            if res.returncode == 0:
                new_files = list(set(out_path.glob(f"*.{ext}")) - existing_files)
                newest = max(new_files, key=os.path.getctime) if new_files else None
                result_path = str(newest) if newest else str(out_path)
                return True, result_path, f"Successfully downloaded ({bitrate_label})"
            else:
                err_text = res.stderr.strip() or res.stdout.strip()
                return False, None, f"spotDL error: {err_text[:200]}"
        except Exception as e:
            return False, None, f"Download failed: {str(e)}"

    else:
        # YouTube, JioSaavn, SoundCloud, direct link via yt-dlp
        output_template = "%(title)s.%(ext)s" if is_single else "%(playlist_title,uploader)s/%(title)s.%(ext)s"
        cmd = [
            "yt-dlp",
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", profile["ytdl_format"],
            "--audio-quality", profile["ytdl_quality"],
            "--embed-metadata",
            "--embed-thumbnail",
            "--write-description",
            "--no-playlist" if is_single else "--yes-playlist",
            "-o", str(out_path / output_template),
            url
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if res.returncode == 0:
                new_files = list(set(out_path.glob("*.*")) - existing_files)
                if new_files:
                    audio_new = [f for f in new_files if f.suffix.lower() in [f".{ext}", ".mp3", ".m4a", ".flac", ".wav", ".opus"]]
                    newest = max(audio_new, key=os.path.getctime) if audio_new else max(new_files, key=os.path.getctime)
                    return True, str(newest), f"Successfully downloaded: {newest.name} ({bitrate_label})"
                return True, str(out_path), f"Successfully downloaded to: {out_path} ({bitrate_label})"
            else:
                err_text = res.stderr.strip() or res.stdout.strip()
                return False, None, f"yt-dlp error: {err_text[:200]}"
        except Exception as e:
            return False, None, f"Download failed: {str(e)}"


# Alias for backward compatibility
def download_high_quality(url: str, output_dir: str = "./downloads", audio_format: str = "flac") -> bool:
    success, _, _ = download_song_or_playlist(url, output_dir=output_dir, quality=audio_format)
    return success
