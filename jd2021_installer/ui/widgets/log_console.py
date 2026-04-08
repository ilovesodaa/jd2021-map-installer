"""Log output console widget for displaying application logs.

Provides a thread-safe QPlainTextEdit accompanied by a custom
logging.Handler that emits PyQt signals so background workers
can log directly to the GUI.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class _Signaller(QObject):
    """Internal QObject used purely to emit signals from the logging handler."""
    log_emitted = pyqtSignal(str, int)


class QtLogHandler(logging.Handler):
    """Custom logging handler that routes records to a Qt signal."""

    def __init__(self) -> None:
        super().__init__()
        self.signaller = _Signaller()
        # Keep raw message text; display formatting/prefixing is handled in the widget.
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.signaller.log_emitted.emit(msg, int(record.levelno))
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
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)
        self.setObjectName("logConsoleWidget")

        self._text_edit = QTextEdit()
        self._text_edit.setObjectName("logConsoleTextEdit")
        self._text_edit.setReadOnly(True)
        self._text_edit.setPlaceholderText("Log output will appear here…")

        root.addWidget(self._text_edit)

    @staticmethod
    def _resolve_level_for_line(text: str, level: int) -> int:
        lowered = text.strip().lower()
        if level >= logging.WARNING:
            return level
        if lowered.startswith("warning:"):
            return logging.WARNING
        if lowered.startswith("error:"):
            return logging.ERROR
        if lowered.startswith("success:"):
            return 25
        if lowered.startswith("debug:"):
            return logging.DEBUG
        if lowered.startswith("info:"):
            return logging.INFO
        return level

    @staticmethod
    def _prefix_for_level(level: int) -> str:
        if level >= logging.ERROR:
            return "ERROR"
        if level >= logging.WARNING:
            return "WARNING"
        if level == 25:
            return "SUCCESS"
        if level <= logging.DEBUG:
            return "DEBUG"
        return "INFO"

    @staticmethod
    def _normalize_line_text(text: str, level: int) -> str:
        normalized = text.replace("\r\n", "\n").rstrip("\n")
        normalized = re.sub(r"^\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\s*", "", normalized, flags=re.IGNORECASE)

        if re.match(r"^\s*(DEBUG|INFO|WARNING|ERROR|SUCCESS)\s*:\s*", normalized, flags=re.IGNORECASE):
            return normalized

        prefix = LogConsoleWidget._prefix_for_level(level)
        return f"{prefix}: {normalized.lstrip()}"

    def _line_color(self, level: int) -> str:
        if level >= logging.ERROR:
            return "#C62828"
        if level >= logging.WARNING:
            return "#E67E22"
        if level == 25:
            return "#1E8E3E"

        # Light themes need a darker info tone; dark themes benefit from a lighter one.
        base_lightness = self.palette().base().color().lightness()
        if base_lightness >= 140:
            return "#30445F"
        return "#D9DCE5"

    def append_log(self, text: str, level: int = logging.INFO) -> None:
        """Slot for thread-safe appending to the console."""
        line_level = self._resolve_level_for_line(text, level)
        normalized = self._normalize_line_text(text, line_level)
        color = self._line_color(line_level)

        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(normalized + "\n", fmt)

        # Ensure scroll to bottom.
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._text_edit.setTextCursor(cursor)

    def clear(self) -> None:
        """Clear all visible logs."""
        self._text_edit.clear()
