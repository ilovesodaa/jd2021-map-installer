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
import re
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
    ApplyOffsetsBatchWorker,
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
        self._preview_audio_warning_shown = False

        # Phase 4: Multi-map navigation
        self._nav_maps: list[NormalizedMapData] = []
        self._nav_index: int = 0
        self._pending_offsets: dict[str, tuple[float, float]] = {}

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
        self._set_preview_controls_ready(False)

    # ==================================================================
    # SIGNAL / SLOT WIRING  (Phase 4)
    # ==================================================================

    def _wire_signals(self) -> None:
        # -- Mode & config signals ------------------------------------------
        self._mode_selector.mode_changed.connect(self._on_mode_changed)
        self._mode_selector.target_selected.connect(self._on_target_selected)
        self._config_panel.game_dir_changed.connect(self._on_game_dir_changed)
        self._config_panel.quality_changed.connect(self._on_quality_changed)
        self._config_panel.clear_cache_requested.connect(self._on_clear_cache)

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
        self._preview_widget.audio_unavailable.connect(self._on_preview_audio_unavailable)

    # ==================================================================
    # SLOT IMPLEMENTATIONS
    # ==================================================================

    # -- Config / mode slots ------------------------------------------------

    def _on_mode_changed(self, mode: str) -> None:
        self._current_mode = mode
        # Prevent stale targets from a previous mode from passing install checks.
        self._current_target = None
        self._set_preview_controls_ready(False)
        self._set_status(f"Mode: {mode}")

    def _on_target_selected(self, target: str) -> None:
        self._current_target = target
        logger.debug("Target selected: %s", target)
        self._set_preview_controls_ready(False)

    def _on_game_dir_changed(self, path: str) -> None:
        self._config.game_directory = Path(path)
        self._set_status(f"Game directory: {path}")
        self._save_settings()

    def _on_quality_changed(self, quality: str) -> None:
        self._config.video_quality = quality
        self._save_settings()

    def _collect_game_dir_checks(self) -> tuple[list[str], list[str]]:
        """Return (blocking issues, non-blocking warnings) for game dir checks."""
        issues: list[str] = []
        warnings: list[str] = []
        game_dir = self._config.game_directory

        if not game_dir:
            issues.append("Game directory is not set.")
            return issues, warnings

        if not game_dir.is_dir():
            issues.append(f"Game directory does not exist: {game_dir}")
            return issues, warnings

        sku_scene = game_dir / "data" / "World" / "SkuScenes" / "SkuScene_Maps_PC_All.isc"
        if not sku_scene.is_file():
            issues.append(
                "SkuScene_Maps_PC_All.isc not found under the selected game directory."
            )

        game_dir_str = str(game_dir)
        if " " in game_dir_str:
            warnings.append("Game path contains spaces; some external tools may fail.")
        try:
            game_dir_str.encode("ascii")
        except UnicodeEncodeError:
            warnings.append("Game path contains non-ASCII characters; some tools may fail.")
        if "Program Files" in game_dir_str:
            warnings.append("Game appears to be in Program Files; admin rights may be required.")

        test_file = game_dir / "data" / ".write_test"
        try:
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("test", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        except PermissionError:
            issues.append("Cannot write to game directory; check permissions or run as admin.")
        except OSError as exc:
            issues.append(f"Cannot write to game directory: {exc}")

        try:
            free_mb = shutil.disk_usage(game_dir).free // (1024 * 1024)
            if free_mb < 500:
                warnings.append(f"Low disk space on destination drive: {free_mb} MB free.")
        except OSError:
            warnings.append("Could not determine free disk space.")

        return issues, warnings

    def _collect_source_target_issues(self) -> list[str]:
        """Validate mode-specific source inputs and refresh the active target."""
        issues: list[str] = []
        from jd2021_installer.ui.widgets.mode_selector import (
            MODE_FETCH,
            MODE_HTML,
            MODE_IPK,
            MODE_BATCH,
            MODE_MANUAL,
        )

        idx = self._mode_selector.current_mode_index

        if idx == MODE_FETCH:
            raw = self._mode_selector.inputs["fetch"]["codenames"].text().strip()
            codenames = [c.strip() for c in raw.split(",") if c.strip()]
            if not codenames:
                issues.append("Enter at least one codename for Fetch mode.")
            else:
                self._current_target = ",".join(codenames)
            return issues

        if idx == MODE_HTML:
            asset_html = self._mode_selector.inputs["html"]["asset"].text().strip()
            nohud_html = self._mode_selector.inputs["html"]["nohud"].text().strip()
            if not asset_html or not nohud_html:
                issues.append("Both Asset HTML and NOHUD HTML files are required.")
                return issues
            if not Path(asset_html).is_file():
                issues.append(f"Asset HTML file was not found: {asset_html}")
            if not Path(nohud_html).is_file():
                issues.append(f"NOHUD HTML file was not found: {nohud_html}")
            if not issues:
                self._current_target = asset_html
            return issues

        if idx == MODE_IPK:
            target = self._mode_selector.inputs["ipk"]["file"].text().strip()
            if not target:
                issues.append("Select an IPK archive first.")
            elif not Path(target).is_file():
                issues.append(f"IPK file was not found: {target}")
            else:
                self._current_target = target
            return issues

        if idx == MODE_BATCH:
            target = self._mode_selector.inputs["batch"]["dir"].text().strip()
            if not target:
                issues.append("Select a batch directory first.")
            elif not Path(target).is_dir():
                issues.append(f"Batch directory was not found: {target}")
            else:
                self._current_target = target
            return issues

        if idx == MODE_MANUAL:
            manual_inputs = self._mode_selector.inputs["manual"]
            codename = manual_inputs["codename"].text().strip()
            root_dir = manual_inputs["root"].text().strip()
            if not codename and not root_dir:
                issues.append("Manual mode requires a codename or a root directory.")
                return issues

            if root_dir and not Path(root_dir).is_dir():
                issues.append(f"Manual root directory was not found: {root_dir}")

            required_files = [
                ("audio", "Audio file is required."),
                ("video", "Video file (.webm) is required."),
                ("mtrack", "Musictrack CKD is required (fatal for config generation)."),
            ]
            for key, missing_msg in required_files:
                value = manual_inputs[key].text().strip()
                if not value:
                    issues.append(missing_msg)
                    continue
                if not Path(value).is_file():
                    issues.append(f"Manual {key} file was not found: {value}")

            if not issues:
                self._current_target = root_dir or codename
            return issues

        if not self._current_target:
            issues.append("No input target selected.")
        return issues

    # -- Pre-flight ---------------------------------------------------------

    def _on_preflight(self) -> None:
        """Run install pre-flight checks (V1 parity-oriented validations)."""
        issues, warnings = self._collect_game_dir_checks()
        issues.extend(self._collect_source_target_issues())

        if issues:
            QMessageBox.warning(
                self,
                "Pre-flight Check Failed",
                "\n".join(f"• {i}" for i in issues),
            )
            self._set_status("Pre-flight failed")
            return

        if warnings:
            QMessageBox.warning(
                self,
                "Pre-flight Check Warnings",
                "\n".join(f"• {w}" for w in warnings),
            )
            self._set_status("Pre-flight passed with warnings")
        else:
            if self._config.show_preflight_success_popup:
                QMessageBox.information(
                    self, "Pre-flight Check", "All checks passed! Ready to install."
                )
            self._set_status("Pre-flight passed")

    # -- Clear cache --------------------------------------------------------

    def _on_clear_cache(self) -> None:
        legacy_path_cache = Path("installer_paths.json")
        has_saved_game_dir = bool(self._config.game_directory)
        has_legacy_cache = legacy_path_cache.is_file()

        if not has_saved_game_dir and not has_legacy_cache:
            QMessageBox.information(self, "Cache Already Empty", "No cached game path was found.")
            return

        reply = QMessageBox.question(
            self,
            "Clear Path Cache",
            "Clear saved game path cache and force path re-discovery on next install/pre-flight?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if has_legacy_cache:
                legacy_path_cache.unlink(missing_ok=True)

            self._config.game_directory = None
            self._config_panel.set_game_directory("")
            self._save_settings()

            self.append_log("Path cache cleared.")
            self._set_status("Path cache cleared")
            QMessageBox.information(
                self,
                "Cache Cleared",
                "Path cache cleared. The next pre-flight/install will require path resolution again.",
            )
        except Exception as exc:
            logger.exception("Failed to clear cache: %s", exc)
            QMessageBox.warning(self, "Clear Cache Failed", f"Failed to clear cache:\n{exc}")

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
                self._set_preview_controls_ready(True)
                
                self.append_log(f"Loaded {map_data.codename} for offset readjustment.")
                self._set_status(f"Readjusting offset for {map_data.codename}")
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load map data:\n{e}")

    # -- Reset state --------------------------------------------------------

    def _on_reset_state(self) -> None:
        self._current_map = None
        self._current_target = None
        self._nav_maps = []
        self._nav_index = 0
        self._pending_offsets.clear()
        self._sync_refinement.reset()
        self._preview_widget.reset()
        self._set_preview_controls_ready(False)
        self._feedback_panel.reset()
        self._set_status("State reset.")

    # ==================================================================
    # PIPELINE EXECUTION  (Install flow)
    # ==================================================================

    def _on_install_requested(self) -> None:
        """Launch the Extract → Normalize → Install pipeline."""
        game_issues, game_warnings = self._collect_game_dir_checks()
        if game_issues:
            QMessageBox.warning(self, "No Game Dir", "\n".join(game_issues))
            return

        # v1 parity: codename whitespace sanitization prompt before fetch scrape starts.
        from jd2021_installer.ui.widgets.mode_selector import MODE_FETCH
        if self._mode_selector.current_mode_index == MODE_FETCH:
            raw_value = self._mode_selector.inputs["fetch"]["codenames"].text()
            if re.search(r"\s", raw_value):
                sanitized = re.sub(r"\s+", "", raw_value)
                reply = QMessageBox.question(
                    self,
                    "Sanitize Codename",
                    (
                        "The codename contains whitespace.\n\n"
                        f"Current: {raw_value}\n"
                        f"Sanitized: {sanitized}\n\n"
                        "Use sanitized codename and continue?"
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._mode_selector.inputs["fetch"]["codenames"].setText(sanitized)
                    self._current_target = sanitized
                else:
                    self.append_log("Install aborted: codename sanitization declined.")
                    self._set_status("Install aborted")
                    return

        source_issues = self._collect_source_target_issues()
        if source_issues:
            QMessageBox.warning(self, "No Target", "\n".join(source_issues))
            return

        if game_warnings:
            QMessageBox.warning(
                self,
                "Install Warnings",
                "\n".join(f"• {w}" for w in game_warnings),
            )

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
            from jd2021_installer.extractors.archive_ipk import validate_ipk_magic
            try:
                validate_ipk_magic(self._current_target)
            except Exception as exc:
                QMessageBox.critical(self, "Invalid IPK", f"Could not open IPK archive:\n{exc}")
                return

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

    def _on_extract_error(self, stage: str, msg: str) -> None:
        failed_stage = stage if stage in PIPELINE_STEPS else "Extract map data"
        self._feedback_panel.update_checklist_step(failed_stage, StepStatus.ERROR)
        self.append_log(f"ERROR: {msg}")
        QMessageBox.critical(
            self,
            "Pipeline Error",
            f"{failed_stage} failed:\n{msg}",
        )
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
        QMessageBox.critical(
            self,
            "Pipeline Error",
            f"Installation failed:\n{msg}",
        )
        self._set_preview_controls_ready(False)
        self._lock_ui(False)
        self._stop_file_logging()

    def _on_install_finished(self, success: bool) -> None:
        if success:
            if "Finalizing Offsets" in self._feedback_panel._step_items:
                self._feedback_panel.update_checklist_step("Finalizing Offsets", StepStatus.DONE)
            self._set_status("Installation complete!")
            self.append_log("✅  Map installed successfully!")

            # If we don't have a nav list yet (single install), set current as the only one
            if not self._nav_maps and self._current_map:
                self._nav_maps = [self._current_map]
                self._nav_index = 0
                self._pending_offsets[self._current_map.codename] = (
                    self._current_map.sync.audio_ms,
                    self._current_map.sync.video_ms,
                )
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
                self._set_preview_controls_ready(True)
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
        self._pending_offsets = {
            m.codename: (m.sync.audio_ms, m.sync.video_ms) for m in self._nav_maps
        }
        
        # Show nav controls if multiple maps
        if len(self._nav_maps) > 1:
            self._sync_refinement.set_nav_visible(True, f"Map 1 / {len(self._nav_maps)}")
            self.append_log(f"Multi-map review: {len(self._nav_maps)} maps ready for offset adjustment.")
        else:
            self._sync_refinement.set_nav_visible(False)
            
        # Preview the first map
        logger.info("Batch finished: setting UI offsets for first map: audio=%.1f, video=%.1f", 
                    self._current_map.sync.audio_ms, self._current_map.sync.video_ms)
        first_audio_ms, first_video_ms = self._pending_offsets.get(
            self._current_map.codename,
            (self._current_map.sync.audio_ms, self._current_map.sync.video_ms),
        )
        self._sync_refinement.set_offsets(
            first_audio_ms,
            first_video_ms,
        )
        self._set_preview_controls_ready(True)
        self._on_preview_toggle(True)

    def _on_nav_requested(self, direction: int) -> None:
        """Switch between maps in a batch/bundle review."""
        if not self._nav_maps:
            return

        # Preserve current map edits before switching.
        if self._current_map is not None:
            self._pending_offsets[self._current_map.codename] = (
                self._sync_refinement._audio_spin.value(),
                self._sync_refinement._video_spin.value(),
            )
            
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
            audio_ms, video_ms = self._pending_offsets.get(
                self._current_map.codename,
                (self._current_map.sync.audio_ms, self._current_map.sync.video_ms),
            )
            self._sync_refinement.set_offsets(
                audio_ms,
                video_ms,
            )
            
            # Start preview for the new map
            self._on_preview_toggle(True)

    # ==================================================================
    # SYNC REFINEMENT / PREVIEW
    # ==================================================================

    def _on_preview_toggle(self, start: bool) -> None:
        """Start or stop the embedded FFmpeg preview."""
        if start:
            if self._current_map and self._current_map.media.video_path and self._current_map.media.video_path.exists():
                video = str(self._current_map.media.video_path)
                audio = (
                    str(self._current_map.media.audio_path)
                    if self._current_map.media.audio_path and self._current_map.media.audio_path.exists()
                    else None
                )
                if not audio:
                    self.append_log("No audio available for preview.")
                    self._sync_refinement.set_preview_state(False)
                    return

                v_override = self._sync_refinement._video_spin.value() / 1000.0
                a_offset = self._sync_refinement._audio_spin.value() / 1000.0
                loop_start, loop_end = self._get_preview_loop_seconds(self._current_map)
                
                logger.debug("Preview launch: v_override=%.3f, a_offset=%.3f", v_override, a_offset)

                self._preview_widget.launch(
                    video, audio,
                    v_override=v_override,
                    a_offset=a_offset,
                    loop_start=loop_start,
                    loop_end=loop_end,
                )
            else:
                self.append_log("No video available for preview.")
                self._sync_refinement.set_preview_state(False)
        else:
            self._preview_widget.stop()

    def _on_offset_spin_changed(self, offset_ms: float) -> None:
        """Debounced preview restart when offsets change."""
        if self._current_map is not None:
            self._pending_offsets[self._current_map.codename] = (
                self._sync_refinement._audio_spin.value(),
                self._sync_refinement._video_spin.value(),
            )

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
        if not self._current_map:
            return

        if not self._current_map.media.video_path or not self._current_map.media.video_path.exists():
            self.append_log("No video available for preview.")
            self._sync_refinement.set_preview_state(False)
            return

        if not self._current_map.media.audio_path or not self._current_map.media.audio_path.exists():
            self.append_log("No audio available for preview.")
            self._sync_refinement.set_preview_state(False)
            return

        if self._current_map and self._current_map.media.video_path and self._current_map.media.video_path.exists():
            v_override = self._sync_refinement._video_spin.value() / 1000.0
            a_offset = self._sync_refinement._audio_spin.value() / 1000.0
            loop_start, loop_end = self._get_preview_loop_seconds(self._current_map)
            
            logger.debug("Debounced preview restart...")
            self._preview_widget.launch(
                str(self._current_map.media.video_path),
                str(self._current_map.media.audio_path),
                v_override=v_override,
                a_offset=a_offset,
                start_time=self._preview_widget._position,
                loop_start=loop_start,
                loop_end=loop_end,
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
        # V1 Parity: use the absolute offset from the spinbox directly
        self._current_map.video_start_time_override = (video_ms / 1000.0)
        self._pending_offsets[self._current_map.codename] = (audio_ms, video_ms)

        # Bundle parity: apply reviewed offsets to every map in the bundle, not only the active one.
        if len(self._nav_maps) > 1:
            entries: list[tuple[NormalizedMapData, Path, float]] = []
            base_game_dir = self._config.game_directory
            while base_game_dir.name.lower() in ("world", "data"):
                base_game_dir = base_game_dir.parent

            for map_data in self._nav_maps:
                map_audio_ms, map_video_ms = self._pending_offsets.get(
                    map_data.codename,
                    (map_data.sync.audio_ms, map_data.sync.video_ms),
                )
                map_data.video_start_time_override = map_video_ms / 1000.0
                entries.append(
                    (
                        map_data,
                        base_game_dir / "data" / "World" / "MAPS" / map_data.codename,
                        map_audio_ms / 1000.0,
                    )
                )

            worker = ApplyOffsetsBatchWorker(entries=entries, config=self._config)
            thread = QThread()
            worker.moveToThread(thread)

            thread.started.connect(worker.run)
            worker.progress.connect(self._feedback_panel.set_progress)
            worker.status.connect(self._on_status_updated)
            worker.error.connect(self._on_install_error)
            worker.finished.connect(self._on_reprocess_finished)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda t=thread: self._cleanup_thread(t, "apply_finish_batch"))

            self._active_threads.add(thread)
            self._active_worker = worker
            self._lock_ui(True)
            thread.start()
            return

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
            if len(self._nav_maps) > 1:
                for map_data in self._nav_maps:
                    if map_data.codename in self._feedback_panel._step_items:
                        self._feedback_panel.update_checklist_step(map_data.codename, StepStatus.DONE)
            if "Finalizing Offsets" in self._feedback_panel._step_items:
                self._feedback_panel.update_checklist_step("Finalizing Offsets", StepStatus.DONE)
            self._preview_widget.reset()
            self._sync_refinement.set_preview_state(False)
            self._sync_refinement.set_nav_visible(False)
            self._set_preview_controls_ready(False)
            # V1 Parity: Don't auto-restart preview anymore after apply
            self._prompt_cleanup()

    def _on_preview_audio_unavailable(self) -> None:
        if self._preview_audio_warning_shown:
            return
        self._preview_audio_warning_shown = True
        QMessageBox.information(
            self,
            "ffplay Not Found",
            "ffplay was not found. Video will play without audio.\n\n"
            "Install FFmpeg to enable audio preview.",
        )

    def _get_preview_loop_seconds(self, map_data: NormalizedMapData) -> tuple[float, float]:
        mt = map_data.music_track
        markers = mt.markers if mt and mt.markers else []
        if not markers:
            return 0.0, 0.0

        try:
            loop_start_idx = int(mt.preview_loop_start)
            loop_end_idx = int(mt.preview_loop_end)
        except (TypeError, ValueError):
            return 0.0, 0.0

        if loop_start_idx < 0 or loop_end_idx < 0:
            return 0.0, 0.0
        if loop_start_idx >= len(markers) or loop_end_idx >= len(markers):
            return 0.0, 0.0
        if loop_end_idx <= loop_start_idx:
            return 0.0, 0.0

        loop_start = markers[loop_start_idx] / 48.0 / 1000.0
        loop_end = markers[loop_end_idx] / 48.0 / 1000.0
        return max(0.0, loop_start), max(0.0, loop_end)

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

            # Provide a codename hint for bundle selection parity when available.
            desired_codename = re.sub(
                r"_(x360|durango|scarlett|nx|orbis|prospero|pc)$",
                "",
                ipk_path.stem,
                flags=re.IGNORECASE,
            )
            return ArchiveIPKExtractor(ipk_path, desired_codename=desired_codename)

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
                source_type=self._mode_selector.manual_source_type,
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
        if locked:
            self._set_preview_controls_ready(False)

    def _set_preview_controls_ready(self, ready: bool) -> None:
        self._preview_widget.setEnabled(ready)
        self._sync_refinement.setEnabled(ready)

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
        # Worker status messages are already logged via _on_status_updated.
        is_worker_status = text in PIPELINE_STEPS or (text.startswith("[") and "]" in text)
        if not is_worker_status:
            logger.info(text)
        self._log_console.append_log(text)

    def set_progress(self, value: int) -> None:
        """Set the progress bar value (delegated to ProgressLogWidget)."""
        self._feedback_panel.set_progress(value)

    def set_status(self, text: str) -> None:
        """Update the status bar message."""
        self._set_status(text)
