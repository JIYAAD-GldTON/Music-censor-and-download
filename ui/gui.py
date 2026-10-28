"""
Cuss-Censor Desktop GUI — Full Fidelity Light Theme (Lite Mode).
Features:
- Single Song Censoring & Direct High-Quality URL Downloader
- Playlist / Batch Censoring & High-Quality Playlist Downloader
- Explicit Audio Quality Selection with Bitrates (FLAC 1411k, MP3 320k, AAC 256k, Opus, WAV)
- REA (Reverse Engineer Anything) Stream & App Probe
- Windows Audio Playback Device Monitor (Clean Output Endpoints)
"""

import os
import sys
import json
import re
import threading
from typing import Optional, List, Tuple
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

# Ensure root dir in path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from core.filter.detector import ProfanityDetector
from core.asr.whisper_engine import WhisperEngine
from core.censor.ffmpeg_censor import FFmpegCensor
from core.rea.format_inspector import REAFormatInspector
from core.rea.protocol_probe import REAProtocolProbe
from core.asr.lyrics_provider import extract_song_and_artist, OnlineLyricsProvider
from core.devices import get_windows_output_devices
from modes.playlist_mode import PlaylistCensorRunner
from downloader import QUALITY_PROFILES, download_song_or_playlist

# Default strictly to Light Theme (Lite Mode) with modern theme styling
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


def parse_shift_offset(shift_str: str) -> float:
    try:
        val_str = shift_str.split()[0].replace("s", "")
        return float(val_str)
    except Exception:
        return 0.0


class CussCensorGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🔇 Cuss-Censor — Hindi & English Audio Censor (Lite Theme)")
        self.geometry("1040x760")
        self.minsize(920, 680)

        # Concurrency lock & cancellation controls
        self._busy = False
        self._cancel_event = threading.Event()

        # Main Tabview (Clean 3-Tab Interface)
        self.tabview = ctk.CTkTabview(self, corner_radius=12)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=12)

        self.tab_file = self.tabview.add("📁 Single Song / File")
        self.tab_playlist = self.tabview.add("🎵 Playlist & Batch Mode")
        self.tab_devices = self.tabview.add("🎧 Audio Output Devices")

        # Build tabs
        self._build_file_tab()
        self._build_playlist_tab()
        self._build_devices_tab()

    def _change_theme(self, choice: str):
        if "Dark" in choice:
            ctk.set_appearance_mode("Dark")
        elif "System" in choice:
            ctk.set_appearance_mode("System")
        else:
            ctk.set_appearance_mode("Light")

    def _set_busy(self, busy: bool):
        """Toggle UI controls during long-running tasks to prevent race conditions."""
        self._busy = busy
        state = "disabled" if busy else "normal"
        cancel_state = "normal" if busy else "disabled"
        if busy:
            self._cancel_event.clear()

        for btn in [
            getattr(self, "single_dl_btn", None),
            getattr(self, "file_run_btn", None),
            getattr(self, "file_find_lyrics_btn", None),
            getattr(self, "pl_download_btn", None),
            getattr(self, "pl_run_btn", None),
        ]:
            if btn:
                try:
                    btn.configure(state=state)
                except Exception:
                    pass

        for cbtn in [
            getattr(self, "file_cancel_btn", None),
            getattr(self, "pl_cancel_btn", None),
        ]:
            if cbtn:
                try:
                    cbtn.configure(state=cancel_state)
                except Exception:
                    pass

    def _cancel_active_task(self):
        """Signal active background worker to terminate gracefully."""
        if hasattr(self, "_cancel_event"):
            self._cancel_event.set()
            if hasattr(self, "file_log"):
                self.file_log.insert("end", "\n[Cancellation requested. Aborting in-progress task...]\n")
            if hasattr(self, "pl_log"):
                self.pl_log.insert("end", "\n[Cancellation requested. Aborting in-progress task...]\n")

    # -------------------------------------------------------------------------
    # TAB 1: Single Song / File (With Direct Downloader)
    # -------------------------------------------------------------------------
    def _build_file_tab(self):
        tab = self.tab_file

        # Section 1: Online Single Song Downloader
        dl_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=("#ffffff", "#212529"), border_width=1, border_color=("#dee2e6", "#343a40"))
        dl_card.pack(fill="x", padx=15, pady=(10, 8))

        ctk.CTkLabel(
            dl_card,
            text="📥 Download Single Song by URL (Spotify, YouTube, JioSaavn, SoundCloud)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#1971c2"
        ).pack(anchor="w", padx=12, pady=(8, 4))

        url_row = ctk.CTkFrame(dl_card, fg_color="transparent")
        url_row.pack(fill="x", padx=12, pady=(0, 6))

        self.single_url_entry = ctk.CTkEntry(
            url_row,
            placeholder_text="Paste single track URL (e.g. https://www.youtube.com/watch?v=... or Spotify link)",
            font=ctk.CTkFont(size=12)
        )
        self.single_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # Explicit Quality Selector
        quality_options = list(QUALITY_PROFILES.keys())
        self.single_quality_var = ctk.StringVar(value=quality_options[1])  # MP3 320k
        self.single_quality_menu = ctk.CTkOptionMenu(
            url_row,
            values=quality_options,
            variable=self.single_quality_var,
            width=270,
            font=ctk.CTkFont(size=11),
            command=self._on_single_quality_change
        )
        self.single_quality_menu.pack(side="left", padx=(0, 10))

        self.single_dl_btn = ctk.CTkButton(
            url_row,
            text="📥 Download Song",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#2b8a3e",
            hover_color="#237032",
            width=130,
            command=self._download_single_song
        )
        self.single_dl_btn.pack(side="right")

        self.single_quality_desc_label = ctk.CTkLabel(
            dl_card,
            text=QUALITY_PROFILES[quality_options[1]]["desc"] + f" [Bitrate: {QUALITY_PROFILES[quality_options[1]]['bitrate_label']}]",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#868e96"
        )
        self.single_quality_desc_label.pack(anchor="w", padx=12, pady=(0, 8))

        # Section 2: Input Media Path (Local File or Downloaded Song)
        media_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=("#ffffff", "#212529"), border_width=1, border_color=("#dee2e6", "#343a40"))
        media_card.pack(fill="x", padx=15, pady=6)

        ctk.CTkLabel(media_card, text="Target File to Censor (Audio or Video):", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(8, 2))
        f_row = ctk.CTkFrame(media_card, fg_color="transparent")
        f_row.pack(fill="x", padx=12, pady=(0, 6))

        self.file_in_entry = ctk.CTkEntry(f_row, placeholder_text="Select local file or download a track above...")
        self.file_in_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        browse_btn = ctk.CTkButton(f_row, text="Browse File...", width=100, command=self._browse_input_file)
        browse_btn.pack(side="right")

        # Output Path
        ctk.CTkLabel(media_card, text="Cleaned Output Destination:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(4, 2))
        o_row = ctk.CTkFrame(media_card, fg_color="transparent")
        o_row.pack(fill="x", padx=12, pady=(0, 6))

        self.file_out_entry = ctk.CTkEntry(o_row, placeholder_text="Auto-filled with _clean.ext")
        self.file_out_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        save_btn = ctk.CTkButton(o_row, text="Change...", width=100, command=self._browse_output_file)
        save_btn.pack(side="right")

        # Song Title and Artist Fields (Search Song Name with Artist)
        song_row = ctk.CTkFrame(media_card, fg_color="transparent")
        song_row.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(song_row, text="Song Name:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#495057").pack(side="left", padx=(0, 4))
        self.file_song_entry = ctk.CTkEntry(song_row, placeholder_text="e.g. 'Khatta Flow' or 'Gojira' (auto-detected)", width=210)
        self.file_song_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkLabel(song_row, text="Artist:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#495057").pack(side="left", padx=(0, 4))
        self.file_artist_entry = ctk.CTkEntry(song_row, placeholder_text="e.g. 'Seedhe Maut' or 'KR$NA' (auto-detected)", width=170)
        self.file_artist_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.file_find_lyrics_btn = ctk.CTkButton(
            song_row,
            text="🔍 Find Lyrics",
            width=100,
            fg_color="#0c8599",
            hover_color="#0b7285",
            font=ctk.CTkFont(weight="bold"),
            command=self._find_and_display_lyrics
        )
        self.file_find_lyrics_btn.pack(side="right")

        # Optional Custom .LRC Synced Lyrics Row
        lrc_row = ctk.CTkFrame(media_card, fg_color="transparent")
        lrc_row.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkLabel(lrc_row, text="Lyrics (.LRC / Paste):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#495057").pack(side="left", padx=(0, 8))
        self.file_lrc_entry = ctk.CTkEntry(lrc_row, placeholder_text="Auto-detects local .lrc file or browse / paste lyrics...")
        self.file_lrc_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        lrc_btn = ctk.CTkButton(lrc_row, text="Browse .LRC...", width=95, fg_color="#495057", hover_color="#343a40", command=self._browse_lrc_file)
        lrc_btn.pack(side="left", padx=(0, 6))

        paste_btn = ctk.CTkButton(lrc_row, text="📋 Paste Lyrics", width=95, fg_color="#1864ab", hover_color="#155592", command=self._open_paste_lyrics_dialog)
        paste_btn.pack(side="left", padx=(0, 6))

        view_lyrics_btn = ctk.CTkButton(lrc_row, text="👁️ View Full", width=85, fg_color="#495057", hover_color="#343a40", command=self._view_full_lyrics_dialog)
        view_lyrics_btn.pack(side="right")

        # Section 3: Censor Options & Action Button
        opt_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=("#ffffff", "#212529"), border_width=1, border_color=("#dee2e6", "#343a40"))
        opt_card.pack(fill="x", padx=15, pady=6)

        opt_row = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_row.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(opt_row, text="Effect:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 4))
        self.file_mode_var = ctk.StringVar(value="beep")
        self.file_mode_menu = ctk.CTkOptionMenu(opt_row, values=["beep", "mute"], variable=self.file_mode_var, width=85)
        self.file_mode_menu.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(opt_row, text="Lang:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 4))
        self.file_lang_var = ctk.StringVar(value="all")
        self.file_lang_menu = ctk.CTkOptionMenu(opt_row, values=["all", "hi", "en"], variable=self.file_lang_var, width=85)
        self.file_lang_menu.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(opt_row, text="Model:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 4))
        self.file_model_var = ctk.StringVar(value="base (Balanced)")
        self.file_model_menu = ctk.CTkOptionMenu(
            opt_row,
            values=["tiny (Fast Lite)", "base (Balanced)", "small (High Accuracy)"],
            variable=self.file_model_var,
            width=150
        )
        self.file_model_menu.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(opt_row, text="Sync:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 4))
        self.file_shift_var = ctk.StringVar(value="0.0s (Normal)")
        self.file_shift_menu = ctk.CTkOptionMenu(
            opt_row,
            values=["0.0s (Normal)", "-0.5s (Fix Lag)", "-0.3s Earlier", "-0.7s Earlier", "+0.3s Later", "+0.5s Later"],
            variable=self.file_shift_var,
            width=125
        )
        self.file_shift_menu.pack(side="left", padx=(0, 10))

        self.file_use_web_lyrics_var = ctk.BooleanVar(value=True)
        self.file_web_lyrics_chk = ctk.CTkCheckBox(
            opt_row,
            text="🌐 Check Web Lyrics First",
            variable=self.file_use_web_lyrics_var,
            font=ctk.CTkFont(size=12)
        )
        self.file_web_lyrics_chk.pack(side="left", padx=(0, 10))

        self.file_run_btn = ctk.CTkButton(
            opt_row,
            text="▶ Start Censoring File",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1864ab",
            hover_color="#155592",
            height=34,
            command=self._start_file_censor
        )
        self.file_run_btn.pack(side="right", padx=(8, 0))

        self.file_cancel_btn = ctk.CTkButton(
            opt_row,
            text="⏹ Cancel",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#d6336c",
            hover_color="#a61e4d",
            width=80,
            height=34,
            command=self._cancel_active_task,
            state="disabled"
        )
        self.file_cancel_btn.pack(side="right")

        self.file_progress = ctk.CTkProgressBar(tab)
        self.file_progress.pack(fill="x", padx=15, pady=(4, 6))
        self.file_progress.set(0)

        # Output Log Box
        self.file_log = ctk.CTkTextbox(
            tab,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=("#ffffff", "#1e1e1e"),
            text_color=("#212529", "#f8f9fa"),
            border_width=1,
            border_color=("#dee2e6", "#343a40")
        )
        self.file_log.pack(fill="both", expand=True, padx=15, pady=(0, 10))

    def _on_single_quality_change(self, choice: str):
        profile = QUALITY_PROFILES.get(choice, {})
        self.single_quality_desc_label.configure(
            text=profile.get("desc", "") + f" [Bitrate: {profile.get('bitrate_label', '')}]"
        )

    def _download_single_song(self):
        url = self.single_url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a valid song URL to download.")
            return

        quality = self.single_quality_var.get()
        dest_dir = str((root_dir / "downloads").resolve())

        self._set_busy(True)
        self.single_dl_btn.configure(text="⏳ Downloading...")
        self.file_progress.set(0.0)
        self.file_log.delete("1.0", "end")
        self.file_log.insert("end", f"▶ Downloading single song in {quality}...\nURL: {url}\n")

        def progress_cb(pct: float, line_text: str):
            if pct >= 0:
                self.after(0, lambda p=pct/100.0: self.file_progress.set(p))
            if line_text:
                self.after(0, lambda t=line_text: self.file_log.insert("end", f"  {t}\n"))

        def worker():
            try:
                success, target_path, msg = download_song_or_playlist(
                    url,
                    output_dir=dest_dir,
                    quality=quality,
                    is_single=True,
                    progress_callback=progress_cb,
                    cancel_event=self._cancel_event
                )
                if success and target_path:
                    self.after(0, lambda: self.file_progress.set(1.0))
                    self.after(0, lambda: self.file_in_entry.delete(0, "end"))
                    self.after(0, lambda: self.file_in_entry.insert(0, target_path))

                    p = Path(target_path)
                    clean_path = str(p.parent / f"{p.stem}_clean{p.suffix}")
                    self.after(0, lambda: self.file_out_entry.delete(0, "end"))
                    self.after(0, lambda: self.file_out_entry.insert(0, clean_path))

                    # Auto-extract Song Title and Artist Name
                    title, artist = extract_song_and_artist(target_path)
                    self.after(0, lambda t=title, a=artist: (
                        self.file_song_entry.delete(0, "end"),
                        self.file_song_entry.insert(0, t),
                        self.file_artist_entry.delete(0, "end"),
                        self.file_artist_entry.insert(0, a)
                    ))

                    adj_lrc = p.with_suffix(".lrc")
                    adj_desc = p.with_suffix(".description")
                    if adj_lrc.exists():
                        self.after(0, lambda l=str(adj_lrc): (
                            self.file_lrc_entry.delete(0, "end"),
                            self.file_lrc_entry.insert(0, l)
                        ))
                    elif adj_desc.exists():
                        self.after(0, lambda d=str(adj_desc): (
                            self.file_lrc_entry.delete(0, "end"),
                            self.file_lrc_entry.insert(0, d)
                        ))

                    self.after(0, lambda: self.file_log.insert("end", f"\n✔ {msg}\nSaved to: {target_path}\nReady for censoring! Click 'Start Censoring File' below.\n"))
                    self.after(0, lambda: messagebox.showinfo("Downloaded", f"Song downloaded in {quality}!\n\nTarget path and metadata set."))
                else:
                    self.after(0, lambda: self.file_log.insert("end", f"\n❌ {msg}\n"))
                    self.after(0, lambda: messagebox.showerror("Download Error", msg))
            finally:
                self.after(0, lambda: self.single_dl_btn.configure(text="📥 Download Song"))
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _open_paste_lyrics_dialog(self):
        """Open a modal window to paste synced [mm:ss] lyrics or plain text."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Paste Synced Lyrics (.LRC)")
        dialog.geometry("640x480")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="Paste Synchronized Lyrics ([mm:ss.xx] line format):",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            dialog,
            text="Example:\n[00:19.40] Hero bane magar hai shakal se lund\n[00:27.04] Bitch im the one",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#868e96",
            justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 8))

        textbox = ctk.CTkTextbox(dialog, wrap="none", font=ctk.CTkFont(family="Consolas", size=12))
        textbox.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        if getattr(self, "_pasted_lyrics_text", None):
            textbox.insert("1.0", self._pasted_lyrics_text)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        def on_apply():
            txt = textbox.get("1.0", "end").strip()
            if txt:
                self._pasted_lyrics_text = txt
                self._last_fetched_lyrics = txt
                lines_count = len([line for line in txt.splitlines() if line.strip()])
                self.file_lrc_entry.delete(0, "end")
                self.file_lrc_entry.insert(0, f"[Custom Pasted Lyrics ({lines_count} lines)]")
            else:
                self._pasted_lyrics_text = None
            dialog.destroy()

        def on_clear():
            textbox.delete("1.0", "end")
            self._pasted_lyrics_text = None
            self.file_lrc_entry.delete(0, "end")

        ctk.CTkButton(btn_row, text="Clear", width=80, fg_color="#d6336c", hover_color="#a61e4d", command=on_clear).pack(side="left")
        ctk.CTkButton(btn_row, text="Cancel", width=80, fg_color="#868e96", hover_color="#495057", command=dialog.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_row, text="✔ Apply Lyrics", width=120, fg_color="#2b8a3e", hover_color="#237032", command=on_apply).pack(side="right")

    def _browse_input_file(self):
        f = filedialog.askopenfilename(
            title="Select Media File",
            filetypes=[("Media Files", "*.mp3 *.wav *.m4a *.aac *.flac *.opus *.mp4 *.mkv *.webm *.mov"), ("All Files", "*.*")]
        )
        if f:
            self.file_in_entry.delete(0, "end")
            self.file_in_entry.insert(0, f)
            p = Path(f)
            suggested_out = p.parent / f"{p.stem}_clean{p.suffix}"
            self.file_out_entry.delete(0, "end")
            self.file_out_entry.insert(0, str(suggested_out))

            # Auto-extract Song Title and Artist Name
            title, artist = extract_song_and_artist(f)
            self.file_song_entry.delete(0, "end")
            self.file_song_entry.insert(0, title)
            self.file_artist_entry.delete(0, "end")
            self.file_artist_entry.insert(0, artist)

            # Auto-detect adjacent .lrc file if exists
            adj_lrc = p.with_suffix(".lrc")
            if adj_lrc.exists():
                self.file_lrc_entry.delete(0, "end")
                self.file_lrc_entry.insert(0, str(adj_lrc))
                self._pasted_lyrics_text = None
            else:
                self.file_lrc_entry.delete(0, "end")
                self._pasted_lyrics_text = None

    def _browse_output_file(self):
        f = filedialog.asksaveasfilename(title="Save Cleaned File As")
        if f:
            self.file_out_entry.delete(0, "end")
            self.file_out_entry.insert(0, f)

    def _browse_lrc_file(self):
        f = filedialog.askopenfilename(
            title="Select Synced Lyrics (.lrc) File",
            filetypes=[("LRC Synced Lyrics", "*.lrc *.txt"), ("All Files", "*.*")]
        )
        if f:
            self._pasted_lyrics_text = None
            self.file_lrc_entry.delete(0, "end")
            self.file_lrc_entry.insert(0, f)

    def _view_full_lyrics_dialog(self):
        """Open a popup window displaying the current lyrics in full."""
        lrc_text = getattr(self, "_last_fetched_lyrics", None) or getattr(self, "_pasted_lyrics_text", None)
        lrc_file = self.file_lrc_entry.get().strip()
        if not lrc_text and lrc_file and os.path.exists(lrc_file):
            try:
                with open(lrc_file, "r", encoding="utf-8", errors="ignore") as lf:
                    lrc_text = lf.read()
            except Exception:
                pass

        if not lrc_text:
            messagebox.showinfo("Lyrics Viewer", "No lyrics loaded yet.\nClick '🔍 Find Lyrics' or '📋 Paste Lyrics' first.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Synchronized Lyrics Viewer")
        dialog.geometry("680x540")
        dialog.transient(self)

        song = self.file_song_entry.get().strip() or "Unknown Song"
        artist = self.file_artist_entry.get().strip() or "Unknown Artist"
        ctk.CTkLabel(
            dialog,
            text=f"📜 Synchronized Lyrics: {song} — {artist}",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=16, pady=(14, 6))

        textbox = ctk.CTkTextbox(dialog, wrap="none", font=ctk.CTkFont(family="Consolas", size=12))
        textbox.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        textbox.insert("1.0", lrc_text)

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        def copy_to_clipboard():
            self.clipboard_clear()
            self.clipboard_append(lrc_text)
            messagebox.showinfo("Copied", "Lyrics copied to clipboard!")

        ctk.CTkButton(btn_row, text="📋 Copy All", width=100, fg_color="#1864ab", hover_color="#155592", command=copy_to_clipboard).pack(side="left")
        ctk.CTkButton(btn_row, text="Close", width=90, fg_color="#868e96", hover_color="#495057", command=dialog.destroy).pack(side="right")

    def _find_and_display_lyrics(self):
        """Search and display synchronized lyrics online (Song Name + Artist) in the meantime."""
        inp = self.file_in_entry.get().strip()
        song_title = self.file_song_entry.get().strip()
        artist_name = self.file_artist_entry.get().strip()

        if not inp and not (song_title and artist_name):
            messagebox.showerror("Missing Information", "Please select a song file or enter Song Name and Artist.")
            return

        self.file_find_lyrics_btn.configure(state="disabled", text="⏳ Searching...")
        self.file_log.delete("1.0", "end")
        if song_title and artist_name:
            search_desc = f"'{song_title} {artist_name}'"
        elif song_title:
            search_desc = f"'{song_title}'"
        elif artist_name:
            search_desc = f"'{artist_name}'"
        else:
            search_desc = Path(inp).name if inp else "" 
        self.file_log.insert("end", f"▶ Searching online lyrics: Song Name + Artist -> {search_desc}...\n")

        def worker():
            try:
                prov = OnlineLyricsProvider()
                url_input = self.single_url_entry.get().strip()
                words = prov.fetch_synced_words(
                    inp if (inp and os.path.exists(inp)) else "dummy.mp3",
                    song_title=song_title,
                    artist_name=artist_name,
                    custom_lrc_text=getattr(self, "_pasted_lyrics_text", None),
                    youtube_desc=url_input if (url_input and ("youtube.com" in url_input or "youtu.be" in url_input)) else None
                )

                if words and prov.last_timed_lines:
                    self._last_fetched_lyrics = prov.last_raw_lyrics
                    shift_val = parse_shift_offset(self.file_shift_var.get())
                    detector = ProfanityDetector(pre_padding=0.25, post_padding=0.18, time_offset=shift_val)
                    annotated_lines = prov.get_annotated_lyrics_lines(profanity_detector=detector)
                    intervals = detector.detect_in_words(words)

                    header = (
                        f"\n========================================================================\n"
                        f"📜 FOUND SYNCHRONIZED LYRICS ({len(prov.last_timed_lines)} lines | {len(words)} words)\n"
                        f"Source: {prov.last_source.upper()} | Matched Query: '{prov.last_matched_query}'\n"
                        f"========================================================================\n"
                    )
                    self.after(0, lambda: self.file_log.insert("end", header))

                    for ts, line, has_cuss in annotated_lines:
                        prefix = "  [CUSS] " if has_cuss else "         "
                        self.after(0, lambda le=f"{prefix}{line}\n": self.file_log.insert("end", le))

                    footer = (
                        f"========================================================================\n"
                        f"✔ Analysis: {len(intervals)} profanity interval(s) detected in lyrics.\n"
                        f"Ready to censor! Click '▶ Start Censoring File' below to generate clean audio.\n"
                    )
                    self.after(0, lambda: self.file_log.insert("end", footer))
                    self.after(0, lambda: messagebox.showinfo(
                        "Lyrics Found",
                        f"✔ Synchronized Lyrics Found!\n\n"
                        f"• Source: {prov.last_source.upper()}\n"
                        f"• Query: '{prov.last_matched_query}'\n"
                        f"• Total Lines: {len(prov.last_timed_lines)} ({len(words)} words)\n"
                        f"• Profanities Detected: {len(intervals)}\n\n"
                        f"Lyrics preview has been loaded in the box below."
                    ))
                else:
                    msg = (
                        f"\n⚠️ No synchronized lyrics found for '{song_title} {artist_name}'.\n"
                        f"Suggestions:\n"
                        f"1. Check spelling of Song Name and Artist above.\n"
                        f"2. Use '📋 Paste Lyrics' to paste timestamped lines.\n"
                        f"3. Click '▶ Start Censoring File' to transcribe automatically via Whisper.\n"
                    )
                    self.after(0, lambda: self.file_log.insert("end", msg))
                    self.after(0, lambda: messagebox.showinfo(
                        "Lyrics Not Found",
                        f"⚠️ No synchronized lyrics found for '{search_desc}'.\n\n"
                        f"When you click 'Export Clean File', the pipeline will automatically proceed with OpenAI Whisper AI speech recognition fallback."
                    ))
            except Exception as e:
                self.after(0, lambda err=str(e): self.file_log.insert("end", f"\n❌ Error searching lyrics: {err}\n"))
            finally:
                self.after(0, lambda: self.file_find_lyrics_btn.configure(state="normal", text="🔍 Find Lyrics"))

        threading.Thread(target=worker, daemon=True).start()

    def _start_file_censor(self):
        inp = self.file_in_entry.get().strip()
        outp = self.file_out_entry.get().strip()
        if not inp or not os.path.exists(inp):
            messagebox.showerror("Error", "Please select or download an input file first.")
            return
        if not outp:
            p = Path(inp)
            outp = str(p.parent / f"{p.stem}_clean{p.suffix}")
            self.file_out_entry.insert(0, outp)

        mode = self.file_mode_var.get()
        lang = self.file_lang_var.get()
        model_selection = self.file_model_var.get().split()[0].lower()
        use_web = self.file_use_web_lyrics_var.get()
        song_title = self.file_song_entry.get().strip() or None
        artist_name = self.file_artist_entry.get().strip() or None

        lrc_file = self.file_lrc_entry.get().strip()
        custom_lrc_text = None
        if lrc_file.startswith("[Custom Pasted Lyrics") and getattr(self, "_pasted_lyrics_text", None):
            custom_lrc_text = self._pasted_lyrics_text
        elif lrc_file and os.path.exists(lrc_file):
            try:
                with open(lrc_file, "r", encoding="utf-8", errors="ignore") as lf:
                    custom_lrc_text = lf.read()
            except Exception:
                pass
        elif getattr(self, "_pasted_lyrics_text", None):
            custom_lrc_text = self._pasted_lyrics_text

        self._set_busy(True)
        self.file_run_btn.configure(text="⏳ Processing...")
        self.file_progress.set(0.10)
        self.file_log.delete("1.0", "end")

        if song_title and artist_name:
            search_desc = f"'{song_title} {artist_name}'"
        elif song_title:
            search_desc = f"'{song_title}'"
        elif artist_name:
            search_desc = f"'{artist_name}'"
        else:
            search_desc = Path(inp).name
        self.file_log.insert("end", f"▶ Starting censorship pipeline for: {Path(inp).name}\nSearching / Transcribing lyrics for: {search_desc}...\n\n")

        def worker():
            try:
                asr = WhisperEngine(model_name=model_selection)
                self.after(0, lambda: self.file_progress.set(0.35))

                url_input = self.single_url_entry.get().strip()
                words = None

                # Step 1: Check for lyrics (LRC, YouTube description, or online)
                if use_web or custom_lrc_text or (lrc_file and os.path.exists(lrc_file)) or (url_input and ("youtube.com" in url_input or "youtu.be" in url_input)):
                    self.after(0, lambda: self.file_log.insert("end", f"▶ Checking for synchronized lyrics across sources...\n"))
                    synced_words = asr.lyrics_provider.fetch_synced_words(
                        inp,
                        custom_lrc_text=custom_lrc_text,
                        song_title=song_title,
                        artist_name=artist_name,
                        youtube_desc=url_input if (url_input and ("youtube.com" in url_input or "youtu.be" in url_input)) else None
                    )

                    if synced_words and asr.lyrics_provider.last_timed_lines:
                        # Pop up: Lyrics found! Ask user whether to proceed with lyrics
                        ask_event = threading.Event()
                        user_wants_lyrics = True

                        def ask_dialog():
                            nonlocal user_wants_lyrics
                            src = (asr.lyrics_provider.last_source or "ONLINE").upper()
                            q = asr.lyrics_provider.last_matched_query or search_desc
                            n_lines = len(asr.lyrics_provider.last_timed_lines)
                            msg = (
                                f"✔ Synchronized Lyrics Found!\n\n"
                                f"• Source: {src}\n"
                                f"• Query: '{q}'\n"
                                f"• Found: {n_lines} lines ({len(synced_words)} words)\n\n"
                                f"Proceed with censoring using these lyrics?\n\n"
                                f"[Yes] — Use found lyrics (instant & high accuracy)\n"
                                f"[No]  — Proceed with OpenAI Whisper AI speech recognition instead"
                            )
                            user_wants_lyrics = messagebox.askyesno("Lyrics Found", msg)
                            ask_event.set()

                        self.after(0, ask_dialog)
                        ask_event.wait()

                        if user_wants_lyrics:
                            # If untimed, run Whisper AI Audio Alignment to accurately time them
                            if getattr(asr.lyrics_provider, "is_untimed", False):
                                self.after(0, lambda: self.file_log.insert("end", f"▶ Untimed lyrics detected. Running AI Audio Alignment to map vocal timestamps...\n"))
                                try:
                                    align_kwargs = {
                                        "initial_prompt": "Hindi, Hinglish, English rap songs, hip hop lyrics, slang, profanity, cuss words."
                                    }
                                    if lang and lang.lower() not in ("auto", "all"):
                                        align_kwargs["language"] = lang.lower()
                                    w_res = asr.model.transcribe(inp, **align_kwargs)
                                    segs = w_res.get("segments", [])
                                    if segs:
                                        from core.asr.lyrics_provider import align_lyrics_with_whisper_segments, parse_lrc_content, get_audio_duration
                                        raw_lines = [line for _, line in asr.lyrics_provider.last_timed_lines]
                                        aligned = align_lyrics_with_whisper_segments(
                                            raw_lines, segs, total_duration=get_audio_duration(inp)
                                        )
                                        lrc_lines = [f"[{int(ts // 60):02d}:{ts % 60:05.2f}] {text}" for ts, text in aligned]
                                        formatted_lrc = "\n".join(lrc_lines)
                                        aligned_words = parse_lrc_content(formatted_lrc)
                                        if aligned_words:
                                            synced_words = aligned_words
                                            asr.lyrics_provider.last_timed_lines = aligned
                                            asr.lyrics_provider.last_raw_lyrics = formatted_lrc
                                            asr.lyrics_provider.last_source = f"{asr.lyrics_provider.last_source} (AI Aligned)"
                                            asr.lyrics_provider.is_untimed = False
                                except Exception as e:
                                    pass
                            words = synced_words
                        else:
                            self.after(0, lambda: self.file_log.insert("end", f"▶ User chose to use AI Whisper. Falling back to local transcription...\n"))
                            words = None
                    else:
                        # Pop up: Lyrics not found! Notify user and proceed to Whisper AI
                        info_event = threading.Event()
                        def info_dialog():
                            msg = (
                                f"ℹ️ No synchronized lyrics found for {search_desc}.\n\n"
                                f"Proceeding to next step:\n"
                                f"🎙️ Local OpenAI Whisper AI Speech Recognition ({model_selection})...\n\n"
                                f"Click OK to proceed."
                            )
                            messagebox.showinfo("Lyrics Not Found", msg)
                            info_event.set()

                        self.after(0, info_dialog)
                        info_event.wait()
                        words = None

                # Step 2: If no lyrics were found or user chose Whisper, transcribe with AI
                if not words:
                    self.after(0, lambda: self.file_log.insert("end", f"▶ Transcribing audio with local OpenAI Whisper ({model_selection})...\n"))
                    words = asr.transcribe(inp, language=lang, prefer_online_lyrics=False)

                if asr.last_raw_lyrics:
                    self._last_fetched_lyrics = asr.last_raw_lyrics

                shift_val = parse_shift_offset(self.file_shift_var.get())
                detector = ProfanityDetector(pre_padding=0.25, post_padding=0.18, time_offset=shift_val)
                intervals = detector.detect_in_words(words, lang=lang)

                # DISPLAY FOUND LYRICS IN THE MEANTIME!
                if asr.last_timed_lines:
                    self.after(0, lambda: self.file_log.insert("end",
                        f"========================================================================\n"
                        f"📜 FOUND SYNCHRONIZED LYRICS ({len(asr.last_timed_lines)} lines | {len(words)} words)\n"
                        f"Source: {asr.last_source.upper()} | Matched Query: '{asr.lyrics_provider.last_matched_query}'\n"
                        f"========================================================================\n"
                    ))
                    annotated_lines = asr.get_annotated_lyrics_lines(profanity_detector=detector)
                    for ts, line, has_cuss in annotated_lines:
                        prefix = "  [CUSS] " if has_cuss else "         "
                        self.after(0, lambda le=f"{prefix}{line}\n": self.file_log.insert("end", le))
                    self.after(0, lambda: self.file_log.insert("end",
                        f"========================================================================\n\n"
                    ))
                else:
                    self.after(0, lambda: self.file_log.insert("end",
                        f"✔ 🎙️ Transcribed via local OpenAI Whisper ({model_selection}) - {len(words)} words detected.\n\n"
                    ))

                self.after(0, lambda: self.file_progress.set(0.65))
                self.after(0, lambda: self.file_log.insert("end", f"✔ Analysis complete: {len(intervals)} profanity interval(s) detected.\n\n"))

                for i in intervals:
                    msg = f"  • [{i.start:.2f}s - {i.end:.2f}s]: {i.matched_word}\n"
                    self.after(0, lambda m=msg: self.file_log.insert("end", m))

                self.after(0, lambda: self.file_progress.set(0.85))
                self.after(0, lambda: self.file_log.insert("end", f"\n▶ Applying audio censorship effect: [{mode.upper()}] via FFmpeg...\n"))

                censor = FFmpegCensor()
                censor.censor_media(inp, outp, intervals, mode=mode)

                self.after(0, lambda: self.file_progress.set(1.0))
                self.after(0, lambda: self.file_log.insert("end", f"\n✨ SUCCESS! Clean media saved to:\n{outp}\n"))
                self.after(0, lambda: messagebox.showinfo("Completed", f"Censoring finished successfully!\nSaved to: {Path(outp).name}"))
            except Exception as e:
                self.after(0, lambda err=str(e): self.file_log.insert("end", f"\n❌ Error: {err}\n"))
                self.after(0, lambda err=str(e): messagebox.showerror("Processing Error", err))
            finally:
                self.after(0, lambda: self.file_run_btn.configure(text="▶ Start Censoring File"))
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------------------------------------
    # TAB 2: Playlist & Batch Mode (With Explicit Quality Downloader)
    # -------------------------------------------------------------------------
    def _build_playlist_tab(self):
        tab = self.tab_playlist

        # Section 1: Playlist Downloader & Input
        in_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=("#ffffff", "#212529"), border_width=1, border_color=("#dee2e6", "#343a40"))
        in_card.pack(fill="x", padx=15, pady=(10, 8))

        ctk.CTkLabel(in_card, text="Playlist Target (Music Folder, .M3U8 File, or Online Playlist URL):", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(8, 2))
        p_row = ctk.CTkFrame(in_card, fg_color="transparent")
        p_row.pack(fill="x", padx=12, pady=(0, 6))

        self.playlist_in_entry = ctk.CTkEntry(p_row, placeholder_text="Select music folder, .m3u8 file, or paste Spotify / YouTube playlist URL...")
        self.playlist_in_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        f_btn = ctk.CTkButton(p_row, text="Folder...", width=80, command=self._browse_playlist_folder)
        f_btn.pack(side="left", padx=(0, 5))

        m_btn = ctk.CTkButton(p_row, text="File...", width=70, command=self._browse_playlist_file)
        m_btn.pack(side="left")

        # Explicit Download Quality Selector for Playlists
        q_row = ctk.CTkFrame(in_card, fg_color="transparent")
        q_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(q_row, text="Download Quality:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 6))
        quality_options = list(QUALITY_PROFILES.keys())
        self.pl_quality_var = ctk.StringVar(value=quality_options[0])  # FLAC Lossless
        self.pl_quality_menu = ctk.CTkOptionMenu(
            q_row,
            values=quality_options,
            variable=self.pl_quality_var,
            width=270,
            font=ctk.CTkFont(size=11),
            command=self._on_pl_quality_change
        )
        self.pl_quality_menu.pack(side="left", padx=(0, 10))

        self.pl_quality_desc_label = ctk.CTkLabel(
            q_row,
            text=f"[Bitrate: {QUALITY_PROFILES[quality_options[0]]['bitrate_label']}]",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#868e96"
        )
        self.pl_quality_desc_label.pack(side="left")

        # Section 2: Destination Folder
        dest_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=("#ffffff", "#212529"), border_width=1, border_color=("#dee2e6", "#343a40"))
        dest_card.pack(fill="x", padx=15, pady=6)

        ctk.CTkLabel(dest_card, text="Destination Folder for Censored Tracks:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(8, 2))
        po_row = ctk.CTkFrame(dest_card, fg_color="transparent")
        po_row.pack(fill="x", padx=12, pady=(0, 10))

        self.playlist_out_entry = ctk.CTkEntry(po_row, placeholder_text="Folder where clean tracks will be saved")
        self.playlist_out_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.playlist_out_entry.insert(0, str((root_dir / "censored_output").resolve()))

        p_out_btn = ctk.CTkButton(po_row, text="Choose...", width=80, command=self._browse_playlist_output)
        p_out_btn.pack(side="right")

        # Section 3: Options & Actions
        act_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=("#ffffff", "#212529"), border_width=1, border_color=("#dee2e6", "#343a40"))
        act_card.pack(fill="x", padx=15, pady=6)

        act_row = ctk.CTkFrame(act_card, fg_color="transparent")
        act_row.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(act_row, text="Mode:").pack(side="left", padx=(0, 5))
        self.pl_mode_var = ctk.StringVar(value="beep")
        self.pl_mode_menu = ctk.CTkOptionMenu(act_row, values=["beep", "mute"], variable=self.pl_mode_var, width=90)
        self.pl_mode_menu.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(act_row, text="Language:").pack(side="left", padx=(0, 5))
        self.pl_lang_var = ctk.StringVar(value="all")
        self.pl_lang_menu = ctk.CTkOptionMenu(act_row, values=["all", "hi", "en"], variable=self.pl_lang_var, width=90)
        self.pl_lang_menu.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(act_row, text="Model:").pack(side="left", padx=(0, 5))
        self.pl_model_var = ctk.StringVar(value="tiny (Fast Lite)")
        self.pl_model_menu = ctk.CTkOptionMenu(
            act_row,
            values=["tiny (Fast Lite)", "base (Balanced)", "small (High Accuracy)"],
            variable=self.pl_model_var,
            width=160
        )
        self.pl_model_menu.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(act_row, text="Sync:").pack(side="left", padx=(0, 5))
        self.pl_shift_var = ctk.StringVar(value="0.0s (Normal)")
        self.pl_shift_menu = ctk.CTkOptionMenu(
            act_row,
            values=["0.0s (Normal)", "-0.5s (Fix Lag)", "-0.3s Earlier", "-0.7s Earlier", "+0.3s Later", "+0.5s Later"],
            variable=self.pl_shift_var,
            width=125
        )
        self.pl_shift_menu.pack(side="left", padx=(0, 10))

        self.pl_download_btn = ctk.CTkButton(
            act_row,
            text="📥 Download Playlist",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#2b8a3e",
            hover_color="#237032",
            command=self._start_playlist_download
        )
        self.pl_download_btn.pack(side="left", padx=(0, 8))

        self.pl_run_btn = ctk.CTkButton(
            act_row,
            text="▶ Batch Censor",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#1864ab",
            hover_color="#155592",
            command=self._start_playlist_censor
        )
        self.pl_run_btn.pack(side="left", padx=(0, 8))

        self.pl_cancel_btn = ctk.CTkButton(
            act_row,
            text="⏹ Cancel",
            font=ctk.CTkFont(weight="bold"),
            width=80,
            fg_color="#d6336c",
            hover_color="#a61e4d",
            command=self._cancel_active_task,
            state="disabled"
        )
        self.pl_cancel_btn.pack(side="left", padx=(0, 8))

        self.pl_open_btn = ctk.CTkButton(
            act_row,
            text="📂 Open Folder",
            width=100,
            command=self._open_playlist_output_folder
        )
        self.pl_open_btn.pack(side="right")

        self.pl_progress = ctk.CTkProgressBar(tab)
        self.pl_progress.pack(fill="x", padx=15, pady=(4, 6))
        self.pl_progress.set(0)

        # Log Output
        self.pl_log = ctk.CTkTextbox(
            tab,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=("#ffffff", "#1e1e1e"),
            text_color=("#212529", "#f8f9fa"),
            border_width=1,
            border_color=("#dee2e6", "#343a40")
        )
        self.pl_log.pack(fill="both", expand=True, padx=15, pady=(0, 10))

    def _on_pl_quality_change(self, choice: str):
        profile = QUALITY_PROFILES.get(choice, {})
        self.pl_quality_desc_label.configure(
            text=f"[Bitrate: {profile.get('bitrate_label', '')}]"
        )

    def _browse_playlist_folder(self):
        d = filedialog.askdirectory(title="Select Folder of Songs/Videos")
        if d:
            self.playlist_in_entry.delete(0, "end")
            self.playlist_in_entry.insert(0, d)

    def _browse_playlist_file(self):
        f = filedialog.askopenfilename(
            title="Select Playlist File",
            filetypes=[("Playlist Files", "*.m3u *.m3u8 *.json"), ("All Files", "*.*")]
        )
        if f:
            self.playlist_in_entry.delete(0, "end")
            self.playlist_in_entry.insert(0, f)

    def _browse_playlist_output(self):
        d = filedialog.askdirectory(title="Select Destination Folder")
        if d:
            self.playlist_out_entry.delete(0, "end")
            self.playlist_out_entry.insert(0, d)

    def _open_playlist_output_folder(self):
        out_dir = self.playlist_out_entry.get().strip()
        if os.path.exists(out_dir):
            if sys.platform == "win32":
                os.startfile(out_dir)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", out_dir])
        else:
            messagebox.showinfo("Folder", "Output directory does not exist yet.")

    def _start_playlist_download(self):
        url = self.playlist_in_entry.get().strip()
        outp = self.playlist_out_entry.get().strip()
        if not url or not url.startswith(("http://", "https://")):
            messagebox.showerror("Error", "Please enter a valid Spotify, YouTube, or audio playlist URL to download.")
            return

        quality = self.pl_quality_var.get()
        self._set_busy(True)
        self.pl_download_btn.configure(text="⏳ Downloading...")
        self.pl_progress.set(0.0)
        self.pl_log.delete("1.0", "end")
        self.pl_log.insert("end", f"▶ Starting Playlist Download in {quality}...\nURL: {url}\n\n")

        def progress_cb(pct: float, line_text: str):
            if pct >= 0:
                self.after(0, lambda p=pct/100.0: self.pl_progress.set(p))
            if line_text:
                self.after(0, lambda t=line_text: self.pl_log.insert("end", f"  {t}\n"))

        def worker():
            try:
                success, target_path, msg = download_song_or_playlist(
                    url,
                    output_dir=outp,
                    quality=quality,
                    is_single=False,
                    progress_callback=progress_cb,
                    cancel_event=self._cancel_event
                )
                if success:
                    self.after(0, lambda: self.pl_progress.set(1.0))
                    self.after(0, lambda: self.pl_log.insert("end", f"\n✔ {msg}\nSaved to: {outp}\nReady to censor! Click 'Batch Censor' to clean profanities.\n"))
                    self.after(0, lambda: messagebox.showinfo("Download Complete", f"Playlist downloaded in {quality}!\nSaved to: {outp}\n\nYou can now click 'Batch Censor'."))
                else:
                    self.after(0, lambda: self.pl_log.insert("end", f"\n❌ {msg}\n"))
                    self.after(0, lambda: messagebox.showerror("Download Error", msg))
            except Exception as e:
                self.after(0, lambda err=str(e): self.pl_log.insert("end", f"\n❌ Download error: {err}\n"))
            finally:
                self.after(0, lambda: self.pl_download_btn.configure(text="📥 Download Playlist"))
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _start_playlist_censor(self):
        inp = self.playlist_in_entry.get().strip()
        outp = self.playlist_out_entry.get().strip()
        if not inp:
            messagebox.showerror("Error", "Please provide a folder, playlist file, or URL.")
            return

        mode = self.pl_mode_var.get()
        lang = self.pl_lang_var.get()
        model_name = self.pl_model_var.get().split()[0].lower()

        self._set_busy(True)
        self.pl_run_btn.configure(text="⏳ Processing...")
        self.pl_progress.set(0.1)
        self.pl_log.delete("1.0", "end")
        self.pl_log.insert("end", f"▶ Initializing hybrid matcher (online synced lyrics first -> Whisper '{model_name}' fallback)...\n")

        def worker():
            try:
                shift_val = parse_shift_offset(self.pl_shift_var.get())
                runner = PlaylistCensorRunner(
                    whisper_model=model_name,
                    mode=mode,
                    lang=lang,
                    output_dir=outp,
                    time_offset=shift_val,
                    pre_padding=0.25,
                    post_padding=0.18,
                    cancel_event=self._cancel_event
                )
                manifest = runner.inspector.inspect_target(inp)
                total_tracks = len(manifest.tracks)
                self.after(0, lambda: self.pl_log.insert("end", f"✔ Format: {manifest.format_type} | Found {total_tracks} track(s).\n\n"))

                out_path = Path(outp)
                out_path.mkdir(parents=True, exist_ok=True)

                clean_count = 0
                censored_count = 0
                total_words = 0

                for idx, track in enumerate(manifest.tracks):
                    if self._cancel_event.is_set():
                        self.after(0, lambda: self.pl_log.insert("end", "\n[Batch processing cancelled by user.]\n"))
                        break

                    t_msg = f"[{idx+1}/{total_tracks}] Processing: {track.title}...\n"
                    self.after(0, lambda m=t_msg: self.pl_log.insert("end", m))

                    res = runner._process_single_track(track, out_path)
                    cuss_n = res.get("cuss_words_count", 0)

                    if cuss_n > 0:
                        censored_count += 1
                        total_words += cuss_n
                        res_msg = f"  -> CENSORED: {cuss_n} cuss word(s) ({', '.join(res.get('flagged_words', []))})\n"
                    else:
                        clean_count += 1
                        res_msg = f"  -> CLEAN: No cuss words detected.\n"

                    self.after(0, lambda m=res_msg: self.pl_log.insert("end", m))
                    prog = (idx + 1) / max(1, total_tracks)
                    self.after(0, lambda p=prog: self.pl_progress.set(p))

                summary_text = (
                    f"\n✨ Batch Playlist Censoring Complete!\n"
                    f"• Total Tracks: {total_tracks}\n"
                    f"• Clean Tracks: {clean_count}\n"
                    f"• Censored Tracks: {censored_count}\n"
                    f"• Total Slangs Censored: {total_words}\n"
                    f"• Destination: {out_path.resolve()}\n"
                )
                self.after(0, lambda: self.pl_log.insert("end", summary_text))
                self.after(0, lambda: messagebox.showinfo("Playlist Done", f"Batch completed!\n{censored_count} explicit tracks censored."))
            except Exception as e:
                self.after(0, lambda err=str(e): self.pl_log.insert("end", f"\n❌ Error: {err}\n"))
                self.after(0, lambda err=str(e): messagebox.showerror("Batch Error", err))
            finally:
                self.after(0, lambda: self.pl_run_btn.configure(text="▶ Batch Censor"))
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

        threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------------------------------------
    # TAB 3: Audio Output Devices (Windows Sound Playback)
    # -------------------------------------------------------------------------
    def _build_devices_tab(self):
        tab = self.tab_devices

        # Header Card
        hdr_card = ctk.CTkFrame(
            tab, corner_radius=10, fg_color=("#ffffff", "#212529"),
            border_width=1, border_color=("#dee2e6", "#343a40")
        )
        hdr_card.pack(fill="x", padx=15, pady=(10, 8))

        title_col = ctk.CTkFrame(hdr_card, fg_color="transparent")
        title_col.pack(side="left", padx=15, pady=10)

        ctk.CTkLabel(
            title_col,
            text="🎧 Windows Audio Output Devices (Sound Playback)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#1864ab"
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_col,
            text="Active Windows playback endpoints matching Windows Sound Settings (driver duplicates filtered).",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#868e96"
        ).pack(anchor="w")

        ref_btn = ctk.CTkButton(
            hdr_card,
            text="🔄 Refresh Devices",
            font=ctk.CTkFont(weight="bold"),
            width=135,
            fg_color="#1864ab",
            hover_color="#155592",
            command=self._populate_devices_table
        )
        ref_btn.pack(side="right", padx=15, pady=10)

        # Device Cards Container (Scrollable Frame)
        self.dev_cards_frame = ctk.CTkScrollableFrame(
            tab,
            corner_radius=10,
            fg_color=("#ffffff", "#212529"),
            border_width=1,
            border_color=("#dee2e6", "#343a40")
        )
        self.dev_cards_frame.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self._populate_devices_table()

    def _populate_devices_table(self):
        for widget in self.dev_cards_frame.winfo_children():
            widget.destroy()

        devices = get_windows_output_devices()
        if not devices:
            ctk.CTkLabel(
                self.dev_cards_frame,
                text="No active audio playback devices found.",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#e03131"
            ).pack(pady=30)
            return

        for dev in devices:
            is_def = dev.get("is_default", False)
            border_col = ("#1971c2", "#1971c2") if is_def else ("#e9ecef", "#343a40")
            bg_col = ("#f8f9fa", "#2b3035") if is_def else ("#ffffff", "#25262b")

            card = ctk.CTkFrame(
                self.dev_cards_frame,
                corner_radius=8,
                fg_color=bg_col,
                border_width=2 if is_def else 1,
                border_color=border_col
            )
            card.pack(fill="x", padx=8, pady=5)

            left_box = ctk.CTkFrame(card, fg_color="transparent")
            left_box.pack(side="left", fill="x", expand=True, padx=14, pady=10)

            name_row = ctk.CTkFrame(left_box, fg_color="transparent")
            name_row.pack(fill="x")

            icon = "🔊" if is_def else "🎧"
            ctk.CTkLabel(
                name_row,
                text=f"{icon} {dev['name']}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=("#1864ab" if is_def else "#212529", "#74c0fc" if is_def else "#f8f9fa")
            ).pack(side="left")

            sub_text = (
                f"Device ID: #{dev['id']}  •  "
                f"{dev['channels']} Channels ({'Stereo' if dev['channels'] == 2 else 'Multi-channel'})  •  "
                f"Sample Rate: {dev['default_samplerate']} Hz  •  "
                f"Host: {dev['api']}"
            )
            ctk.CTkLabel(
                left_box,
                text=sub_text,
                font=ctk.CTkFont(size=11),
                text_color="#868e96"
            ).pack(anchor="w", pady=(3, 0))

            right_box = ctk.CTkFrame(card, fg_color="transparent")
            right_box.pack(side="right", padx=14, pady=10)

            if is_def:
                badge = ctk.CTkLabel(
                    right_box,
                    text="★ Default Playback Endpoint",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#2b8a3e",
                    fg_color=("#d3f9d8", "#1e3a24"),
                    corner_radius=6,
                    padx=10,
                    pady=4
                )
                badge.pack(side="right")
            else:
                badge = ctk.CTkLabel(
                    right_box,
                    text="Ready",
                    font=ctk.CTkFont(size=11),
                    text_color="#868e96",
                    fg_color=("#f1f3f5", "#343a40"),
                    corner_radius=6,
                    padx=10,
                    pady=4
                )
                badge.pack(side="right")


def launch_gui():
    app = CussCensorGUI()
    app.mainloop()


if __name__ == "__main__":
    launch_gui()
