"""Reset installer-managed game data to a deterministic baseline manifest.

Primary baseline source is a bundled map codename manifest under assets.
Fallbacks are kept for resilience if the manifest is missing.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jd2021_installer.core.path_discovery import is_valid_game_dir
from jd2021_installer.installers.sku_scene import unregister_map


# Guardrail: a baseline with only a handful of maps is almost certainly invalid
# and can cause destructive cleanup (including boot-breaking SkuScene edits).
_MIN_SAFE_BASELINE_MAP_COUNT = 10


@dataclass
class CleanDataResult:
    game_directory: Path
    seed_created: bool
    baseline_source: str
    original_maps_count: int
    removed_custom_maps: int
    removed_skuscene_entries: int
    removed_cooked_cache_maps: int


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _baseline_manifest_path() -> Path:
    return _project_root() / "assets" / "clean_data_baseline" / "maps_baseline.json"


def _legacy_seed_metadata_path() -> Path:
    return _project_root() / "cache" / "clean_data_seed" / "seed_meta.json"


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


def _load_manifest_maps() -> Optional[set[str]]:
    path = _baseline_manifest_path()
    if not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    maps = payload.get("original_maps") if isinstance(payload, dict) else None
    if not isinstance(maps, list):
        return None

    normalized = {m.lower() for m in maps if isinstance(m, str) and m.strip()}
    return normalized or None


def _load_legacy_seed_maps() -> Optional[set[str]]:
    path = _legacy_seed_metadata_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    maps = payload.get("original_maps") if isinstance(payload, dict) else None
    if not isinstance(maps, list):
        return None

    normalized = {m.lower() for m in maps if isinstance(m, str) and m.strip()}
    return normalized or None


def _resolve_baseline_maps(game_dir: Path) -> tuple[set[str], str]:
    manifest_maps = _load_manifest_maps()
    if manifest_maps and len(manifest_maps) >= _MIN_SAFE_BASELINE_MAP_COUNT:
        return manifest_maps, "bundled_manifest"

    legacy_maps = _load_legacy_seed_maps()
    if legacy_maps and len(legacy_maps) >= _MIN_SAFE_BASELINE_MAP_COUNT:
        return legacy_maps, "legacy_seed_cache"

    live_maps = _list_map_dirs(_maps_dir(game_dir))
    if len(live_maps) >= _MIN_SAFE_BASELINE_MAP_COUNT:
        return live_maps, "live_game_fallback"

    raise RuntimeError(
        "Could not determine a safe baseline map set. "
        "Baseline manifest/cache appears incomplete and current MAPS content is too small to use as fallback."
    )


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
