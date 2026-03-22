"""Log output console widget for displaying application logs.

Provides a thread-safe QPlainTextEdit accompanied by a custom
logging.Handler that emits PyQt signals so background workers
can log directly to the GUI.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class _Signaller(QObject):
    """Internal QObject used purely to emit signals from the logging handler."""
    log_emitted = pyqtSignal(str)


class QtLogHandler(logging.Handler):
    """Custom logging handler that routes records to a Qt signal."""

    def __init__(self) -> None:
        super().__init__()
        self.signaller = _Signaller()
        # Default format (you can optionally override this or use logging configuration)
        self.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.signaller.log_emitted.emit(msg)
        except Exception:
            self.handleError(record)


class LogConsoleWidget(QWidget):
    """GUI widget containing a read-only text area for scrolling logs."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()
        
        # Create and connect the logging handler automatically
        self.log_handler = QtLogHandler()
        self.log_handler.signaller.log_emitted.connect(self.append_log)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setPlaceholderText("Log output will appear here…")

        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._text_edit.setFont(font)

        # Style matches VS Code / typical dark terminals visually
        self._text_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #1e1e1e; color: #cccccc; }"
        )

        root.addWidget(self._text_edit)

    def append_log(self, text: str) -> None:
        """Slot for thread-safe appending to the console."""
        self._text_edit.appendPlainText(text)
        # Ensure scroll to bottom
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._text_edit.setTextCursor(cursor)

    def clear(self) -> None:
        """Clear all visible logs."""
        self._text_edit.clear()
