"""QObject-based workers for media preview and sync refinement.

PreviewMediaWorker:  Launches FFplay as a subprocess for audio/video
    preview without blocking the main event loop.

SyncRefinementWorker:  Applies a video_start_time_override to an
    already-normalised map and optionally persists the adjustment
    to AppConfig/cache so that a subsequent (re-)installation
    honours the new offset.
"""

from __future__ import annotations

import logging
import subprocess
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QProcess, pyqtSignal

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.models import NormalizedMapData

logger = logging.getLogger("jd2021.ui.workers.media")


# ---------------------------------------------------------------------------
# Preview (FFplay) worker
# ---------------------------------------------------------------------------

class PreviewMediaWorker(QObject):
    """Play audio/video through FFplay without freezing the GUI.

    Uses ``QProcess`` so the subprocess lifecycle stays on the
    Qt event loop (start / stop / error signals work naturally).
    """

    started = pyqtSignal()
    stopped = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        media_path: Path,
        *,
        ffplay_path: str = "ffplay",
        seek_seconds: float = 0.0,
        window_title: str = "JD2021 Preview",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._media_path = media_path
        self._ffplay_path = ffplay_path
        self._seek_seconds = seek_seconds
        self._window_title = window_title
        self._process: Optional[QProcess] = None

    # -- public API ---------------------------------------------------------

    def start(self) -> None:
        """Launch FFplay asynchronously."""
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            logger.debug("Preview already running; stopping first.")
            self.stop()

        self._process = QProcess(self)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

        args: list[str] = [
            "-autoexit",
            "-window_title", self._window_title,
        ]
        if self._seek_seconds:
            args += ["-ss", str(self._seek_seconds)]
        args.append(str(self._media_path))

        logger.info("Starting preview: %s %s", self._ffplay_path, " ".join(args))
        self._process.start(self._ffplay_path, args)
        self.started.emit()

    def stop(self) -> None:
        """Terminate the running FFplay process (if any) gracefully."""
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            logger.debug("Stopping ffplay process gracefully...")
            self._process.terminate()
            if not self._process.waitForFinished(3000):
                logger.debug("ffplay did not terminate gracefully; killing.")
                self._process.kill()
                self._process.waitForFinished(1000)
        self.stopped.emit()

    def is_running(self) -> bool:
        return (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    # -- slots --------------------------------------------------------------

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        logger.debug("Preview exited with code=%d status=%s", exit_code, exit_status)
        self.stopped.emit()

    def _on_error(self, err: QProcess.ProcessError) -> None:
        msg = f"FFplay error: {err.name}"
        logger.error(msg)
        self.error.emit(msg)


# ---------------------------------------------------------------------------
# Sync-refinement worker
# ---------------------------------------------------------------------------

class SyncRefinementWorker(QObject):
    """Apply a video-start-time offset to an in-memory NormalizedMapData.

    If *persist* is ``True``, the adjusted override is also written
    to a lightweight JSON sidecar file alongside the map cache so
    the offset survives across sessions.

    This worker is intentionally fast (no heavy I/O), but is still
    off-loaded from the GUI thread for safety and consistency with
    the rest of the worker architecture.
    """

    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)  # updated NormalizedMapData (or None on error)

    def __init__(
        self,
        map_data: NormalizedMapData,
        offset_ms: float,
        *,
        persist: bool = False,
        cache_dir: Optional[Path] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._map_data = map_data
        self._offset_ms = offset_ms
        self._persist = persist
        self._cache_dir = cache_dir

    def run(self) -> None:
        try:
            original = self._map_data.music_track.video_start_time
            new_override = original + self._offset_ms

            self._map_data.video_start_time_override = new_override

            self.status.emit(
                f"Offset applied: {original:.2f} → {new_override:.2f} ms "
                f"(delta {self._offset_ms:+.2f})"
            )

            if self._persist and self._cache_dir is not None:
                self._write_sidecar(new_override)

            self.finished.emit(self._map_data)

        except Exception as e:
            logger.exception("SyncRefinement failed: %s\n%s", e, traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(None)

    def _write_sidecar(self, override: float) -> None:
        import json

        sidecar = self._cache_dir / f"{self._map_data.codename}_offset.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(
            json.dumps(
                {
                    "codename": self._map_data.codename,
                    "video_start_time_override": override,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("Sidecar written: %s", sidecar)
        self.status.emit(f"Offset persisted to {sidecar.name}")
