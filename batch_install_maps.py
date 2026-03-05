"""Batch-install map folders sequentially with two-phase execution.

Phase 1: Download all maps' assets first (while CDN links are fresh)
Phase 2: Process all maps locally (extraction, conversion, registration)

This two-phase approach prevents link expiration when installing many maps,
since private CDN links (nohud.html) have time-limited auth tokens.

Usage:
    python batch_install_maps.py MapDownloads
    python batch_install_maps.py MapDownloads --skip-existing
    python batch_install_maps.py MapDownloads --quality high --only TikTok Starships
"""

import argparse
import os
import sys
import time
import traceback
import urllib.error

from log_config import get_logger, setup_cli_logging
import map_installer
import map_downloader

logger = get_logger("batch_install")


def collect_map_folders(root_dir):
    """Return list of (mapname, asset_html, nohud_html) found under root_dir.

    Expects structure:
      root_dir/<mapFolder>/assets.html
      root_dir/<mapFolder>/nohud.html
    """
    out = []
    for entry in sorted(os.listdir(root_dir)):
        folder = os.path.join(root_dir, entry)
        if not os.path.isdir(folder):
            continue

        # Accept common filename variants to reduce setup friction:
        # assets.html / asset.html / ASSETS.HTML, etc.
        asset = None
        nohud = None
        try:
            htmls = [os.path.join(folder, n) for n in os.listdir(folder)
                     if os.path.isfile(os.path.join(folder, n)) and n.lower().endswith('.html')]
        except OSError:
            htmls = []

        for h in htmls:
            name = os.path.basename(h).lower()
            if "nohud" in name and not nohud:
                nohud = h
            elif "asset" in name and not asset:
                asset = h

        # Fallback: if names are unusual, use two HTML files and infer by exclusion.
        if len(htmls) >= 2:
            if not nohud:
                for h in htmls:
                    if "nohud" in os.path.basename(h).lower():
                        nohud = h
                        break
            if not asset:
                for h in htmls:
                    if h != nohud:
                        asset = h
                        break

        if asset and nohud:
            out.append((entry, asset, nohud))
    return out


def is_map_installed(map_name, jd21_dir):
    """Check if a map already has an installed directory in the game data."""
    target = os.path.join(jd21_dir, "data", "World", "MAPS", map_name)
    return os.path.isdir(target)


# ---- Pipeline step groups ----
# Steps 1-2 require network (download assets while links are valid)
DOWNLOAD_STEPS = [
    ("Clean previous builds",                   map_installer.step_01_clean),
    ("Download assets from JDU servers",        map_installer.step_02_download),
]

# Steps 3-14 are local-only (no network needed, safe to run after links expire)
PROCESS_STEPS = [
    ("Extract scene archives",                  map_installer.step_03_extract_scenes),
    ("Unpack IPK archives",                     map_installer.step_04_unpack_ipk),
    ("Decode MenuArt textures",                 map_installer.step_05_decode_menuart),
    ("Validate MenuArt covers",                 map_installer.step_05b_validate_menuart),
    ("Generate UbiArt config files",            map_installer.step_06_generate_configs),
    ("Convert choreography/karaoke tapes",      map_installer.step_07_convert_tapes),
    ("Convert cinematic tapes",                 map_installer.step_08_convert_cinematics),
    ("Process ambient sounds",                  map_installer.step_09_process_amb),
    ("Decode pictograms",                       map_installer.step_10_decode_pictos),
    ("Extract moves & autodance",               map_installer.step_11_extract_moves),
    ("Convert audio",                           map_installer.step_12_convert_audio),
    ("Copy gameplay video",                     map_installer.step_13_copy_video),
    ("Register in SkuScene",                    map_installer.step_14_register_sku),
]


