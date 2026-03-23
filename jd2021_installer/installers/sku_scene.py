"""SkuScene ISC registration — add/remove maps from the game's song list.

JD2021 reads ``SkuScene_Maps_PC_All.isc`` to discover which maps are
available.  This module inserts/removes the ``SubSceneActor`` XML entry
that references a map's ``_MAIN_SCENE.isc``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from jd2021_installer.core.exceptions import GameWriterError

logger = logging.getLogger("jd2021.installers.sku_scene")

# SkuScene ISC location relative to the game root (V1 Parity: use data/ prefix)
SKU_SCENE_REL = Path("data/World/SkuScenes/SkuScene_Maps_PC_All.isc")


def _sku_scene_path(game_dir: str | Path) -> Path:
    """Resolve the SkuScene ISC path, trying common locations."""
    game = Path(game_dir)
    while game.name.lower() in ("world", "data"):
        game = game.parent
        
    # Direct path
    candidate = game / SKU_SCENE_REL
    if candidate.is_file():
        return candidate
    # Some installs have a nested cache/ or data/ folder
    for sub in ("", "bundle", "cache/bundle", "data"):
        alt = game / sub / SKU_SCENE_REL
        if alt.is_file():
            return alt
    return candidate  # Return default path (may not exist yet)


def _build_entry(codename: str) -> str:
    """Build the SubSceneActor XML block for a map."""
    return (
        f'\t\t<ACTORS NAME="SubSceneActor">\n'
        f'\t\t\t<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" '
        f'xFLIPPED="0" USERFRIENDLY="{codename}" '
        f'POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" '
        f'LUA="enginedata/actortemplates/subscene.tpl" '
        f'RELATIVEPATH="World/MAPS/{codename}/{codename}_MAIN_SCENE.isc" '
        f'EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">\n'
        f'\t\t\t\t<ENUM NAME="viewType" SEL="2" />\n'
        f'\t\t\t</SubSceneActor>\n'
        f'\t\t</ACTORS>'
    )


def is_registered(game_dir: str | Path, codename: str) -> bool:
    """Check whether a map is already registered in the SkuScene ISC."""
    isc = _sku_scene_path(game_dir)
    if not isc.is_file():
        return False
    content = isc.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        rf'RELATIVEPATH\s*=\s*"World/MAPS/{re.escape(codename)}/{re.escape(codename)}_MAIN_SCENE\.isc"',
        re.IGNORECASE,
    )
    return bool(pattern.search(content))


def register_map(game_dir: str | Path, codename: str) -> None:
    """Register a map in SkuScene_Maps_PC_All.isc.

    Idempotent — does nothing if the map is already registered.

    Raises:
        GameWriterError: If the ISC file cannot be found or modified.
    """
    isc = _sku_scene_path(game_dir)
    if not isc.is_file():
        raise GameWriterError(
            f"SkuScene ISC not found at {isc}. "
            "Ensure the game directory is set correctly."
        )

    content = isc.read_text(encoding="utf-8", errors="replace")

    if is_registered(game_dir, codename):
        logger.info("Map '%s' already registered in SkuScene", codename)
        return

    entry = _build_entry(codename)

    # Insert before the closing </Scene> tag
    close_scene_pattern = re.compile(r'([ \t]*</Scene>)', re.IGNORECASE)
    match = close_scene_pattern.search(content)
    if not match:
        raise GameWriterError(
            "Could not find </Scene> tag in SkuScene ISC. "
            "The file may be corrupted."
        )

    insert_pos = match.start()
    new_content = content[:insert_pos] + entry + "\n" + content[insert_pos:]

    isc.write_text(new_content, encoding="utf-8")
    logger.info("Registered map '%s' in SkuScene ISC", codename)


def unregister_map(game_dir: str | Path, codename: str) -> None:
    """Remove a map's entry from SkuScene_Maps_PC_All.isc.

    Idempotent — does nothing if the map is not registered.
    """
    isc = _sku_scene_path(game_dir)
    if not isc.is_file():
        logger.warning("SkuScene ISC not found; nothing to unregister")
        return

    content = isc.read_text(encoding="utf-8", errors="replace")

    # Match the full <ACTORS>...</ACTORS> block containing this map
    pattern = re.compile(
        r'[ \t]*<ACTORS\s+NAME="SubSceneActor">\s*'
        r'<SubSceneActor[^>]*RELATIVEPATH="World/MAPS/'
        + re.escape(codename) + r'/'
        + re.escape(codename) + r'_MAIN_SCENE\.isc"[^>]*>'
        r'.*?</SubSceneActor>\s*</ACTORS>\s*\n?',
        re.IGNORECASE | re.DOTALL,
    )

    new_content, count = pattern.subn("", content)
    if count > 0:
        isc.write_text(new_content, encoding="utf-8")
        logger.info("Unregistered map '%s' from SkuScene ISC", codename)
    else:
        logger.info("Map '%s' was not registered in SkuScene", codename)
