"""Tools for discovering and verifying the JD2021 installation directory."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jd2021.core.path_discovery")

# Folders to skip during a deep recursive scan to save time
_SCAN_SKIP_DIRS = {
    ".git", "__pycache__", "logs", "downloads", "cache",
    "main_scene_extracted", "ipk_extracted", "tools", "xtx_extractor"
}

_TARGET_FILE = "SkuScene_Maps_PC_All.isc"
_TARGET_SUBPATH = ("data", "World", "SkuScenes", _TARGET_FILE)


def is_valid_game_dir(candidate: Path) -> bool:
    """Verifies a folder contains the essential SkuScene file."""
    if not candidate or not candidate.is_dir():
        return False
    sku_path = candidate.joinpath(*_TARGET_SUBPATH)
    return sku_path.is_file()


def resolve_game_paths(search_root: Path) -> Optional[Path]:
    """Fast heuristics to locate the JD2021 Game Data directory.

    Checks:
    1. search_root/jd21/  (Classic mod layout beside the tool)
    2. search_root/       (User pointed directly to the root)
    3. search_root/../jd21/ (Tool is nested)

    Returns:
        The valid Game Root Path or None if not found via heuristics.
    """
    logger.debug("Running quick heuristics for JD2021 game directory starting at: %s", search_root)
    
    # 1. Classic layout: tool_root/jd21
    candidate = search_root / "jd21"
    if is_valid_game_dir(candidate):
        logger.info("Found JD2021 layout at: %s", candidate)
        return candidate

    # 2. Direct reference
    if is_valid_game_dir(search_root):
        logger.info("Found JD2021 layout directly at: %s", search_root)
        return search_root

    # 3. Up one folder
    candidate = search_root.parent / "jd21"
    if is_valid_game_dir(candidate):
        logger.info("Found JD2021 layout via parent: %s", candidate)
        return candidate

    logger.debug("Quick heuristics failed.")
    return None


def deep_scan_for_game_dir(search_root: Path) -> Optional[Path]:
    """Perform a recursive walk to find the game directory structure.

    This can take several seconds depending on the disk and search_root depth.
    
    Returns:
        The confirmed Game Root Path, or None if not found.
    """
    logger.info("Starting deep scan for JD2021 game directory in %s", search_root)
    
    try:
        for root, dirs, files in os.walk(search_root):
            # Prune skipped dirs to speed up walk
            dirs[:] = [d for d in dirs if d not in _SCAN_SKIP_DIRS]
            
            if _TARGET_FILE in files:
                found_path = Path(root) / _TARGET_FILE
                # Validate the path matches the expected nested structure
                # jd21_dir / data / World / SkuScenes / SkuScene_Maps_PC_All.isc
                parts = found_path.parts
                if len(parts) >= 4 and parts[-4:] == tuple(_TARGET_SUBPATH):
                    game_dir = found_path.parents[3]
                    logger.info("Deep scan found JD2021 game directory at: %s", game_dir)
                    return game_dir
    except (OSError, PermissionError) as e:
        logger.warning("Deep scan interrupted by permissions or IO error: %s", e)
        
    logger.info("Deep scan complete. No JD2021 game directory found.")
    return None
