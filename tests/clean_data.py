import json
import os
import re
import shutil
import subprocess


def _resolve_base_dir(project_root):
    settings_path = os.path.join(project_root, "installer_settings.json")
    base_dir = r"D:\jd2021pc"
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            game_dir = data.get("game_directory")
            if game_dir:
                base_dir = os.path.dirname(os.path.abspath(game_dir))
                print(f"Using game base directory from settings: {base_dir}")
        except Exception as exc:
            print(f"Warning: Could not read settings, using default paths: {exc}")
    return base_dir


def _resolve_7z_path():
    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        shutil.which("7z.exe") or "",
    ]
    return next((p for p in candidates if p and os.path.exists(p)), None)


def _load_seed_metadata(metadata_path):
    if not os.path.exists(metadata_path):
        return None
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        maps = data.get("original_maps")
        if not isinstance(maps, list):
            return None
        mtime = data.get("rar_mtime")
        if not isinstance(mtime, (int, float)):
            return None
        normalized = [m.lower() for m in maps if isinstance(m, str) and m.strip()]
        return {
            "rar_mtime": float(mtime),
            "original_maps": sorted(set(normalized)),
        }
    except Exception:
        return None


def _save_seed_metadata(metadata_path, rar_mtime, original_maps):
    os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
    payload = {
        "rar_mtime": float(rar_mtime),
        "original_maps": sorted(m.lower() for m in original_maps),
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _scan_original_maps_from_rar(rar_path, seven_zip_path):
    print("Seeding cache: scanning jd21.rar for default map folders...")
    proc = subprocess.run(
        [seven_zip_path, "l", rar_path],
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
    )
    original_maps = set()
    for line in proc.stdout.splitlines():
        match = re.search(r"jd21[/\\]data[/\\]World[/\\]MAPS[/\\]([^\/\\]+)", line, re.IGNORECASE)
        if match:
            original_maps.add(match.group(1).strip().lower())
    return original_maps


def _extract_skuscenes_snapshot(rar_path, seven_zip_path, cache_root):
    snapshot_root = os.path.join(cache_root, "SkuScenes")
    temp_root = os.path.join(cache_root, "_extract_tmp")

    if os.path.exists(temp_root):
        shutil.rmtree(temp_root, ignore_errors=True)
    os.makedirs(temp_root, exist_ok=True)

    print("Seeding cache: extracting default SkuScenes snapshot...")
    subprocess.run(
        [
            seven_zip_path,
            "x",
            "-y",
            rar_path,
            r"jd21\data\World\SkuScenes\*",
            f"-o{temp_root}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    extracted = os.path.join(temp_root, "jd21", "data", "World", "SkuScenes")
    if not os.path.isdir(extracted):
        raise RuntimeError("Failed to extract SkuScenes snapshot from archive.")

    if os.path.exists(snapshot_root):
        shutil.rmtree(snapshot_root, ignore_errors=True)
    shutil.copytree(extracted, snapshot_root)
    shutil.rmtree(temp_root, ignore_errors=True)


def _ensure_seed_cache(project_root, rar_path, seven_zip_path):
    cache_root = os.path.join(project_root, "cache", "clean_data_seed")
    metadata_path = os.path.join(cache_root, "seed_meta.json")
    snapshot_root = os.path.join(cache_root, "SkuScenes")
    rar_mtime = os.path.getmtime(rar_path)

    metadata = _load_seed_metadata(metadata_path)
    cache_valid = (
        metadata is not None
        and abs(metadata["rar_mtime"] - rar_mtime) < 0.001
        and os.path.isdir(snapshot_root)
    )

    if cache_valid and metadata is not None:
        return set(metadata["original_maps"]), snapshot_root

    if not seven_zip_path or not os.path.exists(seven_zip_path):
        raise RuntimeError("7-Zip is required to seed clean_data cache from jd21.rar.")

    original_maps = _scan_original_maps_from_rar(rar_path, seven_zip_path)
    if not original_maps:
        raise RuntimeError("Could not detect default map folders from jd21.rar.")

    _extract_skuscenes_snapshot(rar_path, seven_zip_path, cache_root)
    _save_seed_metadata(metadata_path, rar_mtime, original_maps)
    return original_maps, snapshot_root


def _restore_skuscenes_from_snapshot(snapshot_root, destination_root):
    if not os.path.isdir(snapshot_root):
        raise RuntimeError("Cached SkuScenes snapshot is missing.")
    if os.path.exists(destination_root):
        shutil.rmtree(destination_root, ignore_errors=True)
    shutil.copytree(snapshot_root, destination_root)


def _clean_custom_maps(maps_dir, original_maps):
    if not os.path.isdir(maps_dir):
        return 0
    removed = 0
    with os.scandir(maps_dir) as entries:
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name.lower() in original_maps:
                continue
            shutil.rmtree(entry.path, ignore_errors=True)
            removed += 1
            print(f"--> Deleted custom map folder: {entry.name}")
    return removed


def _clean_cooked_cache(itf_cooked_maps_dir):
    if not os.path.isdir(itf_cooked_maps_dir):
        return 0
    removed = 0
    with os.scandir(itf_cooked_maps_dir) as entries:
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name.lower() == "getgetdown":
                continue
            shutil.rmtree(entry.path, ignore_errors=True)
            removed += 1
            print(f"--> Deleted cooked cache folder: {entry.name}")
    return removed


def clean_data():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    base_dir = _resolve_base_dir(project_root)

    jd21_dir = os.path.join(base_dir, "jd21")
    rar_path = os.path.join(base_dir, "jd21.rar")
    seven_zip_path = _resolve_7z_path()

    maps_dir = os.path.join(jd21_dir, "data", "World", "MAPS")
    skuscene_dir = os.path.join(jd21_dir, "data", "World", "SkuScenes")
    itf_cooked_maps_dir = os.path.join(jd21_dir, "data", "cache", "itf_cooked", "pc", "world", "maps")

    if not os.path.exists(rar_path):
        print(f"Error: Archive not found at {rar_path}")
        return

    print(f"Cleaning data at: {jd21_dir}")
    print("Original selective mode with cache seeding enabled.")

    try:
        original_maps, skuscenes_snapshot = _ensure_seed_cache(project_root, rar_path, seven_zip_path)
    except Exception as exc:
        print(f"Error seeding cache from archive: {exc}")
        return

    removed_maps = _clean_custom_maps(maps_dir, original_maps)
    if removed_maps == 0:
        print("No custom maps found to delete.")
    else:
        print(f"Deleted {removed_maps} custom map(s).")

    try:
        _restore_skuscenes_from_snapshot(skuscenes_snapshot, skuscene_dir)
        print("--> Restored SkuScenes from local cache snapshot.")
    except Exception as exc:
        print(f"Error restoring SkuScenes from cache: {exc}")
        return

    removed_cache = _clean_cooked_cache(itf_cooked_maps_dir)
    if removed_cache == 0:
        print("No cooked cache maps found to delete.")
    else:
        print(f"Deleted {removed_cache} cooked cache map(s).")

    print("Cleanup complete! Installation state has been reset.")


if __name__ == "__main__":
    clean_data()
