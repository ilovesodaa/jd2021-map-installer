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
        self.root.geometry("1060x830")
        self.root.minsize(900, 750)

        # State
        self.pipeline_state = None
        self.pipeline_thread = None
        self.preview_ffmpeg = None
        self.preview_ffplay = None
        self._preview_lock = threading.Lock()
        self._frame_stop = None
        self._frame_thread = None
        self._current_photo = None
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._preflight_passed = False
        self._log_file = None

        # Tkinter variables for sync refinement
        self.v_override_var = tk.DoubleVar(value=0.0)
        self.a_offset_var = tk.DoubleVar(value=0.0)

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
            fg="#ffcc00", # Warning yellow/orange
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
        self.install_btn = ttk.Button(
            btn_row, text="Install Map", command=self._on_install, state="disabled")
        self.install_btn.pack(side="left")
        ttk.Button(
            btn_row, text="Clear Path Cache", command=self._on_clear_cache).pack(
            side="left", padx=(12, 0))

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

        # "No Preview" overlay label (centered on the black frame)
        self.preview_label = tk.Label(
            self.preview_container, text="No Preview",
            fg="#555555", bg="black", font=("Consolas", 14))
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")

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

        deltas = [1, 0.1, 0.01, 0.001]

        for row_idx, (label, var) in enumerate([
            ("VIDEO_OVERRIDE", self.v_override_var),
            ("AUDIO_OFFSET", self.a_offset_var),
        ]):
            row = ttk.Frame(self.sync_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=18, anchor="e",
                      font=("Consolas", 9, "bold")).pack(side="left")

            # Decrement buttons (largest delta first)
            for d in deltas:
                btn = ttk.Button(
                    row, text=f"-{d}", width=6,
                    command=lambda v=var, dd=d: self._on_increment(v, -dd))
                btn.pack(side="left", padx=1)

            # Value display
            val_entry = ttk.Entry(row, width=14, justify="center",
                                  font=("Consolas", 10))
            val_entry.pack(side="left", padx=6)
            val_entry.insert(0, f"{var.get():.5f}")
            val_entry.configure(state="readonly")
            if row_idx == 0:
                self._vo_display = val_entry
            else:
                self._ao_display = val_entry

            # Increment buttons (smallest delta first)
            for d in reversed(deltas):
                btn = ttk.Button(
                    row, text=f"+{d}", width=6,
                    command=lambda v=var, dd=d: self._on_increment(v, dd))
                btn.pack(side="left", padx=1)

        # Action buttons
        actions = ttk.Frame(self.sync_frame)
        actions.pack(fill="x", pady=(8, 0))
        self.sync_beatgrid_btn = ttk.Button(
            actions, text="Sync Beatgrid", command=self._on_sync_beatgrid)
        self.sync_beatgrid_btn.pack(side="left", padx=(0, 6))
        self.pad_audio_btn = ttk.Button(
            actions, text="Pad Audio", command=self._on_pad_audio)
        self.pad_audio_btn.pack(side="left", padx=(0, 6))
        self.preview_btn = ttk.Button(
            actions, text="Preview", command=self._on_preview)
        self.preview_btn.pack(side="left", padx=(0, 6))
        self.stop_preview_btn = ttk.Button(
            actions, text="Stop Preview", command=self._on_stop_preview)
        self.stop_preview_btn.pack(side="left", padx=(0, 6))
        self.apply_btn = ttk.Button(
            actions, text="Apply & Finish", command=self._on_apply)
        self.apply_btn.pack(side="left")

        # Start with sync refinement disabled
        self._set_sync_state("disabled")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _browse(self, entry, browse_type, autofill_entry=None):
        if browse_type == "html":
            path = filedialog.askopenfilename(
                filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        else:
            path = filedialog.askdirectory()
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)
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

    def _set_sync_state(self, state):
        """Enable or disable all widgets inside the sync refinement frame."""
        for child in self.sync_frame.winfo_children():
            self._set_widget_state_recursive(child, state)

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
            display.configure(state="normal")
            display.delete(0, tk.END)
            display.insert(0, f"{var.get():.5f}")
            display.configure(state="readonly")

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
                f"These can cause file path and game engine issues.\n\n"
                f"Enter a safe replacement name:",
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

        # Load saved config if available (applies saved sync values)
        saved = map_installer.load_map_config(
            self.pipeline_state.map_name)
        if saved:
            if self.pipeline_state.v_override is None:
                self.pipeline_state.v_override = saved.get('v_override')
            if self.pipeline_state.a_offset is None:
                self.pipeline_state.a_offset = saved.get('a_offset')

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
                       f"  Problem chars: {na}\n\n"
                       f"These can cause game engine errors. Enter a safe replacement (ASCII only):")
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

                def _on_cancel():
                    result_holder[0] = safe # Auto-strip on cancel
                    dlg.destroy()

                ttk.Button(btn_frame, text="Apply Replacement", command=_on_ok).pack(side="right", padx=(4, 0))
                ttk.Button(btn_frame, text="Auto-Strip (Cancel)", command=_on_cancel).pack(side="right")

                dlg.protocol("WM_DELETE_WINDOW", _on_cancel)
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

        # Enable sync refinement
        self._set_sync_state("normal")
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
        self._current_photo = None

        # Restore "No Preview" label
        self.root.after(0, lambda: self.preview_label.configure(
            image="", text="No Preview"))
        self.root.after(0, lambda: self.preview_label.place(
            relx=0.5, rely=0.5, anchor="center"))

    def _launch_preview(self):
        state = self.pipeline_state
        if not state or not state.video_path or not state.audio_path:
            return

        v_override = self.v_override_var.get()
        a_offset = self.a_offset_var.get()

        def _do():
            with self._preview_lock:
                self._kill_current_preview()

                # Get container dimensions
                w = self.preview_container.winfo_width()
                h = self.preview_container.winfo_height()
                if w < 10 or h < 10:
                    w, h = 480, 270

                net_offset = v_override - a_offset
                delay_ms = int(abs(net_offset) * 1000)

                # Build video filter chain
                vf_parts = []
                if net_offset > 0:
                    vf_parts.append(
                        f"tpad=start_duration={net_offset}:color=black")
                vf_parts.append(
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease")
                vf_parts.append(
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black")
                vf_chain = ",".join(vf_parts)

                # Build audio filter (delay audio if video starts first)
                af = None
                if net_offset < 0:
                    af = f"adelay=delays={delay_ms}:all=1"

                # ffmpeg: decode video -> raw RGB24 frames to pipe
                ffmpeg_cmd = [
                    "ffmpeg", "-re", "-loglevel", "error",
                    "-i", state.video_path,
                    "-vf", vf_chain,
                    "-r", "24",
                    "-pix_fmt", "rgb24",
                    "-f", "rawvideo",
                    "-"
                ]

                # ffplay: audio-only playback (no display)
                ffplay_cmd = [
                    "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
                if af:
                    ffplay_cmd += ["-af", af]
                ffplay_cmd += ["-i", state.audio_path]

                print(f"    Launching embedded preview "
                      f"(net delay: {net_offset:.3f}s)...")

                _cflags = (subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0)

                try:
                    self.preview_ffmpeg = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        creationflags=_cflags)
                    self.preview_ffplay = subprocess.Popen(
                        ffplay_cmd,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=_cflags)

                    self._frame_stop = threading.Event()
                    self._frame_thread = threading.Thread(
                        target=self._read_video_frames,
                        args=(self.preview_ffmpeg, w, h, self._frame_stop),
                        daemon=True)
                    self._frame_thread.start()
                except Exception as e:
                    print(f"    ERROR: Could not launch preview: {e}")

        threading.Thread(target=_do, daemon=True).start()

    def _read_video_frames(self, proc, width, height, stop_event):
        """Read raw RGB24 frames from ffmpeg stdout and display them."""
        frame_size = width * height * 3
        try:
            while not stop_event.is_set():
                data = b""
                while len(data) < frame_size:
                    chunk = proc.stdout.read(frame_size - len(data))
                    if not chunk:
                        return
                    data += chunk
                if not stop_event.is_set():
                    img = Image.frombytes("RGB", (width, height), data)
                    self.root.after(0, self._display_frame, img)
        except Exception:
            pass

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
    # Sync refinement callbacks
    # ------------------------------------------------------------------

    def _on_increment(self, var, delta):
        new_val = round(var.get() + delta, 5)
        var.set(new_val)
        self._refresh_value_displays()
        self._launch_preview()

    def _on_sync_beatgrid(self):
        self.a_offset_var.set(self.v_override_var.get())
        self._refresh_value_displays()
        self._launch_preview()

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
                self.root.after(0, self._launch_preview)
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
                    state.target_dir, v_override)
                state.v_override = v_override

                map_installer.convert_audio(
                    state.audio_path, state.map_name,
                    state.target_dir, a_offset)
                map_installer.generate_intro_amb(
                    state.audio_path, state.map_name,
                    state.target_dir, a_offset, v_override)
                state.a_offset = a_offset

                # Save sync config for future re-installs
                map_installer.save_map_config(
                    state.map_name,
                    v_override, a_offset,
                    quality=getattr(state, 'quality', 'ULTRA'),
                    codename=state.codename)

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
