import os
import shutil
import subprocess

def get_original_maps(rar_path, seven_zip_path):
    print("Scanning jd21.rar for original maps (this takes a few seconds)...")
    cmd = [seven_zip_path, "l", "-slt", rar_path]
    # Use errors='replace' to avoid UnicodeDecodeError from foreign characters in paths
    proc = subprocess.run(cmd, capture_output=True, text=True, errors='replace', check=True)
    original_maps = set()
    import re
    # Match jd21\data\World\MAPS\FolderName
    for line in proc.stdout.splitlines():
        match = re.search(r"jd21[/\\]data[/\\]World[/\\]MAPS[/\\]([^\/\\]+)", line, re.IGNORECASE)
        if match:
            folder_name = match.group(1).strip()
            original_maps.add(folder_name.lower())
    return original_maps

def clean_data():
    # Attempt to resolve project root and load game directory from settings
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    settings_path = os.path.join(project_root, "installer_settings.json")
    
    base_dir = r"D:\jd2021pc" # Default fallback
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r") as f:
                import json
                data = json.load(f)
                game_dir = data.get("game_directory")
                if game_dir:
                    # If game_dir is D:\jd2021pc\jd21, base_dir should be D:\jd2021pc
                    base_dir = os.path.dirname(os.path.abspath(game_dir))
                    print(f"Using game base directory from settings: {base_dir}")
        except Exception as e:
            print(f"Warning: Could not read settings, using default paths: {e}")

    jd21_dir = os.path.join(base_dir, "jd21")
    rar_path = os.path.join(base_dir, "jd21.rar")
    
    # Common 7-Zip installation paths
    seven_zip_candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        shutil.which("7z.exe") or ""
    ]
    seven_zip_path = next((p for p in seven_zip_candidates if p and os.path.exists(p)), None)

    maps_dir = os.path.join(jd21_dir, "data", "World", "MAPS")
    skuscene_dir = os.path.join(jd21_dir, "data", "World", "SkuScenes")
    itf_cooked_maps_dir = os.path.join(jd21_dir, "data", "cache", "itf_cooked", "pc", "world", "maps")

    if not os.path.exists(rar_path):
        print(f"Error: Archive not found at {rar_path}")
        return

    if not seven_zip_path or not os.path.exists(seven_zip_path):
        print("Error: 7-Zip (7z.exe) not found. Please install 7-Zip or add it to PATH.")
        return

    print(f"Cleaning data at: {jd21_dir}")
    print("This will selectively delete custom map folders and restore modified SkuScenes.")
    # confirm = input("Are you sure you want to proceed? (y/n): ")
    # if confirm.lower() != 'y':
    #     print("Cleanup aborted.")
    #     return

    original_maps = get_original_maps(rar_path, seven_zip_path)
    if not original_maps:
        print("Warning: Could not detect original maps from archive. Aborting.")
        return

    # 1. Clean extra maps
    if os.path.exists(maps_dir):
        cleaned_maps = 0
        for map_folder in os.listdir(maps_dir):
            if map_folder.lower() not in original_maps:
                folder_path = os.path.join(maps_dir, map_folder)
                if os.path.isdir(folder_path):
                    print(f"--> Deleting custom map folder: {map_folder}")
                    try:
                        shutil.rmtree(folder_path)
                        cleaned_maps += 1
                    except Exception as e:
                        print(f"Error deleting {folder_path}: {e}")
        if cleaned_maps == 0:
            print("No custom maps found to delete.")
        else:
            print(f"Deleted {cleaned_maps} custom map(s).")
    
    # 2. Restore SkuScenes
    print("Restoring SkuScenes from original archive...")
    # Delete the modified SkuScenes first to remove any generated/leftover files
    if os.path.exists(skuscene_dir):
        shutil.rmtree(skuscene_dir, ignore_errors=True)
        
    try:
        subprocess.run([
            seven_zip_path, "x", "-y", rar_path, 
            r"jd21\data\World\SkuScenes\*", 
            f"-o{base_dir}"
        ], check=True, stdout=subprocess.DEVNULL)
        print("--> Successfully restored SkuScenes.")
    except subprocess.CalledProcessError as e:
        print(f"Error restoring SkuScenes: {e}")

    # 3. Clean ITF Cooked cache (keep getgetdown)
    if os.path.exists(itf_cooked_maps_dir):
        print(f"Cleaning ITF Cooked cache in {itf_cooked_maps_dir}...")
        cleaned_cache = 0
        for map_folder in os.listdir(itf_cooked_maps_dir):
            if map_folder.lower() != "getgetdown":
                folder_path = os.path.join(itf_cooked_maps_dir, map_folder)
                if os.path.isdir(folder_path):
                    try:
                        shutil.rmtree(folder_path)
                        cleaned_cache += 1
                        print(f"--> Deleted cached map folder: {map_folder}")
                    except Exception as e:
                        print(f"Error deleting cache {folder_path}: {e}")
        if cleaned_cache == 0:
            print("No cached maps found to delete.")
        else:
            print(f"Deleted {cleaned_cache} cached map(s).")
            
    print("Cleanup complete! The installation state has been reset.")

if __name__ == "__main__":
    clean_data()
