"""Platform detection and Wine wrapping utilities for cross-platform support."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def is_linux() -> bool:
    """Return True when running on Linux."""
    return sys.platform.startswith("linux")


def is_windows() -> bool:
    """Return True when running on Windows."""
    return sys.platform == "win32"


def wine_available() -> bool:
    """Return True when the ``wine`` command is on PATH."""
    return shutil.which("wine") is not None


def wrap_exe_for_platform(exe_path: str | Path) -> list[str]:
    """Build a subprocess command list for the given executable.

    - Windows: ``[str(exe_path)]``
    - Linux with Wine: ``["wine", str(exe_path)]``
    - Linux without Wine: raises :class:`RuntimeError`
    """
    if is_windows():
        return [str(exe_path)]

    # Linux (and other non-Windows platforms)
    if wine_available():
        return ["wine", str(exe_path)]

    raise RuntimeError(
        f"Cannot run '{exe_path}' on Linux without Wine. "
        "Please install Wine using your package manager "
        "(e.g. sudo apt install wine on Debian/Ubuntu)."
    )
