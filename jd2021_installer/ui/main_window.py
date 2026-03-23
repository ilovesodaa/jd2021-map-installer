"""Main window for the JD2021 Map Installer — PyQt6 GUI.

Composes modular widgets from ``ui/widgets/`` and acts as the central
controller, wiring user-facing signals to backend ``QObject`` workers
running on dedicated ``QThread`` instances.

Layout
------
::

    ┌───────────────── QSplitter ────────────────────┐
    │  Top: Install Panel (Mode, Config, Action)     │
    ├───────────────── QSplitter ────────────────────┤
    │  Left: Progress           │  Right: Preview    │
    ├───────────────── QSplitter ────────────────────┤
    │  Bottom: Log Console      │  Sync Refinement   │
    └───────────────────────────┴────────────────────┘
    [                 QProgressBar (status bar)       ]
"""

from __future__ import annotations

import logging
import shutil
import sys
import json
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
    QHBoxLayout,
    QWidget,
    QLabel,
)

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.models import NormalizedMapData
from jd2021_installer.ui.widgets import (
    ActionWidget,
    ConfigWidget,
    ModeSelectorWidget,
    PreviewWidget,
    ProgressLogWidget,
    StepStatus,
    SyncRefinementWidget,
    LogConsoleWidget,
)
from jd2021_installer.ui.workers.media_workers import (
    SyncRefinementWorker,
)
from jd2021_installer.ui.workers.pipeline_workers import (
    ExtractAndNormalizeWorker,
    InstallMapWorker,
    ApplyAndFinishWorker,
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
        self._config = self._load_settings()
        self._current_map: Optional[NormalizedMapData] = None
        self._current_target: Optional[str] = None
        self._current_mode: str = "Fetch (Codename)"

        self._active_threads: set[QThread] = set()
        self._active_worker: Optional[object] = None
        self._file_logger_handler: Optional[logging.Handler] = None

        # -- Window setup -----------------------------------------------------
        self.setWindowTitle("JD2021 Map Installer v2")
        self.setMinimumSize(1060, 700)

        self._build_ui()
        self._wire_signals()

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    # ==================================================================
    # SETTINGS PERSISTENCE
    # ==================================================================

    def _load_settings(self) -> AppConfig:
        settings_file = Path("installer_settings.json")
        if settings_file.exists():
            try:
                with settings_file.open("r") as f:
                    data = json.load(f)
                return AppConfig(**data)
            except Exception as e:
                logger.error("Failed to load settings: %s", e)
        return AppConfig()

    def _save_settings(self) -> None:
        settings_file = Path("installer_settings.json")
        try:
            # handle pydantic v2 vs v1
            if hasattr(self._config, "model_dump"):
                data = self._config.model_dump(mode="json")
            else:
                data = json.loads(self._config.json())
            with settings_file.open("w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error("Failed to save settings: %s", e)

    # ==================================================================
    # UI COMPOSITION  (Phase 3)
    # ==================================================================

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        # -- Column 1 (Left): Fixed width ------------------------------------
        left_col = QWidget()
        left_col.setFixedWidth(450)
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self._mode_selector = ModeSelectorWidget()
        left_layout.addWidget(self._mode_selector)

        self._config_panel = ConfigWidget()
        left_layout.addWidget(self._config_panel)

        self._action_panel = ActionWidget()
        left_layout.addWidget(self._action_panel)

        self._feedback_panel = ProgressLogWidget()
        left_layout.addWidget(self._feedback_panel)
        
        root_layout.addWidget(left_col)

        # -- Column 2 (Right): Expanding -------------------------------------
        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(4, 0, 0, 0)

        self._preview_widget = PreviewWidget()
        right_layout.addWidget(self._preview_widget, stretch=2)

        self._sync_refinement = SyncRefinementWidget()
        right_layout.addWidget(self._sync_refinement, stretch=0)

        self._log_console = LogConsoleWidget()
        # Wire root logger to our console
        logging.getLogger().addHandler(self._log_console.log_handler)
        right_layout.addWidget(self._log_console, stretch=1)

        root_layout.addWidget(right_col, stretch=1)
        
        # Apply loaded settings to config panel
        if self._config.game_directory:
            self._config_panel.set_game_directory(str(self._config.game_directory))
        self._config_panel.set_video_quality(self._config.video_quality)

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
        self._action_panel.readjust_offset_requested.connect(self._on_readjust)
        self._action_panel.settings_requested.connect(self._on_settings)
        self._action_panel.reset_state_requested.connect(self._on_reset_state)

        # -- Sync refinement signals ----------------------------------------
        self._sync_refinement.preview_requested.connect(self._on_preview_toggle)
        self._sync_refinement.apply_requested.connect(self._on_apply_offset)
        self._sync_refinement.offset_changed.connect(self._on_offset_spin_changed)
        self._sync_refinement.pad_audio_requested.connect(self._on_pad_audio)

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
        self._save_settings()

    def _on_quality_changed(self, quality: str) -> None:
        self._config.video_quality = quality
        self._save_settings()

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
                self.append_log("Cache cleared.")
                self._set_status("Cache cleared.")
        else:
            self.append_log("No cache directory to clear.")

    # -- Actions ------------------------------------------------------------

    def _on_settings(self) -> None:
        from jd2021_installer.ui.widgets.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self._config, self)
        if dialog.exec():
            self._config = dialog.get_config()
            self._save_settings()
            self._config_panel.set_video_quality(self._config.video_quality)
            self._set_status("Settings saved.")

    def _on_readjust(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        from jd2021_installer.parsers.normalizer import normalize
        folder = QFileDialog.getExistingDirectory(self, "Select map output directory to readjust offset")
        if folder:
            try:
                map_data = normalize(folder)
                self._current_map = map_data
                self._current_target = folder
                self._sync_refinement.setVisible(True)
                vo = map_data.music_track.video_start_time
                self._sync_refinement.set_offsets(video_ms=vo)
                self.append_log(f"Loaded {map_data.codename} for offset readjustment.")
                self._set_status(f"Readjusting offset for {map_data.codename}")
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load map data:\n{e}")

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

        # Start dynamic per-map logging immediately if target is available
        self._start_file_logging(self._current_target)

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
        worker.status.connect(self.append_log)
        worker.error.connect(self._on_extract_error)
        worker.finished.connect(lambda data: self._on_extract_finished(data))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_thread(t, "extract"))

        self._active_threads.add(thread)
        self._active_worker = worker
        thread.start()

    def _on_extract_error(self, msg: str) -> None:
        self._feedback_panel.update_checklist_step("Extract map data", StepStatus.ERROR)
        self.append_log(f"ERROR: {msg}")
        self._lock_ui(False)
        self._stop_file_logging()

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
        worker.status.connect(self.append_log)
        worker.error.connect(self._on_install_error)
        worker.finished.connect(lambda ok: self._on_install_finished(ok))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_thread(t, "install"))

        self._active_threads.add(thread)
        self._active_worker = worker
        thread.start()

    def _on_install_error(self, msg: str) -> None:
        self._feedback_panel.update_checklist_step(
            "Install to game directory", StepStatus.ERROR
        )
        self.append_log(f"ERROR: {msg}")
        self._lock_ui(False)
        self._stop_file_logging()

    def _on_install_finished(self, success: bool) -> None:
        status = StepStatus.DONE if success else StepStatus.ERROR
        self._feedback_panel.update_checklist_step("Install to game directory", status)
        if success:
            self._set_status("Installation complete!")
            self.append_log("✅  Map installed successfully!")
        self._lock_ui(False)
        self._stop_file_logging()

    # ==================================================================
    # SYNC REFINEMENT / PREVIEW
    # ==================================================================

    def _on_preview_toggle(self, start: bool) -> None:
        """Start or stop the embedded FFmpeg preview."""
        if start:
            if self._current_map and self._current_map.media.video_path:
                video = str(self._current_map.media.video_path)
                audio = str(self._current_map.media.audio_path) if self._current_map.media.audio_path else None
                if not audio:
                    self.append_log("No audio available for preview.")
                    self._sync_refinement._btn_preview.setChecked(False)
                    return

                v_override = self._current_map.effective_video_start_time / 1000.0
                a_offset = self._sync_refinement._audio_spin.value() / 1000.0

                self._preview_widget.launch(
                    video, audio,
                    v_override=v_override,
                    a_offset=a_offset,
                )
            else:
                self.append_log("No video available for preview.")
                self._sync_refinement._btn_preview.setChecked(False)
        else:
            self._preview_widget.stop()

    def _on_offset_spin_changed(self, offset_ms: float) -> None:
        """Auto-restart preview when offsets change."""
        if self._preview_widget.is_playing and self._current_map and self._current_map.media.video_path:
            v_override = self._current_map.effective_video_start_time / 1000.0
            a_offset = self._sync_refinement._audio_spin.value() / 1000.0
            
            # Restart at current playback position
            self._preview_widget.launch(
                str(self._current_map.media.video_path),
                str(self._current_map.media.audio_path) if self._current_map.media.audio_path else None,
                v_override=v_override,
                a_offset=a_offset,
                start_time=self._preview_widget._position,
            )

    def _on_pad_audio(self) -> None:
        """Autofill Audio Offset by probing differences in media lengths."""
        if not self._current_map or not self._current_map.media.audio_path or not self._current_map.media.video_path:
            self.append_log("Both audio and video required to pad audio.")
            return

        from jd2021_installer.installers.media_processor import get_video_duration
        try:
            self.append_log("Probing media durations for Auto Pad...")
            v_dur = get_video_duration(self._current_map.media.video_path, self._config)
            a_dur = get_video_duration(self._current_map.media.audio_path, self._config)
            diff_ms = (v_dur - a_dur) * 1000.0
            
            self._sync_refinement.set_offsets(audio_ms=diff_ms, video_ms=self._sync_refinement._video_spin.value())
            self.append_log(f"Auto Pad Audio computed {diff_ms:+.1f} ms difference.")
        except Exception as e:
            self.append_log(f"Pad audio failed to compute duration: {e}")

    def _on_apply_offset(self, offset_ms: float) -> None:
        """Apply the combined offset to the current map data."""
        if self._current_map is None:
            QMessageBox.warning(self, "No Map", "Load a map before applying offsets.")
            return

        if not self._config.game_directory:
            QMessageBox.warning(self, "No Game Dir", "Cannot apply without a game directory set.")
            return

        # V2 native behavior: We modify the video_start_time_override directly.
        # This replaces V1's ffmpeg hard-padding logic, relying strictly on UbiArt configuration.
        # Note: offset_ms is in milliseconds; video_start_time is in seconds.
        original = self._current_map.music_track.video_start_time
        self._current_map.video_start_time_override = original + (offset_ms / 1000.0)

        worker = ApplyAndFinishWorker(
            map_data=self._current_map,
            target_dir=Path(self._config.game_directory),
            cache_dir=self._config.cache_directory,
            config=self._config,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.status.connect(self.append_log)
        worker.error.connect(lambda msg: self.append_log(f"ERROR: {msg}"))
        worker.finished.connect(self._on_offset_applied)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_thread(t, "apply_finish"))

        self._active_threads.add(thread)
        self._active_worker = worker
        thread.start()

    def _on_offset_applied(self, success: bool) -> None:
        if success and self._current_map:
            self._set_status(
                f"Offset applied & Map updated — effective start: "
                f"{self._current_map.effective_video_start_time:.2f} ms"
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
            from jd2021_installer.extractors.archive_ipk import ArchiveIPKExtractor

            ipk_path = Path(self._current_target)  # type: ignore[arg-type]
            if not ipk_path.is_file():
                QMessageBox.warning(self, "Invalid Path", f"IPK not found: {ipk_path}")
                return None
            return ArchiveIPKExtractor(ipk_path)

        if idx == MODE_FETCH:
            from jd2021_installer.extractors.web_playwright import WebPlaywrightExtractor

            return WebPlaywrightExtractor(
                codenames=[c.strip() for c in (self._current_target or "").split(",") if c.strip()],
                config=self._config,
                quality=self._config.video_quality,
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

    def _cleanup_thread(self, thread: QThread, label: str) -> None:
        logger.debug("Thread cleaned up: %s", label)
        if thread in self._active_threads:
            self._active_threads.remove(thread)
        self._active_worker = None

    def _start_file_logging(self, current_target: str) -> None:
        """Starts a dynamic FileHandler log for this installation."""
        if self._file_logger_handler:
            self._stop_file_logging()

        # Sanitize codename for filename
        codename = Path(current_target).name if current_target else "unknown"
        codename = "".join(c for c in codename if c.isalnum() or c in ("-", "_")).strip()

        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = logs_dir / f"install_{codename}_{timestamp}.log"
        
        self._file_logger_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        )
        self._file_logger_handler.setLevel(logging.DEBUG)
        self._file_logger_handler.setFormatter(file_fmt)
        logging.getLogger("jd2021").addHandler(self._file_logger_handler)

    def _stop_file_logging(self) -> None:
        """Removes the active FileHandler and cleanly closes handles."""
        if self._file_logger_handler:
            logging.getLogger("jd2021").removeHandler(self._file_logger_handler)
            self._file_logger_handler.close()
            self._file_logger_handler = None

    def _set_status(self, text: str) -> None:
        self._status_bar.showMessage(text)

    # -- Public convenience methods (kept for compatibility) ----------------

    def append_log(self, text: str) -> None:
        """Append text to the GUI log console."""
        self._log_console.append_log(text)

    def set_progress(self, value: int) -> None:
        """Set the progress bar value (delegated to ProgressLogWidget)."""
        self._feedback_panel.set_progress(value)

    def set_status(self, text: str) -> None:
        """Update the status bar message."""
        self._set_status(text)
