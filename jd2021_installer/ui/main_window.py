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

# Granular checklist steps (V1 Parity)
PIPELINE_STEPS = [
    "Extract map data",
    "Parse CKDs & Metadata",
    "Normalize assets",
    "Decode XMA2 Audio",
    "Convert Audio (Pad/Trim)",
    "Generate Intro AMB",
    "Copy Video files",
    "Convert Dance Tapes",
    "Convert Karaoke Tapes",
    "Convert Cinematic Tapes",
    "Process Ambient Sounds",
    "Decode MenuArt textures",
    "Decode Pictograms",
    "Integrate Move data",
    "Register in SkuScene",
    "Finalizing Offsets",
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

        # Phase 4: Multi-map navigation
        self._nav_maps: list[NormalizedMapData] = []
        self._nav_index: int = 0

        # -- Window setup -----------------------------------------------------
        self.setWindowTitle("JD2021 Map Installer v2")
        self.setMinimumSize(1060, 800)

        self._build_ui()
        self._wire_signals()

        # Phase 4.4 Quickstart
        if self._config.show_quickstart_on_launch:
            from jd2021_installer.ui.widgets.quickstart_dialog import QuickstartDialog
            dont_show_again = QuickstartDialog.show_guide(self)
            if dont_show_again:
                self._config.show_quickstart_on_launch = False
                self._save_settings()

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

        # Show Quickstart Guide if needed
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, self._show_quickstart_if_needed)

    def closeEvent(self, event) -> None:
        """Ensure all background processes (especially ffplay) are stopped."""
        logger.info("Closing application. Cleaning up...")
        self._preview_widget.stop()
        
        # Give threads a moment to finish, but don't hang if they are stuck
        for thread in list(self._active_threads):
            if thread.isRunning():
                thread.quit()
                thread.wait(1000)
        
        self._save_settings()
        event.accept()

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

    def _show_quickstart_if_needed(self) -> None:
        # Check config (we'll need to add a flag to AppConfig or settings)
        # For now, let's just check if a certain file exists or dummy logic
        if not getattr(self._config, "skip_quickstart", False):
            from jd2021_installer.ui.widgets.quickstart_dialog import QuickstartDialog
            dont_show_again = QuickstartDialog.show_guide(self)
            if dont_show_again:
                self._config.skip_quickstart = True
                self._save_settings()

    def _offer_ffmpeg_install(self, missing: list[str]) -> None:
        """Prompt user to auto-download and install FFmpeg/FFplay."""
        msg = (
            f"The following required tools were not found: {', '.join(missing)}\n\n"
            "Would you like the installer to automatically download and configure "
            "FFmpeg for you? (Requires Internet connection)"
        )
        reply = QMessageBox.question(
            self, "Missing Dependencies", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            from jd2021_installer.ui.widgets.ffmpeg_dialog import FFmpegInstallDialog
            # Ensure tools/ffmpeg exists
            tools_dir = Path("tools/ffmpeg")
            tools_dir.mkdir(parents=True, exist_ok=True)
            
            if FFmpegInstallDialog.install(tools_dir, self):
                # Update config and save
                ffmpeg_exe = tools_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
                self._config.ffmpeg_path = str(ffmpeg_exe)
                self._save_settings()
                QMessageBox.information(self, "Success", "FFmpeg has been installed successfully.")
            else:
                QMessageBox.warning(self, "Failed", "FFmpeg installation was cancelled or failed.")

    # ==================================================================
    # UI COMPOSITION  (Phase 3)
    # ==================================================================

    def resizeEvent(self, event) -> None:
        """Handle window resize by restarting/scaling the preview if active."""
        super().resizeEvent(event)
        if hasattr(self, "_preview_widget") and self._preview_widget.is_playing:
            # Re-trigger preview with current offsets to pick up new dimensions
            self._restart_preview_now()

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
        else:
            from jd2021_installer.core.path_discovery import resolve_game_paths
            from pathlib import Path
            cand = resolve_game_paths(Path.cwd())
            if cand:
                self._config.game_directory = cand
                self._config_panel.set_game_directory(str(cand))
                
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
        self._sync_refinement.nav_requested.connect(self._on_nav_requested)
        
        # -- Preview widget signals -----------------------------------------
        self._preview_widget.preview_stopped.connect(
            lambda: self._sync_refinement.set_preview_state(False)
        )

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
            # Safety check: don't delete if cache is inside game directory (prevents accidental wipeout)
            if self._config.game_directory and (
                self._config.game_directory in cache.parents or 
                self._config.game_directory == cache
            ):
                QMessageBox.critical(self, "Safety Error", "Cache directory cannot be inside or equal to the game directory.")
                return

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
                
                # Use calculated offsets from Normalizer
                logger.info("Readjust: setting UI offsets: audio=%.1f, video=%.1f", 
                            map_data.sync.audio_ms, map_data.sync.video_ms)
                self._sync_refinement.set_offsets(
                    audio_ms=map_data.sync.audio_ms, 
                    video_ms=map_data.sync.video_ms
                )
                
                is_ipk = bool(map_data.media.audio_path and map_data.media.audio_path.suffix.lower() == ".wav")
                self._sync_refinement.set_ipk_mode(is_ipk=is_ipk)
                
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

        # Pre-flight check for FFmpeg/FFplay (required for media + preview)
        import shutil
        missing_binaries = []
        if not shutil.which(self._config.ffmpeg_path):
            missing_binaries.append("ffmpeg")
        # Ensure ffplay is present for preview features
        if not shutil.which("ffplay") and not shutil.which(self._config.ffmpeg_path.replace("ffmpeg", "ffplay")):
            missing_binaries.append("ffplay")
            
        if missing_binaries:
            self._offer_ffmpeg_install(missing_binaries)
            return

        # Pre-flight check for disk space (Minimum 500MB required on target drive)
        try:
            free_space_bytes = shutil.disk_usage(self._config.game_directory).free
            free_mb = free_space_bytes / (1024 * 1024)
            if free_mb < 500:
                QMessageBox.warning(
                    self,
                    "Low Disk Space",
                    f"You only have {int(free_mb)} MB of free space on the destination drive.\n"
                    "Map installation may fail. Proceed with caution."
                )
        except OSError:
            pass  # Non-fatal if we can't look up disk space (e.g. read-only volume edge cases)

        # Start dynamic per-map logging immediately if target is available
        self._start_file_logging(self._current_target)

        # Intercept batch mode - it has a completely different pipeline structure
        from jd2021_installer.ui.widgets.mode_selector import MODE_BATCH
        if self._mode_selector.current_mode_index == MODE_BATCH:
            self._start_batch_install()
            return

        # Bundle IPK support
        from jd2021_installer.ui.widgets.mode_selector import MODE_IPK
        if self._mode_selector.current_mode_index == MODE_IPK and Path(self._current_target).is_file():
            from jd2021_installer.extractors.archive_ipk import inspect_ipk
            maps_found = inspect_ipk(self._current_target)
            if len(maps_found) > 1:
                from jd2021_installer.ui.widgets.bundle_dialog import BundleSelectDialog
                selected_maps = BundleSelectDialog.show_dialog(Path(self._current_target).name, maps_found, self)
                if not selected_maps:
                    return # User cancelled
                
                # Defer to batch installer to handle everything cleanly
                self._sync_refinement.set_ipk_mode(is_ipk=True)
                self._start_batch_install(selected_maps=set(selected_maps), map_names=sorted(list(selected_maps)))
                return

        # Resolve the correct extractor based on mode
        from jd2021_installer.ui.widgets.mode_selector import MODE_IPK
        is_ipk = self._mode_selector.current_mode_index == MODE_IPK
        self._sync_refinement.set_ipk_mode(is_ipk=is_ipk)

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
            output_dir=self._config.temp_directory / "_extraction",
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
        self._feedback_panel.update_checklist_step("Parse CKDs & Metadata", StepStatus.DONE)
        self._feedback_panel.update_checklist_step("Normalize assets", StepStatus.DONE)
        self._feedback_panel.update_checklist_step(
            "Decode XMA2 Audio", StepStatus.IN_PROGRESS
        )

        # Update UI offsets from calculated normalization data
        logger.info("Setting UI offsets from normalization: audio=%.1f ms, video=%.1f ms", 
                    map_data.sync.audio_ms, map_data.sync.video_ms)
        self._sync_refinement.set_offsets(
            audio_ms=map_data.sync.audio_ms,
            video_ms=map_data.sync.video_ms
        )

        # JDU/Fetch/HTML mode parity: Visually disable video offset but keep value applied
        is_fetch = "Fetch" in self._current_mode or "HTML" in self._current_mode
        self._sync_refinement.set_video_editable(not is_fetch)

        # Check metadata for non-ASCII characters
        self._check_metadata(map_data)
        
        # Start install worker
        self._start_install_worker(map_data)

    def _check_metadata(self, map_data: NormalizedMapData) -> None:
        """Verify song metadata fields and prompt for correction if non-ASCII found."""
        fields_to_check = {
            "title": map_data.song_desc.title,
            "artist": map_data.song_desc.artist,
            "dancer_name": map_data.song_desc.dancer_name,
        }
        
        from jd2021_installer.ui.widgets.metadata_dialog import MetadataCorrectionDialog
        
        for field, value in fields_to_check.items():
            if any(ord(c) > 127 for c in value):
                corrected = MetadataCorrectionDialog.get_corrected_value(field, value, self)
                if field == "title": map_data.song_desc.title = corrected
                elif field == "artist": map_data.song_desc.artist = corrected
                elif field == "dancer_name": map_data.song_desc.dancer_name = corrected

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
        worker.status.connect(self._on_status_updated)
        worker.error.connect(self._on_install_error)
        worker.finished.connect(lambda ok: self._on_install_finished(ok))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_thread(t, "install"))

        self._active_threads.add(thread)
        self._active_worker = worker
        thread.start()

    def _on_status_updated(self, msg: str) -> None:
        """Map backend status messages to checklist steps for visual feedback."""
        # Main log console still gets everything
        logger.info(msg)
        
        # Fix for Batch mode status strings e.g. "[1/10] Normalize assets (Koi)" or "[Koi] Extract map data"
        clean_msg = msg
        prefix = ""
        if msg.startswith("[") and "]" in msg:
            try:
                # Extract [Codename] prefix if it exists
                parts = msg.split("]", 1)
                prefix = parts[0][1:].strip()
                step_part = parts[1].strip()
                
                # If prefix is a number (e.g. 1/10), it's the old format
                if "/" in prefix and prefix.replace("/", "").isdigit():
                    prefix = f"[{prefix}]"
                else:
                    # It's likely a codename
                    prefix = f"[{prefix}]"
                
                if "(" in step_part:
                    step_part = step_part.split("(", 1)[0].strip()
                clean_msg = step_part
            except Exception:
                pass

        if clean_msg in PIPELINE_STEPS:
            # If in batch mode, we might be updating by map name instead of step name
            # Check if prefix (without brackets) is a known map in the checklist
            raw_prefix = prefix.strip("[]")
            if raw_prefix in self._feedback_panel._step_items:
                self._feedback_panel.update_checklist_step(raw_prefix, StepStatus.IN_PROGRESS, suffix=clean_msg)
            else:
                # Standard single-map step update
                self._feedback_panel.update_checklist_step(clean_msg, StepStatus.IN_PROGRESS, prefix=prefix)
            
            # Heuristic: Mark ALL preceding steps as DONE (only for single-map mode).
            if raw_prefix not in self._feedback_panel._step_items:
                try:
                    idx = PIPELINE_STEPS.index(clean_msg)
                    for i in range(idx):
                        self._feedback_panel.update_checklist_step(PIPELINE_STEPS[i], StepStatus.DONE, prefix=prefix)
                except ValueError:
                    pass
        elif prefix.strip("[]") in self._feedback_panel._step_items:
            # High-level status for a map in batch mode
            self._feedback_panel.update_checklist_step(prefix.strip("[]"), StepStatus.IN_PROGRESS, suffix=clean_msg)

    def _on_install_error(self, msg: str) -> None:
        self.append_log(f"ERROR: {msg}")
        self._lock_ui(False)
        self._stop_file_logging()

    def _on_install_finished(self, success: bool) -> None:
        if success:
            self._feedback_panel.update_checklist_step("Finalizing Offsets", StepStatus.DONE)
            self._set_status("Installation complete!")
            self.append_log("✅  Map installed successfully!")

            # If we don't have a nav list yet (single install), set current as the only one
            if not self._nav_maps and self._current_map:
                self._nav_maps = [self._current_map]
                self._nav_index = 0
                self._sync_refinement.set_nav_visible(False)

                # Ensure the sync panel reflects the current map's calculated offsets
                logger.info("Installation finished. Syncing UI offsets: audio=%.1f ms, video=%.1f ms", 
                            self._current_map.sync.audio_ms, self._current_map.sync.video_ms)
                self._sync_refinement.set_offsets(
                    self._current_map.sync.audio_ms,
                    self._current_map.sync.video_ms
                )

                # Check if IPK mode based on audio file type
                is_ipk = bool(self._current_map.media.audio_path and self._current_map.media.audio_path.suffix.lower() == ".wav")
                self._sync_refinement.set_ipk_mode(is_ipk=is_ipk)

            # Start preview for the current map
            if self._current_map:
                self._on_preview_toggle(True)
        self._lock_ui(False)
        self._stop_file_logging()

    def _on_batch_finished_with_data(self, installed_maps: list[NormalizedMapData]) -> None:
        """Called when a batch install completes with a list of map data."""
        if not installed_maps:
            return
        
        self._nav_maps = installed_maps
        self._nav_index = 0
        self._current_map = self._nav_maps[0]
        
        # Show nav controls if multiple maps
        if len(self._nav_maps) > 1:
            self._sync_refinement.set_nav_visible(True, f"Map 1 / {len(self._nav_maps)}")
            self.append_log(f"Multi-map review: {len(self._nav_maps)} maps ready for offset adjustment.")
        else:
            self._sync_refinement.set_nav_visible(False)
            
        # Preview the first map
        logger.info("Batch finished: setting UI offsets for first map: audio=%.1f, video=%.1f", 
                    self._current_map.sync.audio_ms, self._current_map.sync.video_ms)
        self._sync_refinement.set_offsets(
            self._current_map.sync.audio_ms,
            self._current_map.sync.video_ms
        )
        self._on_preview_toggle(True)

    def _on_nav_requested(self, direction: int) -> None:
        """Switch between maps in a batch/bundle review."""
        if not self._nav_maps:
            return
            
        new_index = self._nav_index + direction
        if 0 <= new_index < len(self._nav_maps):
            # Stop current preview
            self._on_preview_toggle(False)
            
            self._nav_index = new_index
            self._current_map = self._nav_maps[self._nav_index]
            
            # Update UI
            self._sync_refinement.set_nav_visible(True, f"Map {new_index + 1} / {len(self._nav_maps)}")
            self.append_log(f"Switched to: {self._current_map.codename}")
            
            # Update UI offsets
            logger.info("Nav requested: setting UI offsets: audio=%.1f, video=%.1f", 
                        self._current_map.sync.audio_ms, self._current_map.sync.video_ms)
            self._sync_refinement.set_offsets(
                self._current_map.sync.audio_ms,
                self._current_map.sync.video_ms
            )
            
            # Start preview for the new map
            self._on_preview_toggle(True)

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
                    self._sync_refinement.set_preview_state(False)
                    return

                v_override = self._current_map.effective_video_start_time
                a_offset = self._sync_refinement._audio_spin.value() / 1000.0
                
                logger.debug("Preview launch: v_override=%.3f, a_offset=%.3f", v_override, a_offset)

                self._preview_widget.launch(
                    video, audio,
                    v_override=v_override,
                    a_offset=a_offset,
                )
            else:
                self.append_log("No video available for preview.")
                self._sync_refinement.set_preview_state(False)
        else:
            self._preview_widget.stop()

    def _on_offset_spin_changed(self, offset_ms: float) -> None:
        """Debounced preview restart when offsets change."""
        if not self._preview_widget.is_playing:
            return
            
        # Debounce to prevent spam-launching ffplay while rapid clicking
        from PyQt6.QtCore import QTimer
        if not hasattr(self, "_preview_debounce_timer"):
            self._preview_debounce_timer = QTimer(self)
            self._preview_debounce_timer.setSingleShot(True)
            self._preview_debounce_timer.timeout.connect(self._restart_preview_now)
        
        self._preview_debounce_timer.start(500) # 0.5s delay

    def _restart_preview_now(self) -> None:
        if self._current_map and self._current_map.media.video_path:
            v_override = self._current_map.effective_video_start_time
            a_offset = self._sync_refinement._audio_spin.value() / 1000.0
            
            logger.debug("Debounced preview restart...")
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

    def _on_apply_offset(self, audio_ms: float, video_ms: float) -> None:
        """Apply the combined offset to the current map data."""
        if self._current_map is None:
            QMessageBox.warning(self, "No Map", "Load a map before applying offsets.")
            return

        # V1 Parity: Stop preview and DON'T restart it
        self._preview_widget.stop()
        self._sync_refinement.set_preview_state(False)

        if not self._config.game_directory:
            QMessageBox.warning(self, "No Game Dir", "Cannot apply without a game directory set.")
            return

        # 1. Update videoStartTime override (in seconds)
        original_v = self._current_map.music_track.video_start_time
        self._current_map.video_start_time_override = original_v + (video_ms / 1000.0)

        # 2. Launch worker to rewrite configs and reprocess audio
        from jd2021_installer.ui.workers.pipeline_workers import ApplyAndFinishWorker
        
        base_game_dir = self._config.game_directory
        while base_game_dir.name.lower() in ("world", "data"):
            base_game_dir = base_game_dir.parent
            
        worker = ApplyAndFinishWorker(
            self._current_map,
            base_game_dir / "data" / "World" / "MAPS" / self._current_map.codename,
            self._config.cache_directory / self._current_map.codename,
            a_offset=audio_ms / 1000.0,
            config=self._config,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.status.connect(self._on_status_updated)
        worker.error.connect(self._on_install_error)
        worker.finished.connect(self._on_reprocess_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_thread(t, "apply_finish"))

        self._active_threads.add(thread)
        self._active_worker = worker
        thread.start()

    def _on_reprocess_finished(self, success: bool) -> None:
        self._lock_ui(False)
        if success:
            logger.info("✅  Offsets applied and audio reprocessed.")
            self._feedback_panel.update_checklist_step("Finalizing Offsets", StepStatus.DONE)
            # V1 Parity: Don't auto-restart preview anymore after apply
            self._prompt_cleanup()

    def _prompt_cleanup(self) -> None:
        """Ask user or auto-delete source files based on cleanup_behavior."""
        if not self._current_map:
            return
            
        # 1. Check if we should skip (batch mid-review)
        if len(self._nav_maps) > 1 and self._nav_index < len(self._nav_maps) - 1:
            return # Don't prompt yet
            
        behavior = self._config.cleanup_behavior
        should_delete = False
        
        if behavior == "delete":
            should_delete = True
        elif behavior == "keep":
            should_delete = False
        else: # behavior == "ask"
            reply = QMessageBox.question(
                self,
                "Cleanup Source Files?",
                "The installation and sync are complete.\n\n"
                "Would you like to delete the temporary downloaded/extracted source files to save space?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            should_delete = (reply == QMessageBox.StandardButton.Yes)
        
        if should_delete:
            self._do_cleanup()

    def _do_cleanup(self) -> None:
        """Perform actual deletion of temporary files."""
        self.append_log("Cleaning up source files...")
        try:
            # 1. Clean up _extraction temp
            temp_dir = self._config.temp_directory / "_extraction"
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            # 2. Clean up _batch_temp if it exists
            batch_temp = self._config.cache_directory / "_batch_temp"
            if batch_temp.exists():
                import shutil
                shutil.rmtree(batch_temp, ignore_errors=True)
            
            self.append_log("✅  Source files cleaned up.")
        except Exception as e:
            self.append_log(f"Warning: Cleanup failed ({e})")

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

        if idx == MODE_HTML:
            from jd2021_installer.extractors.web_playwright import WebPlaywrightExtractor
            
            asset_html = self._mode_selector.inputs["html"]["asset"].text()
            nohud_html = self._mode_selector.inputs["html"]["nohud"].text()
            
            if not asset_html and not nohud_html:
                QMessageBox.warning(self, "Missing Files", "Please select at least one HTML file.")
                return None

            return WebPlaywrightExtractor(
                asset_html=asset_html,
                nohud_html=nohud_html,
                config=self._config,
                quality=self._config.video_quality,
            )

        if idx == MODE_MANUAL:
            from jd2021_installer.extractors.manual_extractor import ManualExtractor
            inputs = self._mode_selector.inputs["manual"]
            codename = inputs["codename"].text().strip()
            root_dir = inputs["root"].text().strip()
            
            if not codename and not root_dir:
                QMessageBox.warning(self, "Missing Data", "Codename or Root Directory is required for Manual mode.")
                return None
                
            return ManualExtractor(
                codename=codename,
                root_dir=root_dir,
                files={
                    "audio": inputs["audio"].text().strip(),
                    "video": inputs["video"].text().strip(),
                    "mtrack": inputs["mtrack"].text().strip(),
                    "sdesc": inputs["sdesc"].text().strip(),
                    "dtape": inputs["dtape"].text().strip(),
                    "ktape": inputs["ktape"].text().strip(),
                    "mseq": inputs["mseq"].text().strip(),
                },
                dirs={
                    "moves": inputs["moves"].text().strip(),
                    "pictos": inputs["pictos"].text().strip(),
                    "menuart": inputs["menuart"].text().strip(),
                    "amb": inputs["amb"].text().strip(),
                }
            )

        # Mode not implemented yet
        QMessageBox.information(
            self,
            "Not Implemented",
            f"The '{self._current_mode}' mode is not yet fully implemented.",
        )
        return None

    def _start_batch_install(self, selected_maps: set[str] | None = None, map_names: list[str] | None = None) -> None:
        """Launches the dedicated Batch mode worker."""
        if not self._current_target:
            return
            
        from jd2021_installer.ui.workers.pipeline_workers import BatchInstallWorker

        self._lock_ui(True)
        self._feedback_panel.reset()
        if map_names:
            self._feedback_panel.set_checklist_steps(map_names)
        else:
            self._feedback_panel.set_checklist_steps(PIPELINE_STEPS)
            self._feedback_panel.update_checklist_step("Extract map data", StepStatus.IN_PROGRESS)

        worker = BatchInstallWorker(
            batch_source_dir=Path(self._current_target),
            target_game_dir=self._config.game_directory, # type: ignore[arg-type]
            config=self._config,
            selected_maps=selected_maps,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._feedback_panel.set_progress)
        worker.status.connect(self.append_log)
        worker.status.connect(self._on_status_updated)
        worker.discovered_maps.connect(self._feedback_panel.set_checklist_steps)
        
        # Share the error and success callbacks so the UI gets unlocked
        worker.error.connect(self._on_install_error)
        worker.finished_with_data.connect(self._on_batch_finished_with_data)
        worker.finished.connect(self._on_install_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_thread(t, "batch"))

        self._active_threads.add(thread)
        self._active_worker = worker
        thread.start()

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
