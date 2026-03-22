"""Action-button panel widget.

Groups all the primary action buttons into a single reusable widget:
- **Install Map** — kick off the full Extract → Normalize → Install pipeline.
- **Pre-flight Check** — validate paths and configuration before install.
- **Clear Path Cache** — wipe cached extraction directories.
- **Re-adjust Offset** — launch the sync-refinement workflow.
- **Settings** — open a configuration dialog (stub for now).
- **Reset State** — clear all in-memory state back to defaults.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("jd2021.ui.widgets.action_panel")


class ActionWidget(QWidget):
    """Panel of action buttons, each wired to a named signal."""

    install_requested = pyqtSignal()
    preflight_requested = pyqtSignal()
    clear_cache_requested = pyqtSignal()
    readjust_offset_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    reset_state_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        section_label = QLabel("Actions")
        section_label.setStyleSheet("font-weight: bold;")
        root.addWidget(section_label)

        # -- Primary actions (top row) ------------------------------------
        primary = QHBoxLayout()

        self._btn_install = QPushButton("⬇  Install Map")
        self._btn_install.setObjectName("btn_install")
        self._btn_install.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_install.setMinimumHeight(36)
        self._btn_install.clicked.connect(self.install_requested.emit)
        primary.addWidget(self._btn_install)

        self._btn_preflight = QPushButton("✔  Pre-flight Check")
        self._btn_preflight.setObjectName("btn_preflight")
        self._btn_preflight.clicked.connect(self.preflight_requested.emit)
        primary.addWidget(self._btn_preflight)

        root.addLayout(primary)

        # -- Separator ----------------------------------------------------
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # -- Utility row --------------------------------------------------
        utils = QHBoxLayout()

        self._btn_clear_cache = QPushButton("Clear Path Cache")
        self._btn_clear_cache.setObjectName("btn_clear_cache")
        self._btn_clear_cache.clicked.connect(self.clear_cache_requested.emit)
        utils.addWidget(self._btn_clear_cache)

        self._btn_readjust = QPushButton("Re-adjust Offset")
        self._btn_readjust.setObjectName("btn_readjust")
        self._btn_readjust.clicked.connect(self.readjust_offset_requested.emit)
        utils.addWidget(self._btn_readjust)

        self._btn_settings = QPushButton("⚙  Settings")
        self._btn_settings.setObjectName("btn_settings")
        self._btn_settings.clicked.connect(self.settings_requested.emit)
        utils.addWidget(self._btn_settings)

        self._btn_reset = QPushButton("↺  Reset State")
        self._btn_reset.setObjectName("btn_reset")
        self._btn_reset.clicked.connect(self.reset_state_requested.emit)
        utils.addWidget(self._btn_reset)

        root.addLayout(utils)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_install_enabled(self, enabled: bool) -> None:
        """Enable / disable the Install button (e.g. while a worker runs)."""
        self._btn_install.setEnabled(enabled)

    def set_all_enabled(self, enabled: bool) -> None:
        """Bulk-enable / disable every button in the panel."""
        for btn in (
            self._btn_install,
            self._btn_preflight,
            self._btn_clear_cache,
            self._btn_readjust,
            self._btn_settings,
            self._btn_reset,
        ):
            btn.setEnabled(enabled)