def detect_existing_quality(download_dir):
    """Check download_dir for an existing gameplay .webm and return its quality tier.

    Returns the quality string (e.g. 'ULTRA_HD', 'ULTRA') or None if no video found.
    """
    if not os.path.isdir(download_dir):
        return None
    for f in os.listdir(download_dir):
        if not f.endswith('.webm') or 'MapPreview' in f or 'VideoPreview' in f:
            continue
        for q, pattern in map_downloader.QUALITY_PATTERNS.items():
            if f.endswith(pattern):
                return q
    return None


def create_state(map_name, asset_html, nohud_html, jd_dir, quality="ultra_hd"):
    """Create a PipelineState for a map, loading saved sync config."""
    detected_name = map_name
    if os.path.exists(asset_html):
        urls = map_downloader.extract_urls(asset_html)
        codename = map_downloader.extract_codename_from_urls(urls)
        if codename:
            detected_name = codename

    # Auto-detect quality from existing downloads — use it instead of the
    # global default so already-downloaded videos are reused as-is.
    download_dir = os.path.dirname(asset_html)
    existing_quality = detect_existing_quality(download_dir)
    effective_quality = quality
    if existing_quality:
        effective_quality = existing_quality
        if existing_quality.upper() != quality.upper():
            print(f"    Auto-detected existing video quality: {existing_quality} "
                  f"(requested {quality.upper()})")

    state = map_installer.PipelineState(
        map_name=detected_name,
        asset_html=asset_html,
        nohud_html=nohud_html,
        jd_dir=jd_dir,
        quality=effective_quality,
    )

    return state


def run_steps(state, steps):
    """Run a list of pipeline steps on the given state. Raises on error."""
    for step_name, step_fn in steps:
        if map_installer._interrupted:
            raise RuntimeError(f"Interrupted before '{step_name}'")
        step_fn(state)


