"""Shared logging configuration for the JD2021 Map Installer project.

Provides a unified logging setup that works for both CLI and GUI modes.
Console output uses a plain format (matching existing print() style) so
users see no visual difference.  File output adds timestamps and levels.
"""

import logging
import sys
import os
import datetime


ROOT_LOGGER_NAME = "jd2021"


def get_logger(module_name):
    """Return a child logger: jd2021.map_installer, jd2021.ckd_decode, etc."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{module_name}")


def setup_cli_logging(map_name=None, level=logging.INFO):
    """Configure logging for CLI mode: console + optional file handler.

    The console handler uses a minimal format (matches current print style).
    The file handler uses a detailed format with timestamps and levels.
    Returns the log file path (or None if no file handler was created).
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)

    # Avoid adding duplicate handlers if called multiple times
    if root.handlers:
        return None

    root.setLevel(logging.DEBUG)

    # Console: keep it clean (matches existing print style)
    console_fmt = logging.Formatter("%(message)s")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_fmt)
    root.addHandler(console_handler)

    # File: full detail (only if map_name provided)
    log_path = None
    if map_name:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        logs_dir = os.path.join(script_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = os.path.join(logs_dir, f"install_{map_name}_{timestamp}.log")
        file_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
            datefmt="%H:%M:%S")
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_fmt)
        root.addHandler(file_handler)

    return log_path


def setup_gui_logging(handler):
    """Configure logging for GUI mode with the given handler.

    Args:
        handler: A logging.Handler subclass (e.g. TextWidgetHandler)
                 that routes log records to the GUI's text widget.
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)

    # Avoid adding duplicate handlers
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
