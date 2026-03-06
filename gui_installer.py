"""
JD2021 Map Installer - GUI
Launch with: python gui_installer.py
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import queue
import subprocess
import sys
import os
import gui_settings
import logging
import datetime

# Ensure we can import sibling scripts regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import get_logger, setup_gui_logging
from helpers import TOOLTIP_DELAY_MS
import map_installer
import map_builder
import map_downloader
import source_analysis
from gui_preview import PreviewManager

logger = get_logger("gui")


class ToolTip:
    """Creates a hover tooltip for a given widget."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(TOOLTIP_DELAY_MS, self.showtip)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def showtip(self, event=None):
        x, y, cx, cy = self.widget.bbox("insert") or (0,0,0,0)
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify='left',
                      background="#ffffe0", relief='solid', borderwidth=1,
                      font=("Consolas", "8", "normal"))
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


class TextWidgetHandler(logging.Handler):
    """Logging handler that routes log records to a tkinter Text widget via a queue."""

    def __init__(self, text_widget, root):
        super().__init__()
        self.text_widget = text_widget
        self.root = root
        self._queue = queue.Queue()
        self._poll()

    def emit(self, record):
        msg = self.format(record) + "\n"
        self._queue.put(msg)

    def _poll(self):
        try:
            while True:
                text = self._queue.get_nowait()
                self.text_widget.configure(state="normal")
                self.text_widget.insert(tk.END, text)
                self.text_widget.see(tk.END)
                self.text_widget.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(50, self._poll)


class StdoutToLogger:
    """Thin file-like wrapper that captures stray print() calls and routes them
    through the logging system so they appear in the GUI text widget."""

    def __init__(self, logger_instance, level=logging.INFO):
        self._logger = logger_instance
        self._level = level
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, line)

    def flush(self):
        if self._buffer.strip():
            self._logger.log(self._level, self._buffer.strip())
            self._buffer = ""


