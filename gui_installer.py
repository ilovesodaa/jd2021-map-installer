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
from PIL import Image, ImageTk

# Ensure we can import sibling scripts regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import map_installer
import map_builder
import map_downloader


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
        self.id = self.widget.after(500, self.showtip)

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


class StdoutRedirector:
    """Bridges print() calls from worker threads to a tkinter Text widget via a queue.
    If log_file is set, also writes to it simultaneously."""

    def __init__(self, text_widget, root, log_file=None):
        self.text_widget = text_widget
        self.root = root
        self.log_file = log_file
        self._queue = queue.Queue()
        self._poll()

    def write(self, text):
        self._queue.put(text)
        if self.log_file:
            try:
                self.log_file.write(text)
                self.log_file.flush()
            except Exception:
                pass

    def flush(self):
        pass

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


class MapInstallerGUI:

    STEP_NAMES = [name for name, _ in map_installer.PIPELINE_STEPS]

    def __init__(self, root):
        self.root = root
        self.root.title("JD2021 Map Installer")
        self.root.geometry("850x818")
        self.root.minsize(850, 818)

        # State
        self.pipeline_state = None
        self.pipeline_thread = None
        self.preview_ffmpeg = None
        self.preview_ffplay = None
        self._preview_lock = threading.Lock()
        self._frame_stop = None
        self._frame_thread = None
        self._current_photo = None
        self._preview_position = 0.0
        self._preview_playing = False
        self._preview_auto_resume = False
        self._preview_resizing_timer = None
        self._preview_debounce_timer = None
        self._preview_duration = 0.0
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._preflight_passed = False
        self._log_file = None

        # Tkinter variables for sync refinement
        self.v_override_var = tk.DoubleVar(value=0.0)
        self.a_offset_var = tk.DoubleVar(value=0.0)
        self.v_override_enabled_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._redirect_stdout()

        # Auto-detect JD directory
        detected = map_installer.detect_jd_dir()
        self.jd_dir_entry.insert(0, detected)

        # Clean up on close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=8, pady=4)

        # ===================== CONFIGURATION =====================
        cfg = ttk.LabelFrame(container, text="Configuration", padding=6)
        cfg.pack(fill="x", pady=(0, 4))

        # Warning Label (Asset expiration)
        warning_lbl = tk.Label(
            cfg, 
            text="⚠ Asset/NoHUD links expire after ~30 minutes! Fetch fresh links if download fails.",
            fg="#856404", # Darker warning gold
            font=("Consolas", 9, "bold")
        )
        warning_lbl.grid(row=0, column=0, columnspan=3, pady=(0, 6), sticky="w")

        for i, (label_text, attr_name, browse_type) in enumerate([
            ("Map Name:", "map_name_entry", None),
            ("Asset HTML:", "asset_html_entry", "html"),
            ("NOHUD HTML:", "nohud_html_entry", "html"),
            ("Game Directory:", "jd_dir_entry", "dir"),
        ]):
            ttk.Label(cfg, text=label_text, width=16, anchor="e").grid(
                row=i+1, column=0, sticky="e", padx=(0, 4))
            entry = ttk.Entry(cfg, width=64)
            entry.grid(row=i+1, column=1, sticky="ew", pady=1)
            setattr(self, attr_name, entry)

            # Tooltips for configuration entries
            if attr_name == "map_name_entry":
                ToolTip(entry, "Auto-filled from Asset HTML. Only edit if detection fails.")
            elif attr_name == "asset_html_entry":
                ToolTip(entry, "Click 'Browse' to select the downloaded map asset HTML file containing texture/audio links.")
            elif attr_name == "nohud_html_entry":
                ToolTip(entry, "Click 'Browse' to select the downloaded NoHUD HTML file containing the map video link.")
            elif attr_name == "jd_dir_entry":
                ToolTip(entry, "Path to the Just Dance 2021 installation folder.")
            if browse_type:
                if attr_name == "asset_html_entry":
                    cmd = (lambda e=entry, bt=browse_type: self._browse(e, bt, self.map_name_entry))
                else:
                    cmd = (lambda e=entry, bt=browse_type: self._browse(e, bt))
                ttk.Button(cfg, text="Browse", width=8, command=cmd).grid(
                    row=i+1, column=2, padx=(4, 0))

        # Map name is auto-derived from Asset HTML; readonly unless detection fails
        self.map_name_entry.configure(state="readonly")

        cfg.columnconfigure(1, weight=1)

        # Video quality selector
        ttk.Label(cfg, text="Video Quality:", width=16, anchor="e").grid(
            row=5, column=0, sticky="e", padx=(0, 4))
        self.quality_var = tk.StringVar(value="ultra_hd")
        quality_combo = ttk.Combobox(cfg, textvariable=self.quality_var,
                                     values=["ultra_hd", "ultra", "high_hd", "high", "mid_hd", "mid", "low_hd", "low"],
                                     state="readonly", width=12)
        quality_combo.grid(row=5, column=1, sticky="w", pady=1)

        btn_row = ttk.Frame(cfg)
        btn_row.grid(row=6, column=0, columnspan=3, pady=(6, 0))
        self.preflight_btn = ttk.Button(
            btn_row, text="Pre-flight Check", command=self._on_preflight)
        self.preflight_btn.pack(side="left", padx=(0, 12))
        ToolTip(self.preflight_btn, "Validates file paths and necessary tools (ffmpeg, ffplay) before installing.")

        self.install_btn = ttk.Button(
            btn_row, text="Install Map", command=self._on_install, state="disabled")
        self.install_btn.pack(side="left")
        ToolTip(self.install_btn, "Starts the download and installation pipeline.")

        self.clear_cache_btn = ttk.Button(
            btn_row, text="Clear Path Cache", command=self._on_clear_cache)
        self.clear_cache_btn.pack(side="left", padx=(12, 0))
        ToolTip(self.clear_cache_btn, "Deletes the saved Just Dance 2021 game data paths. The next Pre-flight Check or Install will re-scan your system for the game files.")

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
        self.preview_container = tk.Frame(prev_frame, bg="black", width=480, height=270)
        self.preview_container.pack(fill="both", expand=True)
        self.preview_container.pack_propagate(False)
        self.preview_container.bind("<Configure>", self._on_preview_resize)

        # "No Preview" overlay label (centered on the black frame)
        self.preview_label = tk.Label(
            self.preview_container, text="No Preview",
            fg="#555555", bg="black", font=("Consolas", 14))
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

        # Media Controls (Seek bar + Buttons)
        self.media_ctrls = ttk.Frame(prev_frame)
        self.media_ctrls.pack(fill="x", pady=(4, 0))

        # Time label, Seek bar, Duration label
        self.seek_var = tk.DoubleVar(value=0.0)
        self.time_lbl = ttk.Label(self.media_ctrls, text="0:00", font=("Consolas", 9), width=5, anchor="e")
        self.time_lbl.pack(side="left", padx=(0, 4))
        
        self.seek_slider = ttk.Scale(
            self.media_ctrls, from_=0, to=100, orient="horizontal", variable=self.seek_var,
            command=self._on_seek_drag)
        self.seek_slider.pack(side="left", fill="x", expand=True)
        self.seek_slider.bind("<ButtonRelease-1>", self._on_seek_drop)
        ToolTip(self.seek_slider, "Scrub to a specific timestamp")
        
        self.dur_lbl = ttk.Label(self.media_ctrls, text="0:00", font=("Consolas", 9), width=5)
        self.dur_lbl.pack(side="left", padx=(4, 6))

        # Playback buttons
        btn_frame = ttk.Frame(self.media_ctrls)
        btn_frame.pack(side="left")

        self.btn_rewind = ttk.Button(btn_frame, text="-5s", width=4, command=lambda: self._seek_relative(-5))
        self.btn_rewind.pack(side="left", padx=(0, 2))
        ToolTip(self.btn_rewind, "Skip backward 5 seconds")

        self.btn_playpause = ttk.Button(btn_frame, text="⏸", width=3, command=self._toggle_playback)
        self.btn_playpause.pack(side="left", padx=2)
        ToolTip(self.btn_playpause, "Play/Pause preview")

        self.btn_forward = ttk.Button(btn_frame, text="+5s", width=4, command=lambda: self._seek_relative(5))
        self.btn_forward.pack(side="left", padx=(2, 0))
        ToolTip(self.btn_forward, "Skip forward 5 seconds")

        # ===================== LOG OUTPUT =====================
        log_frame = ttk.LabelFrame(container, text="Log Output", padding=4)
        log_frame.pack(fill="x", pady=(0, 4))

        log_inner = ttk.Frame(log_frame)
        log_inner.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_inner, height=6, state="disabled", wrap="word",
            font=("Consolas", 8), bg="#1e1e1e", fg="#cccccc",
            insertbackground="#cccccc")
        log_sb = ttk.Scrollbar(log_inner, orient="vertical",
                               command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

        # ===================== SYNC REFINEMENT =====================
        self.sync_frame = ttk.LabelFrame(
            container, text="Sync Refinement", padding=6)
        self.sync_frame.pack(fill="x", pady=(0, 4))

        tk.Label(self.sync_frame, text="Fine-tune audio/video timing. Hover over buttons for more details.",
                 font=("Consolas", 8, "italic"), fg="#888888").pack(anchor="w", pady=(0, 4))

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
                ToolTip(cb, "Checking this forces the map to use a custom video start time. Use if you know what you are doing.")
            else:
                lbl = ttk.Label(row, text=label, width=18, anchor="e",
                          font=("Consolas", 9, "bold"))
                lbl.pack(side="left")
                ToolTip(lbl, "Positive values pad the audio with silence at the start. Negative values trim the audio from the beginning.")

            # Decrement buttons (largest delta first)
            for d in deltas:
                btn = ttk.Button(
                    row, text=f"-{d}", width=6,
                    command=lambda v=var, dd=d: self._on_increment(v, -dd))
                btn.pack(side="left", padx=1)
                if row_idx == 0:
                    self._vo_row_widgets.append(btn)

            # Value display
            val_entry = ttk.Entry(row, width=14, justify="center",
                                  font=("Consolas", 10))
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
        ToolTip(self.sync_beatgrid_btn, "Copies the Video Override value to the Audio Offset (aligning them 1:1).")

        self.pad_audio_btn = ttk.Button(
            actions, text="Pad Audio", command=self._on_pad_audio)
        self.pad_audio_btn.pack(side="left", padx=(0, 6))
        ToolTip(self.pad_audio_btn, "Calculates the difference in length between the video and audio, then auto-fills the Audio Offset to pad the audio with silence so they end at the same time.")

        self.preview_btn = ttk.Button(
            actions, text="Preview", command=self._on_preview)
        self.preview_btn.pack(side="left", padx=(0, 6))
        ToolTip(self.preview_btn, "Starts the embedded video and audio preview to test the current synchronization offsets.")

        self.stop_preview_btn = ttk.Button(
            actions, text="Stop Preview", command=self._on_stop_preview)
        self.stop_preview_btn.pack(side="left", padx=(0, 6))
        ToolTip(self.stop_preview_btn, "Stops the embedded video and audio preview.")
        self.apply_btn = ttk.Button(
            actions, text="Apply & Finish", command=self._on_apply)
        self.apply_btn.pack(side="left")

        # Start with sync refinement and preview controls disabled
        self._set_sync_state("disabled")
        self._set_preview_state("disabled")

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

    def _browse(self, entry, browse_type, autofill_entry=None):
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
                            
                            # Auto-extract Map Name from the newly detected Asset HTML
                            if getattr(self, "map_name_entry", None):
                                autofill_entry = self.map_name_entry
                                path = asset_path
                except Exception as e:
                    print(f"Error during complementary HTML auto-detect: {e}")
            # ----------------------------------------
            
            if autofill_entry is not None:
                derived = None
                try:
                    urls = map_downloader.extract_urls(path)
                    derived = map_downloader.extract_codename_from_urls(urls)
                except Exception:
                    pass
                if not derived:
                    derived = os.path.basename(os.path.dirname(os.path.abspath(path)))
                autofill_entry.configure(state="normal")
                autofill_entry.delete(0, tk.END)
                if derived:
                    autofill_entry.insert(0, derived)
                    autofill_entry.configure(state="readonly")
                # else: leave editable so user can type manually

    def _redirect_stdout(self):
        self._redirector = StdoutRedirector(self.log_text, self.root)
        sys.stdout = self._redirector
        sys.stderr = self._redirector

    def _restore_stdout(self):
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

    def _set_preview_state(self, state):
        """Enable or disable the media control bar and preview action buttons."""
        for child in self.media_ctrls.winfo_children():
            self._set_widget_state_recursive(child, state)
        for btn in (self.preview_btn, self.stop_preview_btn):
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass

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
        jd_dir = self.jd_dir_entry.get().strip()
        asset = self.asset_html_entry.get().strip()
        nohud = self.nohud_html_entry.get().strip()
        if not jd_dir:
            messagebox.showerror("Missing",
                                 "Game Directory is required for pre-flight check.")
            return

        self.preflight_btn.configure(state="disabled")

        def _run():
            result = map_installer.preflight_check(
                jd_dir, asset or "(not set)", nohud or "(not set)",
                interactive=False)
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
        result = messagebox.askyesno(
            "FFmpeg Not Found",
            "FFmpeg is required but was not found on your system.\n\n"
            "Would you like to download and install it automatically?\n"
            "(This may take a few minutes)")
        if result:
            def _run_install():
                ok = map_installer.preflight_check(
                    jd_dir, asset or "(not set)", nohud or "(not set)",
                    auto_install=True, interactive=False)
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
        self.preflight_btn.configure(state="normal")
        if passed:
            self.install_btn.configure(state="normal")
            messagebox.showinfo("Pre-flight", "All checks passed!")
        else:
            self.install_btn.configure(state="disabled")
            messagebox.showwarning(
                "Pre-flight", "Some checks failed. See log for details.")

    def _on_clear_cache(self):
        cleared = map_installer.clear_paths_cache()
        if cleared:
            messagebox.showinfo(
                "Cache Cleared",
                "Path cache cleared.\n\n"
                "The next Pre-flight Check or Install will re-scan for game data.")
        else:
            messagebox.showinfo("Cache Cleared", "No path cache found (already clear).")

    # ------------------------------------------------------------------
    # Install pipeline
    # ------------------------------------------------------------------

    def _on_install(self):
        map_name = self.map_name_entry.get().strip()
        asset_html = self.asset_html_entry.get().strip()
        nohud_html = self.nohud_html_entry.get().strip()
        jd_dir = self.jd_dir_entry.get().strip()

        if not asset_html or not nohud_html:
            messagebox.showerror(
                "Missing Input",
                "Asset HTML and NOHUD HTML are required.")
            return

        if not map_name:
            if os.path.exists(asset_html):
                urls = map_downloader.extract_urls(asset_html)
                map_name = map_downloader.extract_codename_from_urls(urls)
            if not map_name:
                map_name = os.path.basename(os.path.dirname(os.path.abspath(asset_html)))
            self.map_name_entry.configure(state="normal")
            self.map_name_entry.delete(0, tk.END)
            if map_name:
                self.map_name_entry.insert(0, map_name)
                self.map_name_entry.configure(state="readonly")
            else:
                messagebox.showerror(
                    "Missing Input",
                    "Could not detect map name. Please enter it manually.")
                return

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
                self.map_name_entry.configure(state="normal")
                self.map_name_entry.delete(0, tk.END)
                self.map_name_entry.insert(0, map_name)
                self.map_name_entry.configure(state="readonly")

        # Disable controls during pipeline
        self.install_btn.configure(state="disabled")
        self.preflight_btn.configure(state="disabled")

        # Reset progress
        for i in range(len(self.STEP_NAMES)):
            self._update_step_status(i, "pending")

        self.pipeline_state = map_installer.PipelineState(
            map_name=map_name,
            asset_html=asset_html,
            nohud_html=nohud_html,
            jd_dir=jd_dir or None,
            quality=self.quality_var.get(),
            original_map_name=original_map_name
        )
        # GUI mode: don't call input() in pipeline steps
        self.pipeline_state._interactive = False

        # Close any previous log file and open a new one for this install run
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
        self._log_file = map_installer.setup_log_file(
            self.pipeline_state.map_name)
        self._redirector.log_file = self._log_file
        print(f"Log file: {self._log_file.name}")

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
                print(f"ERROR at step {i+1}: {e}")
                self.root.after(0, lambda err=str(e), idx=i: messagebox.showerror(
                    "Pipeline Error", f"Step {idx+1} failed:\n{err}"))
                self.root.after(0, lambda: self.install_btn.configure(state="normal"))
                self.root.after(0, lambda: self.preflight_btn.configure(state="normal"))
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
        except Exception:
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
            result_event.wait()  # Block pipeline thread until user responds

            state.metadata_overrides[field] = result_holder[0]
            print(f"    {field}: '{original_val}' → '{result_holder[0]}'")

    def _on_pipeline_complete(self):
        state = self.pipeline_state
        # Populate sync values from pipeline
        self.v_override_var.set(
            state.v_override if state.v_override is not None else 0.0)
        self.a_offset_var.set(
            state.a_offset if state.a_offset is not None else 0.0)
        self._refresh_value_displays()

        # Enable sync refinement and preview controls
        self._set_sync_state("normal")
        self._set_preview_state("normal")
        # Keep install disabled until user finishes sync refinement via Apply
        self.preflight_btn.configure(state="normal")

        messagebox.showinfo(
            "Complete",
            f"Installation pipeline finished for {state.map_name}.\n\n"
            "Use the Sync Refinement panel below to fine-tune "
            "audio/video timing, then click 'Apply & Finish'.")

    # ------------------------------------------------------------------
    # Preview management (PIL frame-by-frame + ffplay audio-only)
    # ------------------------------------------------------------------

    def _kill_current_preview(self):
        # Signal frame reader to stop
        if self._frame_stop is not None:
            self._frame_stop.set()

        # Kill ffmpeg (video frames pipe)
        if self.preview_ffmpeg is not None:
            try:
                self.preview_ffmpeg.stdout.close()
            except Exception:
                pass
            if self.preview_ffmpeg.poll() is None:
                try:
                    self.preview_ffmpeg.terminate()
                    self.preview_ffmpeg.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.preview_ffmpeg.kill()
                except Exception:
                    pass

        # Kill ffplay (audio-only)
        if self.preview_ffplay is not None and self.preview_ffplay.poll() is None:
            try:
                self.preview_ffplay.terminate()
                self.preview_ffplay.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.preview_ffplay.kill()
            except Exception:
                pass

        self.preview_ffmpeg = None
        self.preview_ffplay = None
        self._frame_stop = None
        self._frame_thread = None
        
        # Don't reset photo here so we keep the last frame on screen if paused
        if not hasattr(self, '_keep_preview_image') or not self._keep_preview_image:
            self._current_photo = None

            # Restore "No Preview" label
            self.root.after(0, lambda: self.preview_label.configure(
                image="", text="No Preview"))
            self.root.after(0, lambda: self.preview_label.place(
                relx=0.5, rely=0.5, anchor="center"))
            
        self.root.after(0, lambda: self.btn_playpause.configure(text="▶"))

    def _get_media_duration(self, video_path, audio_path):
        """Estimate playable preview duration.

        preview_position=0 corresponds to the start of whichever file has the
        shorter pre-roll (so the user sees the intro).  Duration is the time
        from that reference to whichever stream ends first.
        """
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=nw=1:nk=1", video_path]
            v_dur = float(subprocess.check_output(cmd, text=True).strip())
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=nw=1:nk=1", audio_path]
            a_dur = float(subprocess.check_output(cmd, text=True).strip())

            v_override = self.v_override_var.get()
            a_offset = self.a_offset_var.get()
            abs_v = abs(v_override) if v_override else 0.0
            abs_a = abs(a_offset)   if a_offset   else 0.0
            offset_diff = abs_a - abs_v

            # Each file's playable length from the shared reference point
            if offset_diff >= 0:
                # Video starts from t=0 → full video duration is playable
                v_playable = v_dur
                a_playable = a_dur - offset_diff
            else:
                v_playable = v_dur - abs(offset_diff)
                a_playable = a_dur
            return max(v_playable, a_playable)
        except Exception:
            return 120.0  # fallback

    def _launch_preview(self, start_time=0.0):
        state = self.pipeline_state
        if not state or not state.video_path or not state.audio_path:
            return

        v_override = self.v_override_var.get()
        a_offset = self.a_offset_var.get()

        def _do():
            with self._preview_lock:
                self._keep_preview_image = (start_time > 0.0)
                self._kill_current_preview()
                self._keep_preview_image = False
                
                if start_time == 0.0:
                    self._preview_duration = self._get_media_duration(state.video_path, state.audio_path)
                
                self._preview_position = start_time
                self._preview_playing = True

                self.root.after(0, lambda: self.btn_playpause.configure(text="⏸"))
                self.root.after(0, lambda: self.dur_lbl.configure(text=f"{int(self._preview_duration//60)}:{int(self._preview_duration%60):02d}"))

                # Get container dimensions
                w = self.preview_container.winfo_width()
                h = self.preview_container.winfo_height()
                if w < 10 or h < 10:
                    w, h = 480, 270

                # Sync both streams using direct seeks (no filters).
                # v_override and a_offset are negative: abs() gives each file's
                # pre-roll length.  The file with the SHORTER pre-roll starts
                # from t=0 (so the user sees the video intro / hears the AMB),
                # and the file with the LONGER pre-roll seeks forward by the
                # difference so both land at the same game-time reference.
                abs_v = abs(v_override) if v_override else 0.0
                abs_a = abs(a_offset)   if a_offset   else 0.0
                offset_diff = abs_a - abs_v  # positive when audio has more pre-roll

                if offset_diff >= 0:
                    # Audio has more pre-roll: video starts from t=0 (shows intro)
                    vid_seek = max(0.0, start_time)
                    aud_seek = max(0.0, start_time + offset_diff)
                else:
                    # Video has more pre-roll: audio starts from t=0 (plays AMB)
                    vid_seek = max(0.0, start_time + abs(offset_diff))
                    aud_seek = max(0.0, start_time)

                # Video filter: display scaling only (no sync padding)
                vf_chain = (
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
                )

                # ffmpeg: decode video -> raw RGB24 frames to pipe
                ffmpeg_cmd = ["ffmpeg", "-loglevel", "error"]
                if vid_seek > 0:
                    ffmpeg_cmd += ["-ss", f"{vid_seek:.6f}"]
                ffmpeg_cmd += [
                    "-i", state.video_path,
                    "-vf", vf_chain,
                    "-r", "24",
                    "-pix_fmt", "rgb24",
                    "-f", "rawvideo",
                    "-"
                ]

                # ffplay: audio-only playback (no display)
                ffplay_cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
                if aud_seek > 0:
                    ffplay_cmd += ["-ss", f"{aud_seek:.6f}"]
                ffplay_cmd += ["-i", state.audio_path]

                print(f"    Launching embedded preview "
                      f"(vid_seek={vid_seek:.3f}s, aud_seek={aud_seek:.3f}s)...")

                _cflags = (subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0)

                try:
                    self.preview_ffmpeg = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        creationflags=_cflags)

                    self._frame_stop = threading.Event()
                    self._frame_thread = threading.Thread(
                        target=self._read_video_frames,
                        args=(self.preview_ffmpeg, w, h, self._frame_stop, ffplay_cmd, _cflags),
                        daemon=True)
                    self._frame_thread.start()
                except Exception as e:
                    print(f"    ERROR: Could not launch preview: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def _read_video_frames(self, proc, width, height, stop_event, ffplay_cmd=None, cflags=0):
        """Read raw RGB24 frames from ffmpeg stdout and display them."""
        import time
        frame_size = width * height * 3
        frames_read = 0
        start_wall = 0
        try:
            while not stop_event.is_set():
                data = b""
                while len(data) < frame_size:
                    chunk = proc.stdout.read(frame_size - len(data))
                    if not chunk:
                        return
                    data += chunk
                
                # First frame ready! Launch ffplay.
                if frames_read == 0 and ffplay_cmd:
                    if not stop_event.is_set():
                        with self._preview_lock:
                            if not stop_event.is_set():
                                try:
                                    self.preview_ffplay = subprocess.Popen(
                                        ffplay_cmd,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=cflags)
                                except Exception as e:
                                    print(f"    ERROR: Could not launch ffplay: {e}")
                    
                    # Assume ~100ms for ffplay to actually start making sound
                    start_wall = time.time() + 0.1

                frames_read += 1
                if not stop_event.is_set():
                    self._preview_position += (1.0 / 24.0)
                    img = Image.frombytes("RGB", (width, height), data)
                    self.root.after(0, self._display_frame, img)
                    
                    if start_wall > 0:
                        expected_elapsed = frames_read / 24.0
                        now = time.time()
                        if now < start_wall + expected_elapsed:
                            time.sleep((start_wall + expected_elapsed) - now)

                    # Update seek GUI natively roughly every 6 frames (250ms) to avoid lagging UI thread
                    if frames_read % 6 == 0:
                        pos = self._preview_position
                        pct = (pos / max(self._preview_duration, 1.0)) * 100.0
                        self.root.after(0, self._update_playback_ui, pos, pct)
                        
        except Exception:
            pass

    def _update_playback_ui(self, pos, pct):
        self.time_lbl.configure(text=f"{int(pos//60)}:{int(pos%60):02d}")
        if not self._preview_auto_resume: # Only update slider if we aren't dragging it
            self.seek_var.set(pct)

    def _display_frame(self, pil_image):
        """Display a PIL image on the preview label (main thread only)."""
        try:
            photo = ImageTk.PhotoImage(pil_image)
            self._current_photo = photo  # prevent garbage collection
            self.preview_label.configure(image=photo, text="")
            self.preview_label.place(relx=0.5, rely=0.5, anchor="center")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Playback UI Callbacks
    # ------------------------------------------------------------------
    def _toggle_playback(self):
        if self._preview_playing:
            # Emulate pause by keeping image but killing streams
            with self._preview_lock:
                self._preview_playing = False
                self._keep_preview_image = True
                self._kill_current_preview()
                self._keep_preview_image = False
        else:
            self._launch_preview(self._preview_position)
            
    def _seek_relative(self, delta):
        new_pos = max(0.0, min(self._preview_position + delta, self._preview_duration))
        self._preview_position = new_pos
        if self._preview_playing:
            self._launch_preview(new_pos)
        else:
            self._update_playback_ui(new_pos, (new_pos / max(self._preview_duration, 1.0)) * 100.0)

    def _on_seek_drag(self, val):
        self._preview_auto_resume = self._preview_playing
        pct = float(val)
        pos = (pct / 100.0) * self._preview_duration
        self.time_lbl.configure(text=f"{int(pos//60)}:{int(pos%60):02d}")

    def _on_seek_drop(self, event):
        pct = self.seek_var.get()
        self._preview_position = (pct / 100.0) * self._preview_duration
        if self._preview_auto_resume:
            self._launch_preview(self._preview_position)
        self._preview_auto_resume = False

    def _on_preview_resize(self, event):
        # Only trigger if the preview is actually playing
        if not self._preview_playing:
            return
            
        # Ignore tiny changes or events from child widgets
        if event.widget != self.preview_container:
            return

        # Cancel any pending resize timer
        if self._preview_resizing_timer:
            self.root.after_cancel(self._preview_resizing_timer)

        # Wait 300ms for user to stop dragging before restarting the pipeline
        self._preview_resizing_timer = self.root.after(300, self._apply_resize)

    def _apply_resize(self):
        self._preview_resizing_timer = None
        if self._preview_playing:
            self._launch_preview(self._preview_position)

    # ------------------------------------------------------------------
    # Sync refinement callbacks
    # ------------------------------------------------------------------

    def _debounce_resume_preview(self):
        if self._preview_debounce_timer:
            self.root.after_cancel(self._preview_debounce_timer)
        self._preview_debounce_timer = self.root.after(400, self._apply_debounced_preview)
        
    def _apply_debounced_preview(self):
        self._preview_debounce_timer = None
        # Only relaunch if it was previously playing or if this is the first preview attempt
        if self._preview_playing or self.preview_ffmpeg is not None:
            self._launch_preview(self._preview_position)

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

                self.root.after(0, lambda: self.a_offset_var.set(diff))
                self.root.after(0, self._refresh_value_displays)
                self.root.after(0, self._debounce_resume_preview)
            except Exception as e:
                print(f"    ERROR computing durations: {e}")

        threading.Thread(target=_compute, daemon=True).start()

    def _on_preview(self):
        self._launch_preview()

    def _on_stop_preview(self):
        def _do():
            with self._preview_lock:
                self._kill_current_preview()
        threading.Thread(target=_do, daemon=True).start()

    def _on_apply(self):
        state = self.pipeline_state
        if not state:
            return

        v_override = self.v_override_var.get()
        a_offset = self.a_offset_var.get()

        # Kill any running preview before applying
        self._kill_current_preview()

        def _apply():
            try:
                print(f"    Applying: VIDEO_OVERRIDE={v_override:.5f}, "
                      f"AUDIO_OFFSET={a_offset:.5f}")
                map_builder.generate_text_files(
                    state.map_name, state.ipk_extracted,
                    state.target_dir, v_override,
                    metadata_overrides=getattr(state, 'metadata_overrides', None))
                state.v_override = v_override

                map_installer.convert_audio(
                    state.audio_path, state.map_name,
                    state.target_dir, a_offset)
                map_installer.generate_intro_amb(
                    state.audio_path, state.map_name,
                    state.target_dir, a_offset, v_override,
                    marker_preroll_ms=getattr(state, 'marker_preroll_ms', None))
                map_installer.extract_amb_audio(
                    state.audio_path, state.map_name,
                    state.target_dir, state)
                state.a_offset = a_offset

                # Clear game cache so the engine picks up the new audio files
                if state.cache_dir and os.path.exists(state.cache_dir):
                    map_installer._safe_rmtree(state.cache_dir)
                    print(f"    Cleared game cache for {state.map_name}.")

                print("    Sync changes applied and config saved.")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Applied",
                    f"Sync values applied and files regenerated.\n\n"
                    f"VIDEO_OVERRIDE: {v_override:.5f}\n"
                    f"AUDIO_OFFSET: {a_offset:.5f}\n\n"
                    f"Map '{state.map_name}' is ready to use."))
                self.root.after(0,
                    lambda: self.install_btn.configure(state="normal"))
            except Exception as e:
                print(f"    ERROR applying changes: {e}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", f"Failed to apply:\n{e}"))

        threading.Thread(target=_apply, daemon=True).start()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _on_close(self):
        self._kill_current_preview()
        self._restore_stdout()
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    MapInstallerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
