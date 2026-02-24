import argparse
import subprocess
import sys
import os


def find_jd21_path(provided_path=None):
    # common default
    candidates = []
    if provided_path:
        candidates.append(provided_path)
    candidates.append(r"d:\jd2021pc\jd21")
    candidates.append(r"d:\jd2021pc")
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


def launch_installer_for(map_name, asset_html, nohud_html, jd21_cwd):
    print(f"\n========================================")
    print(f"Launching installer for {map_name} in new terminal...")
    print(f"========================================\n")
    python_exe = f'"{sys.executable}"'
    # Keep the terminal open so user can interact/review offsets
    cmd = f'start "Install {map_name}" cmd /k {python_exe} map_installer.py --map-name "{map_name}" --asset-html "{asset_html}" --nohud-html "{nohud_html}"'
    subprocess.Popen(cmd, shell=True, cwd=jd21_cwd)


def main():
    parser = argparse.ArgumentParser(description="Batch-install map folders. Provide a directory containing map subfolders (each with assets.html and nohud.html).")
    parser.add_argument("maps_dir", nargs="?", help="Path to folder that contains map subfolders (each with assets.html and nohud.html)")
    parser.add_argument("--jd21-path", help="Path to your JD installation root (optional). If not provided the script will try common defaults and then prompt.")
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
        launch_installer_for(name, asset, nohud, jd21)

    print("\nAll installers launched in separate terminals. Review offsets individually.")


if __name__ == "__main__":
    main()
