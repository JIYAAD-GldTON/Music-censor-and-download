"""
Audio Output Device Inspector.
Extracts clean, user-friendly sound playback devices across Windows, macOS, and Linux,
filtering driver clones, virtual audio mappers, and internal path clutter.
"""

import sys
import re
from typing import List, Dict, Any
from collections.abc import Sequence
import sounddevice as sd
from core.logger import get_logger

logger = get_logger("devices")


def get_audio_output_devices() -> List[Dict[str, Any]]:
    """
    Retrieve clean, deduplicated audio output playback endpoints.
    Cross-platform support:
      - Windows: Prioritizes WASAPI endpoints, strips driver prefix clutter.
      - macOS: Resolves CoreAudio playback endpoints.
      - Linux: Resolves PulseAudio / ALSA playback endpoints.
    """
    try:
        devs = sd.query_devices()
        apis = sd.query_hostapis()
    except Exception as e:
        logger.debug("Failed querying audio devices: %s", e)
        return []

    is_windows = sys.platform == "win32"
    wasapi_api = next((h for h in apis if "WASAPI" in h.get("name", "")), None) if is_windows else None
    wasapi_default_out = wasapi_api["default_output_device"] if wasapi_api else -1

    try:
        default_out_idx = sd.default.device[1]
    except Exception:
        default_out_idx = -1

    default_out_name = ""
    if isinstance(devs, Sequence) and 0 <= default_out_idx < len(devs):
        dev_info = devs[default_out_idx]
        if isinstance(dev_info, dict):
            default_out_name = dev_info.get("name", "")

    primary_pool = []
    secondary_pool = []

    for idx, d in enumerate(devs):
        if not isinstance(d, dict) or d.get("max_output_channels", 0) <= 0:
            continue

        api_idx = d.get("hostapi", 0)
        api = apis[api_idx]["name"] if (isinstance(apis, Sequence) and 0 <= api_idx < len(apis)) else ""
        name = d.get("name", "").strip()

        # Skip raw mapper or generic driver placeholders
        if name in [
            "Microsoft Sound Mapper - Output",
            "Primary Sound Driver",
            "default",
            "sysdefault",
        ]:
            continue

        # Clean Windows driver path junk like @System32\drivers\bthhfenum...
        if "@system32" in name.lower() or "bthhfenum" in name.lower():
            m = re.search(r'\((.*?)\)', name)
            if m:
                name = m.group(1).strip()
            else:
                continue

        clean_name = re.sub(r'\s+', ' ', name).strip()
        # Clean driver prefixes like (2- Realtek) -> (Realtek)
        clean_name = re.sub(r'\(2-\s*', '(', clean_name)

        is_default = (
            idx == wasapi_default_out or
            idx == default_out_idx or
            (bool(default_out_name) and clean_name.lower().split("(")[0].strip() in default_out_name.lower())
        )

        entry = {
            "id": idx,
            "name": clean_name,
            "api": api,
            "channels": int(d.get("max_output_channels", 2)),
            "default_samplerate": int(d.get("default_samplerate", 48000)),
            "is_default": is_default
        }

        if is_windows and "WASAPI" in api:
            primary_pool.append(entry)
        elif not is_windows and ("Core Audio" in api or "PulseAudio" in api or "ALSA" in api):
            primary_pool.append(entry)
        else:
            secondary_pool.append(entry)

    chosen_pool = primary_pool if primary_pool else secondary_pool

    # Deduplicate by friendly name
    seen = set()
    filtered: List[Dict[str, Any]] = []
    for d in chosen_pool:
        key = d["name"].lower()
        if key not in seen:
            seen.add(key)
            filtered.append(d)

    # Sort so default device appears first
    filtered.sort(key=lambda x: (not x["is_default"], x["name"]))
    return filtered


# Backward compatibility alias
get_windows_output_devices = get_audio_output_devices
