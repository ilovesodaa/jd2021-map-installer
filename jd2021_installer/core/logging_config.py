"""Logging profile configuration helpers.

Provides user-facing logging detail profiles and applies sink-specific
handler levels/formatters at runtime.
"""

from __future__ import annotations

import logging
from typing import Any

LOG_DETAIL_LEVELS = ("quiet", "user", "detailed", "developer")

_PROFILE_MAP: dict[str, dict[str, Any]] = {
    "quiet": {
        "logger_level": logging.INFO,
        "console_level": logging.WARNING,
        "ui_level": logging.WARNING,
        "file_level": logging.INFO,
        "console_format": "[%(levelname)s] %(message)s",
        "ui_format": "[%(levelname)s] %(message)s",
        "file_format": "%(asctime)s [%(levelname)-5s] %(message)s",
    },
    "user": {
        "logger_level": logging.INFO,
        "console_level": logging.INFO,
        "ui_level": logging.INFO,
        "file_level": logging.INFO,
        "console_format": "%(message)s",
        "ui_format": "[%(levelname)s] %(message)s",
        "file_format": "%(asctime)s [%(levelname)-5s] %(message)s",
    },
    "detailed": {
        "logger_level": logging.DEBUG,
        "console_level": logging.INFO,
        "ui_level": logging.INFO,
        "file_level": logging.DEBUG,
        "console_format": "[%(levelname)s] %(message)s",
        "ui_format": "[%(levelname)s] %(message)s",
        "file_format": "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
    },
    "developer": {
        "logger_level": logging.DEBUG,
        "console_level": logging.DEBUG,
        "ui_level": logging.DEBUG,
        "file_level": logging.DEBUG,
        "console_format": "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        "ui_format": "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        "file_format": "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
    },
}


def normalize_log_detail(level: str | None) -> str:
    if level in LOG_DETAIL_LEVELS:
        return str(level)
    return "user"


def get_file_log_level(level: str | None) -> int:
    profile = _PROFILE_MAP[normalize_log_detail(level)]
    return int(profile["file_level"])


def apply_log_detail(level: str | None) -> str:
    """Apply current profile to known jd2021 handlers.

    Returns normalized detail level that was applied.
    """
    normalized = normalize_log_detail(level)
    profile = _PROFILE_MAP[normalized]

    jd_logger = logging.getLogger("jd2021")
    jd_logger.setLevel(int(profile["logger_level"]))

    for logger_obj in (jd_logger, logging.getLogger()):
        for handler in logger_obj.handlers:
            _apply_profile_to_handler(handler, profile)

    return normalized


def log_exception_for_profile(logger: logging.Logger, message: str, exc: BaseException) -> None:
    """Log concise errors for users and full traces for debug-capable profiles."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.exception("%s: %s", message, exc)
    else:
        logger.error("%s: %s", message, exc)


def _apply_profile_to_handler(handler: logging.Handler, profile: dict[str, Any]) -> None:
    if isinstance(handler, logging.FileHandler):
        handler.setLevel(int(profile["file_level"]))
        handler.setFormatter(logging.Formatter(str(profile["file_format"]), datefmt="%H:%M:%S"))
        return

    is_qt_handler = handler.__class__.__name__ == "QtLogHandler"
    if is_qt_handler:
        handler.setLevel(int(profile["ui_level"]))
        handler.setFormatter(logging.Formatter(str(profile["ui_format"]), datefmt="%H:%M:%S"))
        return

    handler.setLevel(int(profile["console_level"]))
    handler.setFormatter(logging.Formatter(str(profile["console_format"]), datefmt="%H:%M:%S"))
