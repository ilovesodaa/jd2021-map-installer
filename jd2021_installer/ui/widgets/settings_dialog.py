"""Settings dialog for the GUI installer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QMessageBox,
    QWidget,
)

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.localization_update import (
    resolve_console_save_path,
    update_console_localization,
)

logger = logging.getLogger("jd2021.ui.widgets.settings_dialog")


class SettingsDialog(QDialog):
    """Modal dialog for configuring application settings."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Installer Settings")
        self.setFixedSize(520, 460)
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

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Installer Settings")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # skip_preflight
        self.cb_skip_preflight = QCheckBox("Skip pre-flight checks")
        self.cb_skip_preflight.setChecked(self._config.skip_preflight)
        self.cb_skip_preflight.setToolTip(
            "Skip pre-flight checks if they've already passed.\n"
            "The Install button will be enabled immediately on launch."
        )
        layout.addWidget(self.cb_skip_preflight)

        # suppress_offset_notification
        self.cb_suppress = QCheckBox("Suppress offset refinement notification")
        self.cb_suppress.setChecked(self._config.suppress_offset_notification)
        self.cb_suppress.setToolTip(
            "Don't show the 'offset refinement is needed' popup\n"
            "after the installation pipeline completes."
        )
        layout.addWidget(self.cb_suppress)

        # cleanup_behavior
        cleanup_row = QHBoxLayout()
        cleanup_label = QLabel("After Apply & Finish:")
        cleanup_row.addWidget(cleanup_label)
        
        self.combo_cleanup = QComboBox()
        self.combo_cleanup.addItems(["ask", "delete", "keep"])
        self.combo_cleanup.setCurrentText(self._config.cleanup_behavior)
        self.combo_cleanup.setToolTip(
            "ask: show prompt after apply\n"
            "delete: auto-delete intermediate files immediately\n"
            "keep: keep files and never show cleanup prompt"
        )
        cleanup_row.addWidget(self.combo_cleanup)
        cleanup_row.addStretch()
        layout.addLayout(cleanup_row)

        # locked_status_behavior
        locked_row = QHBoxLayout()
        locked_label = QLabel("Non-3 song status handling:")
        locked_row.addWidget(locked_label)

        self.combo_locked_status = QComboBox()
        self.combo_locked_status.addItems(["ask", "force3", "keep"])
        self.combo_locked_status.setCurrentText(self._config.locked_status_behavior)
        self.combo_locked_status.setToolTip(
            "ask: prompt when any song status other than 3 is detected\n"
            "force3: always force non-3 statuses to 3 (already unlocked)\n"
            "keep: always keep the original status value\n"
            "Status meaning labels are editable in code: jd2021_installer/ui/main_window.py (_SONG_STATUS_MEANINGS)."
        )
        locked_row.addWidget(self.combo_locked_status)
        locked_row.addStretch()
        layout.addLayout(locked_row)

        # show_preflight_success_popup
        self.cb_preflight_popup = QCheckBox("Show 'Pre-flight passed' popup")
        self.cb_preflight_popup.setChecked(self._config.show_preflight_success_popup)
        self.cb_preflight_popup.setToolTip(
            "If disabled, passing pre-flight will only enable the Install button\n"
            "without opening a popup."
        )
        layout.addWidget(self.cb_preflight_popup)

        # show_quickstart_on_launch
        self.cb_quickstart = QCheckBox("Show quick-start hint on launch")
        self.cb_quickstart.setChecked(self._config.show_quickstart_on_launch)
        self.cb_quickstart.setToolTip(
            "Shows a short beginner guide at startup.\n"
            "Helpful for users who skip documentation."
        )
        layout.addWidget(self.cb_quickstart)

        # video_quality
        quality_row = QHBoxLayout()
        quality_label = QLabel("Default video quality:")
        quality_row.addWidget(quality_label)
        
        self.combo_quality = QComboBox()
        self.combo_quality.addItems([
            "ULTRA_HD", "ULTRA", "HIGH_HD", "HIGH",
            "MID_HD", "MID", "LOW_HD", "LOW"
        ])
        self.combo_quality.setCurrentText(self._config.video_quality)
        quality_row.addWidget(self.combo_quality)
        quality_row.addStretch()
        layout.addLayout(quality_row)

        # discord_channel_url
        discord_row = QHBoxLayout()
        discord_label = QLabel("Discord Channel URL:")
        discord_row.addWidget(discord_label)

        self.txt_discord_url = QLineEdit()
        self.txt_discord_url.setText(self._config.discord_channel_url)
        self.txt_discord_url.setPlaceholderText("https://discord.com/channels/...")
        self.txt_discord_url.setToolTip(
            "The URL of the Discord channel where the JDU asset bot lives.\n"
            "Required for Fetch (Codename) mode.\n"
            "Copy from your browser's address bar while in the channel."
        )
        discord_row.addWidget(self.txt_discord_url)
        layout.addLayout(discord_row)

        localization_row = QHBoxLayout()
        localization_row.addWidget(QLabel("Localization:"))
        self.btn_update_localization = QPushButton("Update In-Game Localization...")
        self.btn_update_localization.clicked.connect(self._on_update_localization)
        localization_row.addWidget(self.btn_update_localization)
        localization_row.addStretch()
        layout.addLayout(localization_row)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_save = QPushButton("Save")
        btn_save.setFixedWidth(80)
        btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(btn_save)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def _on_save(self) -> None:
        self._config.skip_preflight = self.cb_skip_preflight.isChecked()
        self._config.suppress_offset_notification = self.cb_suppress.isChecked()
        self._config.cleanup_behavior = self.combo_cleanup.currentText()
        self._config.locked_status_behavior = self.combo_locked_status.currentText()
        self._config.show_preflight_success_popup = self.cb_preflight_popup.isChecked()
        self._config.show_quickstart_on_launch = self.cb_quickstart.isChecked()
        self._config.video_quality = self.combo_quality.currentText()
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

    def get_config(self) -> AppConfig:
        return self._config
