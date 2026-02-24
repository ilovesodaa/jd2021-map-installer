"""
JD2021 Map Installer - GUI
Launch with: python gui_installer.py
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import subprocess
import sys
import os

# Ensure we can import sibling scripts regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import map_installer
import map_builder


class StdoutRedirector:
    """Bridges print() calls from worker threads to a tkinter Text widget via a queue."""

    def __init__(self, text_widget, root):
        self.text_widget = text_widget
        self.root = root
        self._queue = queue.Queue()
        self._poll()

    def write(self, text):
        self._queue.put(text)

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
        self.root.geometry("920x800")
        self.root.minsize(780, 700)

        # State
        self.pipeline_state = None
        self.pipeline_thread = None
        self.preview_ffmpeg = None
        self.preview_ffplay = None
        self._preview_lock = threading.Lock()
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

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
        # Use a canvas with scrollbar for the entire content so it works on small screens
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=8, pady=4)

        # ---------- CONFIGURATION ----------
        cfg = ttk.LabelFrame(container, text="Configuration", padding=6)
        cfg.pack(fill="x", pady=(0, 4))

        for i, (label_text, attr_name, browse_type) in enumerate([
            ("Map Name:", "map_name_entry", None),
            ("Asset HTML:", "asset_html_entry", "html"),
            ("NOHUD HTML:", "nohud_html_entry", "html"),
            ("JD Directory:", "jd_dir_entry", "dir"),
        ]):
            ttk.Label(cfg, text=label_text, width=14, anchor="e").grid(row=i, column=0, sticky="e", padx=(0, 4))
            entry = ttk.Entry(cfg, width=64)
            entry.grid(row=i, column=1, sticky="ew", pady=1)
            setattr(self, attr_name, entry)
            if browse_type:
                cmd = (lambda e=entry, bt=browse_type: self._browse(e, bt))
                ttk.Button(cfg, text="Browse", width=8, command=cmd).grid(row=i, column=2, padx=(4, 0))

        cfg.columnconfigure(1, weight=1)

        btn_row = ttk.Frame(cfg)
        btn_row.grid(row=4, column=0, columnspan=3, pady=(6, 0))
        self.preflight_btn = ttk.Button(btn_row, text="Pre-flight Check", command=self._on_preflight)
        self.preflight_btn.pack(side="left", padx=(0, 12))
        self.install_btn = ttk.Button(btn_row, text="Install Map", command=self._on_install)
        self.install_btn.pack(side="left")

        # ---------- PROGRESS ----------
        prog = ttk.LabelFrame(container, text="Installation Progress", padding=6)
        prog.pack(fill="x", pady=(0, 4))

        self.step_labels = []
        for i, name in enumerate(self.STEP_NAMES):
            lbl = ttk.Label(prog, text=f"[  ] Step {i+1}:  {name}", font=("Consolas", 9))
            lbl.pack(anchor="w")
            self.step_labels.append(lbl)

        # ---------- LOG ----------
        log_frame = ttk.LabelFrame(container, text="Log Output", padding=4)
        log_frame.pack(fill="both", expand=True, pady=(0, 4))

        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word",
                                font=("Consolas", 8), bg="#1e1e1e", fg="#cccccc",
                                insertbackground="#cccccc")
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")

        # ---------- SYNC REFINEMENT ----------
        self.sync_frame = ttk.LabelFrame(container, text="Sync Refinement", padding=6)
        self.sync_frame.pack(fill="x", pady=(0, 4))

        deltas = [1, 0.1, 0.01, 0.001]

        for row_idx, (label, var) in enumerate([
            ("VIDEO_OVERRIDE", self.v_override_var),
            ("AUDIO_OFFSET", self.a_offset_var),
        ]):
            row = ttk.Frame(self.sync_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=18, anchor="e", font=("Consolas", 9, "bold")).pack(side="left")

            # Decrement buttons
            for d in deltas:
                btn = ttk.Button(row, text=f"-{d}", width=6,
                                 command=lambda v=var, dd=d: self._on_increment(v, -dd))
                btn.pack(side="left", padx=1)

            # Value display
            val_entry = ttk.Entry(row, width=14, justify="center", font=("Consolas", 10))
            val_entry.pack(side="left", padx=6)
            val_entry.insert(0, f"{var.get():.5f}")
            val_entry.configure(state="readonly")
            if row_idx == 0:
                self._vo_display = val_entry
            else:
                self._ao_display = val_entry

            # Increment buttons
            for d in reversed(deltas):
                btn = ttk.Button(row, text=f"+{d}", width=6,
                                 command=lambda v=var, dd=d: self._on_increment(v, dd))
                btn.pack(side="left", padx=1)

        # Action buttons
        actions = ttk.Frame(self.sync_frame)
        actions.pack(fill="x", pady=(8, 0))
        self.sync_beatgrid_btn = ttk.Button(actions, text="Sync Beatgrid", command=self._on_sync_beatgrid)
        self.sync_beatgrid_btn.pack(side="left", padx=(0, 6))
        self.pad_audio_btn = ttk.Button(actions, text="Pad Audio", command=self._on_pad_audio)
        self.pad_audio_btn.pack(side="left", padx=(0, 6))
        self.preview_btn = ttk.Button(actions, text="Preview", command=self._on_preview)
        self.preview_btn.pack(side="left", padx=(0, 6))
        self.apply_btn = ttk.Button(actions, text="Apply & Finish", command=self._on_apply)
        self.apply_btn.pack(side="left")

        # Start with sync refinement disabled
        self._set_sync_state("disabled")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _browse(self, entry, browse_type):
        if browse_type == "html":
            path = filedialog.askopenfilename(filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        else:
            path = filedialog.askdirectory()
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

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
            messagebox.showerror("Missing", "JD Directory is required for pre-flight check.")
            return

        def _run():
            ok = map_installer.preflight_check(jd_dir, asset or "(not set)", nohud or "(not set)")
            self.root.after(0, lambda: messagebox.showinfo(
                "Pre-flight", "All checks passed!" if ok else "Some checks failed. See log."))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Install pipeline
    # ------------------------------------------------------------------

    def _on_install(self):
        map_name = self.map_name_entry.get().strip()
        asset_html = self.asset_html_entry.get().strip()
        nohud_html = self.nohud_html_entry.get().strip()
        jd_dir = self.jd_dir_entry.get().strip()

        if not all([map_name, asset_html, nohud_html]):
            messagebox.showerror("Missing Input", "Map Name, Asset HTML, and NOHUD HTML are all required.")
            return

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
        )

        self.pipeline_thread = threading.Thread(target=self._run_pipeline, daemon=True)
        self.pipeline_thread.start()

    def _run_pipeline(self):
        state = self.pipeline_state

        print(f"--- Environment ---")
        print(f"JD Base Dir: {state.jd_dir}")
        print(f"Map Name:    {state.map_name}")
        print(f"Asset HTML:  {state.asset_html}")
        print(f"-------------------")

        if not map_installer.preflight_check(state.jd_dir, state.asset_html, state.nohud_html):
            self.root.after(0, lambda: messagebox.showerror("Pre-flight Failed",
                                                            "Critical dependency checks failed. See log."))
            self.root.after(0, lambda: self.install_btn.configure(state="normal"))
            self.root.after(0, lambda: self.preflight_btn.configure(state="normal"))
            return

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
                self.root.after(0, lambda err=str(e): messagebox.showerror(
                    "Pipeline Error", f"Step {i+1} failed:\n{err}"))
                self.root.after(0, lambda: self.install_btn.configure(state="normal"))
                self.root.after(0, lambda: self.preflight_btn.configure(state="normal"))
                return

        print("=== Automation Complete! ===")
        self.root.after(0, self._on_pipeline_complete)

    def _on_pipeline_complete(self):
        state = self.pipeline_state
        # Populate sync values from pipeline
        self.v_override_var.set(state.v_override if state.v_override is not None else 0.0)
        self.a_offset_var.set(state.a_offset if state.a_offset is not None else 0.0)
        self._refresh_value_displays()

        # Enable sync refinement
        self._set_sync_state("normal")
        # Keep install disabled until user finishes sync refinement via Apply
        self.preflight_btn.configure(state="normal")

        messagebox.showinfo("Complete",
                            f"Installation pipeline finished for {state.map_name}.\n\n"
                            "Use the Sync Refinement panel below to fine-tune audio/video timing, "
                            "then click 'Apply & Finish'.")

    # ------------------------------------------------------------------
    # Preview management
    # ------------------------------------------------------------------

    def _kill_current_preview(self):
        map_installer.kill_preview(self.preview_ffmpeg, self.preview_ffplay)
        self.preview_ffmpeg = None
        self.preview_ffplay = None

    def _launch_preview(self):
        state = self.pipeline_state
        if not state or not state.video_path or not state.audio_path:
            return

        v_override = self.v_override_var.get()
        a_offset = self.a_offset_var.get()

        def _do():
            with self._preview_lock:
                self._kill_current_preview()
                self.preview_ffmpeg, self.preview_ffplay = map_installer.launch_preview_async(
                    state.video_path, state.audio_path, v_override, a_offset)

        threading.Thread(target=_do, daemon=True).start()

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
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", p],
                        capture_output=True, text=True)
                    return float(res.stdout.strip())

                v_dur = get_dur(state.video_path)
                a_dur = get_dur(state.audio_path)
                diff = round(v_dur - a_dur, 5)
                print(f"    Video: {v_dur:.2f}s, Audio: {a_dur:.2f}s, Padding: {diff:.3f}s")

                self.root.after(0, lambda: self.a_offset_var.set(diff))
                self.root.after(0, self._refresh_value_displays)
                self.root.after(0, self._launch_preview)
            except Exception as e:
                print(f"    ERROR computing durations: {e}")

        threading.Thread(target=_compute, daemon=True).start()

    def _on_preview(self):
        self._launch_preview()

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
                # Regenerate config if v_override changed
                print(f"    Applying: VIDEO_OVERRIDE={v_override:.5f}, AUDIO_OFFSET={a_offset:.5f}")
                map_builder.generate_text_files(
                    state.map_name, state.ipk_extracted, state.target_dir, v_override)
                state.v_override = v_override

                # Re-convert audio with new offset
                map_installer.convert_audio(state.audio_path, state.map_name, state.target_dir, a_offset)
                map_installer.generate_intro_amb(state.audio_path, state.map_name, state.target_dir, a_offset)
                state.a_offset = a_offset

                print("    Sync changes applied successfully.")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Applied", f"Sync values applied and files regenerated.\n\n"
                               f"VIDEO_OVERRIDE: {v_override:.5f}\n"
                               f"AUDIO_OFFSET: {a_offset:.5f}\n\n"
                               f"Map '{state.map_name}' is ready to use."))
                self.root.after(0, lambda: self.install_btn.configure(state="normal"))
            except Exception as e:
                print(f"    ERROR applying changes: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to apply:\n{e}"))

        threading.Thread(target=_apply, daemon=True).start()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _on_close(self):
        self._kill_current_preview()
        self._restore_stdout()
        self.root.destroy()


def main():
    root = tk.Tk()
    MapInstallerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