def main():
    # Load persistent settings for defaults
    settings = map_installer.load_settings()

    parser = argparse.ArgumentParser(
        description="Batch-install map folders using two-phase execution. "
                    "Phase 1: Download all maps first (before links expire). "
                    "Phase 2: Process all maps locally.")
    parser.add_argument(
        "maps_dir", nargs="?",
        help="Path to folder containing map subfolders "
             "(default: MapDownloads in the script directory)")
    parser.add_argument(
        "--jd21-path",
        help="Path to JD installation root (auto-detected if omitted)")
    parser.add_argument(
        "--quality",
        choices=["ultra_hd", "ultra", "high_hd", "high",
                 "mid_hd", "mid", "low_hd", "low"],
        default=settings["default_quality"],
        help=f"Video quality for all maps (default: {settings['default_quality']})")
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip maps that already have an installed folder in MAPS/")
    parser.add_argument(
        "--only", nargs="+", metavar="MAP",
        help="Only install these specific map names")
    parser.add_argument(
        "--exclude", "--ignore", nargs="+", metavar="MAP",
        help="Skip these specific map names")
    parser.add_argument(
        "--ignore-non-ascii", action="store_true",
        help="Skip maps that contain non-ASCII characters in their name")
    parser.add_argument(
        "--codename", nargs="+", metavar="CODENAME",
        help="Fetch HTML for these codenames via JDH_Downloader before batch install. "
             "Each codename runs a separate browser session.")
    parser.add_argument(
        "--interactive", action="store_true", default=True,
        help="Prompt for action when non-ASCII metadata is found (default: True). "
             "Use --auto-strip to forcefully auto-strip instead.")
    parser.add_argument(
        "--auto-strip", action="store_true",
        help="Silently auto-strip non-ASCII metadata instead of prompting.")
    args = parser.parse_args()

    # Default maps directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    maps_root = args.maps_dir or os.path.join(script_dir, "MapDownloads")
    maps_root = os.path.abspath(maps_root)

    if not os.path.isdir(maps_root):
        # If --codename is used, create MapDownloads/ if it doesn't exist
        if args.codename:
            os.makedirs(maps_root, exist_ok=True)
        else:
            print(f"Error: maps directory not found: {maps_root}")
            sys.exit(1)

    jd_dir = args.jd21_path or script_dir

    # Set up logging for the batch run
    setup_cli_logging("batch")

    # --- FETCH PHASE: download HTML for any --codename arguments ---
    if args.codename:
        print(f"\n{'='*60}")
        print(f" FETCH PHASE: Retrieving HTML for {len(args.codename)} codename(s)")
        print(f"{'='*60}")

        fetch_ok = 0
        fetch_fail = 0
        for cn in args.codename:
            print(f"\n--- Fetching: {cn} ---")
            try:
                map_installer.fetch_html_via_downloader(cn, maps_root)
                fetch_ok += 1
            except RuntimeError as e:
                print(f"  FAILED: {e}")
                fetch_fail += 1

        print(f"\n{'='*60}")
        print(f" FETCH COMPLETE: {fetch_ok} OK, {fetch_fail} failed")
        print(f"{'='*60}")

        if fetch_ok == 0:
            print("No codenames fetched successfully. Aborting.")
            sys.exit(1)

    # Discover maps
    found = collect_map_folders(maps_root)
    if not found:
        print(f"No valid map folders found under {maps_root}.")
        print("Expected each map folder to contain asset/nohud HTML files.")

        # Interactive recovery path for users who skipped docs.
        if sys.stdin.isatty():
            print("\nQuick recovery:")
            print("  Enter codenames to fetch now (space-separated),")
            print("  or press Enter to abort.")
            raw_codes = input("Codenames: ").strip()
            if raw_codes:
                codes = [c for c in raw_codes.split() if c]
                if codes:
                    ok = 0
                    for cn in codes:
                        print(f"\n--- Fetching: {cn} ---")
                        try:
                            map_installer.fetch_html_via_downloader(cn, maps_root)
                            ok += 1
                        except RuntimeError as e:
                            print(f"  FAILED: {e}")
                    if ok > 0:
                        found = collect_map_folders(maps_root)
                        print(f"\nRecovered {ok} map folder(s). Continuing...")

        if not found:
            print("Nothing to install. Tip: use --codename MAP1 MAP2 to auto-fetch HTML first.")
            sys.exit(1)

    # Preflight using first map's HTMLs
    if settings["skip_preflight"]:
        print("    Pre-flight skipped (disabled in settings)")
    else:
        first_asset, first_nohud = found[0][1], found[0][2]
        if not map_installer.preflight_check(jd_dir, first_asset, first_nohud,
                                             interactive=False):
            sys.exit(1)

    # Resolve game paths for skip-existing check
    game_paths = map_installer.resolve_game_paths(jd_dir)
    jd21_dir = game_paths['jd21_dir'] if game_paths else os.path.join(jd_dir, "jd21")

    # Filter maps
    to_install = []
    skipped = []
    for name, asset, nohud in found:
        if args.only and name not in args.only:
            skipped.append((name, "not in --only list"))
            continue
        if args.exclude and name in args.exclude:
            skipped.append((name, "excluded via --exclude"))
            continue
        if args.skip_existing and is_map_installed(name, jd21_dir):
            skipped.append((name, "already installed"))
            continue
        if args.ignore_non_ascii and any(ord(c) > 127 for c in name):
            skipped.append((name, "contains non-ASCII characters"))
            continue
        to_install.append((name, asset, nohud))

    # Summary before starting
    total = len(to_install)
    print(f"\n{'='*60}")
    print(f" BATCH INSTALL -- TWO-PHASE MODE")
    print(f" Maps directory: {maps_root}")
    print(f" Quality:        {args.quality.upper()}")
    print(f" To install:     {total} map(s)")
    if skipped:
        print(f" Skipped:        {len(skipped)} map(s)")
        for name, reason in skipped:
            print(f"   - {name}: {reason}")
    print(f"{'='*60}")

    if not to_install:
        print("Nothing to install.")
        return

    # =========================================================
    #  PHASE 1: Download all maps' assets while links are fresh
    # =========================================================
    print(f"\n{'='*60}")
    print(f" PHASE 1: DOWNLOADING ALL MAPS ({total} maps)")
    print(f" Downloading first to prevent link expiration")
    print(f"{'='*60}")

    states = []
    download_results = {}

    for i, (name, asset, nohud) in enumerate(to_install, 1):
        if map_installer._interrupted:
            logger.warning("Interrupted before downloading '%s'. Stopping.", name)
            break

        print(f"\n--- [{i}/{total}] Downloading: {name} ---")
        start_time = time.time()

        try:
            state = create_state(name, asset, nohud, jd_dir,
                                 quality=args.quality)
            state._interactive = not args.auto_strip

            run_steps(state, DOWNLOAD_STEPS)
            elapsed = time.time() - start_time
            download_results[name] = ("OK", f"{elapsed:.1f}s")
            states.append((name, state))
            print(f"  Download complete ({elapsed:.1f}s)")

        except (RuntimeError, OSError, urllib.error.URLError) as e:
            download_results[name] = ("FAILED", str(e))
            print(f"  Download FAILED: {e}")
            traceback.print_exc()

    # Phase 1 summary
    dl_ok = sum(1 for s, _ in download_results.values() if s == "OK")
    dl_fail = sum(1 for s, _ in download_results.values() if s == "FAILED")
    print(f"\n{'='*60}")
    print(f" PHASE 1 COMPLETE: {dl_ok} downloaded, {dl_fail} failed")
    print(f"{'='*60}")

    if not states:
        print("No maps were downloaded successfully. Aborting.")
        return

    # =========================================================
    #  PHASE 2: Process all downloaded maps locally
    # =========================================================
    print(f"\n{'='*60}")
    print(f" PHASE 2: PROCESSING ALL MAPS ({len(states)} maps)")
    print(f" All local -- no network needed")
    print(f"{'='*60}")

    process_results = {}

    for i, (name, state) in enumerate(states, 1):
        if map_installer._interrupted:
            logger.warning("Interrupted before processing '%s'. Stopping.", name)
            break

        print(f"\n--- [{i}/{len(states)}] Processing: {name} ---")
        start_time = time.time()

        try:
            run_steps(state, PROCESS_STEPS)

            elapsed = time.time() - start_time
            process_results[name] = ("OK", f"{elapsed:.1f}s")
            print(f"  Processing complete ({elapsed:.1f}s)")

        except (RuntimeError, OSError, urllib.error.URLError) as e:
            elapsed = time.time() - start_time
            process_results[name] = ("FAILED", str(e))
            print(f"  Processing FAILED: {e}")
            traceback.print_exc()

    # =========================================================
    #  FINAL SUMMARY
    # =========================================================
    print(f"\n{'='*60}")
    print(f" BATCH INSTALL COMPLETE")
    print(f"{'='*60}")

    ok_count = 0
    fail_count = 0

    for name, asset, nohud in to_install:
        dl_status, dl_detail = download_results.get(name, ("SKIPPED", ""))
        if dl_status != "OK":
            icon = "[X]"
            status = "DL FAIL"
            detail = dl_detail
            fail_count += 1
        else:
            pr_status, pr_detail = process_results.get(name, ("SKIPPED", ""))
            if pr_status == "OK":
                icon = "[OK]"
                status = "OK"
                detail = pr_detail
                ok_count += 1
            else:
                icon = "[X]"
                status = "FAILED"
                detail = pr_detail
                fail_count += 1
        print(f"  {icon} {name:30s} {status:10s} {detail}")

    if skipped:
        for name, reason in skipped:
            print(f"  [-] {name:30s} {'SKIPPED':10s} {reason}")

    print(f"\n  Total: {ok_count} succeeded, {fail_count} failed, "
          f"{len(skipped)} skipped")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
