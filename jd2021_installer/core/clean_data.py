"""Reset installer-managed game data to a deterministic baseline.

Cleanup keeps that map and removes all custom additions,
without relying on cache files or bundled baseline snapshots.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jd2021_installer.core.path_discovery import is_valid_game_dir
from jd2021_installer.installers.sku_scene import unregister_map


_BASELINE_MAPS = {"getgetdown"}


@dataclass
class CleanDataResult:
    game_directory: Path
    seed_created: bool
    baseline_source: str
    original_maps_count: int
    removed_custom_maps: int
    removed_skuscene_entries: int
    removed_cooked_cache_maps: int


def _resolve_game_dir(configured_path: Optional[Path]) -> Path:
    if configured_path is None:
        raise RuntimeError("Game directory is not configured.")

    base = configured_path.resolve()
    candidates = [base, base / "jd21", *base.parents]

    for candidate in candidates:
        if candidate and is_valid_game_dir(candidate):
            return candidate

    raise RuntimeError(
        "Configured game directory is invalid. It must contain "
        "data/World/SkuScenes/SkuScene_Maps_PC_All.isc."
    )


def _maps_dir(game_dir: Path) -> Path:
    return game_dir / "data" / "World" / "MAPS"


def _skuscenes_file(game_dir: Path) -> Path:
    return game_dir / "data" / "World" / "SkuScenes" / "SkuScene_Maps_PC_All.isc"


def _itf_cooked_maps_dir(game_dir: Path) -> Path:
    return game_dir / "data" / "cache" / "itf_cooked" / "pc" / "world" / "maps"


def _list_map_dirs(maps_dir: Path) -> set[str]:
    if not maps_dir.is_dir():
        return set()
    return {child.name.lower() for child in maps_dir.iterdir() if child.is_dir()}


def _resolve_baseline_maps(game_dir: Path) -> tuple[set[str], str]:
    _ = game_dir
    return set(_BASELINE_MAPS), "builtin_pc"


def _remove_non_baseline_dirs(root_dir: Path, keep_names: set[str]) -> int:
    if not root_dir.is_dir():
        return 0

    removed = 0
    for child in root_dir.iterdir():
        if not child.is_dir():
            continue
        if child.name.lower() in keep_names:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    return removed


def _remove_non_baseline_skuscene_entries(game_dir: Path, removable_names: set[str]) -> int:
    sku_scene = _skuscenes_file(game_dir)
    if not sku_scene.is_file():
        return 0

    if not removable_names:
        return 0

    content = sku_scene.read_text(encoding="utf-8", errors="replace")
    present = {
        match.group(1).strip()
        for match in re.finditer(r'USERFRIENDLY\s*=\s*"([^"]+)"', content, re.IGNORECASE)
        if match.group(1).strip()
    }

    removed = 0
    for codename in sorted(present, key=str.lower):
        if codename.lower() not in removable_names:
            continue
        unregister_map(game_dir, codename)
        removed += 1
    return removed


def clean_game_data(configured_game_directory: Optional[Path]) -> CleanDataResult:
    """Reset custom content by restoring baseline MAPS/SkuScene/cache state."""
    game_dir = _resolve_game_dir(configured_game_directory)
    original_maps, baseline_source = _resolve_baseline_maps(game_dir)

    # Snapshot live map folders first; use this as a strict allow-list for
    # SkuScene removals so non-map USERFRIENDLY entries are never touched.
    live_maps_before = _list_map_dirs(_maps_dir(game_dir))
    removable_map_names = {name for name in live_maps_before if name not in original_maps}

    removed_custom_maps = _remove_non_baseline_dirs(_maps_dir(game_dir), original_maps)
    removed_skuscene_entries = _remove_non_baseline_skuscene_entries(game_dir, removable_map_names)
    removed_cooked_cache_maps = _remove_non_baseline_dirs(_itf_cooked_maps_dir(game_dir), original_maps)

    return CleanDataResult(
        game_directory=game_dir,
        seed_created=False,
        baseline_source=baseline_source,
        original_maps_count=len(original_maps),
        removed_custom_maps=removed_custom_maps,
        removed_skuscene_entries=removed_skuscene_entries,
        removed_cooked_cache_maps=removed_cooked_cache_maps,
    )