class MapInstallerGUI:

    STEP_NAMES = [name for name, _ in map_installer.PIPELINE_STEPS]

    def __init__(self, root):
        self.root = root
        self.root.title("JD2021 Map Installer")
        self.root.geometry("1000x900")
        self.root.minsize(1000, 900)

        # State
        self.pipeline_state = None
        self.pipeline_thread = None
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._preflight_passed = False
        self._file_handler = None
        self._closing = False
        self._pipeline_running = False
        self._fetch_mode_lock = False
        self._last_run_from_fetch = False
        self._source_spec = None

        # Tkinter variables for sync refinement
        self.v_override_var = tk.DoubleVar(value=0.0)
        self.a_offset_var = tk.DoubleVar(value=0.0)
        self.v_override_enabled_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._redirect_stdout()

        # Load persistent settings
        self._settings = map_installer.load_settings()

        # Apply default quality from settings
        self.quality_var.set(self._settings["default_quality"])

        # Auto-detect JD directory
        detected = map_installer.detect_jd_dir()
        self.jd_dir_entry.insert(0, detected)

        # If skip_preflight is enabled, auto-enable the Install button
        if self._settings["skip_preflight"]:
            self._preflight_passed = True
            self.install_btn.configure(state="normal")

        self._show_quickstart_if_needed()

        # Clean up on close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=8, pady=4)

        # ===================== UNIFIED INSTALL PANEL =====================
        install_panel = ttk.LabelFrame(container, text="Install", padding=6)
        install_panel.pack(fill="x", pady=(0, 4))

        # --- Row 0: Mode selector ---
        mode_row = ttk.Frame(install_panel)
        mode_row.pack(fill="x", pady=(0, 4))

        ttk.Label(mode_row, text="Mode:", width=16, anchor="e").pack(
            side="left", padx=(0, 4))
        self.source_mode_var = tk.StringVar(value="fetch")
        self.source_mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.source_mode_var,
            values=["fetch", "html", "ipk", "manual", "batch"],
            state="readonly",
            width=18,
        )
        self.source_mode_combo.pack(side="left")
        self.source_mode_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_source_mode_changed())

        # Manual submode (shown only in manual mode, handled by _on_source_mode_changed)
        self._submode_label = ttk.Label(mode_row, text="Submode:")
        self.manual_submode_var = tk.StringVar(value="auto")
        self.manual_submode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.manual_submode_var,
            values=["auto", "unpacked_ipk", "downloaded_assets"],
            state="readonly",
            width=18,
        )

        # --- Mode-specific frames (swapped by _on_source_mode_changed) ---
        self._mode_frames = {}
        self._mode_frame_parent = ttk.Frame(install_panel)
        self._mode_frame_parent.pack(fill="x", pady=(0, 4))

        # FETCH frame: Codename entry
        f_fetch = ttk.Frame(self._mode_frame_parent)
        ttk.Label(f_fetch, text="Codename:", width=16, anchor="e").pack(
            side="left", padx=(0, 4))
        self.codename_entry = ttk.Entry(f_fetch, width=64)
        self.codename_entry.pack(side="left", fill="x", expand=True)
        ToolTip(self.codename_entry,
                "Enter a map codename (e.g. TemperatureALT) to fetch HTML "
                "from Discord and install automatically.")
        self._mode_frames["fetch"] = f_fetch

        # HTML frame: Asset HTML + NoHUD HTML
        f_html = ttk.Frame(self._mode_frame_parent)
        # Warning label
        tk.Label(
            f_html,
            text="\u26a0 Asset/NoHUD links expire after ~30 minutes! "
                 "Fetch fresh links if download fails.",
            fg="#856404",
            font=("Consolas", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        # Asset HTML row
        html_r1 = ttk.Frame(f_html)
        html_r1.pack(fill="x", pady=1)
        ttk.Label(html_r1, text="Asset HTML:", width=16, anchor="e").pack(
            side="left", padx=(0, 4))
        self.asset_html_entry = ttk.Entry(html_r1, width=64)
        self.asset_html_entry.pack(side="left", fill="x", expand=True)
        ToolTip(self.asset_html_entry,
                "Path to the downloaded map asset HTML file containing "
                "texture/audio links.")
        self.asset_browse_btn = ttk.Button(
            html_r1, text="Browse", width=8,
            command=lambda e=None: self._browse(self.asset_html_entry, "html"))
        self.asset_browse_btn.pack(side="left", padx=(4, 0))
        # NoHUD HTML row
        html_r2 = ttk.Frame(f_html)
        html_r2.pack(fill="x", pady=1)
        ttk.Label(html_r2, text="NOHUD HTML:", width=16, anchor="e").pack(
            side="left", padx=(0, 4))
        self.nohud_html_entry = ttk.Entry(html_r2, width=64)
        self.nohud_html_entry.pack(side="left", fill="x", expand=True)
        ToolTip(self.nohud_html_entry,
                "Path to the downloaded NoHUD HTML file containing "
                "the map video link.")
        self.nohud_browse_btn = ttk.Button(
            html_r2, text="Browse", width=8,
            command=lambda e=None: self._browse(self.nohud_html_entry, "html"))
        self.nohud_browse_btn.pack(side="left", padx=(4, 0))
        self._mode_frames["html"] = f_html

        # IPK frame: IPK file + Audio + Video
        f_ipk = ttk.Frame(self._mode_frame_parent)
        for row_label, attr_name, filetypes in [
            ("IPK File:", "source_path_entry",
             [("IPK files", "*.ipk"), ("All files", "*.*")]),
            ("Audio (.ogg):", "mode_audio_entry",
             [("OGG files", "*.ogg"), ("All files", "*.*")]),
            ("Video (.webm):", "mode_video_entry",
             [("WEBM files", "*.webm"), ("All files", "*.*")]),
        ]:
            r = ttk.Frame(f_ipk)
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=row_label, width=16, anchor="e").pack(
                side="left", padx=(0, 4))
            entry = ttk.Entry(r, width=64)
            entry.pack(side="left", fill="x", expand=True)
            # source_path_entry is created fresh here; audio/video reuse existing attrs
            if attr_name == "source_path_entry":
                self.source_path_entry = entry
            elif attr_name == "mode_audio_entry":
                self.mode_audio_entry = entry
            elif attr_name == "mode_video_entry":
                self.mode_video_entry = entry
            btn = ttk.Button(
                r, text="Browse", width=8,
                command=lambda e=entry, ft=filetypes: self._browse_specific_file(e, ft))
            btn.pack(side="left", padx=(4, 0))
        self._mode_frames["ipk"] = f_ipk

        # MANUAL frame: Folder + Audio + Video (reuses ipk entries via shared refs)
        f_manual = ttk.Frame(self._mode_frame_parent)
        man_r1 = ttk.Frame(f_manual)
        man_r1.pack(fill="x", pady=1)
        ttk.Label(man_r1, text="Source Folder:", width=16, anchor="e").pack(
            side="left", padx=(0, 4))
        self._manual_source_entry = ttk.Entry(man_r1, width=64)
        self._manual_source_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(
            man_r1, text="Browse", width=8,
            command=self._browse_mode_source).pack(side="left", padx=(4, 0))
        # Audio/video rows for manual mode use the same entries as IPK
        # (they're read from mode_audio_entry / mode_video_entry)
        for row_label, entry_ref, filetypes in [
            ("Audio (.ogg):", self.mode_audio_entry,
             [("OGG files", "*.ogg"), ("All files", "*.*")]),
            ("Video (.webm):", self.mode_video_entry,
             [("WEBM files", "*.webm"), ("All files", "*.*")]),
        ]:
            r = ttk.Frame(f_manual)
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=row_label, width=16, anchor="e").pack(
                side="left", padx=(0, 4))
            # Create a separate entry for manual mode so widgets aren't shared
            man_entry = ttk.Entry(r, width=64)
            man_entry.pack(side="left", fill="x", expand=True)
            if "Audio" in row_label:
                self._manual_audio_entry = man_entry
            else:
                self._manual_video_entry = man_entry
            ttk.Button(
                r, text="Browse", width=8,
                command=lambda e=man_entry, ft=filetypes: self._browse_specific_file(e, ft)
            ).pack(side="left", padx=(4, 0))
        self._mode_frames["manual"] = f_manual

        # BATCH frame: Folder only
        f_batch = ttk.Frame(self._mode_frame_parent)
        batch_r1 = ttk.Frame(f_batch)
        batch_r1.pack(fill="x", pady=1)
        ttk.Label(batch_r1, text="Maps Folder:", width=16, anchor="e").pack(
            side="left", padx=(0, 4))
        self._batch_folder_entry = ttk.Entry(batch_r1, width=64)
        self._batch_folder_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(
            batch_r1, text="Browse", width=8,
            command=lambda: self._browse(self._batch_folder_entry, "dir")
        ).pack(side="left", padx=(4, 0))
        self._mode_frames["batch"] = f_batch

        # --- Mode action row: Analyze / Prepare / Status ---
        mode_action_row = ttk.Frame(install_panel)
        mode_action_row.pack(fill="x", pady=(0, 4))

        self.mode_analyze_btn = ttk.Button(
            mode_action_row, text="Analyze", command=self._analyze_mode_source)
        self.mode_analyze_btn.pack(side="left")
        self.mode_prepare_btn = ttk.Button(
            mode_action_row, text="Prepare", command=self._prepare_mode_source)
        self.mode_prepare_btn.pack(side="left", padx=(8, 0))

        self.mode_status_var = tk.StringVar(value="Select a mode and source, then Analyze.")
        ttk.Label(mode_action_row, textvariable=self.mode_status_var,
                  foreground="#555555").pack(side="left", padx=(12, 0))

        ttk.Separator(install_panel, orient="horizontal").pack(
            fill="x", pady=4)

        # --- Common bottom: Game Directory + Quality ---
        common = ttk.Frame(install_panel)
        common.pack(fill="x", pady=(0, 4))

        gd_row = ttk.Frame(common)
        gd_row.pack(fill="x", pady=1)
        ttk.Label(gd_row, text="Game Directory:", width=16, anchor="e").pack(
            side="left", padx=(0, 4))
        self.jd_dir_entry = ttk.Entry(gd_row, width=64)
        self.jd_dir_entry.pack(side="left", fill="x", expand=True)
        ToolTip(self.jd_dir_entry,
                "Path to the Just Dance 2021 installation folder.")
        self.jd_browse_btn = ttk.Button(
            gd_row, text="Browse", width=8,
            command=lambda e=None: self._browse(self.jd_dir_entry, "dir"))
        self.jd_browse_btn.pack(side="left", padx=(4, 0))

        q_row = ttk.Frame(common)
        q_row.pack(fill="x", pady=1)
        ttk.Label(q_row, text="Video Quality:", width=16, anchor="e").pack(
            side="left", padx=(0, 4))
        self.quality_var = tk.StringVar(value="ultra_hd")
        ttk.Combobox(
            q_row, textvariable=self.quality_var,
            values=["ultra_hd", "ultra", "high_hd", "high",
                    "mid_hd", "mid", "low_hd", "low"],
            state="readonly", width=12).pack(side="left")

        # --- Button row ---
        btn_row = ttk.Frame(install_panel)
        btn_row.pack(fill="x", pady=(4, 0))

        self.install_btn = ttk.Button(
            btn_row, text="Install", command=self._on_unified_install)
        self.install_btn.pack(side="left")
        ToolTip(self.install_btn,
                "Run the install pipeline for the currently selected mode.")

        # Aliases so existing control-toggle code keeps working
        self.fetch_install_btn = self.install_btn
        self.mode_install_btn = self.install_btn

        self.preflight_btn = ttk.Button(
            btn_row, text="Pre-flight Check", command=self._on_preflight)
        self.preflight_btn.pack(side="left", padx=(12, 0))
        ToolTip(self.preflight_btn,
                "Validates file paths and necessary tools (ffmpeg, ffplay) "
                "before installing.")

        self.clear_cache_btn = ttk.Button(
            btn_row, text="Clear Path Cache", command=self._on_clear_cache)
        self.clear_cache_btn.pack(side="left", padx=(12, 0))
        ToolTip(self.clear_cache_btn,
                "Deletes the saved Just Dance 2021 game data paths. "
                "The next Pre-flight Check or Install will re-scan.")

        self.readjust_btn = ttk.Button(
            btn_row, text="Re-adjust Offset", command=self._on_readjust)
        self.readjust_btn.pack(side="left", padx=(12, 0))
        ToolTip(self.readjust_btn,
                "Re-adjust audio/video offset on an already-installed map.\n"
                "Select the map's download folder "
                "(must contain .ogg and .webm files).")

        self.settings_btn = ttk.Button(
            btn_row, text="Settings", command=self._on_settings)
        self.settings_btn.pack(side="left", padx=(12, 0))
        ToolTip(self.settings_btn,
                "Open installer settings (preflight, notifications, "
                "cleanup, quality defaults).")

        self.reset_btn = ttk.Button(
            btn_row, text="Reset State", command=self._on_reset_state)
        self.reset_btn.pack(side="left", padx=(12, 0))
        ToolTip(self.reset_btn,
                "Clear current inputs/progress and unlock all controls "
                "without restarting the app.")

        # ===================== MIDDLE: PROGRESS + PREVIEW =====================
        middle = ttk.Frame(container)
        middle.pack(fill="both", expand=True, pady=(0, 4))

        # --- Left: Installation Progress ---
        prog = ttk.LabelFrame(middle, text="Installation Progress", padding=6)
        prog.pack(side="left", fill="both", padx=(0, 4))

        self.step_labels = []
        for i, name in enumerate(self.STEP_NAMES):
            lbl = ttk.Label(prog, text=f"[  ] Step {i+1}:  {name}",
                            font=("Consolas", 9))
            lbl.pack(anchor="w")
            self.step_labels.append(lbl)

        # --- Right: Embedded Preview ---
        prev_frame = ttk.LabelFrame(middle, text="Preview", padding=4)
        prev_frame.pack(side="right", fill="both", expand=True)

        # Black container for embedded video preview
        self.preview_container = tk.Frame(
            prev_frame, bg="black", width=480, height=270)
        self.preview_container.pack(fill="both", expand=True)
        self.preview_container.pack_propagate(False)

        # "No Preview" overlay label
        self.preview_label = tk.Label(
            self.preview_container, text="No Preview",
            fg="#555555", bg="black", font=("Consolas", 14))
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

        # Create PreviewManager and let it build the media controls
        self.preview = PreviewManager(
            self.root, self.preview_container, self.preview_label)
        self.media_ctrls = self.preview.build_controls(prev_frame)

        # ===================== LOG OUTPUT =====================
        log_frame = ttk.LabelFrame(container, text="Log Output", padding=4)
        log_frame.pack(fill="x", pady=(0, 4))

        log_inner = ttk.Frame(log_frame)
        log_inner.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_inner, height=6, state="disabled", wrap="word",
            font=("Consolas", 8), bg="#1e1e1e", fg="#cccccc",
            insertbackground="#cccccc")
        log_sb = ttk.Scrollbar(
            log_inner, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

        # ===================== SYNC REFINEMENT =====================
        self.sync_frame = ttk.LabelFrame(
            container, text="Sync Refinement", padding=6)
        self.sync_frame.pack(fill="x", pady=(0, 4))

        tk.Label(
            self.sync_frame,
            text="Fine-tune audio/video timing. "
                 "Hover over buttons for more details.",
            font=("Consolas", 8, "italic"), fg="#888888").pack(
                anchor="w", pady=(0, 4))

        deltas = [1, 0.1, 0.01, 0.001]

        # Keep track of Video Override row widgets to toggle them
        self._vo_row_widgets = []
        for row_idx, (label, var) in enumerate([
            ("VIDEO_OVERRIDE", self.v_override_var),
            ("AUDIO_OFFSET", self.a_offset_var),
        ]):
            row = ttk.Frame(self.sync_frame)
            row.pack(fill="x", pady=2)

            if row_idx == 0:
                cb = ttk.Checkbutton(
                    row, text=label, variable=self.v_override_enabled_var,
                    command=self._on_v_override_toggle, width=18)
                cb.pack(side="left")
                ToolTip(cb,
                        "Checking this forces the map to use a custom "
                        "video start time. Use if you know what you are doing.")
            else:
                lbl = ttk.Label(row, text=label, width=18, anchor="e",
                                font=("Consolas", 9, "bold"))
                lbl.pack(side="left")
                ToolTip(lbl,
                        "Positive values pad the audio with silence at the "
                        "start. Negative values trim the audio from the "
                        "beginning.")

            # Decrement buttons (largest delta first)
            for d in deltas:
                btn = ttk.Button(
                    row, text=f"-{d}", width=6,
                    command=lambda v=var, dd=d: self._on_increment(v, -dd))
                btn.pack(side="left", padx=1)
                if row_idx == 0:
                    self._vo_row_widgets.append(btn)

            # Value display
            val_entry = ttk.Entry(
                row, width=14, justify="center", font=("Consolas", 10))
            val_entry.pack(side="left", padx=6)
            val_entry.insert(0, f"{var.get():.5f}")
            val_entry.configure(state="readonly")
            if row_idx == 0:
                self._vo_display = val_entry
                self._vo_row_widgets.append(val_entry)
            else:
                self._ao_display = val_entry

            # Increment buttons (smallest delta first)
            for d in reversed(deltas):
                btn = ttk.Button(
                    row, text=f"+{d}", width=6,
                    command=lambda v=var, dd=d: self._on_increment(v, dd))
                btn.pack(side="left", padx=1)
                if row_idx == 0:
                    self._vo_row_widgets.append(btn)

        # Action buttons
        actions = ttk.Frame(self.sync_frame)
        actions.pack(fill="x", pady=(8, 0))
        self.sync_beatgrid_btn = ttk.Button(
            actions, text="Sync Beatgrid", command=self._on_sync_beatgrid)
        self.sync_beatgrid_btn.pack(side="left", padx=(0, 6))
        ToolTip(self.sync_beatgrid_btn,
                "Copies the Video Override value to the Audio Offset "
                "(aligning them 1:1).")

        self.pad_audio_btn = ttk.Button(
            actions, text="Pad Audio", command=self._on_pad_audio)
        self.pad_audio_btn.pack(side="left", padx=(0, 6))
        ToolTip(self.pad_audio_btn,
                "Calculates the difference in length between the video "
                "and audio, then auto-fills the Audio Offset to pad the "
                "audio with silence so they end at the same time.")

        self.preview_btn = ttk.Button(
            actions, text="Preview", command=self._on_preview)
        self.preview_btn.pack(side="left", padx=(0, 6))
        ToolTip(self.preview_btn,
                "Starts the embedded video and audio preview to test the "
                "current synchronization offsets.")

        self.stop_preview_btn = ttk.Button(
            actions, text="Stop Preview", command=self._on_stop_preview)
        self.stop_preview_btn.pack(side="left", padx=(0, 6))
        ToolTip(self.stop_preview_btn,
                "Stops the embedded video and audio preview.")
        self.apply_btn = ttk.Button(
            actions, text="Apply & Finish", command=self._on_apply)
        self.apply_btn.pack(side="left")

        # Start with sync refinement and preview controls disabled
        self._set_sync_state("disabled")
        self._set_preview_state("disabled")
        self._on_source_mode_changed()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_v_override_toggle(self):
        enabled = self.v_override_enabled_var.get()
        if enabled:
            messagebox.showwarning(
                "Video Override",
                "Audio offsets are mostly enough.\n\n"
                "Be sure to test it out first before enabling video override."
            )
            state = "normal"
            ro_state = "readonly"
        else:
            state = "disabled"
            ro_state = "disabled"
            
        for w in self._vo_row_widgets:
            if w == self._vo_display:
                w.configure(state=ro_state)
            else:
                w.configure(state=state)
        
        # Also toggle the Sync Beatgrid button based on if VO is enabled
        try:
            if enabled:
                self.sync_beatgrid_btn.configure(state="normal")
            else:
                self.sync_beatgrid_btn.configure(state="disabled")
        except AttributeError:
            pass

    def _derive_codename(self, asset_html, nohud_html, fallback=None):
        """Best-effort codename detection from selected HTML files."""
        for candidate in (asset_html, nohud_html):
            if candidate and os.path.isfile(candidate):
                try:
                    urls = map_downloader.extract_urls(candidate)
                    derived = map_downloader.extract_codename_from_urls(urls)
                    if derived:
                        return derived
                except Exception as e:
                    logger.debug("codename derivation failed for %s: %s", candidate, e)

        for candidate in (asset_html, nohud_html):
            if candidate:
                folder_name = os.path.basename(os.path.dirname(os.path.abspath(candidate)))
                if folder_name:
                    return folder_name
        return fallback

    def _set_html_inputs_state(self, enabled):
        """Enable/disable HTML input entries (only visible in html mode)."""
        state = "normal" if enabled else "disabled"
        self.asset_html_entry.configure(state=state)
        self.nohud_html_entry.configure(state=state)
        self.asset_browse_btn.configure(state=state)
        self.nohud_browse_btn.configure(state=state)

    def _on_html_inputs_changed(self):
        """No-op -- mode routing is handled by the mode combobox now."""
        pass

    def _reset_ui_state(self, clear_html=True):
        """Return the installer UI to an idle state without restarting the app."""
        self._pipeline_running = False
        self._fetch_mode_lock = False
        self._last_run_from_fetch = False
        self._source_spec = None

        self.preview.kill()
        self.pipeline_state = None

        # Reset progress and refinement controls.
        for i in range(len(self.STEP_NAMES)):
            self._update_step_status(i, "pending")
        self.v_override_var.set(0.0)
        self.a_offset_var.set(0.0)
        self._refresh_value_displays()
        self._set_sync_state("disabled")
        self._set_preview_state("disabled")
        self.preview.reset()

        # Restore top-level controls.
        self.preflight_btn.configure(state="normal", text="Pre-flight Check")
        self.install_btn.configure(state="normal")
        self.codename_entry.configure(state="normal")
        self._set_html_inputs_state(True)

        if clear_html:
            self.asset_html_entry.delete(0, tk.END)
            self.nohud_html_entry.delete(0, tk.END)

        self.mode_status_var.set("Select a mode and source, then Analyze.")

        self._on_html_inputs_changed()

    def _on_reset_state(self):
        if self._pipeline_running:
            messagebox.showwarning(
                "Busy",
                "An install is currently running. Wait for it to finish before resetting state.")
            return

        self._reset_ui_state(clear_html=True)
        print("    UI state reset. You can run Fetch & Install again.")

    def _browse(self, entry, browse_type):
        if browse_type == "html":
            path = filedialog.askopenfilename(
                filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        else:
            path = filedialog.askdirectory()
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)
            
            # --- Auto-detect complementary HTML ---
            if browse_type == "html":
                try:
                    dir_path = os.path.dirname(os.path.abspath(path))
                    base_name = os.path.basename(path).lower()
                    html_files = [f for f in os.listdir(dir_path) if f.lower().endswith(".html")]
                    
                    if entry == self.asset_html_entry:
                        # User selected Asset HTML, find NoHUD HTML
                        nohud_files = [f for f in html_files if "nohud" in f.lower() and f.lower() != base_name]
                        if nohud_files:
                            self.nohud_html_entry.delete(0, tk.END)
                            self.nohud_html_entry.insert(0, os.path.join(dir_path, nohud_files[0]))
                    
                    elif entry == self.nohud_html_entry:
                        # User selected NoHUD HTML, find Asset HTML
                        asset_files = [f for f in html_files if "nohud" not in f.lower() and f.lower() != base_name]
                        if asset_files:
                            asset_path = os.path.join(dir_path, asset_files[0])
                            self.asset_html_entry.delete(0, tk.END)
                            self.asset_html_entry.insert(0, asset_path)
                except Exception as e:
                    print(f"Error during complementary HTML auto-detect: {e}")

            self._on_html_inputs_changed()

    def _browse_specific_file(self, entry, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    def _browse_mode_source(self):
        mode = self.source_mode_var.get()
        if mode == "ipk":
            path = filedialog.askopenfilename(
                filetypes=[("IPK files", "*.ipk"), ("All files", "*.*")])
        else:
            path = filedialog.askopenfilename(
                filetypes=[("All supported", "*.html *.ogg *.webm *.ipk"),
                           ("All files", "*.*")])
            if not path:
                path = filedialog.askdirectory(mustexist=True)

        if not path:
            return

        # Write to the correct entry based on mode
        if mode == "manual":
            target = self._manual_source_entry
        elif mode == "ipk":
            target = self.source_path_entry
        elif mode == "batch":
            target = self._batch_folder_entry
        else:
            target = self.source_path_entry
        target.delete(0, tk.END)
        target.insert(0, path)
        self._analyze_mode_source()

    def _on_source_mode_changed(self):
        mode = self.source_mode_var.get()

        # Swap mode-specific frame
        for key, frame in self._mode_frames.items():
            if key == mode:
                frame.pack(fill="x")
            else:
                frame.pack_forget()

        # Show/hide manual submode selector
        if mode == "manual":
            self._submode_label.pack(side="left", padx=(12, 4))
            self.manual_submode_combo.pack(side="left")
            self.manual_submode_combo.configure(state="readonly")
        else:
            self._submode_label.pack_forget()
            self.manual_submode_combo.pack_forget()

        # Show/hide Analyze/Prepare buttons (not needed for fetch mode)
        if mode == "fetch":
            self.mode_analyze_btn.pack_forget()
            self.mode_prepare_btn.pack_forget()
        else:
            self.mode_analyze_btn.pack(side="left")
            self.mode_prepare_btn.pack(side="left", padx=(8, 0))

        source_hint = "file" if mode == "ipk" else "folder"
        self.mode_status_var.set(
            f"Mode: {mode}. Select a source {source_hint} and click Analyze."
            if mode not in ("fetch",)
            else "Mode: fetch. Enter a codename and click Install.")

    def _get_source_path(self):
        """Return the source path from the appropriate entry for the current mode."""
        mode = self.source_mode_var.get()
        if mode == "ipk":
            return self.source_path_entry.get().strip()
        if mode == "manual":
            return self._manual_source_entry.get().strip()
        if mode == "batch":
            return self._batch_folder_entry.get().strip()
        return ""

    def _get_audio_path(self):
        """Return the audio path from the appropriate entry for the current mode."""
        mode = self.source_mode_var.get()
        if mode == "manual":
            return self._manual_audio_entry.get().strip()
        return self.mode_audio_entry.get().strip()

    def _get_video_path(self):
        """Return the video path from the appropriate entry for the current mode."""
        mode = self.source_mode_var.get()
        if mode == "manual":
            return self._manual_video_entry.get().strip()
        return self.mode_video_entry.get().strip()

    def _analyze_mode_source(self):
        mode = self.source_mode_var.get()
        source_path = self._get_source_path()
        audio_path = self._get_audio_path()
        video_path = self._get_video_path()

        if source_path and os.path.isfile(source_path) and mode in {"manual", "batch", "html"}:
            source_folder = os.path.dirname(source_path)
        else:
            source_folder = source_path

        if mode == "fetch":
            self._source_spec = source_analysis.SourceSpec(mode="fetch", ready_for_prepare=True, ready_for_install=True)
            self.mode_status_var.set("Fetch mode is ready. Enter a codename and click Install.")
            return

        if mode == "html":
            if source_path and os.path.isfile(source_path) and source_path.lower().endswith(".html"):
                lower = os.path.basename(source_path).lower()
                if "nohud" in lower:
                    self.nohud_html_entry.delete(0, tk.END)
                    self.nohud_html_entry.insert(0, source_path)
                else:
                    self.asset_html_entry.delete(0, tk.END)
                    self.asset_html_entry.insert(0, source_path)

            if source_folder and os.path.isdir(source_folder):
                guessed_asset, guessed_nohud = source_analysis._find_html_pair(source_folder)
                if guessed_asset and not self.asset_html_entry.get().strip():
                    self.asset_html_entry.insert(0, guessed_asset)
                if guessed_nohud and not self.nohud_html_entry.get().strip():
                    self.nohud_html_entry.insert(0, guessed_nohud)

            spec = source_analysis.analyze_html_mode(
                self.asset_html_entry.get().strip(),
                self.nohud_html_entry.get().strip(),
            )
        elif mode == "ipk":
            spec = source_analysis.analyze_ipk_file_mode(source_path, audio_path, video_path)
        elif mode == "manual":
            spec = source_analysis.analyze_manual_mode(source_folder, self.manual_submode_var.get())
        elif mode == "batch":
            spec = source_analysis.SourceSpec(mode="batch", source_path=source_folder)
            if not source_folder or not os.path.isdir(source_folder):
                spec.errors.append("Batch mode requires a valid root folder.")
            spec.ready_for_prepare = len(spec.errors) == 0
            spec.ready_for_install = spec.ready_for_prepare
        else:
            return

        self._source_spec = spec

        if spec.audio_path and not self._get_audio_path():
            if mode == "manual":
                self._manual_audio_entry.insert(0, spec.audio_path)
            else:
                self.mode_audio_entry.insert(0, spec.audio_path)
        if spec.video_path and not self._get_video_path():
            if mode == "manual":
                self._manual_video_entry.insert(0, spec.video_path)
            else:
                self.mode_video_entry.insert(0, spec.video_path)

        # Auto-populate legacy HTML inputs so existing flow stays usable.
        if spec.asset_html:
            self.asset_html_entry.delete(0, tk.END)
            self.asset_html_entry.insert(0, spec.asset_html)
        if spec.nohud_html:
            self.nohud_html_entry.delete(0, tk.END)
            self.nohud_html_entry.insert(0, spec.nohud_html)

        if spec.errors:
            self.mode_status_var.set("Analyze failed: " + " | ".join(spec.errors))
        else:
            msg = f"Analyze OK ({mode})"
            if spec.warnings:
                msg += " | " + " | ".join(spec.warnings)
            self.mode_status_var.set(msg)

        self._on_html_inputs_changed()

    def _prepare_mode_source(self):
        if not self._source_spec:
            self._analyze_mode_source()
        spec = self._source_spec
        if not spec:
            return

        if spec.errors:
            messagebox.showerror("Prepare", "Fix source errors before prepare:\n\n" + "\n".join(spec.errors))
            return

        if spec.mode in {"fetch", "html", "batch"}:
            self.mode_status_var.set("Prepare complete (no extra staging required for this mode).")
            return

        if spec.mode == "ipk":
            os.makedirs(spec.ipk_extracted, exist_ok=True)
            try:
                import ipk_unpack
                ipk_unpack.extract(spec.ipk_file, spec.ipk_extracted)
            except Exception as e:
                messagebox.showerror("Prepare Failed", f"Could not unpack IPK:\n{e}")
                return
            spec.ready_for_install = bool(spec.audio_path and spec.video_path)
            self.mode_status_var.set(f"Prepared IPK source at {spec.ipk_extracted}")
            return

        if spec.mode == "manual" and spec.submode == "downloaded_assets" and not spec.ipk_extracted:
            messagebox.showwarning(
                "Prepare Required",
                "Downloaded assets source is missing ipk_extracted/.\n"
                "Please prepare/extract scene IPK first or use IPK mode.")
            return

        self.mode_status_var.set("Prepare complete.")

    def _on_unified_install(self):
        """Single Install button dispatch based on current mode."""
        self._install_from_mode()

    def _install_from_mode(self):
        mode = self.source_mode_var.get()
        if mode == "fetch":
            self._on_fetch_install()
            return

        if mode == "html":
            self._on_install(started_from_fetch=False)
            return

        if mode == "batch":
            source_root = self._batch_folder_entry.get().strip()
            if source_root and os.path.isfile(source_root):
                source_root = os.path.dirname(source_root)
            if not source_root or not os.path.isdir(source_root):
                messagebox.showerror("Batch", "Select a valid batch root folder first.")
                return
            self._run_batch_mode(source_root)
            return

        if not self._source_spec:
            self._analyze_mode_source()
        spec = self._source_spec
        if not spec:
            return
        if spec.errors:
            messagebox.showerror("Install", "Fix source errors before install:\n\n" + "\n".join(spec.errors))
            return

        if mode == "ipk" and not os.path.isdir(spec.ipk_extracted):
            self._prepare_mode_source()
            if not os.path.isdir(spec.ipk_extracted):
                return

        if mode == "manual" and spec.submode == "downloaded_assets" and not spec.ipk_extracted:
            messagebox.showerror(
                "Install",
                "Manual downloaded assets mode requires ipk_extracted/.\n"
                "Use a prepared folder or prepare via IPK mode first.")
            return

        self._install_from_manual_spec(spec)

    def _run_batch_mode(self, root_folder):
        if self._pipeline_running:
            return

        self._pipeline_running = True
        self.mode_install_btn.configure(state="disabled")
        self.mode_status_var.set("Batch mode running...")

        def _run():
            script_dir = os.path.dirname(os.path.abspath(__file__))
            cmd = [
                sys.executable,
                os.path.join(script_dir, "batch_install_maps.py"),
                "--maps-dir",
                root_folder,
                "--jd-dir",
                self.jd_dir_entry.get().strip() or script_dir,
                "--quality",
                self.quality_var.get(),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)

            def _after():
                self._pipeline_running = False
                self.mode_install_btn.configure(state="normal")
                if proc.stdout:
                    print(proc.stdout)
                if proc.stderr:
                    print(proc.stderr)
                if proc.returncode == 0:
                    self.mode_status_var.set("Batch mode complete.")
                    messagebox.showinfo("Batch", "Batch installation completed.")
                else:
                    self.mode_status_var.set("Batch mode failed.")
                    messagebox.showerror("Batch", "Batch installation failed. Check logs output.")

            self.root.after(0, _after)

        threading.Thread(target=_run, daemon=True).start()

    def _install_from_manual_spec(self, spec):
        require_html = spec.mode == "manual" and spec.submode == "downloaded_assets"
        asset_html = spec.asset_html or "(manual)"
        nohud_html = spec.nohud_html or "(manual)"

        def _build_state():
            map_name = spec.codename or os.path.basename(spec.source_path)
            state = map_installer.PipelineState(
                map_name=map_name,
                asset_html=asset_html,
                nohud_html=nohud_html,
                jd_dir=self.jd_dir_entry.get().strip() or None,
                quality=self.quality_var.get(),
                original_map_name=map_name,
            )
            source_type = "ipk_file" if spec.mode == "ipk" else (spec.submode or "manual")
            map_installer.configure_manual_source(
                state,
                source_type=source_type,
                source_dir=spec.source_path,
                ipk_extracted=spec.ipk_extracted,
                audio_path=self._get_audio_path() or spec.audio_path,
                video_path=self._get_video_path() or spec.video_path,
                codename=spec.codename,
                manual_ipk_file=spec.ipk_file,
            )
            return state

        self._launch_install(
            _build_state,
            asset_html=asset_html,
            nohud_html=nohud_html,
            require_html=require_html)

    def _redirect_stdout(self):
        handler = TextWidgetHandler(self.log_text, self.root)
        handler.setFormatter(logging.Formatter("%(message)s"))
        setup_gui_logging(handler)

        # Also set up a file handler for per-install log files
        self._log_handler = handler

        # Capture stray print() calls from pipeline code / third-party libs
        self._stdout_logger = StdoutToLogger(logger, logging.INFO)
        sys.stdout = self._stdout_logger
        sys.stderr = self._stdout_logger

    def _restore_stdout(self):
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

    def _set_preview_state(self, state):
        """Enable or disable the media control bar and preview action buttons."""
        self.preview.set_enabled(state)
        for btn in (self.preview_btn, self.stop_preview_btn):
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass

    def _disable_all_install_controls(self):
        """Disable all install-related controls during pipeline or preflight."""
        self._pipeline_running = True
        self.install_btn.configure(state="disabled")
        self.fetch_install_btn.configure(state="disabled")
        self.preflight_btn.configure(state="disabled", text="Auto-checking...")
        self.mode_install_btn.configure(state="disabled")
        self.codename_entry.configure(state="disabled")
        self._set_html_inputs_state(False)

    def _restore_install_controls(self):
        """Re-enable install controls after pipeline finishes or fails."""
        self._pipeline_running = False
        self._fetch_mode_lock = False
        self.preflight_btn.configure(state="normal", text="Pre-flight Check")
        self.mode_install_btn.configure(state="normal")
        self.fetch_install_btn.configure(state="normal")
        self.codename_entry.configure(state="normal")
        self._set_html_inputs_state(True)
        self._on_html_inputs_changed()

    def _set_sync_state(self, state):
        """Enable or disable all widgets inside the sync refinement frame."""
        for child in self.sync_frame.winfo_children():
            self._set_widget_state_recursive(child, state)
            
        # Re-apply video override specific state if sync frame is enabled
        if state == "normal" and not self.v_override_enabled_var.get():
            for w in self._vo_row_widgets:
                w.configure(state="disabled")
            try:
                self.sync_beatgrid_btn.configure(state="disabled")
            except AttributeError:
                pass

    def _set_widget_state_recursive(self, widget, state):
        try:
            widget.configure(state=state)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._set_widget_state_recursive(child, state)

    def _refresh_value_displays(self):
        for display, var in [(self._vo_display, self.v_override_var),
                             (self._ao_display, self.a_offset_var)]:
            # Restore state temporarily to modify text
            old_state = display.cget("state")
            display.configure(state="normal")
            display.delete(0, tk.END)
            display.insert(0, f"{var.get():.5f}")
            display.configure(state="readonly" if old_state != "disabled" else "disabled")

    def _update_step_status(self, index, status):
        glyphs = {"pending": "  ", "running": ">>", "done": "OK", "error": "!!"}
        glyph = glyphs.get(status, "  ")
        text = f"[{glyph}] Step {index+1}:  {self.STEP_NAMES[index]}"
        lbl = self.step_labels[index]
        lbl.configure(text=text)
        if status == "running":
            lbl.configure(font=("Consolas", 9, "bold"), foreground="")
        elif status == "done":
            lbl.configure(font=("Consolas", 9), foreground="green")
        elif status == "error":
            lbl.configure(font=("Consolas", 9), foreground="red")
        else:
            lbl.configure(font=("Consolas", 9), foreground="")


    # ------------------------------------------------------------------
    # Pre-flight
    # ------------------------------------------------------------------

    def _on_preflight(self):
        # If skip_preflight is enabled, auto-pass
        if self._settings.get("skip_preflight", False):
            print("    Pre-flight skipped (disabled in settings)")
            self._preflight_passed = True
            self._on_preflight_done(True)
            return

        jd_dir = self.jd_dir_entry.get().strip()
        asset = self.asset_html_entry.get().strip()
        nohud = self.nohud_html_entry.get().strip()
        mode = self.source_mode_var.get()
        require_html = mode in {"fetch", "html"}
        if not jd_dir:
            messagebox.showerror("Missing",
                                 "Game Directory is required for pre-flight check.")
            return

        self.preflight_btn.configure(state="disabled", text="Checking...")

        def _run():
            result = map_installer.preflight_check(
                jd_dir, asset or "(not set)", nohud or "(not set)",
                interactive=False, require_html=require_html)
            # preflight_check returns (False, True) when ffmpeg is missing in
            # non-interactive mode, plain False for other failures, or True.
            if isinstance(result, tuple):
                passed, ffmpeg_missing = result
            else:
                passed = result
                ffmpeg_missing = False

            if not passed and ffmpeg_missing:
                # FFmpeg is missing — offer to download it via GUI dialog
                self.root.after(0, self._offer_ffmpeg_install, jd_dir, asset, nohud)
                return
            if not passed:
                # Other failures (bundled tools missing, etc.)
                self._preflight_passed = False
                self.root.after(0, self._on_preflight_done, False)
                return
            self._preflight_passed = True
            self.root.after(0, self._on_preflight_done, True)

        threading.Thread(target=_run, daemon=True).start()

    def _offer_ffmpeg_install(self, jd_dir, asset, nohud):
        mode = self.source_mode_var.get()
        require_html = mode in {"fetch", "html"}
        result = messagebox.askyesno(
            "FFmpeg Not Found",
            "FFmpeg is required but was not found on your system.\n\n"
            "Would you like to download and install it automatically?\n"
            "(This may take a few minutes)")
        if result:
            def _run_install():
                ok = map_installer.preflight_check(
                    jd_dir, asset or "(not set)", nohud or "(not set)",
                    auto_install=True, interactive=False, require_html=require_html)
                # When auto_install=True ffmpeg gets installed, so the
                # return is plain bool (no tuple).
                passed = ok if not isinstance(ok, tuple) else ok[0]
                self._preflight_passed = passed
                self.root.after(0, self._on_preflight_done, passed)
            threading.Thread(target=_run_install, daemon=True).start()
        else:
            self._preflight_passed = False
            self._on_preflight_done(False)

    def _on_preflight_done(self, passed):
        self.preflight_btn.configure(state="normal", text="Pre-flight Check")
        if passed:
            self.install_btn.configure(state="normal")
            if self._settings.get("show_preflight_success_popup", True):
                messagebox.showinfo("Pre-flight", "All checks passed!")
        else:
            self.install_btn.configure(state="disabled")
            messagebox.showwarning(
                "Pre-flight",
                "Some checks failed. See the log output for details.\n\n"
                "Common fixes:\n"
                "  - Install FFmpeg (or click Yes when prompted)\n"
                "  - Verify the Game Directory path is correct\n"
                "  - Ensure bundled tools are in the script directory")

    def _show_quickstart_if_needed(self):
        """Display a short beginner hint once (or until disabled in settings)."""
        gui_settings.show_quickstart_if_needed(self.root, self._settings)

    def _on_clear_cache(self):
        cleared = map_installer.clear_paths_cache()
        if cleared:
            messagebox.showinfo(
                "Cache Cleared",
                "Path cache cleared.\n\n"
                "The next Pre-flight Check or Install will re-scan for game data.")
        else:
            messagebox.showinfo("Cache Cleared", "No path cache found (already clear).")

    def _on_readjust(self):
        """Re-adjust offset on an already-installed map from its download folder."""
        if self._pipeline_running:
            return
        download_dir = filedialog.askdirectory(
            title="Select Map Download Folder",
            mustexist=True)
        if not download_dir:
            return

        jd_dir = self.jd_dir_entry.get().strip() or None

        # Reconstruct state in a background thread
        self.readjust_btn.configure(state="disabled", text="Loading...")

        def _build():
            try:
                state = map_installer.reconstruct_state_for_readjust(
                    download_dir, jd_dir=jd_dir)
                state._interactive = False
                self.root.after(0, lambda: self._on_readjust_ready(state))
            except (FileNotFoundError, RuntimeError) as e:
                self.root.after(0, lambda: self._on_readjust_error(str(e)))

        threading.Thread(target=_build, daemon=True).start()

    def _on_readjust_ready(self, state):
        """Called on main thread when readjust state is built successfully."""
        self.readjust_btn.configure(state="normal", text="Re-adjust Offset")
        self.pipeline_state = state

        # Populate sync values
        self.v_override_var.set(
            state.v_override if state.v_override is not None else 0.0)
        self.a_offset_var.set(
            state.a_offset if state.a_offset is not None else 0.0)
        self._refresh_value_displays()

        # Enable sync refinement and preview controls
        self._set_sync_state("normal")
        self._set_preview_state("normal")

        messagebox.showinfo(
            "Readjust Mode",
            f"Loaded '{state.map_name}' for offset readjustment.\n\n"
            f"VIDEO_OVERRIDE: {state.v_override}\n"
            f"AUDIO_OFFSET: {state.a_offset}\n\n"
            "Use the Sync Refinement panel to adjust, then click 'Apply & Finish'.")

    def _on_readjust_error(self, error_msg):
        """Called on main thread when readjust state build fails."""
        self.readjust_btn.configure(state="normal", text="Re-adjust Offset")
        messagebox.showerror("Readjust Error", f"Failed to load map for readjustment:\n\n{error_msg}")

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def _on_settings(self):
        """Open the settings dialog."""
        gui_settings.open_settings_dialog(
            self.root, self._settings, self._apply_settings)

    def _apply_settings(self, new_settings):
        """Apply saved settings to the current session."""
        self._settings = new_settings
        self.quality_var.set(new_settings["default_quality"])
        if new_settings["skip_preflight"] and not self._pipeline_running:
            self._preflight_passed = True
            self.install_btn.configure(state="normal")

    # ------------------------------------------------------------------
    # Install pipeline
    # ------------------------------------------------------------------

    def _on_fetch_install(self):
        """Fetch HTML via JDH_Downloader, then trigger install."""
        if self._pipeline_running:
            return

        self._last_run_from_fetch = True

        codename = self.codename_entry.get().strip().strip('"').strip("'")
        if not codename:
            messagebox.showerror(
                "Missing Input",
                "Enter a map codename (e.g. TemperatureALT) in the Codename field.")
            return

        if any(ch.isspace() for ch in codename):
            compact = "".join(c for c in codename if not c.isspace())
            use_compact = messagebox.askyesno(
                "Codename Contains Spaces",
                "The codename contains spaces, which usually means it was pasted with extra characters.\n\n"
                f"Use '{compact}' instead?"
            )
            if not use_compact:
                return
            codename = compact
            self.codename_entry.delete(0, tk.END)
            self.codename_entry.insert(0, codename)

        # Disable controls during fetch
        self._fetch_mode_lock = True
        self._disable_all_install_controls()

        # Reset progress
        for i in range(len(self.STEP_NAMES)):
            self._update_step_status(i, "pending")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        maps_dir = os.path.join(script_dir, "MapDownloads")

        def _fetch():
            try:
                print("--- JDH_Downloader: Fetching HTML from Discord ---")
                asset_html, nohud_html = map_installer.fetch_html_via_downloader(
                    codename, maps_dir)
                print("--- Fetch complete, starting installation ---\n")

                # Fill in the GUI entries on the main thread, then trigger install
                def _proceed():
                    self._pipeline_running = False

                    # Temporarily enable HTML inputs so fetched paths can be injected.
                    self._set_html_inputs_state(True)

                    # Fill Asset HTML
                    self.asset_html_entry.delete(0, tk.END)
                    self.asset_html_entry.insert(0, asset_html)

                    # Fill NoHUD HTML
                    self.nohud_html_entry.delete(0, tk.END)
                    self.nohud_html_entry.insert(0, nohud_html)

                    # Re-enable and trigger install
                    self.install_btn.configure(state="normal")
                    self.preflight_btn.configure(state="normal")
                    self._on_install(started_from_fetch=True)

                self.root.after(0, _proceed)

            except RuntimeError as e:
                err_msg = str(e)
                print(f"ERROR: {err_msg}")
                def _error():
                    self._restore_install_controls()
                    messagebox.showerror(
                        "Fetch Failed",
                        f"JDH_Downloader failed for '{codename}':\n\n{err_msg}")
                self.root.after(0, _error)

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_install(self, started_from_fetch=False):
        if self._pipeline_running:
            return

        self._last_run_from_fetch = bool(started_from_fetch)

        asset_html = self.asset_html_entry.get().strip()
        nohud_html = self.nohud_html_entry.get().strip()

        if not asset_html or not nohud_html:
            messagebox.showerror(
                "Missing Input",
                "Both Asset HTML and NOHUD HTML files are required.\n\n"
                "Use the 'Browse' buttons to select the downloaded HTML files,\n"
                "or enter a codename and click 'Fetch & Install' to automate it.")
            return

        if not os.path.isfile(asset_html):
            messagebox.showerror(
                "Missing File",
                f"Asset HTML file was not found:\n{asset_html}\n\n"
                "Select a valid file and retry.")
            return

        if not os.path.isfile(nohud_html):
            messagebox.showerror(
                "Missing File",
                f"NOHUD HTML file was not found:\n{nohud_html}\n\n"
                "Select a valid file and retry.")
            return

        def _build_state():
            map_name = self._derive_codename(asset_html, nohud_html, fallback=None)
            if not map_name:
                messagebox.showerror(
                    "Missing Input",
                    "Could not detect map codename from the selected files.\n"
                    "Try selecting valid HTML files from a map folder.")
                return None
            # Check for non-ASCII characters and prompt for replacement
            original_map_name = map_name
            if any(ord(c) > 127 for c in map_name):
                non_ascii = [c for c in map_name if ord(c) > 127]
                replacement = simpledialog.askstring(
                    "Non-ASCII Characters Detected",
                    f"Map name '{map_name}' contains non-standard characters: {non_ascii}\n"
                    f"Some of these (e.g. Chinese characters) may cause file path issues.\n\n"
                    f"Enter a replacement name, or click Cancel to keep the original as-is:",
                    initialvalue=map_name,
                    parent=self.root
                )
                if replacement and replacement.strip():
                    map_name = replacement.strip()

            return map_installer.PipelineState(
                map_name=map_name,
                asset_html=asset_html,
                nohud_html=nohud_html,
                jd_dir=self.jd_dir_entry.get().strip() or None,
                quality=self.quality_var.get(),
                original_map_name=original_map_name
            )

        self._launch_install(
            _build_state,
            asset_html=asset_html,
            nohud_html=nohud_html,
            require_html=True)

    def _launch_install(self, state_factory, asset_html="(manual)",
                        nohud_html="(manual)", require_html=True):
        """Unified install: validates, runs auto-preflight if needed, starts pipeline.

        Args:
            state_factory: Callable() -> PipelineState, called after preflight passes.
            asset_html: HTML path for preflight (or "(manual)" for non-HTML modes).
            nohud_html: HTML path for preflight (or "(manual)" for non-HTML modes).
            require_html: Whether preflight should require valid HTML files.
        """
        if self._pipeline_running:
            return

        jd_dir = self.jd_dir_entry.get().strip()
        if not jd_dir:
            messagebox.showerror("Missing Input", "Game Directory is required.")
            return

        self._disable_all_install_controls()

        if not self._settings.get("skip_preflight", False) and not self._preflight_passed:
            print("    Pre-flight was not run manually. Running automatic pre-flight now...")

            def _auto_preflight():
                result = map_installer.preflight_check(
                    jd_dir, asset_html, nohud_html,
                    auto_install=True, interactive=False,
                    require_html=require_html)
                passed = result if not isinstance(result, tuple) else result[0]

                def _after():
                    if not passed:
                        self._preflight_passed = False
                        self._restore_install_controls()
                        self.install_btn.configure(state="disabled")
                        messagebox.showwarning(
                            "Pre-flight Failed",
                            "Automatic pre-flight failed.\n\n"
                            "Review Log Output for details, then fix the issue and retry.")
                        return

                    self._preflight_passed = True
                    self.install_btn.configure(state="normal")
                    # Build the PipelineState and start the pipeline
                    state = state_factory()
                    if state is None:
                        self._restore_install_controls()
                        return
                    state._interactive = False
                    self._start_pipeline_with_state(state)

                self.root.after(0, _after)

            threading.Thread(target=_auto_preflight, daemon=True).start()
            return

        # Preflight already passed -- build state immediately
        state = state_factory()
        if state is None:
            self._restore_install_controls()
            return
        state._interactive = False
        self._start_pipeline_with_state(state)

    def _start_pipeline_with_state(self, state):
        """Common start logic for HTML, IPK, and manual source modes.

        Controls are already disabled by _launch_install -> _disable_all_install_controls.
        """
        # Reset progress
        for i in range(len(self.STEP_NAMES)):
            self._update_step_status(i, "pending")

        self.pipeline_state = state

        # Close any previous log file handler and open a new one for this install run
        if self._file_handler:
            root_logger = logging.getLogger("jd2021")
            root_logger.removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None

        script_dir = os.path.dirname(os.path.abspath(__file__))
        logs_dir = os.path.join(script_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = os.path.join(
            logs_dir, f"install_{state.map_name}_{timestamp}.log")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"))
        logging.getLogger("jd2021").addHandler(fh)
        self._file_handler = fh
        logger.info("Log file: %s", log_path)

        self.pipeline_thread = threading.Thread(
            target=self._run_pipeline, daemon=True)
        self.pipeline_thread.start()

    def _run_pipeline(self):
        state = self.pipeline_state

        print(f"--- Environment ---")
        print(f"Game Dir:    {state.jd21_dir}")
        print(f"Search Root: {state.jd_dir}")
        print(f"Map Name:    {state.map_name}")
        print(f"Asset HTML:  {state.asset_html}")
        print(f"-------------------")

        # Skip preflight here since we already passed it via the button
        print(f"=== Starting Automation for {state.map_name} ===")

        step_fns = [fn for _, fn in map_installer.PIPELINE_STEPS]
        for i, step_fn in enumerate(step_fns):
            self.root.after(0, self._update_step_status, i, "running")
            try:
                step_fn(state)
                self.root.after(0, self._update_step_status, i, "done")
            except Exception as e:
                self.root.after(0, self._update_step_status, i, "error")
                step_name = self.STEP_NAMES[i]
                print(f"ERROR at step {i+1} ({step_name}): {e}")
                hint = ""
                if i <= 1:
                    hint = "\n\nIf download failed, your HTML links may have expired.\nGet fresh links and try again."
                self.root.after(0, lambda err=str(e), idx=i, sn=step_name, h=hint: messagebox.showerror(
                    "Pipeline Error", f"Step {idx+1} ({sn}) failed:\n{err}{h}"))
                self.root.after(0, self._on_pipeline_error)
                return

            # After step 4 (IPK unpack), check for non-ASCII metadata and prompt
            if i == 4 and hasattr(state, 'ipk_extracted') and state.ipk_extracted:
                self._check_metadata_gui(state)

        print("=== Automation Complete! ===")
        self.root.after(0, self._on_pipeline_complete)

    def _check_metadata_gui(self, state):
        """Check for non-ASCII characters in song metadata and prompt via GUI dialogs."""
        try:
            problems = map_builder.check_metadata_encoding(state.ipk_extracted)
        except Exception as e:
            logger.warning("metadata encoding check failed: %s", e)
            return

        if not problems:
            return

        # For each problematic field, ask the user on the main thread
        for field, original_val in problems.items():
            if field in state.metadata_overrides:
                continue  # Already overridden
            non_ascii = [c for c in original_val if ord(c) > 127]
            result_event = threading.Event()
            result_holder = [None]

            def _ask(f=field, v=original_val, na=non_ascii):
                # Custom dialog to handle long strings with word wrap
                dlg = tk.Toplevel(self.root)
                dlg.title("Non-ASCII Characters in Metadata")
                dlg.geometry("600x400")
                dlg.minsize(400, 300)
                dlg.transient(self.root)
                dlg.grab_set()

                # Center the dialog
                dlg.update_idletasks()
                x = self.root.winfo_x() + (self.root.winfo_width() - 600) // 2
                y = self.root.winfo_y() + (self.root.winfo_height() - 400) // 2
                dlg.geometry(f"+{x}+{y}")

                content = ttk.Frame(dlg, padding=12)
                content.pack(fill="both", expand=True)

                msg = (f"The '{f}' field contains non-ASCII characters:\n\n"
                       f"  Characters: {na}\n\n"
                       f"Some characters (e.g. Chinese) may cause game engine errors, "
                       f"while others (e.g. ©) work fine. Replace, auto-strip, or ignore to keep the original:")
                lbl = ttk.Label(content, text=msg, wraplength=550)
                lbl.pack(fill="x", pady=(0, 8))

                # Display the current (long) value in a read-only text widget
                ttk.Label(content, text="Current Value:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
                curr_txt = tk.Text(content, height=4, wrap="word", font=("Consolas", 9), bg="#f0f0f0")
                curr_txt.pack(fill="x", pady=(2, 10))
                curr_txt.insert("1.0", v)
                curr_txt.configure(state="disabled")

                # Input for replacement
                ttk.Label(content, text="Replacement:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
                rep_txt = tk.Text(content, height=4, wrap="word", font=("Consolas", 9))
                rep_txt.pack(fill="both", expand=True, pady=(2, 10))

                # Pre-fill with auto-stripped value
                safe = ''.join(c for c in v if ord(c) < 128)
                rep_txt.insert("1.0", safe)

                # Buttons
                btn_frame = ttk.Frame(content)
                btn_frame.pack(fill="x")

                def _on_ok():
                    result_holder[0] = rep_txt.get("1.0", "end-1c").strip()
                    dlg.destroy()

                def _on_auto_strip():
                    result_holder[0] = safe
                    dlg.destroy()

                def _on_ignore():
                    result_holder[0] = v  # Keep original unchanged
                    dlg.destroy()

                ttk.Button(btn_frame, text="Apply Replacement", command=_on_ok).pack(side="right", padx=(4, 0))
                ttk.Button(btn_frame, text="Auto-Strip", command=_on_auto_strip).pack(side="right", padx=(4, 0))
                ttk.Button(btn_frame, text="Ignore", command=_on_ignore).pack(side="right")

                dlg.protocol("WM_DELETE_WINDOW", _on_ignore)
                self.root.wait_window(dlg)
                result_event.set()

            self.root.after(0, _ask)
            # Block pipeline thread until user responds, but check for window close
            while not result_event.wait(timeout=0.5):
                if self._closing:
                    return

            state.metadata_overrides[field] = result_holder[0]
            print(f"    {field}: '{original_val}' → '{result_holder[0]}'")

    def _on_pipeline_error(self):
        self._restore_install_controls()
        self.install_btn.configure(state="normal")

        # If this run came from Fetch mode, clear stale HTML inputs so
        # the user can immediately retry Fetch & Install.
        if self._last_run_from_fetch:
            self.asset_html_entry.delete(0, tk.END)
            self.nohud_html_entry.delete(0, tk.END)
            print("    Cleared stale HTML inputs after fetch-based failure. Retry Fetch & Install.")

        self._last_run_from_fetch = False

    def _on_pipeline_complete(self):
        state = self.pipeline_state
        self._restore_install_controls()

        # Populate sync values from pipeline
        self.v_override_var.set(
            state.v_override if state.v_override is not None else 0.0)
        self.a_offset_var.set(
            state.a_offset if state.a_offset is not None else 0.0)
        self._refresh_value_displays()

        # Enable sync refinement and preview controls
        self._set_sync_state("normal")
        self._set_preview_state("normal")

        # Auto-start preview so users can validate sync immediately.
        self.preview.launch(
            state.video_path, state.audio_path,
            self.v_override_var.get(), self.a_offset_var.get())

        if not self._settings.get("suppress_offset_notification", False):
            messagebox.showinfo(
                "Complete",
                f"Installation pipeline finished for {state.map_name}.\n\n"
                "The Tool isnt perfect, offset refinement is needed.\n\n"
                "Use the Sync Refinement panel below to fine-tune "
                "audio/video timing, then click 'Apply & Finish'.")

    # ------------------------------------------------------------------
    # Sync refinement callbacks
    # ------------------------------------------------------------------

    def _debounce_resume_preview(self):
        """Convenience: debounce-resume preview with current state/vars."""
        state = self.pipeline_state
        if state and state.video_path and state.audio_path:
            self.preview.debounce_resume(
                state.video_path, state.audio_path,
                self.v_override_var.get(), self.a_offset_var.get())

    def _on_increment(self, var, delta):
        new_val = round(var.get() + delta, 5)
        var.set(new_val)
        self._refresh_value_displays()
        self._debounce_resume_preview()

    def _on_sync_beatgrid(self):
        self.a_offset_var.set(self.v_override_var.get())
        self._refresh_value_displays()
        self._debounce_resume_preview()

    def _on_pad_audio(self):
        state = self.pipeline_state
        if not state or not state.video_path or not state.audio_path:
            return

        self.pad_audio_btn.configure(state="disabled")

        def _compute():
            try:
                def get_dur(p):
                    res = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries",
                         "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", p],
                        capture_output=True, text=True)
                    return float(res.stdout.strip())

                v_dur = get_dur(state.video_path)
                a_dur = get_dur(state.audio_path)
                diff = round(v_dur - a_dur, 5)
                print(f"    Video: {v_dur:.2f}s, Audio: {a_dur:.2f}s, "
                      f"Padding: {diff:.3f}s")

                def _done():
                    self.pad_audio_btn.configure(state="normal")
                    self.a_offset_var.set(diff)
                    self._refresh_value_displays()
                    self._debounce_resume_preview()

                self.root.after(0, _done)
            except Exception as e:
                print(f"    ERROR computing durations: {e}")
                self.root.after(0, lambda: self.pad_audio_btn.configure(state="normal"))

        threading.Thread(target=_compute, daemon=True).start()

    def _on_preview(self):
        state = self.pipeline_state
        if state:
            self.preview.launch(
                state.video_path, state.audio_path,
                self.v_override_var.get(), self.a_offset_var.get())

    def _on_stop_preview(self):
        self.preview.stop()

    def _on_apply(self):
        if self._pipeline_running:
            return
        state = self.pipeline_state
        if not state:
            return

        self._pipeline_running = True
        self.apply_btn.configure(state="disabled")

        v_override = self.v_override_var.get()
        a_offset = self.a_offset_var.get()

        # Kill any running preview before applying
        self.preview.kill()

        def _apply():
            try:
                print(f"    Applying: VIDEO_OVERRIDE={v_override:.5f}, "
                      f"AUDIO_OFFSET={a_offset:.5f}")
                map_builder.generate_text_files(
                    state.map_name, state.ipk_extracted,
                    state.target_dir, v_override,
                    metadata_overrides=getattr(state, 'metadata_overrides', None))
                state.v_override = v_override

                map_installer.reprocess_audio(state, a_offset, v_override)

                print("    Sync changes applied and config saved.")

                def _done():
                    self._pipeline_running = False
                    self.apply_btn.configure(state="normal")
                    messagebox.showinfo(
                        "Applied",
                        f"Sync values applied and files regenerated.\n\n"
                        f"VIDEO_OVERRIDE: {v_override:.5f}\n"
                        f"AUDIO_OFFSET: {a_offset:.5f}\n\n"
                        f"Map '{state.map_name}' is ready to use.")
                    self.install_btn.configure(state="normal")

                self.root.after(0, _done)
                self.root.after(100, lambda: self._prompt_cleanup(state))
            except Exception as e:
                print(f"    ERROR applying changes: {e}")
                def _err():
                    self._pipeline_running = False
                    self.apply_btn.configure(state="normal")
                    messagebox.showerror("Error", f"Failed to apply:\n{e}")
                self.root.after(0, _err)

        threading.Thread(target=_apply, daemon=True).start()

    # ------------------------------------------------------------------
    # Post-apply cleanup
    # ------------------------------------------------------------------

    def _prompt_cleanup(self, state):
        """Ask user whether to delete downloaded source files after apply."""
        gui_settings.prompt_cleanup(self.root, state, self._settings)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _on_close(self):
        self._closing = True
        self.preview.kill()
        self._restore_stdout()
        if self._file_handler:
            root_logger = logging.getLogger("jd2021")
            root_logger.removeHandler(self._file_handler)
            self._file_handler.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    MapInstallerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
