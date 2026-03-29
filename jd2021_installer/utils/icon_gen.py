"""Generate default SVG icons used by the UI if they are missing."""

from __future__ import annotations

from pathlib import Path

_ICON_SVGS: dict[str, str] = {
    "install.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"M11 4h2v8.2l2.8-2.8 1.4 1.4-5.2 5.2-5.2-5.2 1.4-1.4 2.8 2.8z\"/><path fill=\"#EAF0FF\" d=\"M5 18h14v2H5z\"/></svg>""",
    "preflight.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"m9.4 16.6-3.7-3.7 1.4-1.4 2.3 2.3 7.4-7.4 1.4 1.4z\"/></svg>""",
    "reset.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"M12 5a7 7 0 1 1-6.7 9h2.1A5 5 0 1 0 9 8.4V11H3V5h2v2.1A8.9 8.9 0 0 1 12 5\"/></svg>""",
    "apply.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"m8.9 16.8-4.7-4.7 1.4-1.4 3.3 3.3 2.1-2.1 1.4 1.4zm8-9.8 1.4 1.4-7.8 7.8-1.4-1.4z\"/></svg>""",
    "play.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"M8 5.5v13l10-6.5z\"/></svg>""",
    "stop.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><rect x=\"7\" y=\"7\" width=\"10\" height=\"10\" rx=\"1.8\" fill=\"#EAF0FF\"/></svg>""",
    "rewind.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"M11 5.5v13L2.5 12zM21 5.5v13L12.5 12z\"/></svg>""",
    "forward.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"M13 5.5v13l8.5-6.5zM3 5.5v13l8.5-6.5z\"/></svg>""",
    "folder.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"M3.5 6.5A2.5 2.5 0 0 1 6 4h4l2 2h6A2.5 2.5 0 0 1 20.5 8.5v8A2.5 2.5 0 0 1 18 19H6a2.5 2.5 0 0 1-2.5-2.5z\"/></svg>""",
    "settings.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path fill=\"#EAF0FF\" d=\"m20.7 13.7-.9-.5c.1-.4.2-.8.2-1.2s-.1-.8-.2-1.2l.9-.5a1 1 0 0 0 .4-1.4l-1.3-2.2a1 1 0 0 0-1.3-.4l-.9.5a8 8 0 0 0-2.1-1.2V3.6a1 1 0 0 0-1-1h-2.6a1 1 0 0 0-1 1v1.1c-.8.2-1.5.6-2.1 1.1l-.9-.5a1 1 0 0 0-1.3.4L3.3 9a1 1 0 0 0 .4 1.4l.9.5c-.1.4-.2.8-.2 1.2s.1.8.2 1.2l-.9.5a1 1 0 0 0-.4 1.4l1.3 2.2a1 1 0 0 0 1.3.4l.9-.5c.6.5 1.3.9 2.1 1.2v1.1a1 1 0 0 0 1 1h2.6a1 1 0 0 0 1-1v-1.1c.8-.2 1.5-.6 2.1-1.1l.9.5a1 1 0 0 0 1.3-.4l1.3-2.2a1 1 0 0 0-.4-1.4M12 15.3A3.3 3.3 0 1 1 12 8.7a3.3 3.3 0 0 1 0 6.6\"/></svg>""",
}


def ensure_default_icons(project_root: Path) -> Path:
    """Ensure required SVG icons exist under assets/icons and return that folder."""
    icon_dir = project_root / "assets" / "icons"
    icon_dir.mkdir(parents=True, exist_ok=True)

    for filename, svg in _ICON_SVGS.items():
        icon_path = icon_dir / filename
        if icon_path.exists():
            continue
        icon_path.write_text(svg, encoding="utf-8")

    return icon_dir
