"""Configuration panel widget.

Exposes the two most essential configuration controls:
- **Game directory** browser (QFileDialog)
- **Video quality** selector (QComboBox)

Signals carry the selected values upward to the main-window controller.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jd2021_installer.core.config import QUALITY_ORDER

logger = logging.getLogger("jd2021.ui.widgets.config_panel")


class ConfigWidget(QWidget):
    """Game directory + Video quality configuration panel."""

    game_dir_changed = pyqtSignal(str)     # absolute path string
    quality_changed = pyqtSignal(str)      # quality tier label

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        section_label = QLabel("Configuration")
        section_label.setObjectName("configSectionLabel")
        root.addWidget(section_label)

        # -- Game directory row -------------------------------------------
        dir_label = QLabel("Game Directory:")
        root.addWidget(dir_label)

        dir_row = QHBoxLayout()
        self._dir_line = QLineEdit()
        self._dir_line.setReadOnly(True)
        self._dir_line.setPlaceholderText("Select the folder that contains data and engine…")
        self._dir_line.setToolTip(
            "Choose the JD2021 installation root. It must contain both the data and engine folders."
        )
        dir_row.addWidget(self._dir_line)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setToolTip("Browse to the JD2021 folder that contains data and engine.")
        self._browse_btn.clicked.connect(self._browse_game_dir)
        btn_layout.addWidget(self._browse_btn)

        dir_row.addLayout(btn_layout)
        root.addLayout(dir_row)

        # -- Video quality row --------------------------------------------
        qual_label = QLabel("Video Quality:")
        root.addWidget(qual_label)

        self._quality_combo = QComboBox()
        self._quality_combo.addItems(QUALITY_ORDER)
        self._quality_combo.setCurrentText("ULTRA_HD")
        self._quality_combo.setToolTip("Select output video quality profile for converted map files")
        self._quality_combo.currentTextChanged.connect(self._on_quality_changed)
        root.addWidget(self._quality_combo)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select the folder that contains data and engine",
        )
        if path:
            self._dir_line.setText(path)
            self.game_dir_changed.emit(path)
            logger.info("Game directory set to: %s", path)

    def _on_quality_changed(self, quality: str) -> None:
        self.quality_changed.emit(quality)
        logger.info("Video quality set to: %s", quality)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def game_directory(self) -> Optional[Path]:
        text = self._dir_line.text()
        return Path(text) if text else None

    @property
    def video_quality(self) -> str:
        return self._quality_combo.currentText()

    def set_game_directory(self, path: str) -> None:
        """Programmatically set the game directory display."""
        self._dir_line.setText(path)

    def set_video_quality(self, quality: str) -> None:
        """Programmatically select a video quality tier."""
        self._quality_combo.setCurrentText(quality)
