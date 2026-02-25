import argparse
import subprocess
import sys
import os


def find_jd21_path(provided_path=None):
    candidates = []
    if provided_path:
        candidates.append(provided_path)
    # Default: the script lives in the project root alongside map_installer.py
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    for p in candidates:
        if p and os.path.isdir(p):
            return p
    return None


def check_executable(name):
    """Check if an executable is available on PATH."""
    try:
        subprocess.run([name, "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def preflight_check(jd21):
    """Run pre-flight checks before launching batch installers. Returns True if all pass."""
    print("--- Pre-flight Checks ---")
    failures = 0

    def ok(msg):
        print(f"  [OK] {msg}")

    def fail(msg):
        nonlocal failures
        failures += 1
        print(f"  [FAIL] {msg}")

    if os.path.isfile(os.path.join(jd21, "map_installer.py")):
        ok("map_installer.py found")
    else:
        fail(f"map_installer.py not found in {jd21}")

    if os.path.isdir(os.path.join(jd21, "jd21")):
        ok("JD2021 game data (jd21/)")
    else:
        fail(f"jd21/ directory not found in {jd21}")

    if check_executable("ffmpeg"):
        ok("ffmpeg found")
    else:
        fail("ffmpeg not found in PATH (install from https://ffmpeg.org)")

    print("-------------------------")

    if failures > 0:
        print(f"\nERROR: {failures} critical check(s) failed. Cannot proceed.")
        return False
    return True


def collect_map_folders(root_dir):
    """Return list of (mapname, asset_html, nohud_html) found under root_dir.

    Expects structure:
      root_dir/<mapFolder>/assets.html
      root_dir/<mapFolder>/nohud.html
    """
    out = []
    for entry in os.listdir(root_dir):
        folder = os.path.join(root_dir, entry)
        if not os.path.isdir(folder):
            continue
        asset = os.path.join(folder, "assets.html")
        nohud = os.path.join(folder, "nohud.html")
        if os.path.isfile(asset) and os.path.isfile(nohud):
            out.append((entry, asset, nohud))
    return out


def launch_installer_for(map_name, asset_html, nohud_html, jd21_cwd, quality="ultra_hd"):
    print(f"\n========================================")
    print(f"Launching installer for {map_name} in new terminal...")
    print(f"========================================\n")
    # Build inner command with proper quoting for paths that may contain spaces
    inner_cmd_parts = [
        sys.executable, "map_installer.py",
        "--map-name", map_name,
        "--asset-html", asset_html,
        "--nohud-html", nohud_html,
        "--quality", quality,
    ]

    # Pass saved sync config if one exists for this map
    config_path = os.path.join(jd21_cwd, "map_configs", f"{map_name}.json")
    if os.path.isfile(config_path):
        inner_cmd_parts += ["--sync-config", config_path]
        print(f"    Using saved config: {config_path}")

    inner_cmd = subprocess.list2cmdline(inner_cmd_parts)
    # cmd /k strips the outermost quotes (old behavior), leaving the inner command intact
    cmd = f'start "Install {map_name}" cmd /k "{inner_cmd}"'
    subprocess.Popen(cmd, shell=True, cwd=jd21_cwd)


def main():
    parser = argparse.ArgumentParser(description="Batch-install map folders. Provide a directory containing map subfolders (each with assets.html and nohud.html).")
    parser.add_argument("maps_dir", nargs="?", help="Path to folder that contains map subfolders (each with assets.html and nohud.html)")
    parser.add_argument("--jd21-path", help="Path to your JD installation root (optional). If not provided the script will try common defaults and then prompt.")
    parser.add_argument("--quality", choices=["ultra_hd", "ultra", "high_hd", "high", "mid_hd", "mid", "low_hd", "low"],
                        default="ultra_hd", help="Video quality for all maps (default: ultra_hd)")
    args = parser.parse_args()

    maps_root = args.maps_dir or os.getcwd()
    if not os.path.isdir(maps_root):
        print(f"Error: maps directory not found: {maps_root}")
        return

    jd21 = find_jd21_path(args.jd21_path)
    if not jd21:
        print("Could not locate JD installation directory automatically.")
        resp = input("Enter path to your JD root (or leave empty to abort): ").strip()
        if resp:
            if os.path.isdir(resp):
                jd21 = resp
            else:
                print(f"Provided path does not exist: {resp}")
                return
        else:
            print("Aborting: JD install path not provided.")
            print("Usage: batch_install_maps.py <maps_dir> [--jd21-path <path>] -- maps_dir should contain map folders with assets.html and nohud.html")
            return

    if not preflight_check(jd21):
        return

    found = collect_map_folders(maps_root)
    if not found:
        print(f"No valid map folders found under {maps_root}. Each map folder must contain assets.html and nohud.html.")
        return

    print(f"Found {len(found)} map(s) to install. JD root: {jd21}")
    for name, asset, nohud in found:
        launch_installer_for(name, asset, nohud, jd21, quality=args.quality)

    print("\nAll installers launched in separate terminals. Review offsets individually.")


if __name__ == "__main__":
    main()
