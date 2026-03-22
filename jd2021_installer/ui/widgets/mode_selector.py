"""Mode-selection widget: choose input mode and provide dynamic inputs.

Modes
-----
- **Fetch**   – Enter one or more song codenames to scrape from the web.
- **HTML**    – Load a previously-saved HTML page.
- **IPK**     – Load a local IPK archive file.
- **Batch**   – Select a directory containing multiple IPK files.
- **Manual**  – Point to a pre-extracted map directory.

Each mode shows a tailored input area via a ``QStackedWidget``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("jd2021.ui.widgets.mode_selector")

# Mode identifiers (indices match the combo-box order)
MODE_FETCH = 0
MODE_HTML = 1
MODE_IPK = 2
MODE_BATCH = 3
MODE_MANUAL = 4

MODE_LABELS = ["Fetch (Codename)", "HTML File", "IPK Archive", "Batch (Directory)", "Manual (Directory)"]


class ModeSelectorWidget(QWidget):
    """Dropdown + dynamic input area for selecting the map-import mode."""

    mode_changed = pyqtSignal(str)       # emits the label string
    target_selected = pyqtSignal(str)    # emits the user-provided input

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Mode combo box
        lbl = QLabel("Input Mode")
        lbl.setStyleSheet("font-weight: bold;")
        root.addWidget(lbl)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(MODE_LABELS)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_index_changed)
        root.addWidget(self._mode_combo)

        # Stacked widget for mode-specific inputs
        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._stack.addWidget(self._build_fetch_page())    # 0
        self._stack.addWidget(self._build_file_page("HTML Files (*.html *.htm)"))  # 1
        self._stack.addWidget(self._build_file_page("IPK Archives (*.ipk)"))       # 2
        self._stack.addWidget(self._build_dir_page("Select Batch Directory"))      # 3
        self._stack.addWidget(self._build_dir_page("Select Map Directory"))        # 4

    # -- Fetch page ---------------------------------------------------------

    def _build_fetch_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)

        lbl = QLabel("Codename(s) — comma-separated:")
        lay.addWidget(lbl)

        self._fetch_input = QLineEdit()
        self._fetch_input.setPlaceholderText("e.g. RainOnMe, DontStartNow")
        self._fetch_input.textChanged.connect(lambda t: self.target_selected.emit(t))
        lay.addWidget(self._fetch_input)
        return page

    # -- File picker page ---------------------------------------------------

    def _build_file_page(self, file_filter: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)

        row = QHBoxLayout()
        line = QLineEdit()
        line.setReadOnly(True)
        line.setPlaceholderText("No file selected")
        row.addWidget(line)

        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._pick_file(line, file_filter))
        row.addWidget(btn)

        lay.addLayout(row)
        return page

    # -- Directory picker page ----------------------------------------------

    def _build_dir_page(self, dialog_title: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)

        row = QHBoxLayout()
        line = QLineEdit()
        line.setReadOnly(True)
        line.setPlaceholderText("No directory selected")
        row.addWidget(line)

        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._pick_dir(line, dialog_title))
        row.addWidget(btn)

        lay.addLayout(row)
        return page

    # ------------------------------------------------------------------
    # Slots / helpers
    # ------------------------------------------------------------------

    def _on_mode_index_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self.mode_changed.emit(MODE_LABELS[index])
        logger.debug("Mode switched to: %s", MODE_LABELS[index])

    def _pick_file(self, line_edit: QLineEdit, file_filter: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter)
        if path:
            line_edit.setText(path)
            self.target_selected.emit(path)

    def _pick_dir(self, line_edit: QLineEdit, title: str) -> None:
        path = QFileDialog.getExistingDirectory(self, title)
        if path:
            line_edit.setText(path)
            self.target_selected.emit(path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_mode(self) -> str:
        return MODE_LABELS[self._mode_combo.currentIndex()]

    @property
    def current_mode_index(self) -> int:
        return self._mode_combo.currentIndex()
