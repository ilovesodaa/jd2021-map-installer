"""Theme stylesheet loading helpers."""

from __future__ import annotations

from pathlib import Path


_STYLE_DEBUG_OVERLAY = """
/* Style Debug Mode overlay (temporary visual mapping aid) */
QWidget#mainWindowLeftPanel { border: 2px solid #ff6b6b; }
QWidget#mainWindowRightPanel { border: 2px solid #4c6fff; }
QWidget#mainWindowPreviewWidget { border: 2px dashed #2f9e44; border-radius: 6px; }
QWidget#mainWindowSyncRefinement { border: 2px dashed #f08c00; border-radius: 6px; }
QWidget#mainWindowLogConsole { border: 2px dashed #a33fd6; border-radius: 6px; padding: 4px; }
QFrame#sectionSeparator { background-color: #ff4d4f; }
QLabel#panelMapHintLabel {
    color: #ffffff;
    background-color: rgba(20, 22, 26, 200);
    border: 1px solid #6f7c96;
    border-radius: 4px;
    padding: 2px 6px;
}
"""


def _theme_filename(theme: str) -> str:
    return "style_dark.qss" if theme == "dark" else "style_light.qss"


def resolve_theme_stylesheet_path(theme: str, project_root: Path) -> Path:
    """Resolve the active stylesheet path, including dark->legacy fallback."""
    chosen = theme if theme in {"light", "dark"} else "light"
    style_path = project_root / _theme_filename(chosen)

    if chosen == "dark" and not style_path.exists():
        legacy = project_root / "style.qss"
        style_path = legacy if legacy.exists() else style_path

    return style_path


def load_theme_stylesheet(theme: str, project_root: Path, style_debug_mode: bool = False) -> str:
    """Load theme stylesheet from project root. Returns empty string on failure."""
    style_path = resolve_theme_stylesheet_path(theme, project_root)

    if not style_path.exists():
        return ""

    try:
        stylesheet = style_path.read_text(encoding="utf-8")
        if style_debug_mode:
            return f"{stylesheet}\n\n{_STYLE_DEBUG_OVERLAY}"
        return stylesheet
    except OSError:
        return ""
