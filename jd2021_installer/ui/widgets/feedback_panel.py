"""Feedback panel: progress checklist, progress bar, and live log.

Provides three coordinated feedback mechanisms:

1. **Checklist** — A ``QListWidget`` showing named steps, each with a
   status icon (⏳/⚙/✅/❌) representing waiting / in-progress / done /
   error.
2. **Progress bar** — A standard ``QProgressBar`` (0–100).
3. **Log output** — A ``QPlainTextEdit`` for scrolling log messages.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("jd2021.ui.widgets.feedback_panel")


class StepStatus(Enum):
    """Visual status for a checklist step."""
    WAITING = auto()
    IN_PROGRESS = auto()
    DONE = auto()
    ERROR = auto()


_STATUS_ICONS = {
    StepStatus.WAITING: "⏳",
    StepStatus.IN_PROGRESS: "⚙️",
    StepStatus.DONE: "✅",
    StepStatus.ERROR: "❌",
}


class ProgressLogWidget(QWidget):
    """Combined progress checklist, progress bar, and live log panel."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._step_items: dict[str, QListWidgetItem] = {}
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        section_label = QLabel("Progress")
        section_label.setStyleSheet("font-weight: bold;")
        root.addWidget(section_label)

        # Vertical splitter: checklist (top) + log (bottom)
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(self._splitter)

        # -- Checklist -------------------------------------------------------
        self._checklist = QListWidget()
        self._checklist.setAlternatingRowColors(True)
        self._checklist.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._checklist.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._splitter.addWidget(self._checklist)

        # -- Log output ------------------------------------------------------
        self._log_output = QPlainTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setPlaceholderText("Log output will appear here…")
        log_font = QFont("Consolas", 9)
        log_font.setStyleHint(QFont.StyleHint.Monospace)
        self._log_output.setFont(log_font)
        self._splitter.addWidget(self._log_output)

        self._splitter.setSizes([180, 280])

        # -- Progress bar ----------------------------------------------------
        self._progress = QProgressBar()
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        root.addWidget(self._progress)

    # ------------------------------------------------------------------
    # Checklist API
    # ------------------------------------------------------------------

    def set_checklist_steps(self, steps: list[str]) -> None:
        """Initialise (or reset) the checklist with named steps."""
        self._checklist.clear()
        self._step_items.clear()
        for name in steps:
            item = QListWidgetItem(f"{_STATUS_ICONS[StepStatus.WAITING]}  {name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._checklist.addItem(item)
            self._step_items[name] = item

    def update_checklist_step(self, step_name: str, status: StepStatus) -> None:
        """Update the icon for *step_name* to reflect *status*."""
        item = self._step_items.get(step_name)
        if item is None:
            logger.warning("Checklist step not found: %s", step_name)
            return
        icon = _STATUS_ICONS[status]
        item.setText(f"{icon}  {step_name}")

        # Colour hint for quick scanning
        colour_map = {
            StepStatus.WAITING: QColor("#888888"),
            StepStatus.IN_PROGRESS: QColor("#2196F3"),
            StepStatus.DONE: QColor("#4CAF50"),
            StepStatus.ERROR: QColor("#F44336"),
        }
        item.setForeground(colour_map.get(status, QColor("#FFFFFF")))

    # ------------------------------------------------------------------
    # Progress bar API
    # ------------------------------------------------------------------

    def set_progress(self, value: int) -> None:
        """Set progress bar value (0–100)."""
        self._progress.setValue(max(0, min(100, value)))

    def reset_progress(self) -> None:
        """Reset the progress bar to zero."""
        self._progress.setValue(0)

    # ------------------------------------------------------------------
    # Log API
    # ------------------------------------------------------------------

    def append_log(self, text: str) -> None:
        """Append a line to the log pane and auto-scroll."""
        self._log_output.appendPlainText(text)

    def clear_log(self) -> None:
        """Clear all log output."""
        self._log_output.clear()

    # ------------------------------------------------------------------
    # Combined reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear checklist, progress bar, and log."""
        self._checklist.clear()
        self._step_items.clear()
        self._progress.setValue(0)
        self._log_output.clear()
