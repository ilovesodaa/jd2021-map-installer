"""Shared filesystem utilities for the JD2021 installer pipeline."""

from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, data: dict, *, indent: int = 2) -> None:
    """Serialise *data* as UTF-8 JSON and write it to *path*.

    Creates parent directories as needed.  ``ensure_ascii=True`` is always
    used so the files stay ASCII-safe regardless of the caller's locale.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=indent), encoding="utf-8")
