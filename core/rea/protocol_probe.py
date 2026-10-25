"""
REA Protocol & Binary Probe Module.
Integrates with REA (Reverse Engineer Anything) CLI to analyze unknown media applications,
binaries, WebBundles, or network streams.
"""

import os
import json
import shutil
import subprocess
from typing import Dict, Any, Optional


class REAProtocolProbe:
    def __init__(self):
        # Check if npx is available
        self.npx_available = shutil.which("npx") is not None

    def run_rea_command(self, subcmd: str, target: str, extra_args: list = None) -> Dict[str, Any]:
        """
        Execute an REA command via `npx rea-agents <subcmd> <target>`
        """
        import sys
        npx_binary = "npx.cmd" if sys.platform == "win32" else "npx"
        args = [npx_binary, "--yes", "rea-agents", subcmd, target, "--format", "json"]
        if extra_args:
            args.extend(extra_args)

        try:
            res = subprocess.run(args, capture_output=True, text=True, timeout=60, shell=(sys.platform == "win32"))
            if res.returncode == 0:
                try:
                    return json.loads(res.stdout)
                except Exception:
                    return {"output": res.stdout}
            else:
                return {
                    "error": res.stderr.strip() or f"REA exited with code {res.returncode}",
                    "raw_output": res.stdout
                }
        except subprocess.TimeoutExpired:
            return {"error": "REA command timed out"}
        except Exception as e:
            return {"error": str(e)}

    def inspect_binary_or_app(self, target_path: str) -> Dict[str, Any]:
        """
        Use REA to inspect a local media player binary or Electron package.
        """
        if not os.path.exists(target_path):
            return {"error": f"Target not found: {target_path}"}
        
        # Check if it's an Electron/JS app or native binary
        if target_path.endswith((".js", ".asar", "package.json")) or os.path.isdir(target_path):
            return self.run_rea_command("analyze-javascript-application", target_path)
        else:
            return self.run_rea_command("inspect", target_path)

    def probe_stream_protocol(self, stream_url: str) -> Dict[str, Any]:
        """
        Probe a streaming protocol endpoint using ffprobe/curl + REA analysis.
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            stream_url
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                info = json.loads(res.stdout)
                streams = info.get("streams", [])
                audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
                return {
                    "url": stream_url,
                    "format": info.get("format", {}).get("format_name", "unknown"),
                    "duration": info.get("format", {}).get("duration", "live"),
                    "audio_codecs": [s.get("codec_name") for s in audio_streams],
                    "sample_rate": [s.get("sample_rate") for s in audio_streams],
                    "channels": [s.get("channels") for s in audio_streams],
                    "raw_probe": info
                }
            else:
                return {"error": f"ffprobe error: {res.stderr}"}
        except Exception as e:
            return {"error": str(e)}
