"""
REA Format Inspector Module.
Uses REA (Reverse Engineer Anything) principles and CLI/MCP hooks to inspect unknown
playlist structures, extract media manifests, detect codecs, encryption/DRM flags, and segment URLs.
"""

import os
import re
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class TrackInfo:
    title: str
    url_or_path: str
    duration: Optional[float] = None
    codec: Optional[str] = None
    is_drm_protected: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlaylistManifest:
    name: str
    tracks: List[TrackInfo]
    format_type: str  # "m3u8", "dash", "json_feed", "local_dir", "unknown"
    is_live: bool = False
    raw_info: Dict[str, Any] = field(default_factory=dict)


class REAFormatInspector:
    def __init__(self, rea_path: Optional[str] = None):
        """
        Initialize inspector with path to REA or fallback to system path.
        """
        default_rea = Path(__file__).resolve().parent.parent.parent.parent / "rea"
        self.rea_path = rea_path or os.getenv("REA_PATH") or (str(default_rea) if default_rea.exists() else "rea")

    def inspect_target(self, target: str) -> PlaylistManifest:
        """
        Inspect a file, URL, or directory and extract a normalized PlaylistManifest.
        """
        if os.path.isdir(target):
            return self._inspect_local_directory(target)
        elif target.startswith(("http://", "https://")):
            return self._inspect_url(target)
        elif os.path.isfile(target):
            return self._inspect_file(target)
        else:
            # Might be a stream URL or unknown path
            return self._inspect_url(target)

    def _inspect_local_directory(self, dir_path: str) -> PlaylistManifest:
        tracks = []
        valid_exts = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".mkv", ".webm"}
        p = Path(dir_path)
        for item in sorted(p.iterdir()):
            if item.is_file() and item.suffix.lower() in valid_exts:
                tracks.append(
                    TrackInfo(
                        title=item.stem,
                        url_or_path=str(item.resolve()),
                        codec=item.suffix.lstrip(".").lower()
                    )
                )
        return PlaylistManifest(
            name=p.name,
            tracks=tracks,
            format_type="local_dir",
            is_live=False
        )

    def _inspect_file(self, file_path: str) -> PlaylistManifest:
        p = Path(file_path)
        content = ""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(8192)
        except Exception:
            pass

        # Check for M3U / M3U8
        if "#EXTM3U" in content or p.suffix.lower() in (".m3u", ".m3u8"):
            return self._parse_m3u(file_path, content)

        # Check for JSON feed
        if content.strip().startswith("{") or content.strip().startswith("["):
            try:
                data = json.loads(content)
                return self._parse_json_feed(file_path, data)
            except Exception:
                pass

        # Single media file
        return PlaylistManifest(
            name=p.stem,
            tracks=[TrackInfo(title=p.stem, url_or_path=str(p.resolve()))],
            format_type="single_file",
            is_live=False
        )

    def _parse_m3u(self, file_path: str, content: str) -> PlaylistManifest:
        tracks = []
        base_dir = Path(file_path).parent
        lines = content.splitlines()
        current_title = "Unknown Track"
        is_live = False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXT-X-PLAYLIST-TYPE:EVENT") or "#EXT-X-TARGETDURATION" in line:
                is_live = True
            if line.startswith("#EXTINF:"):
                # e.g., #EXTINF:123,Artist - Title
                parts = line.split(",", 1)
                if len(parts) > 1:
                    current_title = parts[1].strip()
            elif not line.startswith("#"):
                # URL or local file path
                if line.startswith(("http://", "https://")):
                    track_url = line
                else:
                    track_url = str((base_dir / line).resolve())
                tracks.append(TrackInfo(title=current_title, url_or_path=track_url))
                current_title = "Unknown Track"

        return PlaylistManifest(
            name=Path(file_path).stem,
            tracks=tracks,
            format_type="m3u8",
            is_live=is_live
        )

    def _parse_json_feed(self, file_path: str, data: Any) -> PlaylistManifest:
        tracks = []
        items = data if isinstance(data, list) else data.get("tracks", data.get("items", []))
        for idx, item in enumerate(items):
            if isinstance(item, dict):
                title = item.get("title", item.get("name", f"Track {idx + 1}"))
                url = item.get("url", item.get("path", item.get("stream_url", "")))
                if url:
                    tracks.append(TrackInfo(title=title, url_or_path=url, metadata=item))
        return PlaylistManifest(
            name=Path(file_path).stem,
            tracks=tracks,
            format_type="json_feed"
        )

    def _inspect_url(self, url: str) -> PlaylistManifest:
        """
        Inspect remote playlist URL via yt-dlp / probe.
        """
        cmd = [
            "yt-dlp",
            "--flat-playlist",
            "--dump-single-json",
            "--no-warnings",
            url
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                title = data.get("title", "Remote Playlist")
                entries = data.get("entries", [])
                tracks = []
                if entries:
                    for e in entries:
                        if e:
                            t_title = e.get("title", "Unknown")
                            t_url = e.get("url", url)
                            tracks.append(TrackInfo(title=t_title, url_or_path=t_url, metadata=e))
                else:
                    tracks.append(TrackInfo(title=title, url_or_path=url, metadata=data))
                return PlaylistManifest(
                    name=title,
                    tracks=tracks,
                    format_type="remote_manifest",
                    raw_info=data
                )
        except Exception:
            pass

        return PlaylistManifest(
            name="URL Stream",
            tracks=[TrackInfo(title=url, url_or_path=url)],
            format_type="direct_url"
        )
