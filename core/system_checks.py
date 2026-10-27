"""
System pre-flight checks for external tools and runtime binaries (FFmpeg, yt-dlp, etc.).
"""

import shutil
import sys
from typing import Dict, Tuple, Optional
from core.logger import get_logger

logger = get_logger("system_checks")

REQUIRED_BINARIES = {
    "ffmpeg": {
        "desc": "Audio and video processing engine",
        "install_guide": "Install FFmpeg and add it to PATH (e.g. 'winget install Gyan.FFmpeg' on Windows or 'brew install ffmpeg' on macOS)."
    },
    "ffprobe": {
        "desc": "Media format stream probe and inspector",
        "install_guide": "Included with standard FFmpeg distributions. Ensure ffprobe is on PATH."
    },
}

OPTIONAL_BINARIES = {
    "yt-dlp": {
        "desc": "High-quality YouTube / stream media downloader",
        "install_guide": "Install via 'pip install yt-dlp' or 'winget install yt-dlp'."
    },
    "spotdl": {
        "desc": "Spotify metadata and audio fetcher",
        "install_guide": "Install via 'pip install spotdl'."
    }
}


def check_binary(binary_name: str) -> bool:
    """Check if a binary exists in system PATH."""
    return shutil.which(binary_name) is not None


def verify_system_requirements() -> Dict[str, bool]:
    """
    Verify all required and optional binaries.
    Logs friendly guidance for any missing tools.
    """
    status: Dict[str, bool] = {}

    for bin_name, info in REQUIRED_BINARIES.items():
        found = check_binary(bin_name)
        status[bin_name] = found
        if not found:
            logger.warning(
                "Required tool '%s' was NOT found in system PATH. %s. %s",
                bin_name, info["desc"], info["install_guide"]
            )
        else:
            logger.debug("Found required tool: %s (%s)", bin_name, shutil.which(bin_name))

    for bin_name, info in OPTIONAL_BINARIES.items():
        found = check_binary(bin_name)
        status[bin_name] = found
        if not found:
            logger.debug(
                "Optional tool '%s' not found. %s. %s",
                bin_name, info["desc"], info["install_guide"]
            )

    return status
