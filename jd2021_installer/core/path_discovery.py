"""Tools for discovering and verifying the JD2021 installation directory."""

from __future__ import annotations

import logging
import os
import re
import time
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
_DEEP_SCAN_CACHE_TTL_S = 600.0
_DEEP_SCAN_CACHE: dict[Path, tuple[float, Optional[Path]]] = {}


def clear_deep_scan_cache(search_root: Optional[Path] = None) -> None:
    """Clear cached deep-scan results.

    Args:
        search_root: Optional root to clear a single cache entry. If omitted,
            clears all cached entries.
    """
    if search_root is None:
        _DEEP_SCAN_CACHE.clear()
        return
    _DEEP_SCAN_CACHE.pop(search_root.resolve(), None)


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
        logger.debug("Found JD2021 layout at: %s", candidate)
        return candidate

    # 2. Direct reference
    if is_valid_game_dir(search_root):
        logger.debug("Found JD2021 layout directly at: %s", search_root)
        return search_root

    # 3. Up one folder
    candidate = search_root.parent / "jd21"
    if is_valid_game_dir(candidate):
        logger.debug("Found JD2021 layout via parent: %s", candidate)
        return candidate

    logger.debug("Quick heuristics failed.")
    return None


def deep_scan_for_game_dir(search_root: Path) -> Optional[Path]:
    """Perform a recursive walk to find the game directory structure.

    This can take several seconds depending on the disk and search_root depth.
    
    Returns:
        The confirmed Game Root Path, or None if not found.
    """
    cache_key = search_root.resolve()
    now = time.monotonic()
    cached = _DEEP_SCAN_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _DEEP_SCAN_CACHE_TTL_S:
        logger.debug("Using cached deep-scan result for %s", search_root)
        return cached[1]

    logger.debug("Starting deep scan for JD2021 game directory in %s", search_root)
    
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
                    logger.debug("Deep scan found JD2021 game directory at: %s", game_dir)
                    _DEEP_SCAN_CACHE[cache_key] = (now, game_dir)
                    return game_dir
    except (OSError, PermissionError) as e:
        logger.debug("Deep scan interrupted by permissions or IO error: %s", e)
        
    logger.debug("Deep scan complete. No JD2021 game directory found.")
    _DEEP_SCAN_CACHE[cache_key] = (now, None)
    return None


def infer_codename(path: Path) -> str:
    """Infer a map codename from a file or directory path, cleaning platform suffixes.

    Ported from V1 source_analysis.py:_extract_codename_from_ipk_name.
    """
    # Use stem if it's a file, otherwise name if it's a directory
    base = path.stem if path.is_file() else path.name
    
    # Strip platform suffixes: _x360, _durango, _scarlett, _nx, _orbis, _prospero, _pc
    # Also handle some common garbage like (1), - Copy, etc.
    cleaned = re.sub(r"(_(x360|durango|scarlett|nx|orbis|prospero|pc))+$", "", base, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\((\d+)\)$", "", cleaned) # Remove (1), (2)
    
    logger.debug("Inferred codename '%s' from path: %s", cleaned, path)
    return cleaned
