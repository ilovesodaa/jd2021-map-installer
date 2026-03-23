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


def _build_actor_entry(codename: str) -> str:
    """Build the SongDesc Actor XML block for a map."""
    return (
        f'\t\t<ACTORS NAME="Actor">\n'
        f'\t\t\t<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" '
        f'xFLIPPED="0" USERFRIENDLY="{codename}" '
        f'POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" '
        f'LUA="world/maps/{codename}/songdesc.tpl">\n'
        f'\t\t\t\t<COMPONENTS NAME="JD_SongDescComponent">\n'
        f'\t\t\t\t\t<JD_SongDescComponent />\n'
        f'\t\t\t\t</COMPONENTS>\n'
        f'\t\t\t</Actor>\n'
        f'\t\t</ACTORS>'
    )


def _build_coverflow_entry(codename: str) -> str:
    """Build the CoverflowSkuSongs XML blocks for a map."""
    return (
        f'\t\t\t\t\t\t\t<CoverflowSkuSongs>\n'
        f'\t\t\t\t\t\t\t\t<CoverflowSong name="{codename}" '
        f'cover_path="world/maps/{codename}/menuart/actors/{codename}_cover_generic.act">\n'
        f'\t\t\t\t\t\t\t\t</CoverflowSong>\n'
        f'\t\t\t\t\t\t\t</CoverflowSkuSongs>\n'
        f'\t\t\t\t\t\t\t<CoverflowSkuSongs>\n'
        f'\t\t\t\t\t\t\t\t<CoverflowSong name="{codename}" '
        f'cover_path="world/maps/{codename}/menuart/actors/{codename}_cover_online.act">\n'
        f'\t\t\t\t\t\t\t\t</CoverflowSong>\n'
        f'\t\t\t\t\t\t\t</CoverflowSkuSongs>'
    )


def is_registered(game_dir: str | Path, codename: str) -> bool:
    """Check whether a map is already registered in the SkuScene ISC."""
    isc = _sku_scene_path(game_dir)
    if not isc.is_file():
        return False
    content = isc.read_text(encoding="utf-8", errors="replace")
    # Check for the main actor entry
    pattern = re.compile(
        rf'USERFRIENDLY\s*=\s*"{re.escape(codename)}"',
        re.IGNORECASE,
    )
    return bool(pattern.search(content))


def register_map(game_dir: str | Path, codename: str) -> None:
    """Register a map in SkuScene_Maps_PC_All.isc.

    Idempotent — does nothing if the map is already registered.
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

    # 1. Insert Actor block before <sceneConfigs>
    actor_entry = _build_actor_entry(codename)
    scene_configs_pattern = re.compile(r'([ \t]*<sceneConfigs>)', re.IGNORECASE)
    match_sc = scene_configs_pattern.search(content)
    if not match_sc:
        raise GameWriterError("Could not find <sceneConfigs> in SkuScene ISC")
    
    insert_pos_sc = match_sc.start()
    content = content[:insert_pos_sc] + actor_entry + "\n" + content[insert_pos_sc:]

    # 2. Insert Coverflow blocks before </JD_SongDatabaseSceneConfig>
    coverflow_entry = _build_coverflow_entry(codename)
    db_config_pattern = re.compile(r'([ \t]*</JD_SongDatabaseSceneConfig>)', re.IGNORECASE)
    match_db = db_config_pattern.search(content)
    if not match_db:
        # Fallback for some ISC variations: look for </sceneConfigs> or just before </Scene>
        match_db = re.compile(r'([ \t]*</sceneConfigs>)', re.IGNORECASE).search(content)
        if not match_db:
            match_db = re.compile(r'([ \t]*</Scene>)', re.IGNORECASE).search(content)

    if match_db:
        insert_pos_db = match_db.start()
        content = content[:insert_pos_db] + coverflow_entry + "\n" + content[insert_pos_db:]
    else:
        logger.warning("Could not find insertion point for Coverflow entries in SkuScene")

    isc.write_text(content, encoding="utf-8")
    logger.info("Registered map '%s' in SkuScene ISC (Actor + Coverflow)", codename)


def unregister_map(game_dir: str | Path, codename: str) -> None:
    """Remove a map's entry from SkuScene_Maps_PC_All.isc."""
    isc = _sku_scene_path(game_dir)
    if not isc.is_file():
        logger.warning("SkuScene ISC not found; nothing to unregister")
        return

    content = isc.read_text(encoding="utf-8", errors="replace")

    # 1. Remove Actor block
    actor_pattern = re.compile(
        r'[ \t]*<ACTORS\s+NAME="Actor">\s*'
        r'<Actor[^>]*USERFRIENDLY="' + re.escape(codename) + r'"[^>]*>'
        r'.*?</ACTORS>\s*\n?',
        re.IGNORECASE | re.DOTALL,
    )
    content, count_act = actor_pattern.subn("", content)

    # 2. Remove Coverflow blocks
    cover_pattern = re.compile(
        r'[ \t]*<CoverflowSkuSongs>\s*'
        r'<CoverflowSong[^>]*name="' + re.escape(codename) + r'"[^>]*>'
        r'.*?</CoverflowSkuSongs>\s*\n?',
        re.IGNORECASE | re.DOTALL,
    )
    content, count_cov = cover_pattern.subn("", content)

    if count_act > 0 or count_cov > 0:
        # Clean up excessive newlines
        content = re.sub(r'\n{3,}', '\n\n', content)
        isc.write_text(content, encoding="utf-8")
        logger.info("Unregistered map '%s' from SkuScene ISC", codename)
    else:
        logger.info("Map '%s' was not registered in SkuScene", codename)
