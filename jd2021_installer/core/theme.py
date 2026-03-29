"""Theme stylesheet loading helpers."""

from __future__ import annotations

from pathlib import Path


def _theme_filename(theme: str) -> str:
    return "style_dark.qss" if theme == "dark" else "style_light.qss"


def load_theme_stylesheet(theme: str, project_root: Path) -> str:
    """Load theme stylesheet from project root. Returns empty string on failure."""
    chosen = theme if theme in {"light", "dark"} else "light"
    style_path = project_root / _theme_filename(chosen)

    # Backward compatibility: if dark file does not exist, fallback to legacy style.qss.
    if chosen == "dark" and not style_path.exists():
        legacy = project_root / "style.qss"
        style_path = legacy if legacy.exists() else style_path

    if not style_path.exists():
        return ""

    try:
        return style_path.read_text(encoding="utf-8")
    except OSError:
        return ""
