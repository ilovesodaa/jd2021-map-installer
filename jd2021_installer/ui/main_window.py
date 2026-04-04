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
import importlib.util
import re
import shutil
import sys
import json
import subprocess
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer
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
    QDialog,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QAbstractItemView,
    QFileDialog,
    QProgressDialog,
    QSizePolicy,
)

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.logging_config import apply_log_detail, get_file_log_level
from jd2021_installer.core.theme import load_theme_stylesheet
from jd2021_installer.core.models import (
    MapMedia,
    MapSync,
    MusicTrackStructure,
    NormalizedMapData,
    SongDescription,
)
from jd2021_installer.core.readjust_index import (
    ReadjustIndexEntry,
    prune_stale_entries,
    read_video_start_time_from_trk,
    update_offsets,
    upsert_entry,
)
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
    ApplyReadjustOffsetsBatchWorker,
)

logger = logging.getLogger("jd2021.ui.main_window")

_READY_STATUS_VALUE = 3
# Editable status meaning labels live in code (not installer_settings.json).
# Add or change entries here as new statuses are understood.
_SONG_STATUS_MEANINGS: dict[int, str] = {
    1: "Hidden",
    2: "MojoLocked",
    3: "Available",
    4: "RedeemLocked",
    5: "UplayLocked",
    9: "GachaLocked",
    10: "StarLocked",
    11: "DLCLocked",
    12: "ObjectiveLocked",
    13: "AnthologyLocked",
}

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

# Runtime dependencies required for end-user operation.
# key: pip package name, value: import module name
RUNTIME_DEPENDENCIES = {
    "pydantic": "pydantic",
    "requests": "requests",
    "Pillow": "PIL",
    "playwright": "playwright",
}


