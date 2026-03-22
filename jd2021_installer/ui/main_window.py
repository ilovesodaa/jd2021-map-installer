"""Main window skeleton for the JD2021 Map Installer PyQt6 GUI.

This is a structural placeholder establishing the main window layout,
menu bar, status bar, and placeholder panels.  The real widget
implementations will be added in subsequent iterations.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("jd2021.ui.main_window")


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("JD2021 Map Installer v2")
        self.setMinimumSize(1000, 650)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Splitter: left panel (controls) + right panel (preview)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        self._title_label = QLabel("JD2021 Map Installer")
        self._title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        left_layout.addWidget(self._title_label)

        self._btn_load_html = QPushButton("Load HTML / URLs")
        left_layout.addWidget(self._btn_load_html)

        self._btn_load_ipk = QPushButton("Load IPK Archive")
        left_layout.addWidget(self._btn_load_ipk)

        self._btn_install = QPushButton("Install Map")
        self._btn_install.setEnabled(False)
        left_layout.addWidget(self._btn_install)

        left_layout.addStretch()
        splitter.addWidget(left_panel)

        # Right panel — log output
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setPlaceholderText("Log output will appear here...")
        right_layout.addWidget(self._log_output)

        splitter.addWidget(right_panel)
        splitter.setSizes([350, 650])

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    def append_log(self, text: str) -> None:
        """Append text to the log output panel."""
        self._log_output.append(text)

    def set_progress(self, value: int) -> None:
        """Set the progress bar value (0-100)."""
        self._progress.setValue(value)

    def set_status(self, text: str) -> None:
        """Update the status bar message."""
        self._status_bar.showMessage(text)
