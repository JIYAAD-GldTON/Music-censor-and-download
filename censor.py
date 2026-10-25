#!/usr/bin/env python3
"""
Hindi & English Audio Cuss Word Censoring Application.
Powered by OpenAI Whisper, FFmpeg, and REA (Reverse Engineer Anything).
"""

import sys
from pathlib import Path

# Force UTF-8 on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Ensure root directory is in sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from ui.cli import cli

if __name__ == "__main__":
    cli()