class MainWindow(QMainWindow):
    """Primary application window — orchestrates widgets and workers."""

    def __init__(self) -> None:
        super().__init__()

        # -- Application state ------------------------------------------------
        self._config = self._load_settings()
        self._config.log_detail_level = apply_log_detail(self._config.log_detail_level)
        self._current_map: Optional[NormalizedMapData] = None
        self._current_target: Optional[str] = None
        self._current_mode: str = "Fetch (Codename)"

        self._active_threads: set[QThread] = set()
        self._active_worker: Optional[object] = None
        self._file_logger_handler: Optional[logging.Handler] = None
        self._preview_audio_warning_shown = False
        self._size_overlay: Optional[QLabel] = None
        self._size_overlay_hide_timer = QTimer(self)
        self._size_overlay_hide_timer.setSingleShot(True)
        self._size_overlay_hide_timer.timeout.connect(self._hide_size_overlay)

        # Phase 4: Multi-map navigation
        self._nav_maps: list[NormalizedMapData] = []
        self._nav_index: int = 0
        self._pending_offsets: dict[str, tuple[float, float]] = {}
        self._readjust_pending_updates: list[tuple[str, float, float]] = []

        # -- Window setup -----------------------------------------------------
        self.setWindowTitle("JD2021 Map Installer v2")
        self._apply_window_size_config()

        self._build_ui()
        self._config.log_detail_level = apply_log_detail(self._config.log_detail_level)
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
        self._init_size_overlay()

        # Show Quickstart Guide if needed
        QTimer.singleShot(500, self._show_quickstart_if_needed)
        QTimer.singleShot(900, self._run_startup_dependency_guardrail)

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

    def _apply_window_size_config(self) -> None:
        if getattr(self._config, "enforce_min_window_size", True):
            min_w = max(640, int(getattr(self._config, "min_window_width", 1000)))
            min_h = max(480, int(getattr(self._config, "min_window_height", 920)))
            self.setMinimumSize(min_w, min_h)
            return

        self.setMinimumSize(0, 0)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return

        project_root = Path(__file__).resolve().parents[2]
        app.setStyleSheet(load_theme_stylesheet(self._config.theme, project_root))

    def _show_quickstart_if_needed(self) -> None:
        # Check config (we'll need to add a flag to AppConfig or settings)
        # For now, let's just check if a certain file exists or dummy logic
        if not getattr(self._config, "skip_quickstart", False):
            from jd2021_installer.ui.widgets.quickstart_dialog import QuickstartDialog
            dont_show_again = QuickstartDialog.show_guide(self)
            if dont_show_again:
                self._config.skip_quickstart = True
                self._save_settings()

    def _offer_ffmpeg_install(self, missing: list[str]) -> bool:
        """Prompt user to auto-download and install FFmpeg toolchain."""
        msg = (
            f"The following required tools were not found: {', '.join(missing)}\n\n"
            "Would you like the installer to automatically download and configure "
            "FFmpeg for you? (Requires Internet connection)"
        )
        reply = QMessageBox.question(
            self, "Missing Dependencies", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return False

        from jd2021_installer.ui.widgets.ffmpeg_dialog import FFmpegInstallDialog

        tools_dir = Path("tools/ffmpeg")
        tools_dir.mkdir(parents=True, exist_ok=True)

        if FFmpegInstallDialog.install(tools_dir, self):
            resolved = self._refresh_media_tool_configuration(persist=True)
            missing_after_install = [name for name, path in resolved.items() if not path]
            if missing_after_install:
                QMessageBox.warning(
                    self,
                    "Install Incomplete",
                    "FFmpeg auto-install completed, but required tools are still missing: "
                    + ", ".join(missing_after_install),
                )
                return False
            QMessageBox.information(
                self,
                "Success",
                "FFmpeg toolchain installed and configured successfully.",
            )
            return True

        QMessageBox.warning(self, "Failed", "FFmpeg installation was cancelled or failed.")
        return False

    def _find_missing_python_dependencies(self) -> list[str]:
        """Return missing pip package names from runtime dependency list."""
        missing: list[str] = []
        for pip_name, module_name in RUNTIME_DEPENDENCIES.items():
            if importlib.util.find_spec(module_name) is None:
                missing.append(pip_name)
        return missing

    def _offer_python_dependencies_install(self, missing: list[str]) -> bool:
        """Prompt user to install missing Python packages using current interpreter."""
        msg = (
            "The following required Python package(s) are missing:\n\n"
            f"- {'\n- '.join(missing)}\n\n"
            "Install them now with pip using this app's Python environment?"
        )
        reply = QMessageBox.question(
            self,
            "Missing Python Packages",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", *missing],
                capture_output=True,
                text=True,
                timeout=600,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Install Failed",
                f"Could not run pip install:\n{exc}",
            )
            return False
        finally:
            QApplication.restoreOverrideCursor()

        if result.returncode != 0:
            output = (result.stderr or result.stdout or "Unknown pip error")[:1200]
            QMessageBox.critical(
                self,
                "Install Failed",
                "Pip failed to install required packages.\n\n"
                f"Output:\n{output}",
            )
            return False

        still_missing = self._find_missing_python_dependencies()
        if still_missing:
            QMessageBox.warning(
                self,
                "Dependency Check",
                "Package installation completed, but some modules are still unavailable:\n\n"
                + "\n".join(still_missing)
                + "\n\nPlease restart the installer and run Pre-flight Check again.",
            )
            return False

        QMessageBox.information(
            self,
            "Dependencies Installed",
            "Required Python packages were installed successfully.",
        )
        return True

    def _playwright_chromium_available(self) -> tuple[bool, str]:
        """Verify that Playwright can launch Chromium in this environment."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return False, str(exc)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def _offer_playwright_browser_install(self) -> bool:
        """Prompt user to install Chromium used by Playwright."""
        reply = QMessageBox.question(
            self,
            "Playwright Browser Missing",
            "Playwright Chromium is not installed or not usable.\n\n"
            "Would you like to install Chromium now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=900,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Playwright Install Failed",
                f"Could not run Playwright install:\n{exc}",
            )
            return False
        finally:
            QApplication.restoreOverrideCursor()

        if result.returncode != 0:
            output = (result.stderr or result.stdout or "Unknown Playwright error")[:1200]
            QMessageBox.critical(
                self,
                "Playwright Install Failed",
                f"Could not install Chromium.\n\nOutput:\n{output}",
            )
            return False

        ok, reason = self._playwright_chromium_available()
        if not ok:
            QMessageBox.warning(
                self,
                "Playwright Check",
                "Chromium was installed, but launch verification still failed.\n\n"
                f"Details:\n{reason[:1000]}",
            )
            return False

        QMessageBox.information(
            self,
            "Playwright Ready",
            "Playwright Chromium is installed and ready.",
        )
        return True

    def _collect_missing_media_binaries(self) -> list[str]:
        """Return missing media binaries required by install/preview flows."""
        resolved = self._refresh_media_tool_configuration(persist=True)
        return [name for name, path in resolved.items() if not path]

    def _resolve_media_binary(
        self,
        binary_name: str,
        configured_path: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve media tools with system-first policy, then local fallback."""
        system_path = shutil.which(binary_name)
        if system_path:
            return system_path

        exe_name = f"{binary_name}.exe" if sys.platform == "win32" else binary_name
        local_candidate = (Path("tools/ffmpeg") / exe_name).resolve()
        if local_candidate.exists() and local_candidate.is_file():
            return str(local_candidate)

        if configured_path:
            configured_candidate = Path(configured_path)
            if configured_candidate.exists() and configured_candidate.is_file():
                return str(configured_candidate.resolve())
            configured_found = shutil.which(configured_path)
            if configured_found:
                return configured_found

        return None

    def _refresh_media_tool_configuration(self, persist: bool = False) -> dict[str, Optional[str]]:
        """Resolve ffmpeg tool paths and propagate them to preview/runtime state."""
        resolved_ffmpeg = self._resolve_media_binary("ffmpeg", self._config.ffmpeg_path)
        resolved_ffprobe = self._resolve_media_binary("ffprobe", self._config.ffprobe_path)
        resolved_ffplay = self._resolve_media_binary("ffplay")

        updated = False
        if resolved_ffmpeg and self._config.ffmpeg_path != resolved_ffmpeg:
            self._config.ffmpeg_path = resolved_ffmpeg
            updated = True
        if resolved_ffprobe and self._config.ffprobe_path != resolved_ffprobe:
            self._config.ffprobe_path = resolved_ffprobe
            updated = True

        if hasattr(self, "_preview_widget"):
            self._preview_widget.set_tool_paths(
                ffmpeg_path=resolved_ffmpeg or self._config.ffmpeg_path,
                ffprobe_path=resolved_ffprobe or self._config.ffprobe_path,
                ffplay_path=resolved_ffplay or "ffplay",
            )

        if persist and updated:
            self._save_settings()

        return {
            "ffmpeg": resolved_ffmpeg,
            "ffprobe": resolved_ffprobe,
            "ffplay": resolved_ffplay,
        }

    def _ensure_runtime_dependencies(self, include_fetch_checks: bool) -> bool:
        """Comprehensive guard rail for Python packages + toolchain dependencies."""
        missing_python = self._find_missing_python_dependencies()
        if missing_python and not self._offer_python_dependencies_install(missing_python):
            return False

        missing_media = self._collect_missing_media_binaries()
        if missing_media and not self._offer_ffmpeg_install(missing_media):
            return False

        if include_fetch_checks:
            ok, reason = self._playwright_chromium_available()
            if not ok and not self._offer_playwright_browser_install():
                if reason:
                    QMessageBox.warning(
                        self,
                        "Fetch Mode Dependency",
                        "Fetch mode cannot continue until Playwright Chromium is available.\n\n"
                        f"Details:\n{reason[:1000]}",
                    )
                return False

        return True

    def _run_startup_dependency_guardrail(self) -> None:
        """Run a lightweight startup dependency health check with remediation."""
        # Do not force Playwright browser launch at startup; that check is mode-specific.
        self._ensure_runtime_dependencies(include_fetch_checks=False)

    # ==================================================================
    # UI COMPOSITION  (Phase 3)
    # ==================================================================

    def resizeEvent(self, event) -> None:
        """Handle window resize by restarting/scaling the preview if active."""
        super().resizeEvent(event)
        self._show_size_overlay()
        if hasattr(self, "_preview_widget") and self._preview_widget.is_playing:
            # Re-trigger preview with current offsets to pick up new dimensions
            self._restart_preview_now()

    def _init_size_overlay(self) -> None:
        self._size_overlay = QLabel(self)
        self._size_overlay.setObjectName("windowSizeOverlay")
        self._size_overlay.setVisible(False)
        self._size_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._size_overlay.raise_()

    def _hide_size_overlay(self) -> None:
        if self._size_overlay is not None:
            self._size_overlay.hide()

    def _show_size_overlay(self) -> None:
        if not getattr(self._config, "show_window_size_overlay", True):
            self._hide_size_overlay()
            return

        if self._size_overlay is None:
            return

        self._size_overlay.setText(f"{self.width()} x {self.height()}")
        self._size_overlay.adjustSize()
        margin = 14
        x = max(margin, self.width() - self._size_overlay.width() - margin)
        y = margin
        self._size_overlay.move(x, y)
        self._size_overlay.show()
        self._size_overlay.raise_()

        timeout_ms = int(getattr(self._config, "window_size_overlay_timeout_ms", 1100))
        self._size_overlay_hide_timer.start(max(200, timeout_ms))

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("mainWindowCentral")
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # -- Column 1 (Left): Sidebar ----------------------------------------
        left_col = QWidget()
        left_col.setObjectName("mainWindowLeftPanel")
        left_col.setMinimumWidth(380)
        left_col.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        self._mode_selector = ModeSelectorWidget()
        self._mode_selector.setObjectName("mainWindowModeSelector")
        self._mode_selector.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        left_layout.addWidget(self._mode_selector, stretch=0)

        self._config_panel = ConfigWidget()
        self._config_panel.setObjectName("mainWindowConfigPanel")
        left_layout.addWidget(self._config_panel, stretch=0)

        self._action_panel = ActionWidget()
        self._action_panel.setObjectName("mainWindowActionPanel")
        left_layout.addWidget(self._action_panel, stretch=0)

        self._feedback_panel = ProgressLogWidget()
        self._feedback_panel.setObjectName("mainWindowFeedbackPanel")
        self._feedback_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        left_layout.addWidget(self._feedback_panel, stretch=1)
        
        root_layout.addWidget(left_col)

        # -- Column 2 (Right): Expanding -------------------------------------
        right_col = QWidget()
        right_col.setObjectName("mainWindowRightPanel")
        right_col.setMinimumWidth(500)
        right_col.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(8)

        self._preview_widget = PreviewWidget()
        self._preview_widget.set_tool_paths(
            ffmpeg_path=self._config.ffmpeg_path,
            ffprobe_path=self._config.ffprobe_path,
            ffplay_path="ffplay",
        )
        self._preview_widget.setObjectName("mainWindowPreviewWidget")
        self._preview_widget.setMinimumHeight(300)
        self._preview_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        right_layout.addWidget(self._preview_widget, stretch=2)

        self._sync_refinement = SyncRefinementWidget()
        self._sync_refinement.setObjectName("mainWindowSyncRefinement")
        self._sync_refinement.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        right_layout.addWidget(self._sync_refinement, stretch=0)

        self._log_console = LogConsoleWidget()
        self._log_console.setObjectName("mainWindowLogConsole")
        self._log_console.setMinimumHeight(180)
        self._log_console.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        # Wire root logger to our console
        logging.getLogger().addHandler(self._log_console.log_handler)
        right_layout.addWidget(self._log_console, stretch=1)

        root_layout.addWidget(right_col, stretch=6)
        root_layout.setStretch(0, 4)
        root_layout.setStretch(1, 6)
        
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
        self._mode_selector.source_state_changed.connect(
            lambda state: self._on_target_selected(str(state.get("target", "")))
        )
        self._config_panel.game_dir_changed.connect(self._on_game_dir_changed)
        self._config_panel.quality_changed.connect(self._on_quality_changed)

        # -- Action panel signals -------------------------------------------
        self._action_panel.install_requested.connect(self._on_install_requested)
        self._action_panel.preflight_requested.connect(self._on_preflight)
        self._action_panel.readjust_offset_requested.connect(self._on_readjust)
        self._action_panel.settings_requested.connect(self._on_settings)
        self._action_panel.reset_state_requested.connect(self._on_reset_state)

        # -- Sync refinement signals ----------------------------------------
        self._sync_refinement.preview_requested.connect(self._on_preview_toggle)
        self._sync_refinement.apply_requested.connect(self._on_apply_offset)
        self._sync_refinement.offsets_changed.connect(self._on_offset_spin_changed)
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

        source_state = self._mode_selector.get_current_state()
        idx = int(source_state.get("mode_index", MODE_FETCH))
        fields = source_state.get("fields", {})

        if idx == MODE_FETCH:
            fetch_fields = fields.get("fetch", {}) if isinstance(fields, dict) else {}
            raw = str(fetch_fields.get("codenames", "")).strip()
            codenames = [c.strip() for c in raw.split(",") if c.strip()]
            if not codenames:
                issues.append("Enter at least one codename for Fetch mode.")
            else:
                self._current_target = ",".join(codenames)
            return issues

        if idx == MODE_HTML:
            html_fields = fields.get("html", {}) if isinstance(fields, dict) else {}
            asset_html = str(html_fields.get("asset", "")).strip()
            nohud_html = str(html_fields.get("nohud", "")).strip()
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
            ipk_fields = fields.get("ipk", {}) if isinstance(fields, dict) else {}
            target = str(ipk_fields.get("file", "")).strip()
            if not target:
                issues.append("Select an IPK archive first.")
            elif not Path(target).is_file():
                issues.append(f"IPK file was not found: {target}")
            else:
                self._current_target = target
            return issues

        if idx == MODE_BATCH:
            batch_fields = fields.get("batch", {}) if isinstance(fields, dict) else {}
            target = str(batch_fields.get("dir", "")).strip()
            if not target:
                issues.append("Select a batch directory first.")
            elif not Path(target).is_dir():
                issues.append(f"Batch directory was not found: {target}")
            else:
                self._current_target = target
            return issues

        if idx == MODE_MANUAL:
            manual_inputs = fields.get("manual", {}) if isinstance(fields, dict) else {}
            codename = str(manual_inputs.get("codename", "")).strip()
            root_dir = str(manual_inputs.get("root", "")).strip()
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
                value = str(manual_inputs.get(key, "")).strip()
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

        from jd2021_installer.ui.widgets.mode_selector import MODE_FETCH
        source_state = self._mode_selector.get_current_state()
        include_fetch_checks = int(source_state.get("mode_index", -1)) == MODE_FETCH
        if not self._ensure_runtime_dependencies(include_fetch_checks=include_fetch_checks):
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
            self._config.log_detail_level = apply_log_detail(self._config.log_detail_level)
            self._apply_window_size_config()
            self._apply_theme()
            self._save_settings()
            if not getattr(self._config, "show_window_size_overlay", True):
                self._hide_size_overlay()
            self._config_panel.set_video_quality(self._config.video_quality)
            self.append_log(f"Logging detail profile set to '{self._config.log_detail_level}'.")
            self._set_status("Settings saved.")

    def _on_readjust(self) -> None:
        entries, pruned = prune_stale_entries()
        if pruned:
            self.append_log(
                f"Readjust index auto-pruned {len(pruned)} stale entr{'y' if len(pruned) == 1 else 'ies'}."
            )

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Maps for Offset Readjust")
        dialog.setMinimumSize(560, 380)
        root = QVBoxLayout(dialog)
        root.addWidget(QLabel("Choose one or more maps from the index, or browse source folder manually."))

        list_widget = QListWidget(dialog)
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        list_widget.itemChanged.connect(lambda _item: _refresh_selection_count())
        for entry in sorted(entries, key=lambda e: e.codename.lower()):
            label = f"{entry.codename}  [{entry.source_mode}]"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, entry.codename)
            item.setToolTip(entry.source_root)
            list_widget.addItem(item)
        root.addWidget(list_widget)

        btns = QHBoxLayout()
        btn_select_all = QPushButton("Select All")
        
        def _set_all_checked(checked: bool) -> None:
            state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            for i in range(list_widget.count()):
                list_widget.item(i).setCheckState(state)
            _refresh_selection_count()

        btn_select_all.clicked.connect(lambda: _set_all_checked(True))
        btns.addWidget(btn_select_all)

        btn_clear = QPushButton("Unselect All")
        btn_clear.clicked.connect(lambda: _set_all_checked(False))
        btns.addWidget(btn_clear)

        count_label = QLabel()
        btns.addWidget(count_label)

        def _refresh_selection_count() -> None:
            total = list_widget.count()
            selected = 0
            for i in range(total):
                if list_widget.item(i).checkState() == Qt.CheckState.Checked:
                    selected += 1
            count_label.setText(f"{selected} of {total} selected")

        _refresh_selection_count()

        btns.addStretch()

        picked_folder: dict[str, Optional[str]] = {"value": None}

        def _browse_fallback() -> None:
            folder = QFileDialog.getExistingDirectory(dialog, "Select Source Folder for Readjust")
            if folder:
                picked_folder["value"] = folder
                dialog.accept()

        btn_browse = QPushButton("Browse Folder…")
        btn_browse.clicked.connect(_browse_fallback)
        btns.addWidget(btn_browse)

        btn_load = QPushButton("Load Selected")
        btn_load.clicked.connect(dialog.accept)
        btns.addWidget(btn_load)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(dialog.reject)
        btns.addWidget(btn_cancel)

        root.addLayout(btns)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if picked_folder["value"]:
            self._load_readjust_from_folder(picked_folder["value"])
            return

        selected_codes = {
            str(list_widget.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(list_widget.count())
            if list_widget.item(i).checkState() == Qt.CheckState.Checked
        }
        if not selected_codes:
            QMessageBox.information(self, "No Map Selected", "Select at least one map or use Browse Folder.")
            return

        selected_entries = [e for e in entries if e.codename in selected_codes]
        loaded_maps: list[NormalizedMapData] = []
        failed: list[str] = []
        progress = QProgressDialog("Loading selected maps for readjust...", "Cancel", 0, len(selected_entries), self)
        progress.setWindowTitle("Loading Readjust Maps")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        for index, entry in enumerate(selected_entries, start=1):
            progress.setLabelText(f"Loading {entry.codename} ({index}/{len(selected_entries)})")
            QApplication.processEvents()
            if progress.wasCanceled():
                break
            try:
                loaded_maps.append(self._load_readjust_map_from_index(entry))
            except Exception as exc:
                failed.append(f"{entry.codename}: {exc}")
            progress.setValue(index)

        progress.close()

        if failed:
            QMessageBox.warning(
                self,
                "Readjust Load Warning",
                "Some maps could not be loaded:\n\n" + "\n".join(failed),
            )

        if not loaded_maps:
            return

        self._activate_readjust_maps(loaded_maps)

    def _load_readjust_from_folder(self, folder: str) -> None:
        from jd2021_installer.parsers.normalizer import normalize

        try:
            map_data = normalize(folder)
            setattr(map_data, "_readjust_profile", "generic")
            setattr(map_data, "_readjust_update_audio", True)
            setattr(map_data, "_readjust_update_video", True)
            target_dir = self._resolve_target_map_dir(map_data.codename)
            setattr(map_data, "_readjust_target_dir", target_dir)
            self._activate_readjust_maps([map_data])
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Readjust Unavailable",
                (
                    "Readjust could not load this folder.\n\n"
                    "Readjust requires valid source files for preview/apply.\n"
                    "If sources were deleted after install, readjust is not available.\n\n"
                    f"Details: {exc}"
                ),
            )

    def _build_minimal_readjust_map(self, entry: ReadjustIndexEntry) -> NormalizedMapData:
        source_root = Path(entry.source_root)
        discovered_audio, discovered_video = self._discover_readjust_media_paths(source_root, entry.codename)
        audio_path = discovered_audio or Path(entry.source_audio)
        video_path = discovered_video or Path(entry.source_video)

        map_data = NormalizedMapData(
            codename=entry.codename,
            song_desc=SongDescription(map_name=entry.codename, title=entry.codename),
            music_track=MusicTrackStructure(),
            media=MapMedia(
                audio_path=audio_path,
                video_path=video_path,
            ),
            sync=MapSync(),
            source_dir=source_root,
        )
        return map_data

    def _discover_readjust_media_paths(self, source_root: Path, codename: str) -> tuple[Optional[Path], Optional[Path]]:
        if not source_root.is_dir():
            return None, None

        codename_low = codename.lower()
        audio_matches: list[Path] = []
        video_matches: list[Path] = []

        try:
            for path in source_root.rglob("*"):
                if not path.is_file():
                    continue
                lower_name = path.name.lower()
                if lower_name.endswith(".webm") and "mappreview" not in lower_name and "videopreview" not in lower_name:
                    video_matches.append(path)
                elif lower_name.endswith(".ogg") or lower_name.endswith(".wav") or lower_name.endswith(".wav.ckd"):
                    if "audiopreview" not in lower_name:
                        audio_matches.append(path)
        except OSError:
            return None, None

        def _pick_best(candidates: list[Path]) -> Optional[Path]:
            if not candidates:
                return None
            codename_hits = [p for p in candidates if codename_low in p.as_posix().lower().split("/") or p.name.lower().startswith(codename_low)]
            if codename_hits:
                return sorted(codename_hits)[0]
            return sorted(candidates)[0]

        return _pick_best(audio_matches), _pick_best(video_matches)

    def _resolve_target_map_dir(self, codename: str) -> Path:
        if not self._config.game_directory:
            raise RuntimeError("Game directory not configured.")
        game_dir = self._config.game_directory
        while game_dir.name.lower() in ("world", "data"):
            game_dir = game_dir.parent
        return game_dir / "data" / "World" / "MAPS" / codename

    def _load_readjust_map_from_index(self, entry: ReadjustIndexEntry) -> NormalizedMapData:
        from jd2021_installer.parsers.normalizer import normalize

        source_root = Path(entry.source_root)
        if not source_root.is_dir():
            raise RuntimeError("Source folder no longer exists.")

        try:
            map_data = normalize(source_root, codename=entry.codename, search_root=source_root)
        except Exception:
            map_data = self._build_minimal_readjust_map(entry)

        discovered_audio, discovered_video = self._discover_readjust_media_paths(source_root, entry.codename)
        if discovered_audio is not None:
            map_data.media.audio_path = discovered_audio
        elif not map_data.media.audio_path or not map_data.media.audio_path.exists():
            map_data.media.audio_path = Path(entry.source_audio)

        if discovered_video is not None:
            map_data.media.video_path = discovered_video
        elif not map_data.media.video_path or not map_data.media.video_path.exists():
            map_data.media.video_path = Path(entry.source_video)

        installed_trk = Path(entry.installed_trk)
        vst = read_video_start_time_from_trk(installed_trk)
        if vst is None:
            source_trk = source_root / "Audio" / f"{entry.codename}.trk"
            vst = read_video_start_time_from_trk(source_trk)
        if vst is None:
            vst = map_data.sync.video_ms / 1000.0

        mode_low = entry.source_mode.lower()
        is_ipk = "ipk" in mode_low
        is_fetch_html = ("fetch" in mode_low) or ("html" in mode_low)

        # Always trust the persisted index values (including legitimate 0.0 values).
        default_audio_ms = float(entry.last_audio_ms)
        default_video_ms = float(entry.last_video_ms)

        if is_ipk:
            map_data.sync.audio_ms = 0.0
            map_data.sync.video_ms = default_video_ms
            setattr(map_data, "_readjust_profile", "ipk")
            setattr(map_data, "_readjust_update_audio", False)
            setattr(map_data, "_readjust_update_video", True)
        elif is_fetch_html:
            map_data.sync.audio_ms = default_audio_ms
            map_data.sync.video_ms = default_video_ms
            setattr(map_data, "_readjust_profile", "fetch_html")
            setattr(map_data, "_readjust_update_audio", True)
            setattr(map_data, "_readjust_update_video", False)
        else:
            map_data.sync.audio_ms = default_audio_ms
            map_data.sync.video_ms = default_video_ms
            setattr(map_data, "_readjust_profile", "generic")
            setattr(map_data, "_readjust_update_audio", True)
            setattr(map_data, "_readjust_update_video", True)

        map_data.video_start_time_override = map_data.sync.video_ms / 1000.0
        setattr(map_data, "_readjust_target_dir", Path(entry.installed_map_dir))
        setattr(map_data, "_readjust_indexed", True)
        return map_data

    def _apply_readjust_profile(self, map_data: NormalizedMapData) -> None:
        profile = str(getattr(map_data, "_readjust_profile", "generic"))
        self._sync_refinement.apply_profile(profile)
        self._sync_refinement.set_ipk_mode(is_ipk=self._is_ipk_source_map(map_data))

    def _is_ipk_source_map(self, map_data: Optional[NormalizedMapData]) -> bool:
        """Best-effort detection for maps originating from IPK sources."""
        if map_data is None:
            return False

        profile = str(getattr(map_data, "_readjust_profile", "")).strip().lower()
        if profile == "ipk":
            return True

        if bool(getattr(map_data, "_is_ipk_source", False)):
            return True

        mode_low = (self._current_mode or "").lower()
        if "ipk" in mode_low:
            return True

        source_dir = getattr(map_data, "source_dir", None)
        if source_dir:
            src_low = str(source_dir).lower().replace("\\", "/")
            if "_batch_temp" in src_low and "/world/maps/" in src_low:
                return True

        audio_path = map_data.media.audio_path
        if audio_path and audio_path.name.lower().endswith(".wav.ckd"):
            return True

        return False

    def _activate_readjust_maps(self, maps: list[NormalizedMapData]) -> None:
        self._nav_maps = maps
        self._nav_index = 0
        self._current_map = self._nav_maps[0]
        self._pending_offsets = {
            m.codename: (m.sync.audio_ms, m.sync.video_ms) for m in self._nav_maps
        }

        if len(self._nav_maps) > 1:
            self._sync_refinement.set_nav_visible(True, f"Map 1 / {len(self._nav_maps)}")
        else:
            self._sync_refinement.set_nav_visible(False)

        first_audio_ms, first_video_ms = self._pending_offsets.get(
            self._current_map.codename,
            (self._current_map.sync.audio_ms, self._current_map.sync.video_ms),
        )
        self._sync_refinement.set_offsets(first_audio_ms, first_video_ms)
        self._apply_readjust_profile(self._current_map)

        self._set_preview_controls_ready(True)
        self.append_log(f"Loaded {len(self._nav_maps)} map(s) for offset readjustment.")
        self._set_status(f"Readjusting offset for {self._current_map.codename}")
        self._on_preview_toggle(True)

    # -- Reset state --------------------------------------------------------

    def _on_reset_state(self) -> None:
        self._current_map = None
        self._current_target = None
        self._nav_maps = []
        self._nav_index = 0
        self._pending_offsets.clear()
        self._readjust_pending_updates.clear()
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
        source_state = self._mode_selector.get_current_state()
        source_fields = source_state.get("fields", {})
        if int(source_state.get("mode_index", -1)) == MODE_FETCH:
            fetch_fields = source_fields.get("fetch", {}) if isinstance(source_fields, dict) else {}
            raw_value = str(fetch_fields.get("codenames", ""))
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
                    self._mode_selector.set_fetch_codenames(sanitized)
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

        from jd2021_installer.ui.widgets.mode_selector import MODE_FETCH
        source_state = self._mode_selector.get_current_state()
        mode_index = int(source_state.get("mode_index", -1))
        include_fetch_checks = mode_index == MODE_FETCH
        if not self._ensure_runtime_dependencies(include_fetch_checks=include_fetch_checks):
            return

        # Start dynamic per-map logging immediately if target is available
        self._start_file_logging(self._current_target)

        # Intercept batch mode - it has a completely different pipeline structure
        from jd2021_installer.ui.widgets.mode_selector import MODE_BATCH
        if mode_index == MODE_BATCH:
            self._start_batch_install()
            return

        # Bundle IPK support
        from jd2021_installer.ui.widgets.mode_selector import MODE_IPK
        if mode_index == MODE_IPK and Path(self._current_target).is_file():
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
        is_ipk = mode_index == MODE_IPK
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
        worker.status.connect(self._on_status_updated)
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

        # Detect maps that are locked behind unlock/login conditions and ask how to proceed.
        if not self._apply_locked_status_policy_single(map_data):
            self.append_log("Install aborted by user during locked-status prompt.")
            self._set_status("Install aborted")
            self._lock_ui(False)
            self._stop_file_logging()
            return
        
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

    def _apply_locked_status_policy_single(self, map_data: NormalizedMapData) -> bool:
        """Prompt user when a map has a non-default song status and apply choice."""
        status_value = int(getattr(map_data.song_desc, "status", _READY_STATUS_VALUE))
        if status_value == _READY_STATUS_VALUE:
            return True

        behavior = getattr(self._config, "locked_status_behavior", "ask")
        codename = map_data.codename
        status_meaning = _SONG_STATUS_MEANINGS.get(status_value, "Unknown status")
        if behavior == "force3":
            map_data.song_desc.status = _READY_STATUS_VALUE
            self.append_log(
                f"[{codename}] Non-default status {status_value} ({status_meaning}) detected. Policy=force3, forcing Status={_READY_STATUS_VALUE}."
            )
            return True
        if behavior == "keep":
            self.append_log(
                f"[{codename}] Non-default status {status_value} ({status_meaning}) detected. Policy=keep, preserving original status."
            )
            return True

        reply = QMessageBox.question(
            self,
            "Non-default Song Status Detected",
            (
                f"Detected Status = {status_value} for '{codename}'.\n"
                f"Meaning: {status_meaning}.\n\n"
                f"Yes: Force Status to {_READY_STATUS_VALUE} (default playable behavior).\n"
                "No: Keep original status value.\n"
                "Cancel: Abort installation."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )

        if reply == QMessageBox.StandardButton.Cancel:
            return False

        if reply == QMessageBox.StandardButton.Yes:
            map_data.song_desc.status = _READY_STATUS_VALUE
            self.append_log(
                f"[{codename}] Non-default status {status_value} ({status_meaning}) detected. Forcing Status={_READY_STATUS_VALUE}."
            )
        else:
            self.append_log(
                f"[{codename}] Non-default status {status_value} ({status_meaning}) detected. Preserving original status."
            )
        return True

    def _ask_batch_locked_status_policy(self) -> Optional[bool]:
        """Ask once for batch mode: force non-3 statuses to 3 or preserve originals."""
        behavior = getattr(self._config, "locked_status_behavior", "ask")
        if behavior == "force3":
            self.append_log("Batch status policy: force3 (auto-convert any non-3 status to 3).")
            return True
        if behavior == "keep":
            self.append_log("Batch status policy: keep (preserve all original status values).")
            return False

        reply = QMessageBox.question(
            self,
            "Batch Song Status Policy",
            (
                "Batch mode can auto-detect any song status that is not 3.\n\n"
                "Yes: For every detected non-3 status, force Status to 3.\n"
                "No: Keep original status values.\n"
                "Cancel: Abort batch install."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return None
        return reply == QMessageBox.StandardButton.Yes

    def _start_install_worker(self, map_data: NormalizedMapData) -> None:
        worker = InstallMapWorker(
            map_data=map_data,
            target_dir=self._config.game_directory,  # type: ignore[arg-type]
            source_mode=self._current_mode,
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
        self._log_with_level(msg, self._classify_status_level(msg))
        
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

                self._sync_refinement.set_ipk_mode(
                    is_ipk=self._is_ipk_source_map(self._current_map)
                )

            # Start preview for the current map
            if self._current_map:
                self._register_map_in_readjust_index(self._current_map)
                self._set_preview_controls_ready(True)
                self._on_preview_toggle(True)
        self._lock_ui(False)
        self._stop_file_logging()

    def _on_batch_finished_with_data(self, installed_maps: list[NormalizedMapData]) -> None:
        """Called when a batch install completes with a list of map data."""
        if not installed_maps:
            return

        for map_data in installed_maps:
            self._register_map_in_readjust_index(map_data)
        
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
        self._apply_readjust_profile(self._current_map)
        self._set_preview_controls_ready(True)
        self._on_preview_toggle(True)

    def _register_map_in_readjust_index(self, map_data: NormalizedMapData) -> None:
        """Upsert one map's source metadata for readjust discovery."""
        if not map_data or not map_data.codename:
            return

        if not map_data.media.audio_path or not map_data.media.video_path:
            return

        audio_path = map_data.media.audio_path.resolve()
        video_path = map_data.media.video_path.resolve()

        source_root = self._infer_readjust_source_root(map_data, audio_path, video_path)
        source_mode = self._infer_readjust_source_mode(map_data)

        target_dir = self._resolve_target_map_dir(map_data.codename)
        trk_path = target_dir / "Audio" / f"{map_data.codename}.trk"

        entry = ReadjustIndexEntry(
            codename=map_data.codename,
            source_mode=source_mode,
            source_root=str(source_root),
            source_audio=str(audio_path),
            source_video=str(video_path),
            installed_map_dir=str(target_dir.resolve()),
            installed_trk=str(trk_path.resolve()),
            last_audio_ms=float(map_data.sync.audio_ms),
            last_video_ms=float(map_data.sync.video_ms),
        )
        upsert_entry(entry)

    def _infer_readjust_source_mode(self, map_data: NormalizedMapData) -> str:
        mode = (self._current_mode or "").strip()
        audio_suffix = map_data.media.audio_path.suffix.lower() if map_data.media.audio_path else ""

        if "fetch" in mode.lower():
            return "Fetch"
        if "html" in mode.lower():
            return "HTML"
        if "ipk" in mode.lower():
            return "IPK Archive"
        if "batch" in mode.lower():
            if audio_suffix == ".wav":
                return "IPK Bundle"
            return "Batch"
        return mode or "unknown"

    def _infer_readjust_source_root(
        self,
        map_data: NormalizedMapData,
        audio_path: Path,
        video_path: Path,
    ) -> Path:
        mode_low = (self._current_mode or "").lower()

        if "fetch" in mode_low or "html" in mode_low:
            candidate = (self._config.download_root / map_data.codename).resolve()
            if candidate.is_dir():
                return candidate

        if map_data.source_dir and map_data.source_dir.exists():
            src = map_data.source_dir.resolve()
            if src.is_dir() and "_batch_temp" not in str(src).lower() and "_extraction" not in str(src).lower():
                return src

        audio_parent = audio_path.parent
        video_parent = video_path.parent
        try:
            common = Path(os.path.commonpath([str(audio_parent), str(video_parent)]))
            if common.exists():
                return common.resolve()
        except Exception:
            pass

        if audio_parent.exists():
            return audio_parent.resolve()
        return video_parent.resolve()

    def _on_nav_requested(self, direction: int) -> None:
        """Switch between maps in a batch/bundle review."""
        if not self._nav_maps:
            return

        # Preserve current map edits before switching.
        if self._current_map is not None:
            audio_ms, video_ms = self._sync_refinement.get_offsets()
            self._pending_offsets[self._current_map.codename] = (
                audio_ms,
                video_ms,
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
            self._apply_readjust_profile(self._current_map)
            
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

                v_override = self._sync_refinement.get_video_offset() / 1000.0
                a_offset = self._sync_refinement.get_audio_offset() / 1000.0
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

    def _on_offset_spin_changed(self, audio_ms: float, video_ms: float) -> None:
        """Debounced preview restart when offsets change."""
        if self._current_map is not None:
            self._pending_offsets[self._current_map.codename] = (
                audio_ms,
                video_ms,
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
            v_override = self._sync_refinement.get_video_offset() / 1000.0
            a_offset = self._sync_refinement.get_audio_offset() / 1000.0
            loop_start, loop_end = self._get_preview_loop_seconds(self._current_map)
            
            logger.debug("Debounced preview restart...")
            self._preview_widget.launch(
                str(self._current_map.media.video_path),
                str(self._current_map.media.audio_path),
                v_override=v_override,
                a_offset=a_offset,
                start_time=self._preview_widget.get_current_position(),
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

            self._sync_refinement.set_offsets(audio_ms=diff_ms, video_ms=self._sync_refinement.get_video_offset())
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
        is_readjust_index_mode = bool(getattr(self._current_map, "_readjust_indexed", False))
        self._readjust_pending_updates.clear()

        # Bundle parity: apply reviewed offsets to every map in the bundle, not only the active one.
        if len(self._nav_maps) > 1:
            entries: list[tuple[NormalizedMapData, Path, float]] = []
            readjust_entries: list[tuple[NormalizedMapData, Path, float, float, bool, bool]] = []
            base_game_dir = self._config.game_directory
            while base_game_dir.name.lower() in ("world", "data"):
                base_game_dir = base_game_dir.parent

            for map_data in self._nav_maps:
                map_audio_ms, map_video_ms = self._pending_offsets.get(
                    map_data.codename,
                    (map_data.sync.audio_ms, map_data.sync.video_ms),
                )
                map_data.video_start_time_override = map_video_ms / 1000.0
                target_dir_attr = getattr(map_data, "_readjust_target_dir", None)
                target_dir = Path(target_dir_attr) if target_dir_attr else (
                    base_game_dir / "data" / "World" / "MAPS" / map_data.codename
                )

                entries.append(
                    (
                        map_data,
                        target_dir,
                        map_audio_ms / 1000.0,
                    )
                )

                readjust_entries.append(
                    (
                        map_data,
                        target_dir,
                        map_audio_ms / 1000.0,
                        map_video_ms / 1000.0,
                        bool(getattr(map_data, "_readjust_update_video", True)),
                        bool(getattr(map_data, "_readjust_update_audio", True)),
                    )
                )

            for map_data in self._nav_maps:
                map_audio_ms, map_video_ms = self._pending_offsets.get(
                    map_data.codename,
                    (map_data.sync.audio_ms, map_data.sync.video_ms),
                )
                self._readjust_pending_updates.append((map_data.codename, map_audio_ms, map_video_ms))

            if any(bool(getattr(m, "_readjust_indexed", False)) for m in self._nav_maps):
                worker = ApplyReadjustOffsetsBatchWorker(entries=readjust_entries, config=self._config)
            else:
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

        if is_readjust_index_mode:
            target_dir_attr = getattr(self._current_map, "_readjust_target_dir", None)
            target_dir = Path(target_dir_attr) if target_dir_attr else (
                base_game_dir / "data" / "World" / "MAPS" / self._current_map.codename
            )
            worker = ApplyReadjustOffsetsBatchWorker(
                entries=[
                    (
                        self._current_map,
                        target_dir,
                        audio_ms / 1000.0,
                        video_ms / 1000.0,
                        bool(getattr(self._current_map, "_readjust_update_video", True)),
                        bool(getattr(self._current_map, "_readjust_update_audio", True)),
                    )
                ],
                config=self._config,
            )
            self._readjust_pending_updates = [(self._current_map.codename, audio_ms, video_ms)]
        else:
            worker = ApplyAndFinishWorker(
                self._current_map,
                base_game_dir / "data" / "World" / "MAPS" / self._current_map.codename,
                self._config.cache_directory / self._current_map.codename,
                a_offset=audio_ms / 1000.0,
                config=self._config,
            )
            self._readjust_pending_updates = [(self._current_map.codename, audio_ms, video_ms)]
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
            for codename, audio_ms, video_ms in self._readjust_pending_updates:
                update_offsets(codename, audio_ms=audio_ms, video_ms=video_ms)
            self._readjust_pending_updates.clear()
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
        else:
            self._readjust_pending_updates.clear()

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

        source_state = self._mode_selector.get_current_state()
        idx = int(source_state.get("mode_index", MODE_FETCH))
        source_fields = source_state.get("fields", {})

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

            html_fields = source_fields.get("html", {}) if isinstance(source_fields, dict) else {}
            asset_html = str(html_fields.get("asset", ""))
            nohud_html = str(html_fields.get("nohud", ""))
            
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
            manual_fields = source_fields.get("manual", {}) if isinstance(source_fields, dict) else {}
            codename = str(manual_fields.get("codename", "")).strip()
            root_dir = str(manual_fields.get("root", "")).strip()
            
            if not codename and not root_dir:
                QMessageBox.warning(self, "Missing Data", "Codename or Root Directory is required for Manual mode.")
                return None
                
            return ManualExtractor(
                codename=codename,
                source_type=str(source_state.get("manual_source_type", "jdu")),
                root_dir=root_dir,
                files={
                    "audio": str(manual_fields.get("audio", "")).strip(),
                    "video": str(manual_fields.get("video", "")).strip(),
                    "mtrack": str(manual_fields.get("mtrack", "")).strip(),
                    "sdesc": str(manual_fields.get("sdesc", "")).strip(),
                    "dtape": str(manual_fields.get("dtape", "")).strip(),
                    "ktape": str(manual_fields.get("ktape", "")).strip(),
                    "mseq": str(manual_fields.get("mseq", "")).strip(),
                },
                dirs={
                    "moves": str(manual_fields.get("moves", "")).strip(),
                    "pictos": str(manual_fields.get("pictos", "")).strip(),
                    "menuart": str(manual_fields.get("menuart", "")).strip(),
                    "amb": str(manual_fields.get("amb", "")).strip(),
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

        force_unlock_locked_status = self._ask_batch_locked_status_policy()
        if force_unlock_locked_status is None:
            self.append_log("Batch install aborted by user during locked-status policy prompt.")
            self._set_status("Install aborted")
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
            force_unlock_locked_status=force_unlock_locked_status,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._feedback_panel.set_progress)
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
        self._file_logger_handler.setLevel(get_file_log_level(self._config.log_detail_level))
        logging.getLogger("jd2021").addHandler(self._file_logger_handler)
        self._config.log_detail_level = apply_log_detail(self._config.log_detail_level)
        logger.info("Install log file: %s", log_path)

    def _stop_file_logging(self) -> None:
        """Removes the active FileHandler and cleanly closes handles."""
        if self._file_logger_handler:
            logging.getLogger("jd2021").removeHandler(self._file_logger_handler)
            self._file_logger_handler.close()
            self._file_logger_handler = None

    def _set_status(self, text: str) -> None:
        self._status_bar.showMessage(text)

    # -- Public convenience methods (kept for compatibility) ----------------

    def _log_with_level(self, text: str, level: int) -> None:
        if level >= logging.ERROR:
            logger.error(text)
        elif level >= logging.WARNING:
            logger.warning(text)
        elif level <= logging.DEBUG:
            logger.debug(text)
        else:
            logger.info(text)

    def _classify_status_level(self, text: str) -> int:
        lowered = text.strip().lower()
        if lowered.startswith("error") or " failed" in lowered or lowered.startswith("failed"):
            return logging.ERROR
        if lowered.startswith("warning") or " warning" in lowered:
            return logging.WARNING
        if lowered.startswith("debug"):
            return logging.DEBUG
        return logging.INFO

    def append_log(self, text: str) -> None:
        """Append text to the GUI log console."""
        self._log_with_level(text, self._classify_status_level(text))

    def set_progress(self, value: int) -> None:
        """Set the progress bar value (delegated to ProgressLogWidget)."""
        self._feedback_panel.set_progress(value)

    def set_status(self, text: str) -> None:
        """Update the status bar message."""
        self._set_status(text)
