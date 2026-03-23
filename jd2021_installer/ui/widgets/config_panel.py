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
        root.setContentsMargins(0, 0, 0, 0)

        section_label = QLabel("Configuration")
        section_label.setStyleSheet("font-weight: bold;")
        root.addWidget(section_label)

        # -- Game directory row -------------------------------------------
        dir_label = QLabel("Game Directory:")
        root.addWidget(dir_label)

        dir_row = QHBoxLayout()
        self._dir_line = QLineEdit()
        self._dir_line.setReadOnly(True)
        self._dir_line.setPlaceholderText("Select JD2021 game folder…")
        dir_row.addWidget(self._dir_line)

        # Buttons side-by-side
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        
        self._auto_btn = QPushButton("Auto-Detect")
        self._auto_btn.clicked.connect(self._auto_detect_game_dir)
        btn_layout.addWidget(self._auto_btn)

        self._browse_btn = QPushButton("Browse…")
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
        self._quality_combo.currentTextChanged.connect(self._on_quality_changed)
        root.addWidget(self._quality_combo)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select JD2021 Game Directory")
        if path:
            self._dir_line.setText(path)
            self.game_dir_changed.emit(path)
            logger.info("Game directory set to: %s", path)

    def _auto_detect_game_dir(self) -> None:
        """Attempt to fast-resolve the game directory via heuristics."""
        from jd2021_installer.core.path_discovery import resolve_game_paths
        from PyQt6.QtWidgets import QMessageBox

        # Start from the current working directory to detect local installations
        candidate = resolve_game_paths(Path.cwd())
        if candidate:
            self._dir_line.setText(str(candidate))
            self.game_dir_changed.emit(str(candidate))
            logger.info("Auto-detected game directory at: %s", candidate)
            QMessageBox.information(
                self, 
                "Target Discovered", 
                f"Successfully detected JD2021 game installation at:\n{candidate}"
            )
        else:
            logger.warning("Auto-detection failed via quick heuristics.")
            ans = QMessageBox.question(
                self,
                "Auto-Detect Failed",
                "Heuristic search failed to locate JD2021. Would you like to run a deep "
                "recursive scan of the current drive? (This may take a few minutes.)"
            )
            if ans == QMessageBox.StandardButton.Yes:
                # We do this synchronously or via thread for simplicity for now
                # In the future a dedicated worker would prevent GUI lock
                from jd2021_installer.core.path_discovery import deep_scan_for_game_dir
                
                deep_cand = deep_scan_for_game_dir(Path(Path.cwd().anchor)) # e.g. C:\
                if deep_cand:
                    self._dir_line.setText(str(deep_cand))
                    self.game_dir_changed.emit(str(deep_cand))
                    logger.info("Deep-scanned game directory at: %s", deep_cand)
                    QMessageBox.information(
                        self, 
                        "Target Discovered", 
                        f"Successfully found JD2021 game installation at:\n{deep_cand}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Deep Scan Failed",
                        "Could not locate JD2021 on the root drive. Please browse manually."
                    )

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
