"""Embedded FFmpeg preview widget — PyQt6 port of V1 ``gui_preview.py``.

Displays raw RGB24 video frames from ``ffmpeg`` piped into a ``QLabel``
at ~24 FPS, with audio played via a separate ``ffplay`` subprocess.
All heavy I/O runs in ``QThread``-based workers so the Qt event loop
is never blocked.

Layout::

    ┌──────────────────────────────────────────┐
    │              Video Canvas                │
    │            (480 × 270, black)            │
    ├──────────────────────────────────────────┤
    │  0:00  ═══════ seek ═══════  3:45       │
    │        [−5s]  [▶/⏸]  [+5s]  [⏹]        │
    └──────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("jd2021.ui.widgets.preview")

PREVIEW_FPS = 24
PREVIEW_PROXY_WIDTH = 960
_CFLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class _AspectRatioLabel(QLabel):
    """A QLabel that automatically scales its pixmap while maintaining aspect ratio on resize."""
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._base_pixmap = QPixmap()

    def setPixmap(self, pixmap: QPixmap) -> None:
        self._base_pixmap = pixmap
        super().setPixmap(self._scaled_pixmap())

    def resizeEvent(self, event) -> None:
        if not self._base_pixmap.isNull():
            super().setPixmap(self._scaled_pixmap())
        super().resizeEvent(event)

    def _scaled_pixmap(self) -> QPixmap:
        return self._base_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )


# ---------------------------------------------------------------------------
# Frame reader thread (runs ffmpeg, emits QPixmap frames)
# ---------------------------------------------------------------------------

class _FrameReaderWorker(QObject):
    """Reads raw RGB24 frames from ffmpeg stdout in a background thread.

    Emits:
        frame_ready(QPixmap): a new video frame for display
        position_updated(float): current playback position in seconds
        playback_ended(): the ffmpeg process reached EOF
    """

    frame_ready = pyqtSignal(QPixmap)
    position_updated = pyqtSignal(float)
    playback_ended = pyqtSignal()
    ffplay_missing = pyqtSignal()

    def __init__(
        self,
        ffmpeg_cmd: list[str],
        width: int,
        height: int,
        ffplay_cmd: Optional[list[str]] = None,
        start_position: float = 0.0,
        fps: float = PREVIEW_FPS,
        startup_compensation_ms: float = 0.0,
    ) -> None:
        super().__init__()
        self._ffmpeg_cmd = ffmpeg_cmd
        self._ffplay_cmd = ffplay_cmd
        self._width = width
        self._height = height
        self._start_position = start_position
        self._fps = max(1.0, float(fps))
        self._startup_compensation_s = max(0.0, float(startup_compensation_ms) / 1000.0)
        self._stop_flag = threading.Event()
        self._ffmpeg: Optional[subprocess.Popen] = None
        self._ffplay: Optional[subprocess.Popen] = None

    # -- public ------------------------------------------------------------

    def request_stop(self) -> None:
        """Set the stop flag so the read loop exits on next iteration."""
        self._stop_flag.set()

    @pyqtSlot()
    def run(self) -> None:
        """Main loop — launched via ``thread.started.connect(worker.run)``."""
        frame_size = self._width * self._height * 3
        frames_read = 0
        wall_start: float = 0.0
        position = self._start_position

        try:
            self._ffmpeg = subprocess.Popen(
                self._ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=_CFLAGS,
            )

            wall_start = 0.0

            while not self._stop_flag.is_set():
                data = b""
                ffmpeg_stdout = self._ffmpeg.stdout if self._ffmpeg else None
                if ffmpeg_stdout is None:
                    self.playback_ended.emit()
                    return
                while len(data) < frame_size:
                    chunk = ffmpeg_stdout.read(frame_size - len(data))
                    if not chunk:
                        # EOF — video over
                        self.playback_ended.emit()
                        return
                    data += chunk

                frames_read += 1

                if frames_read == 1:
                    # Anchor both audio and video timing to first decoded frame.
                    # This avoids per-timestamp drift where some seek targets need
                    # more decode warm-up before video output becomes available.
                    wall_start = time.time() + self._startup_compensation_s
                    if self._ffplay_cmd:
                        try:
                            self._ffplay = subprocess.Popen(
                                self._ffplay_cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=_CFLAGS,
                            )
                        except FileNotFoundError:
                            logger.warning("ffplay not found — audio preview disabled.")
                            self.ffplay_missing.emit()
                        except Exception as exc:
                            logger.error("Could not launch ffplay: %s", exc)

                if self._stop_flag.is_set():
                    return

                # Convert raw bytes to QPixmap
                q_img = QImage(
                    data,
                    self._width,
                    self._height,
                    self._width * 3,
                    QImage.Format.Format_RGB888,
                )
                pixmap = QPixmap.fromImage(q_img.copy())  # .copy() — data outlives loop
                self.frame_ready.emit(pixmap)

                if wall_start > 0:
                    position = self._start_position + max(0.0, time.time() - wall_start)

                # Emit position every frame so seek/relaunch operations use
                # up-to-date timestamps instead of 0.5s-quantized values.
                self.position_updated.emit(position)

                # Keep preview rendering near target FPS without relying on ffmpeg -re.
                if wall_start > 0:
                    expected = frames_read / float(self._fps)
                    now = time.time()
                    remaining = (wall_start + expected) - now
                    if remaining > 0:
                        time.sleep(remaining)

        except Exception as exc:
            logger.debug("Frame reader ended: %s", exc)
        finally:
            self._cleanup()

    # -- internal ----------------------------------------------------------

    def _cleanup(self) -> None:
        for proc, label in [
            (self._ffmpeg, "ffmpeg"),
            (self._ffplay, "ffplay"),
        ]:
            if proc is None:
                continue
            try:
                if label == "ffmpeg" and proc.stdout:
                    proc.stdout.close()
            except OSError:
                pass
            if proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=3)
                except OSError:
                    pass
        self._ffmpeg = None
        self._ffplay = None


# ---------------------------------------------------------------------------
# Preview widget (public API)
# ---------------------------------------------------------------------------

class PreviewWidget(QWidget):
    """Embedded video-preview widget with playback controls.

    Signals:
        preview_started(): emitted when playback begins.
        preview_stopped(): emitted when playback ends.
    """

    preview_started = pyqtSignal()
    preview_stopped = pyqtSignal()
    audio_unavailable = pyqtSignal()
    position_changed = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # State
        self._playing = False
        self._position: float = 0.0
        self._duration: float = 120.0  # fallback

        # Subprocess tracking
        self._worker: Optional[_FrameReaderWorker] = None
        self._thread: Optional[QThread] = None

        # Stashed launch params (for resume / seek)
        self._video_path: Optional[str] = None
        self._audio_path: Optional[str] = None
        self._v_override: float = 0.0
        self._a_offset: float = 0.0
        self._resume_after_seek: bool = False
        self._loop_start: float = 0.0
        self._loop_end: float = 0.0
        self._stop_requested: bool = False
        self._ffplay_warned: bool = False
        self._ffmpeg_path: str = "ffmpeg"
        self._ffprobe_path: str = "ffprobe"
        self._ffplay_path: str = "ffplay"
        self._ffmpeg_hwaccel: str = "auto"
        self._preview_video_mode: str = "proxy_low"
        self._preview_fps_default: float = float(PREVIEW_FPS)
        self._playback_fps: float = float(PREVIEW_FPS)
        self._preview_startup_compensation_ms: float = 100.0
        self._startup_compensation_override_ms: Optional[float] = None
        self._preview_proxy_cache: dict[str, str] = {}
        self._repeat_seek_timer = QTimer(self)
        self._repeat_seek_timer.setInterval(900)
        self._repeat_seek_timer.timeout.connect(self._on_repeat_seek_tick)

        self._build_ui()

    # ==================================================================
    # UI CONSTRUCTION
    # ==================================================================

    def _set_play_button_icon(self, playing: bool) -> None:
        tooltip = "Pause Preview" if playing else "Play Preview"
        self._btn_play.setText("Stop" if playing else "Play")
        self._btn_play.setToolTip(tooltip)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        self.setObjectName("previewWidget")

        # -- Video canvas ---------------------------------------------------
        self._canvas = _AspectRatioLabel("No Preview")
        self._canvas.setObjectName("previewCanvas")
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setMinimumSize(480, 270)
        self._canvas.setToolTip("Video preview area for sync checking")
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        root.addWidget(self._canvas, stretch=1)

        # -- Seek bar -------------------------------------------------------
        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(4, 0, 4, 0)

        self._lbl_time = QLabel("0:00")
        self._lbl_time.setObjectName("previewCurrentTimeLabel")
        self._lbl_time.setMinimumWidth(40)
        self._lbl_time.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._lbl_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        seek_row.addWidget(self._lbl_time)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.setValue(0)
        self._seek_slider.setTracking(True)
        self._seek_slider.setToolTip("Drag to seek within the preview timeline")
        self._seek_slider.valueChanged.connect(self._on_seek_value_changed)
        self._seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self._seek_slider.sliderReleased.connect(self._on_seek_released)
        seek_row.addWidget(self._seek_slider)

        self._lbl_dur = QLabel("0:00")
        self._lbl_dur.setObjectName("previewDurationLabel")
        self._lbl_dur.setMinimumWidth(40)
        self._lbl_dur.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._lbl_dur.setToolTip("Total preview duration")
        seek_row.addWidget(self._lbl_dur)

        root.addLayout(seek_row)

        # -- Buttons --------------------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(4, 0, 4, 0)
        btn_row.addStretch()

        self._btn_rewind = QPushButton()
        self._btn_rewind.setObjectName("previewRewindButton")
        self._btn_rewind.setText("-5s")
        self._btn_rewind.setMinimumWidth(52)
        self._btn_rewind.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._btn_rewind.setToolTip("Rewind 5 seconds")
        self._btn_rewind.clicked.connect(lambda: self._seek_relative(-5))
        btn_row.addWidget(self._btn_rewind)

        self._btn_play = QPushButton()
        self._btn_play.setObjectName("previewPlayButton")
        self._btn_play.setMinimumWidth(52)
        self._btn_play.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._set_play_button_icon(False)
        self._btn_play.clicked.connect(self._toggle_playback)
        btn_row.addWidget(self._btn_play)

        self._btn_forward = QPushButton()
        self._btn_forward.setObjectName("previewForwardButton")
        self._btn_forward.setText("+5s")
        self._btn_forward.setMinimumWidth(52)
        self._btn_forward.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._btn_forward.setToolTip("Forward 5 seconds")
        self._btn_forward.clicked.connect(lambda: self._seek_relative(5))
        btn_row.addWidget(self._btn_forward)

        btn_row.addStretch()
        root.addLayout(btn_row)

        # -- Timestamp test tools ------------------------------------------
        test_row = QHBoxLayout()
        test_row.setContentsMargins(4, 0, 4, 0)

        test_label = QLabel("Test:")
        test_label.setObjectName("previewTestTimestampLabel")
        test_row.addWidget(test_label)

        self._timestamp_input = QLineEdit()
        self._timestamp_input.setObjectName("previewTestTimestampInput")
        self._timestamp_input.setPlaceholderText("3.0 or 0:03.250")
        self._timestamp_input.setToolTip("Timestamp for quick sync testing")
        self._timestamp_input.setMinimumWidth(120)
        self._timestamp_input.returnPressed.connect(self._go_to_test_timestamp)
        test_row.addWidget(self._timestamp_input)

        self._btn_go_timestamp = QPushButton("Go")
        self._btn_go_timestamp.setObjectName("previewGoTimestampButton")
        self._btn_go_timestamp.setToolTip("Jump to test timestamp")
        self._btn_go_timestamp.clicked.connect(self._go_to_test_timestamp)
        test_row.addWidget(self._btn_go_timestamp)

        self._btn_repeat_timestamp = QPushButton("Repeat Off")
        self._btn_repeat_timestamp.setObjectName("previewRepeatTimestampButton")
        self._btn_repeat_timestamp.setCheckable(True)
        self._btn_repeat_timestamp.setToolTip("Repeatedly jump to test timestamp")
        self._btn_repeat_timestamp.toggled.connect(self._on_repeat_seek_toggled)
        test_row.addWidget(self._btn_repeat_timestamp)

        test_row.addStretch()
        root.addLayout(test_row)

    # ==================================================================
    # PUBLIC API
    # ==================================================================

    def set_tool_paths(
        self,
        ffmpeg_path: str,
        ffprobe_path: str,
        ffplay_path: str,
        ffmpeg_hwaccel: str = "auto",
        preview_video_mode: str = "proxy_low",
        preview_fps: int = PREVIEW_FPS,
        preview_startup_compensation_ms: float = 100.0,
    ) -> None:
        """Update ffmpeg tool paths used by preview subprocesses."""
        self._ffmpeg_path = ffmpeg_path or "ffmpeg"
        self._ffprobe_path = ffprobe_path or "ffprobe"
        self._ffplay_path = ffplay_path or "ffplay"
        self._ffmpeg_hwaccel = ffmpeg_hwaccel or "auto"
        self._preview_video_mode = preview_video_mode or "proxy_low"
        try:
            fps = float(preview_fps)
        except (TypeError, ValueError):
            fps = float(PREVIEW_FPS)
        self._preview_fps_default = fps if fps > 0 else float(PREVIEW_FPS)
        try:
            compensation_ms = float(preview_startup_compensation_ms)
        except (TypeError, ValueError):
            compensation_ms = 100.0
        self._preview_startup_compensation_ms = max(0.0, compensation_ms)

    def launch(
        self,
        video_path: str,
        audio_path: str,
        v_override: float = 0.0,
        a_offset: float = 0.0,
        start_time: float = 0.0,
        loop_start: float = 0.0,
        loop_end: float = 0.0,
        preview_fps: Optional[float] = None,
        startup_compensation_ms: Optional[float] = None,
    ) -> None:
        """Start (or restart) embedded preview playback.

        Args:
            video_path:  Absolute path to the ``.webm`` video file.
            audio_path:  Absolute path to the ``.ogg`` audio file.
            v_override:  Video start-time override (seconds, negative = intro).
            a_offset:    Audio offset in seconds.
            start_time:  Seek position in seconds to start from.
            loop_start:  Loop start in seconds (0 disables looping).
            loop_end:    Loop end in seconds.
        """
        if not video_path or not audio_path:
            return

        if preview_fps is None:
            effective_fps = self._preview_fps_default
        else:
            try:
                fps_val = float(preview_fps)
            except (TypeError, ValueError):
                fps_val = self._preview_fps_default
            effective_fps = fps_val if fps_val > 0 else self._preview_fps_default

        if startup_compensation_ms is None:
            effective_startup_compensation_ms = self._preview_startup_compensation_ms
        else:
            try:
                effective_startup_compensation_ms = max(0.0, float(startup_compensation_ms))
            except (TypeError, ValueError):
                effective_startup_compensation_ms = self._preview_startup_compensation_ms

        resolved_video_path = self._resolve_preview_video_path(video_path)
        resolved_audio_path = self._resolve_preview_audio_path(audio_path)

        # Stash for resume / seek
        self._video_path = video_path
        self._audio_path = resolved_audio_path
        self._v_override = v_override
        self._a_offset = a_offset
        self._loop_start = max(0.0, loop_start)
        self._loop_end = max(0.0, loop_end)
        self._playback_fps = effective_fps
        self._startup_compensation_override_ms = startup_compensation_ms
        self._stop_requested = False

        # Kill previous, but keep position if we are just restarting/seeking
        self.stop(
            reset_position=(start_time == 0.0),
            clear_canvas=(start_time == 0.0),
        )

        # Probe duration (best effort)
        if start_time == 0.0:
            self._duration = self._probe_duration(
                resolved_video_path,
                resolved_audio_path,
                v_override,
                a_offset,
                ffprobe_path=self._ffprobe_path,
            )
            self._lbl_dur.setText(self._fmt(self._duration))

        # Canvas dimensions
        w = max(self._canvas.width(), 320)
        h = max(self._canvas.height(), 180)

        # Compute seek positions
        vid_seek = abs(v_override) if v_override < 0 else 0.0
        video_delay_s = v_override if v_override > 0 else 0.0
        aud_delay_ms = 0
        if a_offset and a_offset < 0:
            aud_seek = abs(a_offset)
        elif a_offset and a_offset > 0:
            aud_seek = 0.0
            aud_delay_ms = int(a_offset * 1000)
        else:
            aud_seek = 0.0

        vid_seek += start_time
        aud_seek += start_time

        coarse_video_seek = 0
        fine_video_seek = max(0.0, vid_seek)

        vf_filters: list[str] = []
        if fine_video_seek > 1e-6:
            vf_filters.extend([
                f"trim=start={fine_video_seek:.6f}",
                "setpts=PTS-STARTPTS",
            ])
        if video_delay_s > 0:
            vf_filters.append(f"tpad=start_duration={video_delay_s:.6f}")
        vf_filters.append(
            f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos"
        )
        vf_filters.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black")
        vf_chain = ",".join(vf_filters)

        fps_arg = str(int(effective_fps)) if abs(effective_fps - round(effective_fps)) < 1e-6 else f"{effective_fps:.6f}"

        ffmpeg_cmd: list[str] = [self._ffmpeg_path, "-loglevel", "error"]
        if self._ffmpeg_hwaccel == "auto":
            ffmpeg_cmd += ["-hwaccel", "auto"]
        # Accuracy-first preview seek: avoid input-seek keyframe snapping.
        ffmpeg_cmd += [
            "-i", resolved_video_path,
            "-vf", vf_chain,
            "-r", fps_arg,
            "-pix_fmt", "rgb24",
            "-f", "rawvideo",
            "-",
        ]

        ffplay_cmd: list[str] = [
            self._ffplay_path, "-nodisp", "-autoexit", "-loglevel", "quiet",
        ]
        fine_audio_seek = max(0.0, aud_seek)
        ffplay_cmd += ["-i", resolved_audio_path]

        afilters: list[str] = []
        if fine_audio_seek > 1e-6:
            # Fine decoder-side trim preserves fractional precision after coarse seek.
            afilters.extend([
                f"atrim=start={fine_audio_seek:.6f}",
                "asetpts=PTS-STARTPTS",
            ])
        if aud_delay_ms > 0:
            afilters.append(f"adelay={aud_delay_ms}|{aud_delay_ms}")
        if afilters:
            ffplay_cmd += ["-af", ",".join(afilters)]

        # Build worker + thread
        self._position = start_time
        self.position_changed.emit(self._position)
        self._playing = True
        self._set_play_button_icon(True)

        worker = _FrameReaderWorker(
            ffmpeg_cmd, w, h,
            ffplay_cmd=ffplay_cmd,
            start_position=start_time,
            fps=effective_fps,
            startup_compensation_ms=effective_startup_compensation_ms,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.frame_ready.connect(self._on_frame)
        worker.position_updated.connect(self._on_position)
        worker.playback_ended.connect(self._on_playback_ended)
        worker.ffplay_missing.connect(self._on_ffplay_missing)

        # Clean-up chain
        worker.playback_ended.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._worker = worker
        self._thread = thread
        thread.start()
        self.preview_started.emit()

    def stop(self, reset_position: bool = True, clear_canvas: bool = True) -> None:
        """Stop any running preview subprocess safely.
        
        Args:
            reset_position: If True, sets _position back to 0.0 and clears labels.
            clear_canvas: If True, clears the preview canvas to "No Preview".
        """
        self._set_repeat_seek_enabled(False)
        self._stop_requested = True
        if self._worker is not None:
            self._worker.request_stop()
        
        # Guard against RuntimeError if the C++ object was already deleted
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    self._thread.quit()
                    self._thread.wait(3000)
            except RuntimeError:
                logger.debug("Preview thread already deleted.")

        self._worker = None
        self._thread = None
        if reset_position:
            self._position = 0.0
            self._lbl_time.setText("0:00")
            self._seek_slider.setValue(0)
            self.position_changed.emit(self._position)
        
        if clear_canvas:
            self._canvas.clear()
            self._canvas.setText("No Preview")

        if self._playing:
            self._playing = False
            self._set_play_button_icon(False)
            self.preview_stopped.emit()

    def reset(self) -> None:
        """Stop playback and reset all state."""
        self.stop()
        self._position = 0.0
        self.position_changed.emit(self._position)
        self._duration = 120.0
        self._loop_start = 0.0
        self._loop_end = 0.0
        self._canvas.setPixmap(QPixmap())
        self._canvas.setText("No Preview")
        self._seek_slider.setValue(0)
        self._lbl_time.setText("0:00")
        self._lbl_dur.setText("0:00")

    @property
    def is_playing(self) -> bool:
        return self._playing

    def get_current_position(self) -> float:
        """Return current preview playback position in seconds."""
        return self._position

    # ==================================================================
    # SLOTS
    # ==================================================================

    @pyqtSlot(QPixmap)
    def _on_frame(self, pixmap: QPixmap) -> None:
        self._canvas.setPixmap(pixmap)

    @pyqtSlot(float)
    def _on_position(self, pos: float) -> None:
        self._position = pos
        self.position_changed.emit(self._position)
        self._lbl_time.setText(self._fmt(pos))
        if self._duration > 0 and not self._seek_slider.isSliderDown():
            pct = int((pos / self._duration) * 1000)
            self._seek_slider.blockSignals(True)
            self._seek_slider.setValue(min(pct, 1000))
            self._seek_slider.blockSignals(False)

    @pyqtSlot()
    def _on_playback_ended(self) -> None:
        if (
            not self._stop_requested
            and self._loop_start > 0.0
            and self._loop_end > self._loop_start
            and self._video_path
            and self._audio_path
        ):
            self.launch(
                self._video_path,
                self._audio_path,
                self._v_override,
                self._a_offset,
                start_time=self._loop_start,
                loop_start=self._loop_start,
                loop_end=self._loop_end,
                preview_fps=self._playback_fps,
                startup_compensation_ms=self._startup_compensation_override_ms,
            )
            return

        self._playing = False
        self._set_play_button_icon(False)
        self.preview_stopped.emit()

    @pyqtSlot()
    def _on_ffplay_missing(self) -> None:
        if self._ffplay_warned:
            return
        self._ffplay_warned = True
        self.audio_unavailable.emit()

    # ==================================================================
    # UI CALLBACKS
    # ==================================================================

    def _toggle_playback(self) -> None:
        if self._playing:
            self.stop(reset_position=False, clear_canvas=False)
        else:
            self._relaunch(self._position)

    def _parse_timestamp_input(self) -> Optional[float]:
        raw = self._timestamp_input.text().strip() if hasattr(self, "_timestamp_input") else ""
        if not raw:
            return None

        try:
            if ":" in raw:
                parts = raw.split(":")
                if len(parts) != 2:
                    return None
                mins = float(parts[0])
                secs = float(parts[1])
                value = (mins * 60.0) + secs
            else:
                value = float(raw)
        except ValueError:
            return None

        return max(0.0, value)

    def _jump_to_timestamp(self, target: float) -> None:
        if self._duration > 0:
            target = min(target, self._duration)

        self._position = target
        self.position_changed.emit(self._position)
        self._lbl_time.setText(self._fmt(target))

        if self._duration > 0:
            pct = int((target / self._duration) * 1000)
            self._seek_slider.blockSignals(True)
            self._seek_slider.setValue(min(max(pct, 0), 1000))
            self._seek_slider.blockSignals(False)

        if self._playing:
            self._relaunch(target)

    def _go_to_test_timestamp(self) -> None:
        target = self._parse_timestamp_input()
        if target is None:
            logger.warning("Invalid preview test timestamp input: '%s'", self._timestamp_input.text().strip())
            return
        self._jump_to_timestamp(target)

    def _set_repeat_seek_enabled(self, enabled: bool) -> None:
        if enabled:
            self._repeat_seek_timer.start()
        else:
            self._repeat_seek_timer.stop()

        if self._btn_repeat_timestamp.isChecked() != enabled:
            self._btn_repeat_timestamp.blockSignals(True)
            self._btn_repeat_timestamp.setChecked(enabled)
            self._btn_repeat_timestamp.blockSignals(False)
        self._btn_repeat_timestamp.setText("Repeat On" if enabled else "Repeat Off")

    def _on_repeat_seek_toggled(self, enabled: bool) -> None:
        if enabled:
            target = self._parse_timestamp_input()
            if target is None:
                logger.warning("Repeat seek ignored due to invalid timestamp input.")
                self._set_repeat_seek_enabled(False)
                return
            self._jump_to_timestamp(target)
            self._set_repeat_seek_enabled(True)
            return

        self._set_repeat_seek_enabled(False)

    def _on_repeat_seek_tick(self) -> None:
        if not self._playing:
            return
        target = self._parse_timestamp_input()
        if target is None:
            self._set_repeat_seek_enabled(False)
            return
        self._jump_to_timestamp(target)

    def _seek_relative(self, delta: float) -> None:
        new_pos = max(0.0, min(self._position + delta, self._duration))
        self._position = new_pos
        self.position_changed.emit(self._position)
        if self._playing:
            self._relaunch(new_pos)
        else:
            self._lbl_time.setText(self._fmt(new_pos))
            if self._duration > 0:
                pct = int((new_pos / self._duration) * 1000)
                self._seek_slider.setValue(min(pct, 1000))

    def _on_seek_released(self) -> None:
        pct = self._seek_slider.value() / 1000.0
        self._position = pct * self._duration
        self.position_changed.emit(self._position)
        self._lbl_time.setText(self._fmt(self._position))
        if self._playing or self._resume_after_seek:
            self._relaunch(self._position)
        self._resume_after_seek = False

    def _on_seek_pressed(self) -> None:
        self._resume_after_seek = self._playing

    def _on_seek_value_changed(self, value: int) -> None:
        target = (value / 1000.0) * self._duration
        self._lbl_time.setText(self._fmt(target))
        if self._seek_slider.isSliderDown():
            return

        # Clicking directly on the timeline groove may not set slider-down state.
        # Seek immediately so click-to-seek behaves as expected.
        if self._playing and abs(target - self._position) >= 0.25:
            self._position = target
            self.position_changed.emit(self._position)
            self._relaunch(self._position)

    def _relaunch(self, start_time: float = 0.0) -> None:
        if self._video_path and self._audio_path:
            self.launch(
                self._video_path, self._audio_path,
                self._v_override, self._a_offset,
                start_time=start_time,
                loop_start=self._loop_start,
                loop_end=self._loop_end,
                preview_fps=self._playback_fps,
                startup_compensation_ms=self._startup_compensation_override_ms,
            )

    # ==================================================================
    # HELPERS
    # ==================================================================

    def _resolve_preview_audio_path(self, audio_path: str) -> str:
        """Resolve a preview-playable audio path.

        Preview input may be a cooked `.wav.ckd` path that ffplay cannot decode.
        Prefer existing decoded siblings first, then try a one-time decode fallback.
        """
        path = Path(audio_path)

        # Convert streaming formats to a seek-friendly PCM WAV cache for stable preview jumps.
        if path.suffix.lower() in {".ogg", ".opus"}:
            try:
                stat = path.stat()
                cache_key_src = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
                cache_key = hashlib.sha1(cache_key_src.encode("utf-8")).hexdigest()
                cache_dir = Path(tempfile.gettempdir()) / "jd2021_preview_audio_cache"
                cache_dir.mkdir(parents=True, exist_ok=True)
                cached_wav = cache_dir / f"{path.stem}_{cache_key[:10]}_seek.wav"
                if cached_wav.exists() and cached_wav.stat().st_size > 1024:
                    return str(cached_wav)

                cmd = [
                    self._ffmpeg_path,
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_s16le",
                    str(cached_wav),
                ]
                completed = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_CFLAGS,
                    timeout=120,
                    check=False,
                )
                if completed.returncode == 0 and cached_wav.exists() and cached_wav.stat().st_size > 1024:
                    logger.info("Preview audio cache created: %s", cached_wav.name)
                    return str(cached_wav)
            except Exception as exc:
                logger.debug("Preview audio cache conversion skipped for %s: %s", path.name, exc)

        if path.suffix.lower() != ".ckd":
            return audio_path

        base_no_ckd = path.with_suffix("")
        stem = base_no_ckd.stem
        preview_cache = path.parent / "_preview_audio"
        candidates: list[Path] = [
            base_no_ckd,
            base_no_ckd.with_suffix(".wav"),
            base_no_ckd.with_suffix(".ogg"),
            path.parent / f"{stem}_raw_vgm.wav",
            path.parent / f"{stem}_decoded.wav",
            path.parent / f"{stem}_fixed.wav",
            path.parent / f"{stem}_fallback_fixed.wav",
            preview_cache / f"{stem}_raw_vgm.wav",
            preview_cache / f"{stem}_decoded.wav",
            preview_cache / f"{stem}_fixed.wav",
            preview_cache / f"{stem}_fallback_fixed.wav",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.suffix.lower() in {".wav", ".ogg"}:
                if str(candidate) != audio_path:
                    logger.debug("Preview audio fallback selected: %s", candidate)
                return str(candidate)

        try:
            from jd2021_installer.installers.media_processor import extract_ckd_audio_v1

            preview_cache.mkdir(parents=True, exist_ok=True)
            decoded = extract_ckd_audio_v1(path, preview_cache)
            if decoded and Path(decoded).exists():
                logger.info("Preview audio decoded from CKD: %s", Path(decoded).name)
                return str(decoded)
        except Exception as exc:
            logger.warning("Preview audio decode failed for %s: %s", path.name, exc)

        logger.warning("Preview audio remains cooked CKD; ffplay may be silent: %s", path.name)
        return audio_path

    def _resolve_preview_video_path(self, video_path: str) -> str:
        """Resolve a preview-friendly proxy video for heavy source codecs.

        For VP9/large WebM sources, repeated seeks can become expensive on some
        machines. A cached low-res H.264 proxy keeps preview controls responsive.
        """
        path = Path(video_path)
        if path.suffix.lower() != ".webm":
            return video_path
        if self._preview_video_mode == "original":
            return video_path

        try:
            stat = path.stat()
        except OSError:
            return video_path

        cache_key_src = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
        cache_key = hashlib.sha1(cache_key_src.encode("utf-8")).hexdigest()
        cached = self._preview_proxy_cache.get(cache_key)
        if cached and Path(cached).exists():
            return cached

        cache_dir = Path(tempfile.gettempdir()) / "jd2021_preview_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        proxy_path = cache_dir / f"{path.stem}_{cache_key[:10]}_preview.mp4"

        if proxy_path.exists() and proxy_path.stat().st_size > 1024:
            self._preview_proxy_cache[cache_key] = str(proxy_path)
            return str(proxy_path)

        # Keep transcode fast; quality only needs to be good enough for sync checks.
        cmd = [
            self._ffmpeg_path,
            "-y",
            "-v",
            "error",
        ]
        if self._ffmpeg_hwaccel == "auto":
            cmd += ["-hwaccel", "auto"]
        cmd += [
            "-i",
            str(path),
            "-vf",
            f"scale=min({PREVIEW_PROXY_WIDTH}\\,iw):-2:flags=lanczos",
            "-an",
            "-pix_fmt",
            "yuv420p",
            # Keep proxy generation fast and game-like (WebM/VP8 style).
            "-c:v", "libvpx",
            "-deadline", "realtime",
            "-cpu-used", "8",
            "-b:v", "900k",
            str(proxy_path),
        ]

        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CFLAGS,
                timeout=120,
                check=False,
            )
            if completed.returncode == 0 and proxy_path.exists() and proxy_path.stat().st_size > 1024:
                logger.info("Preview proxy created: %s", proxy_path.name)
                self._preview_proxy_cache[cache_key] = str(proxy_path)
                return str(proxy_path)
        except Exception as exc:
            logger.debug("Preview proxy transcode skipped for %s: %s", path.name, exc)

        return video_path

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = max(0.0, seconds)
        return f"{int(s // 60)}:{int(s % 60):02d}"

    @staticmethod
    def _probe_duration(
        video_path: str, audio_path: str,
        v_override: float, a_offset: float,
        ffprobe_path: str = "ffprobe",
    ) -> float:
        """Estimate playable preview duration via ffprobe."""
        def _ffprobe_duration(path: str) -> float:
            cmd = [
                ffprobe_path, "-v", "error", "-show_entries",
                "format=duration", "-of", "default=nw=1:nk=1",
                path,
            ]
            return float(
                subprocess.check_output(cmd, text=True, creationflags=_CFLAGS).strip()
            )

        def _audio_probe_candidates(path: str) -> list[str]:
            # Preview sometimes points to extracted .wav.ckd, which ffprobe cannot read.
            # Try sibling decoded files before giving up.
            p = Path(path)
            candidates = [str(p)]
            if p.suffix.lower() == ".ckd":
                no_ckd = p.with_suffix("")
                candidates.extend(
                    [
                        str(no_ckd),
                        str(no_ckd.with_suffix(".wav")),
                        str(no_ckd.with_suffix(".ogg")),
                    ]
                )
            seen: set[str] = set()
            ordered: list[str] = []
            for item in candidates:
                key = item.lower()
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(item)
            return ordered

        v_dur: float | None = None
        a_dur: float | None = None

        try:
            v_dur = _ffprobe_duration(video_path)
        except Exception as exc:
            logger.debug("Video duration probe failed for %s: %s", video_path, exc)

        for candidate in _audio_probe_candidates(audio_path):
            try:
                a_dur = _ffprobe_duration(candidate)
                if candidate != audio_path:
                    logger.debug("Audio duration fallback probe succeeded: %s", candidate)
                break
            except Exception:
                continue

        if v_dur is None and a_dur is None:
            logger.warning("Duration probe failed, using 120 s fallback: video=%s audio=%s", video_path, audio_path)
            return 120.0

        playable_values: list[float] = []
        if v_dur is not None:
            if v_override < 0:
                playable_values.append(v_dur - abs(v_override))
            elif v_override > 0:
                playable_values.append(v_dur + v_override)
            else:
                playable_values.append(v_dur)

        if a_dur is not None:
            if a_offset and a_offset < 0:
                playable_values.append(a_dur - abs(a_offset))
            elif a_offset and a_offset > 0:
                playable_values.append(a_dur + a_offset)
            else:
                playable_values.append(a_dur)

        return max(playable_values) if playable_values else 120.0
