"""Settings dialog for the GUI installer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QFormLayout,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
    QSpinBox,
    QWidget,
    QSizePolicy,
)

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.localization_update import (
    resolve_console_save_path,
    update_console_localization,
)
from jd2021_installer.core.songdb_update import (
    resolve_songdb_synth_path,
    synthesize_jdnext_songdb,
)

logger = logging.getLogger("jd2021.ui.widgets.settings_dialog")


class SettingsDialog(QDialog):
    """Modal dialog for configuring application settings."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(780, 620)
        self.setModal(True)
        
        # We work on a copy of the config, and only return it if Save is clicked.
        # This prevents partial settings from applying on Cancel.
        # Try to use model_copy (pydantic 2) or copy (pydantic 1)
        if hasattr(config, "model_copy"):
            self._config = config.model_copy()
        elif hasattr(config, "copy"):
            self._config = config.copy()
        else:
            self._config = AppConfig(**config.dict())

        self._build_ui()

    @staticmethod
    def _set_combo_from_value(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            return

        text_idx = combo.findText(value)
        combo.setCurrentIndex(text_idx if text_idx >= 0 else 0)

    @staticmethod
    def _combo_value(combo: QComboBox) -> str:
        data = combo.currentData()
        return str(data) if data is not None else combo.currentText()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.setObjectName("settingsDialog")

        title = QLabel("Installer Settings")
        title.setObjectName("settingsDialogTitle")
        layout.addWidget(title)

        subtitle = QLabel("These settings control installer behavior, defaults, and UI appearance.")
        subtitle.setObjectName("settingsDialogSubtitle")
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.setObjectName("settingsDialogTabs")
        layout.addWidget(tabs, 1)

        # ----- General tab -----
        tab_general = QWidget()
        general_layout = QVBoxLayout(tab_general)
        general_layout.setContentsMargins(10, 10, 10, 10)
        general_layout.setSpacing(10)

        # skip_preflight
        self.cb_skip_preflight = QCheckBox("Skip startup pre-flight checks")
        self.cb_skip_preflight.setChecked(self._config.skip_preflight)
        self.cb_skip_preflight.setToolTip(
            "Skip the pre-flight check on app launch.\n"
            "Use this only when your setup is stable and already validated."
        )
        general_layout.addWidget(self.cb_skip_preflight)

        # suppress_offset_notification
        self.cb_suppress = QCheckBox("Hide post-install offset refinement reminder")
        self.cb_suppress.setChecked(self._config.suppress_offset_notification)
        self.cb_suppress.setToolTip(
            "Do not show the reminder popup about offset refinement\n"
            "after install completes."
        )
        general_layout.addWidget(self.cb_suppress)

        general_form = QFormLayout()
        general_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        general_form.setHorizontalSpacing(12)
        general_form.setVerticalSpacing(10)
        
        self.combo_cleanup = QComboBox()
        self.combo_cleanup.addItem("Ask every time", "ask")
        self.combo_cleanup.addItem("Always delete temporary files", "delete")
        self.combo_cleanup.addItem("Keep temporary files", "keep")
        self._set_combo_from_value(self.combo_cleanup, self._config.cleanup_behavior)
        self.combo_cleanup.setToolTip(
            "Choose what happens to installer temp files after install."
        )
        general_form.addRow("After install cleanup:", self.combo_cleanup)

        self.combo_locked_status = QComboBox()
        self.combo_locked_status.addItem("Ask when needed", "ask")
        self.combo_locked_status.addItem("Always force status to 3 (unlocked)", "force3")
        self.combo_locked_status.addItem("Keep original status values", "keep")
        self._set_combo_from_value(self.combo_locked_status, self._config.locked_status_behavior)
        self.combo_locked_status.setToolTip(
            "Controls how the installer treats locked-song status values\n"
            "when importing maps."
        )
        general_form.addRow("Song unlock status:", self.combo_locked_status)

        # show_preflight_success_popup
        self.cb_preflight_popup = QCheckBox("Show pre-flight success popup")
        self.cb_preflight_popup.setChecked(self._config.show_preflight_success_popup)
        self.cb_preflight_popup.setToolTip(
            "If disabled, passing pre-flight only enables Install\n"
            "without opening a confirmation popup."
        )
        general_layout.addWidget(self.cb_preflight_popup)

        self.cb_install_summary = QCheckBox("Show installation summary popup")
        self.cb_install_summary.setChecked(getattr(self._config, "show_install_summary_popup", True))
        self.cb_install_summary.setToolTip(
            "Shows a checklist-style summary at the end of install with\n"
            "required/optional files, counts, and warnings."
        )
        general_layout.addWidget(self.cb_install_summary)

        # show_quickstart_on_launch
        self.cb_quickstart = QCheckBox("Show quick-start help on launch")
        self.cb_quickstart.setChecked(self._config.show_quickstart_on_launch)
        self.cb_quickstart.setToolTip(
            "Shows a short beginner guide at startup.\n"
            "Helpful for users who skip documentation."
        )
        general_layout.addWidget(self.cb_quickstart)

        self.combo_log_detail = QComboBox()
        self.combo_log_detail.addItem("Quiet (warnings and errors only)", "quiet")
        self.combo_log_detail.addItem("Normal (recommended)", "user")
        self.combo_log_detail.addItem("Detailed (extra debug in logs)", "detailed")
        self.combo_log_detail.addItem("Developer (maximum verbosity)", "developer")
        self._set_combo_from_value(self.combo_log_detail, self._config.log_detail_level)
        self.combo_log_detail.setToolTip(
            "Controls how much detail appears in the app and log files."
        )
        general_form.addRow("Log detail level:", self.combo_log_detail)

        self.combo_theme = QComboBox()
        self.combo_theme.addItem("Light", "light")
        self.combo_theme.addItem("Dark", "dark")
        self._set_combo_from_value(self.combo_theme, self._config.theme)
        self.combo_theme.setToolTip(
            "Pick the installer color theme."
        )
        general_form.addRow("Theme:", self.combo_theme)

        general_layout.addLayout(general_form)
        general_layout.addStretch()

        tabs.addTab(tab_general, "General")

        # ----- Window tab -----
        tab_window = QWidget()
        window_layout = QVBoxLayout(tab_window)
        window_layout.setContentsMargins(10, 10, 10, 10)
        window_layout.setSpacing(10)

        # minimum window size policy
        self.cb_enforce_min_size = QCheckBox("Enforce minimum window size")
        self.cb_enforce_min_size.setChecked(self._config.enforce_min_window_size)
        self.cb_enforce_min_size.setToolTip(
            "When disabled, the main window can be resized smaller than the default minimum."
        )
        window_layout.addWidget(self.cb_enforce_min_size)

        window_form = QFormLayout()
        window_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        window_form.setHorizontalSpacing(12)
        window_form.setVerticalSpacing(10)

        min_size_row = QHBoxLayout()
        min_size_row.setSpacing(8)

        self.spin_min_width = QSpinBox()
        self.spin_min_width.setRange(640, 3840)
        self.spin_min_width.setValue(self._config.min_window_width)
        self.spin_min_width.setSuffix(" px")
        min_size_row.addWidget(self.spin_min_width)

        min_size_row.addWidget(QLabel("x"))

        self.spin_min_height = QSpinBox()
        self.spin_min_height.setRange(480, 2160)
        self.spin_min_height.setValue(self._config.min_window_height)
        self.spin_min_height.setSuffix(" px")
        min_size_row.addWidget(self.spin_min_height)
        min_size_row.addStretch()

        min_size_widget = QWidget()
        min_size_widget.setLayout(min_size_row)
        window_form.addRow("Minimum window size:", min_size_widget)
        window_layout.addLayout(window_form)

        def _toggle_min_size_inputs(enabled: bool) -> None:
            self.spin_min_width.setEnabled(enabled)
            self.spin_min_height.setEnabled(enabled)

        self.cb_enforce_min_size.toggled.connect(_toggle_min_size_inputs)
        _toggle_min_size_inputs(self.cb_enforce_min_size.isChecked())

        self.cb_size_overlay = QCheckBox("Show floating current window size while resizing")
        self.cb_size_overlay.setChecked(
            getattr(self._config, "show_window_size_overlay", True)
        )
        self.cb_size_overlay.setToolTip(
            "Displays an overlay like 1280 x 720 when you resize the main window."
        )
        window_layout.addWidget(self.cb_size_overlay)

        self.cb_style_debug = QCheckBox("Enable Style Debug Mode (outline sections)")
        self.cb_style_debug.setChecked(
            getattr(self._config, "style_debug_mode", False)
        )
        self.cb_style_debug.setToolTip(
            "Adds colored outlines and section labels to help map widgets to QSS selectors.\n"
            "While enabled, stylesheet edits auto-reload as you save.\n"
            "Use while tuning colors, then disable for normal appearance."
        )
        window_layout.addWidget(self.cb_style_debug)
        window_layout.addStretch()

        tabs.addTab(tab_window, "Window")

        # ----- Media tab -----
        tab_media = QWidget()
        media_layout = QVBoxLayout(tab_media)
        media_layout.setContentsMargins(10, 10, 10, 10)
        media_layout.setSpacing(10)

        media_form = QFormLayout()
        media_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        media_form.setHorizontalSpacing(12)
        media_form.setVerticalSpacing(10)

        self.combo_quality = QComboBox()
        self.combo_quality.addItems([
            "ULTRA_HD", "ULTRA", "HIGH_HD", "HIGH",
            "MID_HD", "MID", "LOW_HD", "LOW"
        ])
        self.combo_quality.setCurrentText(self._config.video_quality)
        media_form.addRow("Default download quality:", self.combo_quality)

        self.combo_hwaccel = QComboBox()
        self.combo_hwaccel.addItems(["auto", "none"])
        self.combo_hwaccel.setCurrentText(getattr(self._config, "ffmpeg_hwaccel", "auto"))
        self.combo_hwaccel.setToolTip(
            "auto: let FFmpeg pick available hardware decoding acceleration\n"
            "none: disable hardware acceleration"
        )
        media_form.addRow("FFmpeg acceleration:", self.combo_hwaccel)

        self.combo_vp9_mode = QComboBox()
        self.combo_vp9_mode.addItem("Re-encode VP9 to VP8 (best compatibility)", "reencode_to_vp8")
        self.combo_vp9_mode.addItem("Use next compatible quality down (no re-encode)", "fallback_compatible_down")
        current_vp9_mode = getattr(self._config, "vp9_handling_mode", "reencode_to_vp8")
        vp9_idx = self.combo_vp9_mode.findData(current_vp9_mode)
        self.combo_vp9_mode.setCurrentIndex(vp9_idx if vp9_idx >= 0 else 0)
        self.combo_vp9_mode.setToolTip(
            "Re-encode VP9 to VP8: keeps requested tier but may reduce quality.\n"
            "Next compatible down: skips VP9 tiers and picks a lower HD-compatible tier."
        )
        media_form.addRow("VP9 handling:", self.combo_vp9_mode)

        self.combo_preview_mode = QComboBox()
        self.combo_preview_mode.addItem("Low-res proxy (faster and smoother)", "proxy_low")
        self.combo_preview_mode.addItem("Original video file", "original")
        self._set_combo_from_value(
            self.combo_preview_mode,
            getattr(self._config, "preview_video_mode", "proxy_low"),
        )
        self.combo_preview_mode.setToolTip(
            "Choose whether preview uses a generated proxy or the source file."
        )
        media_form.addRow("Preview source:", self.combo_preview_mode)

        media_layout.addLayout(media_form)
        media_layout.addStretch()

        tabs.addTab(tab_media, "Media")

        # ----- Integrations tab -----
        tab_integrations = QWidget()
        integrations_layout = QVBoxLayout(tab_integrations)
        integrations_layout.setContentsMargins(10, 10, 10, 10)
        integrations_layout.setSpacing(10)

        integrations_form = QFormLayout()
        integrations_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        integrations_form.setHorizontalSpacing(12)
        integrations_form.setVerticalSpacing(10)

        self.txt_discord_url = QLineEdit()
        self.txt_discord_url.setText(self._config.discord_channel_url)
        self.txt_discord_url.setPlaceholderText("https://discord.com/channels/...")
        self.txt_discord_url.setToolTip(
            "The URL of the Discord channel where the JDU asset bot lives.\n"
            "Required for Fetch (Codename) mode.\n"
            "Copy from your browser's address bar while in the channel."
        )
        integrations_form.addRow("Discord channel URL:", self.txt_discord_url)
        integrations_layout.addLayout(integrations_form)

        localization_row = QHBoxLayout()
        localization_row.addWidget(QLabel("Update in-game localization from JSON:"))
        self.btn_update_localization = QPushButton("Update In-Game Localization...")
        self.btn_update_localization.clicked.connect(self._on_update_localization)
        localization_row.addWidget(self.btn_update_localization)
        localization_row.addStretch()
        integrations_layout.addLayout(localization_row)

        songdb_row = QHBoxLayout()
        songdb_row.addWidget(QLabel("Update JDNext song database cache from JSON:"))
        self.btn_update_songdb = QPushButton("Update Song Database...")
        self.btn_update_songdb.clicked.connect(self._on_update_songdb)
        songdb_row.addWidget(self.btn_update_songdb)
        songdb_row.addStretch()
        integrations_layout.addLayout(songdb_row)

        integrations_layout.addStretch()

        tabs.addTab(tab_integrations, "Integrations")

        tabs.setCurrentIndex(0)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_save = QPushButton("Save Settings")
        btn_save.setMinimumWidth(80)
        btn_save.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(btn_save)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setMinimumWidth(80)
        btn_cancel.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def _on_save(self) -> None:
        self._config.skip_preflight = self.cb_skip_preflight.isChecked()
        self._config.suppress_offset_notification = self.cb_suppress.isChecked()
        self._config.cleanup_behavior = self._combo_value(self.combo_cleanup)
        self._config.locked_status_behavior = self._combo_value(self.combo_locked_status)
        self._config.show_preflight_success_popup = self.cb_preflight_popup.isChecked()
        self._config.show_install_summary_popup = self.cb_install_summary.isChecked()
        self._config.show_quickstart_on_launch = self.cb_quickstart.isChecked()
        self._config.log_detail_level = self._combo_value(self.combo_log_detail)
        self._config.theme = self._combo_value(self.combo_theme)
        self._config.enforce_min_window_size = self.cb_enforce_min_size.isChecked()
        self._config.min_window_width = self.spin_min_width.value()
        self._config.min_window_height = self.spin_min_height.value()
        self._config.show_window_size_overlay = self.cb_size_overlay.isChecked()
        self._config.style_debug_mode = self.cb_style_debug.isChecked()
        self._config.video_quality = self.combo_quality.currentText()
        self._config.ffmpeg_hwaccel = self.combo_hwaccel.currentText()
        self._config.vp9_handling_mode = str(self.combo_vp9_mode.currentData())
        self._config.preview_video_mode = self._combo_value(self.combo_preview_mode)
        self._config.discord_channel_url = self.txt_discord_url.text().strip()
        
        self.accept()

    def _on_update_localization(self) -> None:
        if not self._config.game_directory:
            QMessageBox.warning(
                self,
                "Game Directory Required",
                "Set your JD2021 game directory first, then try localization update again.",
            )
            return

        default_dir = str(Path.cwd())
        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select localisation JSON",
            default_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if not selected_file:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Localization Update",
            "Use this file to update in-game localization?\n\n"
            f"Source: {selected_file}\n\n"
            "A backup of ConsoleSave.json will be created before updating.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            console_save_path = resolve_console_save_path(Path(self._config.game_directory))
            result = update_console_localization(Path(selected_file), console_save_path)
            logger.info(
                "Localization updated: %s updated, %s added, backup=%s",
                result.updated_existing,
                result.added_new,
                result.backup_path,
            )
        except Exception as exc:
            logger.exception("Localization update failed: %s", exc)
            QMessageBox.critical(
                self,
                "Localization Update Failed",
                f"Could not update localization:\n{exc}",
            )
            return

        QMessageBox.information(
            self,
            "Localization Updated",
            "Localization update completed successfully.\n\n"
            f"Updated IDs: {result.updated_existing}\n"
            f"New IDs: {result.added_new}\n\n"
            f"Backup: {result.backup_path}",
        )

    def _on_update_songdb(self) -> None:
        default_dir = str(Path.cwd())
        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select JDNext song database JSON",
            default_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if not selected_file:
            return

        output_path = resolve_songdb_synth_path()
        confirm = QMessageBox.question(
            self,
            "Confirm Song Database Update",
            "Use this file to synthesize the local JDNext song database cache?\n\n"
            f"Source: {selected_file}\n"
            f"Output: {output_path}\n\n"
            "This cache helps metadata fallback when source extraction is incomplete.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        progress = QProgressDialog("Synthesizing JDNext song database cache...", "", 0, 0, self)
        progress.setWindowTitle("Updating Song Database")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        QApplication.processEvents()

        try:
            logger.info("Starting JDNext song database synthesis from %s", selected_file)
            result = synthesize_jdnext_songdb(Path(selected_file), output_dir=output_path.parent)
            logger.info(
                "JDNext song database synthesized: source=%s usable=%s keys=%s output=%s",
                result.source_entries,
                result.usable_entries,
                result.index_keys,
                result.output_path,
            )
        except Exception as exc:
            logger.exception("Song database synthesis failed: %s", exc)
            QMessageBox.critical(
                self,
                "Song Database Update Failed",
                f"Could not synthesize JDNext song database cache:\n{exc}",
            )
            return
        finally:
            progress.close()

        backup_line = f"Backup: {result.backup_path}\n" if result.backup_path else ""
        QMessageBox.information(
            self,
            "Song Database Updated",
            "JDNext song database cache created successfully.\n\n"
            f"Source entries: {result.source_entries}\n"
            f"Usable entries: {result.usable_entries}\n"
            f"Indexed keys: {result.index_keys}\n\n"
            f"Output: {result.output_path}\n"
            f"{backup_line}"
            "If this cache is missing later, installer fallback remains active.",
        )

    def get_config(self) -> AppConfig:
        return self._config
