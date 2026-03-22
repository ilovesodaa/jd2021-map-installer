"""Main window for the JD2021 Map Installer — PyQt6 GUI.

Composes modular widgets from ``ui/widgets/`` and acts as the central
controller, wiring user-facing signals to backend ``QObject`` workers
running on dedicated ``QThread`` instances.

Layout
------
::

    ┌───────────────── QSplitter ────────────────────┐
    │  Left Panel               │  Right Panel       │
    │  ─────────────            │  ──────────────    │
    │  ModeSelectorWidget       │  ProgressLogWidget │
    │  ConfigWidget             │                    │
    │  ActionWidget             │                    │
    │  SyncRefinementWidget     │                    │
    └───────────────────────────┴────────────────────┘
    [                 QProgressBar (status bar)       ]
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.models import NormalizedMapData
from jd2021_installer.ui.widgets import (
    ActionWidget,
    ConfigWidget,
    ModeSelectorWidget,
    ProgressLogWidget,
    StepStatus,
    SyncRefinementWidget,
)
from jd2021_installer.ui.workers.media_workers import (
    PreviewMediaWorker,
    SyncRefinementWorker,
)
from jd2021_installer.ui.workers.pipeline_workers import (
    ExtractAndNormalizeWorker,
    InstallMapWorker,
)

logger = logging.getLogger("jd2021.ui.main_window")

# Checklist step names (displayed in the feedback panel)
PIPELINE_STEPS = [
    "Extract map data",
    "Normalize map data",
    "Install to game directory",
]


class MainWindow(QMainWindow):
    """Primary application window — orchestrates widgets and workers."""

    def __init__(self) -> None:
        super().__init__()

        # -- Application state ------------------------------------------------
        self._config = AppConfig()
        self._current_map: Optional[NormalizedMapData] = None
        self._current_target: Optional[str] = None
        self._current_mode: str = "Fetch (Codename)"

        self._active_thread: Optional[QThread] = None
        self._active_worker: Optional[object] = None
        self._preview_worker: Optional[PreviewMediaWorker] = None

        # -- Window setup -----------------------------------------------------
        self.setWindowTitle("JD2021 Map Installer v2")
        self.setMinimumSize(1060, 700)

        self._build_ui()
        self._wire_signals()

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    # ==================================================================
    # UI COMPOSITION  (Phase 3)
    # ==================================================================

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # Primary splitter: left (controls) | right (feedback)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)

        # -- Left panel -------------------------------------------------------
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        self._mode_selector = ModeSelectorWidget()
        left_layout.addWidget(self._mode_selector)

        self._config_panel = ConfigWidget()
        left_layout.addWidget(self._config_panel)

        self._action_panel = ActionWidget()
        left_layout.addWidget(self._action_panel)

        self._sync_refinement = SyncRefinementWidget()
        left_layout.addWidget(self._sync_refinement)

        left_layout.addStretch()
        splitter.addWidget(left_panel)

        # -- Right panel -------------------------------------------------------
        self._feedback_panel = ProgressLogWidget()
        splitter.addWidget(self._feedback_panel)

        splitter.setSizes([380, 680])

    # ==================================================================
    # SIGNAL / SLOT WIRING  (Phase 4)
    # ==================================================================

    def _wire_signals(self) -> None:
        # -- Mode & config signals ------------------------------------------
        self._mode_selector.mode_changed.connect(self._on_mode_changed)
        self._mode_selector.target_selected.connect(self._on_target_selected)
        self._config_panel.game_dir_changed.connect(self._on_game_dir_changed)
        self._config_panel.quality_changed.connect(self._on_quality_changed)

        # -- Action panel signals -------------------------------------------
        self._action_panel.install_requested.connect(self._on_install_requested)
        self._action_panel.preflight_requested.connect(self._on_preflight)
        self._action_panel.clear_cache_requested.connect(self._on_clear_cache)
        self._action_panel.readjust_offset_requested.connect(
            lambda: self._sync_refinement.setVisible(
                not self._sync_refinement.isVisible()
            )
        )
        self._action_panel.reset_state_requested.connect(self._on_reset_state)

        # -- Sync refinement signals ----------------------------------------
        self._sync_refinement.preview_requested.connect(self._on_preview_toggle)
        self._sync_refinement.apply_requested.connect(self._on_apply_offset)

    # ==================================================================
    # SLOT IMPLEMENTATIONS
    # ==================================================================

    # -- Config / mode slots ------------------------------------------------

    def _on_mode_changed(self, mode: str) -> None:
        self._current_mode = mode
        self._set_status(f"Mode: {mode}")

    def _on_target_selected(self, target: str) -> None:
        self._current_target = target
        logger.debug("Target selected: %s", target)

    def _on_game_dir_changed(self, path: str) -> None:
        self._config.game_directory = Path(path)
        self._set_status(f"Game directory: {path}")

    def _on_quality_changed(self, quality: str) -> None:
        self._config.video_quality = quality

    # -- Pre-flight ---------------------------------------------------------

    def _on_preflight(self) -> None:
        """Quick sanity checks before installation."""
        issues: list[str] = []

        if not self._config.game_directory:
            issues.append("Game directory is not set.")
        elif not self._config.game_directory.is_dir():
            issues.append(f"Game directory does not exist: {self._config.game_directory}")

        if not self._current_target:
            issues.append("No input target selected.")

        if issues:
            QMessageBox.warning(
                self,
                "Pre-flight Check Failed",
                "\n".join(f"• {i}" for i in issues),
            )
        else:
            QMessageBox.information(
                self, "Pre-flight Check", "All checks passed! Ready to install."
            )

    # -- Clear cache --------------------------------------------------------

    def _on_clear_cache(self) -> None:
        cache = self._config.cache_directory
        if cache.exists():
            reply = QMessageBox.question(
                self,
                "Clear Cache",
                f"Delete all files in {cache}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                shutil.rmtree(cache, ignore_errors=True)
                cache.mkdir(parents=True, exist_ok=True)
                self._feedback_panel.append_log("Cache cleared.")
                self._set_status("Cache cleared.")
        else:
            self._feedback_panel.append_log("No cache directory to clear.")

    # -- Reset state --------------------------------------------------------

    def _on_reset_state(self) -> None:
        self._current_map = None
        self._current_target = None
        self._sync_refinement.reset()
        self._feedback_panel.reset()
        self._set_status("State reset.")

    # ==================================================================
    # PIPELINE EXECUTION  (Install flow)
    # ==================================================================

    def _on_install_requested(self) -> None:
        """Launch the Extract → Normalize → Install pipeline."""
        if not self._current_target:
            QMessageBox.warning(self, "No Target", "Please select an input target first.")
            return
        if not self._config.game_directory:
            QMessageBox.warning(self, "No Game Dir", "Please set the game directory first.")
            return

        # Resolve the correct extractor based on mode
        extractor = self._resolve_extractor()
        if extractor is None:
            return

        # Prepare UI
        self._lock_ui(True)
        self._feedback_panel.reset()
        self._feedback_panel.set_checklist_steps(PIPELINE_STEPS)
        self._feedback_panel.update_checklist_step("Extract map data", StepStatus.IN_PROGRESS)

        # Create worker + thread
        worker = ExtractAndNormalizeWorker(
            extractor=extractor,
            output_dir=self._config.cache_directory,
        )
        thread = QThread()
        worker.moveToThread(thread)

        # Wire signals
        thread.started.connect(worker.run)
        worker.progress.connect(self._feedback_panel.set_progress)
        worker.status.connect(self._feedback_panel.append_log)
        worker.error.connect(self._on_extract_error)
        worker.finished.connect(lambda data: self._on_extract_finished(data))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup_thread("extract"))

        self._active_thread = thread
        self._active_worker = worker
        thread.start()

    def _on_extract_error(self, msg: str) -> None:
        self._feedback_panel.update_checklist_step("Extract map data", StepStatus.ERROR)
        self._feedback_panel.append_log(f"ERROR: {msg}")
        self._lock_ui(False)

    def _on_extract_finished(self, map_data: Optional[NormalizedMapData]) -> None:
        if map_data is None:
            return  # error already handled

        self._current_map = map_data
        self._feedback_panel.update_checklist_step("Extract map data", StepStatus.DONE)
        self._feedback_panel.update_checklist_step("Normalize map data", StepStatus.DONE)
        self._feedback_panel.update_checklist_step(
            "Install to game directory", StepStatus.IN_PROGRESS
        )

        # Start install worker
        self._start_install_worker(map_data)

    def _start_install_worker(self, map_data: NormalizedMapData) -> None:
        worker = InstallMapWorker(
            map_data=map_data,
            target_dir=self._config.game_directory,  # type: ignore[arg-type]
            config=self._config,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._feedback_panel.set_progress)
        worker.status.connect(self._feedback_panel.append_log)
        worker.error.connect(self._on_install_error)
        worker.finished.connect(lambda ok: self._on_install_finished(ok))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup_thread("install"))

        self._active_thread = thread
        self._active_worker = worker
        thread.start()

    def _on_install_error(self, msg: str) -> None:
        self._feedback_panel.update_checklist_step(
            "Install to game directory", StepStatus.ERROR
        )
        self._feedback_panel.append_log(f"ERROR: {msg}")
        self._lock_ui(False)

    def _on_install_finished(self, success: bool) -> None:
        status = StepStatus.DONE if success else StepStatus.ERROR
        self._feedback_panel.update_checklist_step("Install to game directory", status)
        if success:
            self._set_status("Installation complete!")
            self._feedback_panel.append_log("✅  Map installed successfully!")
        self._lock_ui(False)

    # ==================================================================
    # SYNC REFINEMENT / PREVIEW
    # ==================================================================

    def _on_preview_toggle(self, start: bool) -> None:
        """Start or stop the FFplay preview."""
        if start:
            if self._current_map and self._current_map.media.video_path:
                self._preview_worker = PreviewMediaWorker(
                    media_path=self._current_map.media.video_path,
                    seek_seconds=self._current_map.effective_video_start_time / 1000.0,
                )
                self._preview_worker.error.connect(
                    lambda msg: self._feedback_panel.append_log(f"Preview error: {msg}")
                )
                self._preview_worker.start()
            else:
                self._feedback_panel.append_log("No video available for preview.")
                self._sync_refinement._btn_preview.setChecked(False)
        else:
            if self._preview_worker:
                self._preview_worker.stop()
                self._preview_worker = None

    def _on_apply_offset(self, offset_ms: float) -> None:
        """Apply the combined offset to the current map data."""
        if self._current_map is None:
            QMessageBox.warning(self, "No Map", "Load a map before applying offsets.")
            return

        worker = SyncRefinementWorker(
            map_data=self._current_map,
            offset_ms=offset_ms,
            persist=True,
            cache_dir=self._config.cache_directory,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.status.connect(self._feedback_panel.append_log)
        worker.error.connect(lambda msg: self._feedback_panel.append_log(f"ERROR: {msg}"))
        worker.finished.connect(self._on_offset_applied)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.start()

    def _on_offset_applied(self, map_data: Optional[NormalizedMapData]) -> None:
        if map_data:
            self._current_map = map_data
            self._set_status(
                f"Offset applied — effective start: "
                f"{map_data.effective_video_start_time:.2f} ms"
            )

    # ==================================================================
    # HELPERS
    # ==================================================================

    def _resolve_extractor(self):
        """Create the correct BaseExtractor for the current mode/target.

        Returns ``None`` (and shows a warning) if the mode is not yet
        implemented or the target is invalid.
        """
        from jd2021_installer.ui.widgets.mode_selector import (
            MODE_FETCH,
            MODE_HTML,
            MODE_IPK,
            MODE_BATCH,
            MODE_MANUAL,
        )

        idx = self._mode_selector.current_mode_index

        if idx == MODE_IPK:
            from jd2021_installer.extractors.archive_ipk import IPKExtractor

            ipk_path = Path(self._current_target)  # type: ignore[arg-type]
            if not ipk_path.is_file():
                QMessageBox.warning(self, "Invalid Path", f"IPK not found: {ipk_path}")
                return None
            return IPKExtractor(ipk_path)

        if idx == MODE_FETCH:
            from jd2021_installer.extractors.web_playwright import WebExtractor

            return WebExtractor(
                codenames=[c.strip() for c in (self._current_target or "").split(",") if c.strip()],
                config=self._config,
            )

        # HTML, Batch, Manual are not fully implemented yet
        QMessageBox.information(
            self,
            "Not Implemented",
            f"The '{self._current_mode}' mode is not yet fully implemented.",
        )
        return None

    def _lock_ui(self, locked: bool) -> None:
        """Disable input panels while a worker is active."""
        self._mode_selector.setEnabled(not locked)
        self._config_panel.setEnabled(not locked)
        self._action_panel.set_all_enabled(not locked)

    def _cleanup_thread(self, label: str) -> None:
        logger.debug("Thread cleaned up: %s", label)
        self._active_thread = None
        self._active_worker = None

    def _set_status(self, text: str) -> None:
        self._status_bar.showMessage(text)

    # -- Public convenience methods (kept for compatibility) ----------------

    def append_log(self, text: str) -> None:
        """Append text to the feedback log (delegated to ProgressLogWidget)."""
        self._feedback_panel.append_log(text)

    def set_progress(self, value: int) -> None:
        """Set the progress bar value (delegated to ProgressLogWidget)."""
        self._feedback_panel.set_progress(value)

    def set_status(self, text: str) -> None:
        """Update the status bar message."""
        self._set_status(text)
