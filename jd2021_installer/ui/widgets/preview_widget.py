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

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("jd2021.ui.widgets.preview")

PREVIEW_FPS = 24
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

    def __init__(
        self,
        ffmpeg_cmd: list[str],
        width: int,
        height: int,
        ffplay_cmd: Optional[list[str]] = None,
        start_position: float = 0.0,
    ) -> None:
        super().__init__()
        self._ffmpeg_cmd = ffmpeg_cmd
        self._ffplay_cmd = ffplay_cmd
        self._width = width
        self._height = height
        self._start_position = start_position
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

            while not self._stop_flag.is_set():
                data = b""
                while len(data) < frame_size:
                    chunk = self._ffmpeg.stdout.read(frame_size - len(data))
                    if not chunk:
                        # EOF — video over
                        self.playback_ended.emit()
                        return
                    data += chunk

                # Launch ffplay once the first frame is ready
                if frames_read == 0 and self._ffplay_cmd:
                    try:
                        self._ffplay = subprocess.Popen(
                            self._ffplay_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=_CFLAGS,
                        )
                    except FileNotFoundError:
                        logger.warning("ffplay not found — audio preview disabled.")
                    except Exception as exc:
                        logger.error("Could not launch ffplay: %s", exc)
                    wall_start = time.time() + 0.1

                frames_read += 1
                position += 1.0 / PREVIEW_FPS

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

                # Emit position every 12 frames (~0.5 s)
                if frames_read % 12 == 0:
                    self.position_updated.emit(position)

                # Simple wall-clock throttle to ~24 FPS
                if wall_start > 0:
                    expected = frames_read / float(PREVIEW_FPS)
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
        for proc, label in [(self._ffmpeg, "ffmpeg"), (self._ffplay, "ffplay")]:
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

        self._build_ui()

    # ==================================================================
    # UI CONSTRUCTION
    # ==================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # -- Video canvas ---------------------------------------------------
        self._canvas = _AspectRatioLabel("No Preview")
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setMinimumSize(480, 270)
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        self._canvas.setStyleSheet(
            "background-color: #111; color: #666; "
            "font-size: 13px; border-radius: 6px;"
        )
        root.addWidget(self._canvas, stretch=1)

        # -- Seek bar -------------------------------------------------------
        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)

        self._lbl_time = QLabel("0:00")
        self._lbl_time.setFixedWidth(40)
        self._lbl_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_time.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        seek_row.addWidget(self._lbl_time)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.setValue(0)
        self._seek_slider.setTracking(True)
        self._seek_slider.sliderReleased.connect(self._on_seek_released)
        seek_row.addWidget(self._seek_slider)

        self._lbl_dur = QLabel("0:00")
        self._lbl_dur.setFixedWidth(40)
        self._lbl_dur.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        seek_row.addWidget(self._lbl_dur)

        root.addLayout(seek_row)

        # -- Buttons --------------------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()

        self._btn_rewind = QPushButton("−5 s")
        self._btn_rewind.setFixedWidth(50)
        self._btn_rewind.clicked.connect(lambda: self._seek_relative(-5))
        btn_row.addWidget(self._btn_rewind)

        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedWidth(50)
        self._btn_play.clicked.connect(self._toggle_playback)
        btn_row.addWidget(self._btn_play)

        self._btn_forward = QPushButton("+5 s")
        self._btn_forward.setFixedWidth(50)
        self._btn_forward.clicked.connect(lambda: self._seek_relative(5))
        btn_row.addWidget(self._btn_forward)

        self._btn_stop = QPushButton("⏹")
        self._btn_stop.setFixedWidth(40)
        self._btn_stop.clicked.connect(self.stop)
        btn_row.addWidget(self._btn_stop)

        btn_row.addStretch()
        root.addLayout(btn_row)

    # ==================================================================
    # PUBLIC API
    # ==================================================================

    def launch(
        self,
        video_path: str,
        audio_path: str,
        v_override: float = 0.0,
        a_offset: float = 0.0,
        start_time: float = 0.0,
    ) -> None:
        """Start (or restart) embedded preview playback.

        Args:
            video_path:  Absolute path to the ``.webm`` video file.
            audio_path:  Absolute path to the ``.ogg`` audio file.
            v_override:  Video start-time override (seconds, negative = intro).
            a_offset:    Audio offset in seconds.
            start_time:  Seek position in seconds to start from.
        """
        if not video_path or not audio_path:
            return

        # Stash for resume / seek
        self._video_path = video_path
        self._audio_path = audio_path
        self._v_override = v_override
        self._a_offset = a_offset

        # Kill previous, but keep position if we are just restarting/seeking
        self.stop(reset_position=(start_time == 0.0))

        # Probe duration (best effort)
        if start_time == 0.0:
            self._duration = self._probe_duration(video_path, audio_path, v_override, a_offset)
            self._lbl_dur.setText(self._fmt(self._duration))

        # Canvas dimensions
        w = max(self._canvas.width(), 320)
        h = max(self._canvas.height(), 180)

        # Compute seek positions
        vid_seek = abs(v_override) if v_override else 0.0
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

        vf_chain = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
        )

        ffmpeg_cmd: list[str] = ["ffmpeg", "-loglevel", "error"]
        if vid_seek > 0:
            ffmpeg_cmd += ["-ss", f"{vid_seek:.6f}"]
        ffmpeg_cmd += [
            "-i", video_path,
            "-vf", vf_chain,
            "-r", str(PREVIEW_FPS),
            "-pix_fmt", "rgb24",
            "-f", "rawvideo",
            "-",
        ]

        ffplay_cmd: list[str] = [
            "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
        ]
        if aud_seek > 0:
            ffplay_cmd += ["-ss", f"{aud_seek:.6f}"]
        if aud_delay_ms > 0:
            ffplay_cmd += [
                "-i", audio_path,
                "-af", f"adelay={aud_delay_ms}|{aud_delay_ms},asetpts=PTS-STARTPTS",
            ]
        else:
            ffplay_cmd += ["-i", audio_path]

        # Build worker + thread
        self._position = start_time
        self._playing = True
        self._btn_play.setText("⏸")

        worker = _FrameReaderWorker(
            ffmpeg_cmd, w, h,
            ffplay_cmd=ffplay_cmd,
            start_position=start_time,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.frame_ready.connect(self._on_frame)
        worker.position_updated.connect(self._on_position)
        worker.playback_ended.connect(self._on_playback_ended)

        # Clean-up chain
        worker.playback_ended.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._worker = worker
        self._thread = thread
        thread.start()
        self.preview_started.emit()

    def stop(self, reset_position: bool = True) -> None:
        """Stop any running preview subprocess safely.
        
        Args:
            reset_position: If True, sets _position back to 0.0 and clears labels.
        """
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
        
        # Reset canvas to black ("No Preview" state)
        self._canvas.clear()
        self._canvas.setText("No Preview")
        self._canvas.setStyleSheet(
            "background-color: #111; color: #666; "
            "font-size: 13px; border-radius: 6px;"
        )

        if self._playing:
            self._playing = False
            self._btn_play.setText("▶")
            self.preview_stopped.emit()

    def reset(self) -> None:
        """Stop playback and reset all state."""
        self.stop()
        self._position = 0.0
        self._duration = 120.0
        self._canvas.setPixmap(QPixmap())
        self._canvas.setText("No Preview")
        self._seek_slider.setValue(0)
        self._lbl_time.setText("0:00")
        self._lbl_dur.setText("0:00")

    @property
    def is_playing(self) -> bool:
        return self._playing

    # ==================================================================
    # SLOTS
    # ==================================================================

    @pyqtSlot(QPixmap)
    def _on_frame(self, pixmap: QPixmap) -> None:
        self._canvas.setPixmap(pixmap)

    @pyqtSlot(float)
    def _on_position(self, pos: float) -> None:
        self._position = pos
        self._lbl_time.setText(self._fmt(pos))
        if self._duration > 0:
            pct = int((pos / self._duration) * 1000)
            self._seek_slider.blockSignals(True)
            self._seek_slider.setValue(min(pct, 1000))
            self._seek_slider.blockSignals(False)

    @pyqtSlot()
    def _on_playback_ended(self) -> None:
        self._playing = False
        self._btn_play.setText("▶")
        self.preview_stopped.emit()

    # ==================================================================
    # UI CALLBACKS
    # ==================================================================

    def _toggle_playback(self) -> None:
        if self._playing:
            self.stop()
        else:
            self._relaunch(self._position)

    def _seek_relative(self, delta: float) -> None:
        new_pos = max(0.0, min(self._position + delta, self._duration))
        self._position = new_pos
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
        self._lbl_time.setText(self._fmt(self._position))
        if self._playing:
            self._relaunch(self._position)

    def _relaunch(self, start_time: float = 0.0) -> None:
        if self._video_path and self._audio_path:
            self.launch(
                self._video_path, self._audio_path,
                self._v_override, self._a_offset,
                start_time=start_time,
            )

    # ==================================================================
    # HELPERS
    # ==================================================================

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = max(0.0, seconds)
        return f"{int(s // 60)}:{int(s % 60):02d}"

    @staticmethod
    def _probe_duration(
        video_path: str, audio_path: str,
        v_override: float, a_offset: float,
    ) -> float:
        """Estimate playable preview duration via ffprobe."""
        try:
            cmd_v = [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=nw=1:nk=1",
                video_path,
            ]
            v_dur = float(subprocess.check_output(cmd_v, text=True,
                          creationflags=_CFLAGS).strip())
            cmd_a = [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=nw=1:nk=1",
                audio_path,
            ]
            a_dur = float(subprocess.check_output(cmd_a, text=True,
                          creationflags=_CFLAGS).strip())

            vid_beat0 = abs(v_override) if v_override else 0.0
            v_playable = v_dur - vid_beat0

            if a_offset and a_offset < 0:
                a_playable = a_dur - abs(a_offset)
            elif a_offset and a_offset > 0:
                a_playable = a_dur + a_offset
            else:
                a_playable = a_dur

            return max(v_playable, a_playable)
        except Exception as exc:
            logger.warning("Duration probe failed, using 120 s fallback: %s", exc)
            return 120.0
