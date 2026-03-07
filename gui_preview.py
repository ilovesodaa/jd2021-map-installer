"""
JD2021 Map Installer - Preview Manager

Handles embedded video/audio preview playback using ffmpeg (video frames via
pipe) and ffplay (audio-only).
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import sys
import time
from log_config import get_logger

from PIL import Image, ImageTk
from helpers import PREVIEW_FPS, PREVIEW_POLL_FRAMES

from log_config import get_logger
logger = get_logger("gui.preview")


class PreviewManager:
    """Self-contained preview subsystem for the map installer GUI.

    Owns all ffmpeg/ffplay subprocess management, frame decoding, seek/playback
    UI, and debounce logic.  The parent GUI communicates via the public methods
    (launch, stop, kill, reset, debounce_resume) and reads state via properties.
    """

    def __init__(self, root, container, label):
        """
        Args:
            root:      The tkinter root window (for ``after`` scheduling).
            container: The ``tk.Frame`` that holds the video (black background).
            label:     The ``tk.Label`` placed inside *container* for frames /
                       "No Preview" text.
        """
        self.root = root
        self.container = container
        self.label = label

        # Subprocess handles
        self._ffmpeg = None
        self._ffplay = None

        # Threading
        self._lock = threading.Lock()
        self._frame_stop = None
        self._frame_thread = None

        # Playback state
        self._current_photo = None
        self._position = 0.0
        self._playing = False
        self._duration = 0.0
        self._starting = False
        self._keep_image = False
        self._ffplay_warned = False
        self._auto_resume = False

        # Stashed launch arguments so toggle/seek/resize can relaunch
        self._last_video_path = None
        self._last_audio_path = None
        self._last_v_override = 0.0
        self._last_a_offset = 0.0

        # Debounce / resize timers
        self._resize_timer = None
        self._debounce_timer = None

        # UI widgets (populated by build_controls)
        self._seek_var = None
        self._time_lbl = None
        self._dur_lbl = None
        self._btn_playpause = None
        self._media_ctrls = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = value

    @property
    def playing(self):
        return self._playing

    @property
    def duration(self):
        return self._duration

    # ------------------------------------------------------------------
    # UI construction (called once by the parent GUI)
    # ------------------------------------------------------------------

    def build_controls(self, parent):
        """Create the media-control widgets inside *parent* and return the
        frame.

        The parent GUI should call this once during ``_build_ui`` and keep the
        returned frame reference for layout purposes.
        """
        from gui_installer import ToolTip

        self._media_ctrls = ttk.Frame(parent)
        self._media_ctrls.pack(fill="x", pady=(4, 0))

        self._seek_var = tk.DoubleVar(value=0.0)
        self._time_lbl = ttk.Label(
            self._media_ctrls, text="0:00", font=("Consolas", 9),
            width=5, anchor="e")
        self._time_lbl.pack(side="left", padx=(0, 4))

        self._seek_slider = ttk.Scale(
            self._media_ctrls, from_=0, to=100, orient="horizontal",
            variable=self._seek_var, command=self._on_seek_drag)
        self._seek_slider.pack(side="left", fill="x", expand=True)
        self._seek_slider.bind("<ButtonRelease-1>", self._on_seek_drop)
        ToolTip(self._seek_slider, "Scrub to a specific timestamp")

        self._dur_lbl = ttk.Label(
            self._media_ctrls, text="0:00", font=("Consolas", 9), width=5)
        self._dur_lbl.pack(side="left", padx=(4, 6))

        btn_frame = ttk.Frame(self._media_ctrls)
        btn_frame.pack(side="left")

        btn_rewind = ttk.Button(
            btn_frame, text="-5s", width=4,
            command=lambda: self._seek_relative(-5))
        btn_rewind.pack(side="left", padx=(0, 2))
        ToolTip(btn_rewind, "Skip backward 5 seconds")

        self._btn_playpause = ttk.Button(
            btn_frame, text="\u25b6", width=3,
            command=self._toggle_playback)
        self._btn_playpause.pack(side="left", padx=2)
        ToolTip(self._btn_playpause, "Play/Pause preview")

        btn_forward = ttk.Button(
            btn_frame, text="+5s", width=4,
            command=lambda: self._seek_relative(5))
        btn_forward.pack(side="left", padx=(2, 0))
        ToolTip(btn_forward, "Skip forward 5 seconds")

        self.container.bind("<Configure>", self._on_resize)

        return self._media_ctrls

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def launch(self, video_path, audio_path, v_override, a_offset,
               start_time=0.0):
        """Start (or restart) the preview from *start_time*."""
        if not video_path or not audio_path:
            return
        if self._starting:
            return
        self._starting = True

        # Stash for toggle / seek / resize callbacks
        self._last_video_path = video_path
        self._last_audio_path = audio_path
        self._last_v_override = v_override
        self._last_a_offset = a_offset

        def _do():
            with self._lock:
                self._keep_image = (start_time > 0.0)
                self._kill()
                self._keep_image = False

                if start_time == 0.0:
                    self._duration = self._probe_duration(
                        video_path, audio_path, v_override, a_offset)

                self._position = start_time
                self._playing = True

                self.root.after(
                    0, lambda: self._btn_playpause.configure(text="\u23f8"))
                self.root.after(
                    0, lambda: self._dur_lbl.configure(
                        text=self._fmt(self._duration)))

                # Container dimensions
                w = self.container.winfo_width()
                h = self.container.winfo_height()
                if w < 10 or h < 10:
                    w, h = 480, 270

                # Compute seek positions (sign-aware)
                # v_override: typically negative; |v_override| = video intro before beat-0
                # a_offset: negative = audio pre-roll to trim; positive = silence to pad
                vid_seek = abs(v_override) if v_override else 0.0

                aud_delay_ms = 0
                if a_offset and a_offset < 0:
                    aud_seek = abs(a_offset)
                elif a_offset and a_offset > 0:
                    aud_seek = 0.0
                    aud_delay_ms = int(a_offset * 1000)
                else:
                    aud_seek = 0.0

                # Offset both by start_time for scrubbing
                vid_seek += start_time
                aud_seek += start_time

                vf_chain = (
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
                )

                ffmpeg_cmd = ["ffmpeg", "-loglevel", "error"]
                if vid_seek > 0:
                    ffmpeg_cmd += ["-ss", f"{vid_seek:.6f}"]
                ffmpeg_cmd += [
                    "-i", video_path,
                    "-vf", vf_chain,
                    "-r", str(PREVIEW_FPS),
                    "-pix_fmt", "rgb24",
                    "-f", "rawvideo",
                    "-"
                ]

                if aud_delay_ms > 0:
                    # Positive offset: pad silence via adelay filter
                    ffplay_cmd = [
                        "ffplay", "-nodisp", "-autoexit",
                        "-loglevel", "quiet"]
                    if aud_seek > 0:
                        ffplay_cmd += ["-ss", f"{aud_seek:.6f}"]
                    ffplay_cmd += [
                        "-i", audio_path,
                        "-af",
                        f"adelay={aud_delay_ms}|{aud_delay_ms},"
                        f"asetpts=PTS-STARTPTS"]
                else:
                    # Zero or negative offset: simple seek
                    ffplay_cmd = [
                        "ffplay", "-nodisp", "-autoexit",
                        "-loglevel", "quiet"]
                    if aud_seek > 0:
                        ffplay_cmd += ["-ss", f"{aud_seek:.6f}"]
                    ffplay_cmd += ["-i", audio_path]

                logger.debug("Launching embedded preview "
                      "(vid_seek=%.3fs, "
                      "aud_seek=%.3fs, "
                      "aud_delay_ms=%s)...",
                      vid_seek, aud_seek, aud_delay_ms)

                _cflags = (subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0)

                try:
                    self._ffmpeg = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        creationflags=_cflags)

                    self._frame_stop = threading.Event()
                    self._frame_thread = threading.Thread(
                        target=self._read_frames,
                        args=(self._ffmpeg, w, h, self._frame_stop,
                              ffplay_cmd, _cflags),
                        daemon=True)
                    self._frame_thread.start()
                except Exception as e:
                    print(f"    ERROR: Could not launch preview: {e}")
                finally:
                    self._starting = False

        threading.Thread(target=_do, daemon=True).start()

    def stop(self):
        """Stop the preview (threaded to avoid blocking the main thread)."""
        def _do():
            with self._lock:
                self._kill()
        threading.Thread(target=_do, daemon=True).start()

    def kill(self):
        """Immediately kill preview subprocesses (call from main thread)."""
        self._kill()

    def reset(self):
        """Kill preview and reset all playback state to initial values."""
        self._kill()
        self._position = 0.0
        self._duration = 0.0
        self._playing = False
        if self._seek_var:
            self._seek_var.set(0.0)
        if self._time_lbl:
            self._time_lbl.configure(text="0:00")
        if self._dur_lbl:
            self._dur_lbl.configure(text="0:00")

    def set_enabled(self, state):
        """Enable or disable the media control bar widgets."""
        if self._media_ctrls is None:
            return
        self._set_widget_state_recursive(self._media_ctrls, state)

    def debounce_resume(self, video_path, audio_path, v_override, a_offset):
        """Schedule a preview relaunch after a short debounce delay."""
        # Stash for callbacks
        self._last_video_path = video_path
        self._last_audio_path = audio_path
        self._last_v_override = v_override
        self._last_a_offset = a_offset

        if self._debounce_timer:
            self.root.after_cancel(self._debounce_timer)
        self._debounce_timer = self.root.after(
            400,
            lambda: self._apply_debounced(
                video_path, audio_path, v_override, a_offset))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt(seconds):
        """Format seconds as M:SS."""
        return f"{int(seconds // 60)}:{int(seconds % 60):02d}"

    def _relaunch_current(self, start_time=None):
        """Relaunch with the most recently used paths/offsets."""
        if self._last_video_path and self._last_audio_path:
            st = start_time if start_time is not None else self._position
            self.launch(self._last_video_path, self._last_audio_path,
                        self._last_v_override, self._last_a_offset,
                        start_time=st)

    def _kill(self):
        """Terminate ffmpeg/ffplay subprocesses and reset handles."""
        if self._frame_stop is not None:
            self._frame_stop.set()

        if self._ffmpeg is not None:
            try:
                self._ffmpeg.stdout.close()
            except OSError:
                pass
            if self._ffmpeg.poll() is None:
                try:
                    self._ffmpeg.terminate()
                    self._ffmpeg.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._ffmpeg.kill()
                except OSError:
                    pass

        if self._ffplay is not None and self._ffplay.poll() is None:
            try:
                self._ffplay.terminate()
                self._ffplay.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._ffplay.kill()
            except OSError:
                pass

        self._ffmpeg = None
        self._ffplay = None
        self._frame_stop = None
        self._frame_thread = None

        if not self._keep_image:
            self._current_photo = None
            self.root.after(0, lambda: self.label.configure(
                image="", text="No Preview"))
            self.root.after(0, lambda: self.label.place(
                relx=0.5, rely=0.5, anchor="center"))

        if self._btn_playpause:
            self.root.after(
                0, lambda: self._btn_playpause.configure(text="\u25b6"))

    def _probe_duration(self, video_path, audio_path, v_override, a_offset):
        """Estimate playable preview duration using ffprobe."""
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries",
                   "format=duration", "-of", "default=nw=1:nk=1", video_path]
            v_dur = float(subprocess.check_output(cmd, text=True).strip())
            cmd = ["ffprobe", "-v", "error", "-show_entries",
                   "format=duration", "-of", "default=nw=1:nk=1", audio_path]
            a_dur = float(subprocess.check_output(cmd, text=True).strip())

            # Sign-aware playable duration
            vid_beat0 = abs(v_override) if v_override else 0.0
            v_playable = v_dur - vid_beat0

            if a_offset and a_offset < 0:
                a_playable = a_dur - abs(a_offset)
            elif a_offset and a_offset > 0:
                a_playable = a_dur + a_offset
            else:
                a_playable = a_dur

            return max(v_playable, a_playable)
        except Exception as e:
            logger.warning(
                "media duration probe failed, using 120s fallback: %s", e)
            return 120.0

    def _read_frames(self, proc, width, height, stop_event,
                     ffplay_cmd=None, cflags=0):
        """Read raw RGB24 frames from ffmpeg stdout and display them."""
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

                # First frame ready -- launch ffplay
                if frames_read == 0 and ffplay_cmd:
                    if not stop_event.is_set():
                        with self._lock:
                            if not stop_event.is_set():
                                try:
                                    self._ffplay = subprocess.Popen(
                                        ffplay_cmd,
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                        creationflags=cflags)
                                except FileNotFoundError:
                                    if not self._ffplay_warned:
                                        self._ffplay_warned = True
                                        self.root.after(
                                            0,
                                            lambda: messagebox.showinfo(
                                                "ffplay Not Found",
                                                "ffplay was not found. Video "
                                                "will play without audio.\n\n"
                                                "Install FFmpeg to enable "
                                                "audio preview."))
                                except Exception as e:
                                    print(f"    ERROR: Could not launch "
                                          f"ffplay: {e}")
                    start_wall = time.time() + 0.1

                frames_read += 1
                if not stop_event.is_set():
                    self._position += (1.0 / PREVIEW_FPS)
                    img = Image.frombytes("RGB", (width, height), data)
                    self.root.after(0, self._display_frame, img)

                    if start_wall > 0:
                        expected = frames_read / float(PREVIEW_FPS)
                        now = time.time()
                        if now < start_wall + expected:
                            time.sleep((start_wall + expected) - now)

                    if frames_read % PREVIEW_POLL_FRAMES == 0:
                        pos = self._position
                        pct = (pos / max(self._duration, 1.0)) * 100.0
                        self.root.after(
                            0, self._update_playback_ui, pos, pct)
        except Exception as e:
            logger.debug("frame reader ended: %s", e)

    def _display_frame(self, pil_image):
        """Display a PIL image on the preview label (main thread only)."""
        try:
            photo = ImageTk.PhotoImage(pil_image)
            self._current_photo = photo
            self.label.configure(image=photo, text="")
            self.label.place(relx=0.5, rely=0.5, anchor="center")
        except Exception as e:
            logger.debug("display_frame error: %s", e)

    def _update_playback_ui(self, pos, pct):
        if self._time_lbl:
            self._time_lbl.configure(text=self._fmt(pos))
        if not self._auto_resume and self._seek_var:
            self._seek_var.set(pct)

    # ------------------------------------------------------------------
    # Playback UI callbacks
    # ------------------------------------------------------------------

    def _toggle_playback(self):
        if self._playing:
            with self._lock:
                self._playing = False
                self._keep_image = True
                self._kill()
                self._keep_image = False
        else:
            self._relaunch_current()

    def _seek_relative(self, delta):
        new_pos = max(0.0, min(self._position + delta, self._duration))
        self._position = new_pos
        if self._playing:
            self._relaunch_current(start_time=new_pos)
        else:
            pct = (new_pos / max(self._duration, 1.0)) * 100.0
            self._update_playback_ui(new_pos, pct)

    def _on_seek_drag(self, val):
        self._auto_resume = self._playing
        pct = float(val)
        pos = (pct / 100.0) * self._duration
        if self._time_lbl:
            self._time_lbl.configure(text=self._fmt(pos))

    def _on_seek_drop(self, event):
        if self._seek_var is None:
            return
        pct = self._seek_var.get()
        self._position = (pct / 100.0) * self._duration
        if self._auto_resume:
            self.debounce_resume(
                self._last_video_path, self._last_audio_path,
                self._last_v_override, self._last_a_offset)
        self._auto_resume = False

    def _on_resize(self, event):
        if not self._playing:
            return
        if event.widget != self.container:
            return
        if self._resize_timer:
            self.root.after_cancel(self._resize_timer)
        self._resize_timer = self.root.after(300, self._apply_resize)

    def _apply_resize(self):
        self._resize_timer = None
        if self._playing:
            self._relaunch_current()

    def _apply_debounced(self, video_path, audio_path, v_override, a_offset):
        self._debounce_timer = None
        if self._playing or self._ffmpeg is not None:
            self.launch(video_path, audio_path, v_override, a_offset,
                        start_time=self._position)

    def _set_widget_state_recursive(self, widget, state):
        try:
            widget.configure(state=state)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._set_widget_state_recursive(child, state)
