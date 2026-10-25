"""
Windows Audio Output Device Inspector.
Extracts clean, friendly Windows sound playback devices (matching Windows Sound Settings),
filtering out driver duplicates (MME/DirectSound/WDM-KS) and internal driver path clutter.
"""

import re
from typing import List, Dict, Any
from collections.abc import Sequence
import sounddevice as sd


def get_windows_output_devices() -> List[Dict[str, Any]]:
    """
    Retrieve clean, important audio output playback devices matching Windows Sound Settings.
    Deduplicates driver clones and marks the system default playback endpoint.
    """
    try:
        devs = sd.query_devices()
        apis = sd.query_hostapis()
        wasapi_api = next((h for h in apis if "WASAPI" in h.get("name", "")), None)
        wasapi_default_out = wasapi_api["default_output_device"] if wasapi_api else -1
        default_out_idx = sd.default.device[1]
        default_out_name = ""
        if isinstance(devs, Sequence) and 0 <= default_out_idx < len(devs):
            dev_info = devs[default_out_idx]
            if isinstance(dev_info, dict):
                default_out_name = dev_info.get("name", "")
    except Exception:
        return []

    wasapi_devs = []
    other_devs = []

    for idx, d in enumerate(devs):
        if not isinstance(d, dict) or d.get("max_output_channels", 0) <= 0:
            continue

        api_idx = d.get("hostapi", 0)
        api = apis[api_idx]["name"] if (isinstance(apis, Sequence) and 0 <= api_idx < len(apis)) else ""
        name = d.get("name", "").strip()

        # Skip raw mapper or generic driver placeholders
        if name in ["Microsoft Sound Mapper - Output", "Primary Sound Driver"]:
            continue

        # Clean driver path junk like @System32\drivers\bthhfenum...
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

        if "WASAPI" in api:
            wasapi_devs.append(entry)
        else:
            other_devs.append(entry)

    # Windows native audio endpoints are exposed via WASAPI
    chosen_pool = wasapi_devs if wasapi_devs else other_devs

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
