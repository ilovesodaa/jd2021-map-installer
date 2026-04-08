import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jd2021_installer.core.clean_data import clean_game_data


def _resolve_game_dir_from_settings(project_root: Path) -> Path:
    settings_path = project_root / "installer_settings.json"
    if not settings_path.is_file():
        raise RuntimeError("installer_settings.json was not found.")

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    game_dir = payload.get("game_directory")
    if not game_dir:
        raise RuntimeError("game_directory is not set in installer_settings.json.")
    return Path(str(game_dir))


def clean_data() -> None:
    project_root = Path(__file__).resolve().parents[1]

    try:
        configured_game_dir = _resolve_game_dir_from_settings(project_root)
        result = clean_game_data(configured_game_dir)
    except Exception as exc:
        print(f"Error: {exc}")
        return

    print(f"Cleaning data at: {result.game_directory}")
    print(f"Baseline source: {result.baseline_source}")
    if result.seed_created:
        print("Baseline cleanup cache was seeded from current game state.")
    print(f"Baseline maps tracked: {result.original_maps_count}")
    print(f"Deleted custom maps: {result.removed_custom_maps}")
    print(f"Deleted SkuScene entries: {result.removed_skuscene_entries}")
    print(f"Deleted cooked cache maps: {result.removed_cooked_cache_maps}")
    print("Cleanup complete! Installation state has been reset.")


if __name__ == "__main__":
    clean_data()
