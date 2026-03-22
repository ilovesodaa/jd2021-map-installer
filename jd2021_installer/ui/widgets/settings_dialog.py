"""Settings dialog for the GUI installer."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QCheckBox,
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QWidget,
)

from jd2021_installer.core.config import AppConfig

logger = logging.getLogger("jd2021.ui.widgets.settings_dialog")


class SettingsDialog(QDialog):
    """Modal dialog for configuring application settings."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Installer Settings")
        self.setFixedSize(520, 360)
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
        self._config.show_preflight_success_popup = self.cb_preflight_popup.isChecked()
        self._config.show_quickstart_on_launch = self.cb_quickstart.isChecked()
        self._config.video_quality = self.combo_quality.currentText()
        
        self.accept()

    def get_config(self) -> AppConfig:
        return self._config
