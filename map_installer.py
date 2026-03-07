import os
import shutil
import subprocess
import glob
import wave
import zipfile
import argparse
import sys
import signal
import re
import datetime
import time
import json
import platform
import struct
from pathlib import Path
from log_config import get_logger, setup_cli_logging
from helpers import DISK_SPACE_MIN_MB

logger = get_logger("map_installer")

# Directory containing this script - always the project root regardless of
# where the user's game data lives.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Cached discovered game-data paths so we don't scan on every run.
PATHS_CACHE_FILE = os.path.join(SCRIPT_DIR, "installer_paths.json")

# Import our individual scripts
import map_downloader
import map_builder
import ubiart_lua
import ipk_unpack
import json_to_lua


# ---------------------------------------------------------------------------
# Graceful Ctrl+C handling
# ---------------------------------------------------------------------------

_interrupted = False


def _signal_handler(signum, frame):
    global _interrupted
    _interrupted = True
    logger.warning("\nInterrupt received. Will stop after current step completes.")


signal.signal(signal.SIGINT, _signal_handler)


def sanitize_map_name(map_name, interactive=True):
    """Check for non-ASCII or problematic characters. Prompt for replacement if found."""
    try:
        map_name.encode('ascii')
        return map_name  # All ASCII, no issues
    except UnicodeEncodeError:
        pass

    non_ascii = [c for c in map_name if ord(c) > 127]
    logger.warning("\n    [!] Map name '%s' contains non-standard characters: %s", map_name, non_ascii)
    logger.warning("    These characters can cause file path and game engine issues.")

    if interactive:
        replacement = input(f"    Enter a replacement name (or press Enter to keep '{map_name}'): ").strip()
        if replacement:
            logger.info("    Using replacement name: %s", replacement)
            return replacement

    # Non-interactive fallback: strip non-ASCII chars
    safe_name = ''.join(c for c in map_name if ord(c) < 128)
    if safe_name and safe_name != map_name:
        logger.info("    Auto-stripped to: %s", safe_name)
        return safe_name

    return map_name


class PipelineState:
    """Holds all intermediate state for a map installation pipeline run."""
    def __init__(self, map_name, asset_html, nohud_html, jd_dir=None,
                 video_override=None, audio_offset=None, quality="ultra_hd",
                 original_map_name=None):
        self.original_map_name = (original_map_name or map_name).strip()
        self.map_name = sanitize_map_name(self.original_map_name, interactive=False)
        self.map_lower = self.map_name.lower()
        self.asset_html = clean_path(asset_html)
        self.nohud_html = clean_path(nohud_html)

        # jd_dir is the user's search-root hint for finding game data
        search_root = clean_path(jd_dir) if jd_dir else SCRIPT_DIR
        self.jd_dir = search_root  # kept for display and as the search hint

        # Resolve the actual jd21 game-data directory
        game_paths = resolve_game_paths(search_root)
        if game_paths:
            self.jd21_dir = game_paths['jd21_dir']
        else:
            # Best-guess fallback; preflight will fail with a clear message
            _base = os.path.normpath(search_root)
            if os.path.basename(_base).lower() == 'jd21':
                self.jd21_dir = _base
            else:
                self.jd21_dir = os.path.join(_base, "jd21")

        # Video quality preference
        self.quality = quality.upper()

        # Derived paths (all game-data paths use jd21_dir, not jd_dir)
        self.download_dir = os.path.dirname(self.asset_html)
        self.target_dir = os.path.join(
            self.jd21_dir, "data", "World", "MAPS", self.map_name)
        self.cache_dir = os.path.join(
            self.jd21_dir, "data", "cache", "itf_cooked", "pc", "world", "maps", self.map_lower)
        self.extracted_zip_dir = os.path.join(self.download_dir, "main_scene_extracted")
        self.ipk_extracted = os.path.join(self.download_dir, "ipk_extracted")

        # Populated during pipeline execution
        self.codename = self.map_name
        self.audio_path = None
        self.video_path = None
        self.video_start_time = None

        # Musictrack marker data (populated in step 06)
        self.musictrack_start_beat = None   # int, typically negative
        self.marker_preroll_ms = None       # float: markers[abs(startBeat)] / 48 + offset

        # SoundSetClip data from mainsequence tape (populated in step 08)
        self.amb_sound_clips = []           # list of dicts from mainsequence SoundSetClips

        # Sync parameters (may be overridden during refinement)
        self.v_override = video_override
        self.a_offset = audio_offset

        # Metadata overrides for non-ASCII replacement in Title/Artist/Credits
        self.metadata_overrides = {}

        # Interactive mode: True for CLI, False for GUI/batch (controls input() calls)
        self._interactive = True

        # Source mode flags (default: legacy HTML-driven flow)
        self.source_type = "html"
        self.skip_download = False
        self.skip_scene_extract = False
        self.skip_ipk_unpack = False
        self.preserve_source_dirs = False
        self.manual_ipk_file = None

        # Manual mode: per-asset override paths
        # When set, pipeline steps use these instead of globbing ipk_extracted.
        self.override_musictrack = None
        self.override_songdesc = None
        self.override_dtape = None
        self.override_ktape = None
        self.override_mainsequence = None
        self.override_moves_dir = None
        self.override_pictos_dir = None
        self.override_menuart_dir = None
        self.override_amb_dir = None


def clean_path(path):
    """Deep cleans a path: removes quotes, trims whitespace, normalizes, and makes absolute if possible."""
    if not path:
        return path
    # Remove surrounding quotes (e.g., from drag-and-drop into terminal)
    path = path.strip().strip('"').strip("'").strip()
    # Normalize slashes
    path = os.path.normpath(path)
    # Convert to absolute
    if os.path.exists(path):
        return os.path.abspath(path)
    return path

def detect_jd_dir(provided_dir=None):
    """Return the best default to pre-fill the 'Game Directory' field in the GUI.

    Checks the cached discovered path first, then falls back to SCRIPT_DIR.
    Actual path resolution (including scanning) happens in resolve_game_paths()
    when the pipeline or preflight runs.
    """
    cached = load_paths_cache()
    if cached and os.path.isdir(cached.get('jd21_dir', '')):
        return cached['jd21_dir']

    if provided_dir:
        cleaned = clean_path(provided_dir)
        if cleaned and os.path.isdir(cleaned):
            return cleaned

    return SCRIPT_DIR



# ---------------------------------------------------------------------------
# Offset readjustment: reconstruct state from existing downloads
# ---------------------------------------------------------------------------

def reconstruct_state_for_readjust(download_dir, jd_dir=None):
    """Build a minimal PipelineState from a map's download directory.

    Used for re-adjusting offset on an already-installed map without
    re-running the full pipeline.  Requires that .ogg and .webm files
    still exist in download_dir.

    Args:
        download_dir: Path to the map's download folder (containing .ogg, .webm,
                      and optionally ipk_extracted/).
        jd_dir:       Search root for game data (auto-detected if omitted).

    Returns:
        A PipelineState ready for reprocess_audio() / generate_text_files().

    Raises:
        FileNotFoundError: If required audio/video files are missing.
        RuntimeError:      If game data cannot be located.
    """
    download_dir = os.path.abspath(download_dir)
    if not os.path.isdir(download_dir):
        raise FileNotFoundError(f"Download directory not found: {download_dir}")

    # --- Locate .ogg audio ---
    ogg_files = [f for f in os.listdir(download_dir) if f.endswith('.ogg')]
    if not ogg_files:
        raise FileNotFoundError(f"No .ogg audio file found in {download_dir}")
    audio_path = os.path.join(download_dir, ogg_files[0])

    # --- Locate .webm video (exclude previews) ---
    webm_files = [f for f in os.listdir(download_dir)
                  if f.endswith('.webm')
                  and 'MapPreview' not in f
                  and 'VideoPreview' not in f]
    if not webm_files:
        raise FileNotFoundError(f"No gameplay .webm video found in {download_dir}")
    video_path = os.path.join(download_dir, webm_files[0])

    # --- Derive map name ---
    map_name = None
    asset_html = os.path.join(download_dir, "assets.html")
    if os.path.isfile(asset_html):
        urls = map_downloader.extract_urls(asset_html)
        map_name = map_downloader.extract_codename_from_urls(urls)
    if not map_name:
        map_name = os.path.basename(download_dir)
    map_name = sanitize_map_name(map_name, interactive=False)

    # --- Resolve game paths ---
    search_root = jd_dir or SCRIPT_DIR
    game_paths = resolve_game_paths(search_root)
    if not game_paths:
        raise RuntimeError(
            f"Cannot locate JD2021 game data from '{search_root}'. "
            "Provide the correct --jd-dir or ensure jd21/ is accessible.")
    jd21_dir = game_paths['jd21_dir']

    # --- Build a minimal PipelineState ---
    # Use dummy HTML paths since we won't download anything
    state = PipelineState(
        map_name=map_name,
        asset_html=asset_html if os.path.isfile(asset_html) else "(readjust)",
        nohud_html="(readjust)",
        jd_dir=search_root,
    )
    state.audio_path = audio_path
    state.video_path = video_path
    state._interactive = True

    # --- IPK extracted dir ---
    ipk_dir = os.path.join(download_dir, "ipk_extracted")
    if os.path.isdir(ipk_dir):
        state.ipk_extracted = ipk_dir

    # --- Extract musictrack metadata from ipk_extracted if available ---
    v_override = None
    marker_preroll_ms = None
    if os.path.isdir(ipk_dir):
        mt_meta = map_builder.extract_musictrack_metadata(ipk_dir)
        if mt_meta:
            v_override = mt_meta["video_start_time"]
            state.musictrack_start_beat = mt_meta["start_beat"]
            marker_preroll_ms = compute_marker_preroll(
                mt_meta["markers"], mt_meta["start_beat"])
            # For IPK maps with pre-roll, synthesize from markers rather than
            # trusting the raw CKD value (X360 binary CKDs store 0.0).
            if (v_override == 0.0
                    and mt_meta["start_beat"] < 0
                    and mt_meta["markers"]):
                idx = abs(mt_meta["start_beat"])
                if idx < len(mt_meta["markers"]):
                    v_override = -(mt_meta["markers"][idx] / 48.0 / 1000.0)

    # --- Fallback: parse videoStartTime from installed .trk file ---
    if v_override is None:
        trk_pattern = os.path.join(
            state.target_dir, "Timeline", f"{map_name}_MusicTrack.trk")
        if os.path.isfile(trk_pattern):
            try:
                with open(trk_pattern, 'r', encoding='utf-8') as f:
                    trk_text = f.read()
                m = re.search(r'videoStartTime\s*=\s*([-\d.]+)', trk_text)
                if m:
                    v_override = float(m.group(1))
                    print(f"    Read videoStartTime from installed .trk: {v_override}")
            except (OSError, ValueError) as e:
                logger.warning("    Could not read .trk file: %s", e)

    state.v_override = v_override  # may be None; step_06 will synthesize if needed
    state.marker_preroll_ms = marker_preroll_ms

    # --- Compute a_offset from marker data ---
    if marker_preroll_ms is not None:
        state.a_offset = -(marker_preroll_ms / 1000.0)
    else:
        state.a_offset = state.v_override

    # --- Load AMB sound clip metadata from mainsequence tape if available ---
    if os.path.isdir(ipk_dir):
        import ubiart_lua as _ual
        cine_tapes = glob.glob(
            os.path.join(ipk_dir, "**", "*mainsequence*tape.ckd"), recursive=True)
        for tape_file in cine_tapes:
            try:
                tape_data = _ual.load_ckd_json(tape_file)
                for raw_clip in tape_data.get("Clips", []):
                    if raw_clip.get("__class") == "SoundSetClip":
                        clip_name = raw_clip["SoundSetPath"].split("/")[-1].split(".")[0]
                        state.amb_sound_clips.append({
                            "name": clip_name,
                            "start_time": raw_clip["StartTime"],
                            "duration": raw_clip["Duration"],
                            "path": raw_clip["SoundSetPath"],
                        })
            except (json.JSONDecodeError, KeyError, OSError):
                pass

    print(f"    Readjust state built for '{map_name}':")
    print(f"      Audio:    {audio_path}")
    print(f"      Video:    {video_path}")
    print(f"      v_override: {state.v_override}")
    print(f"      a_offset:   {state.a_offset}")
    if marker_preroll_ms is not None:
        print(f"      marker_preroll_ms: {marker_preroll_ms:.1f}")

    return state


# ---------------------------------------------------------------------------
# Game-data path discovery and caching
# ---------------------------------------------------------------------------

def load_paths_cache():
    """Load previously discovered game-data paths. Returns dict or None."""
    if os.path.isfile(PATHS_CACHE_FILE):
        try:
            with open(PATHS_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Validate: SkuScene must still exist on disk
            if os.path.isfile(data.get('sku_scene', '')):
                return data
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    return None


def save_paths_cache(paths):
    """Persist discovered game-data paths to disk."""
    try:
        with open(PATHS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(paths, f, indent=2)
    except OSError:
        pass


def clear_paths_cache():
    """Delete the cached game-data paths. Returns True if anything was deleted."""
    if os.path.isfile(PATHS_CACHE_FILE):
        os.remove(PATHS_CACHE_FILE)
        return True
    return False


# ---------------------------------------------------------------------------
# User settings (persistent preferences)
# ---------------------------------------------------------------------------

SETTINGS_FILE = os.path.join(SCRIPT_DIR, "installer_settings.json")

DEFAULT_SETTINGS = {
    "skip_preflight": False,
    "suppress_offset_notification": False,
    "cleanup_behavior": "ask",  # ask | delete | keep
    "default_quality": "ultra_hd",
    "show_preflight_success_popup": True,
    "show_quickstart_on_launch": True,
    "quickstart_seen": False,
}

_VALID_QUALITYS = {
    "ultra_hd", "ultra", "high_hd", "high", "mid_hd", "mid", "low_hd", "low"
}

_VALID_CLEANUP_BEHAVIORS = {"ask", "delete", "keep"}


def _coerce_bool(value, default=False):
    """Best-effort bool coercion for settings loaded from JSON.

    Accepts native bools, common int/string values, and falls back to default.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _normalize_settings(saved):
    """Return a sanitized settings dict plus whether any value changed."""
    normalized = dict(DEFAULT_SETTINGS)
    changed = False

    if not isinstance(saved, dict):
        return normalized, True

    normalized["skip_preflight"] = _coerce_bool(
        saved.get("skip_preflight"), DEFAULT_SETTINGS["skip_preflight"])
    normalized["suppress_offset_notification"] = _coerce_bool(
        saved.get("suppress_offset_notification"),
        DEFAULT_SETTINGS["suppress_offset_notification"])

    # Migrate legacy boolean auto_cleanup_downloads -> cleanup_behavior.
    cleanup_behavior = saved.get("cleanup_behavior")
    if isinstance(cleanup_behavior, str):
        cleanup_behavior = cleanup_behavior.strip().lower()
    if cleanup_behavior not in _VALID_CLEANUP_BEHAVIORS:
        legacy_auto_cleanup = _coerce_bool(saved.get("auto_cleanup_downloads"), False)
        cleanup_behavior = "delete" if legacy_auto_cleanup else DEFAULT_SETTINGS["cleanup_behavior"]
    normalized["cleanup_behavior"] = cleanup_behavior

    quality = saved.get("default_quality", DEFAULT_SETTINGS["default_quality"])
    if isinstance(quality, str):
        quality = quality.strip().lower()
    else:
        quality = DEFAULT_SETTINGS["default_quality"]

    if quality not in _VALID_QUALITYS:
        quality = DEFAULT_SETTINGS["default_quality"]
    normalized["default_quality"] = quality

    normalized["show_preflight_success_popup"] = _coerce_bool(
        saved.get("show_preflight_success_popup"),
        DEFAULT_SETTINGS["show_preflight_success_popup"])
    normalized["show_quickstart_on_launch"] = _coerce_bool(
        saved.get("show_quickstart_on_launch"),
        DEFAULT_SETTINGS["show_quickstart_on_launch"])
    normalized["quickstart_seen"] = _coerce_bool(
        saved.get("quickstart_seen"), DEFAULT_SETTINGS["quickstart_seen"])

    for key, default_value in DEFAULT_SETTINGS.items():
        if normalized.get(key) != default_value and key not in saved:
            changed = True

    # Any mismatch between saved and normalized means the file should be healed.
    for key in DEFAULT_SETTINGS:
        if saved.get(key) != normalized.get(key):
            changed = True
            break

    return normalized, changed


def _backup_corrupt_settings(raw_text):
    """Keep a timestamped backup of unreadable settings for debugging."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{SETTINGS_FILE}.broken_{timestamp}"
    try:
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(raw_text)
        logger.warning("Corrupt settings were backed up to %s", backup_path)
    except OSError:
        logger.warning("Could not back up corrupt settings file")


def load_settings():
    """Load user settings, returning defaults merged with saved values."""
    settings = dict(DEFAULT_SETTINGS)
    if not os.path.isfile(SETTINGS_FILE):
        return settings

    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            raw_text = f.read()
    except OSError:
        return settings

    try:
        saved = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Settings file is invalid JSON, resetting to defaults: %s", SETTINGS_FILE)
        _backup_corrupt_settings(raw_text)
        save_settings(settings)
        return settings

    settings, changed = _normalize_settings(saved)
    if changed:
        logger.info("Normalized installer settings values in %s", SETTINGS_FILE)
        save_settings(settings)
    return settings


def save_settings(settings):
    """Persist user settings to disk."""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
    except OSError as e:
        logger.warning("Could not save settings: %s", e)


def get_setting(key):
    """Convenience accessor for a single setting value."""
    return load_settings().get(key, DEFAULT_SETTINGS.get(key))


def _scan_for_sku_scene(search_root):
    """Walk search_root recursively to find SkuScene_Maps_PC_All.isc."""
    target = "SkuScene_Maps_PC_All.isc"
    skip = {'__pycache__', '.git', 'logs', 'downloads',
            'main_scene_extracted', 'ipk_extracted', 'tools', 'xtx_extractor'}
    for root, dirs, files in os.walk(search_root):
        dirs[:] = [d for d in dirs if d not in skip]
        if target in files:
            return os.path.join(root, target)
    return None


def resolve_game_paths(search_root, use_cache=True):
    """Locate the JD2021 game-data directory from any starting point.

    Checks, in order:
      1. Cached paths (installer_paths.json) — skipped when use_cache=False.
      2. search_root/jd21/ — classic layout where the project sits beside jd21/.
      3. search_root itself — user pointed directly at the jd21 folder.
      4. SCRIPT_DIR/jd21/ — in case search_root was wrong but classic layout exists.
      5. Recursive scan under search_root.

    Returns dict with keys 'jd21_dir' and 'sku_scene', or None if not found.
    Saves the result to installer_paths.json for future runs.
    """
    if use_cache:
        cached = load_paths_cache()
        if cached:
            return cached

    search_root = os.path.normpath(search_root)
    checked_paths = []  # Track every path we try for diagnostics

    def _found(jd21_dir, sku):
        paths = {'jd21_dir': jd21_dir, 'sku_scene': sku}
        save_paths_cache(paths)
        return paths

    # Case 1: search_root/jd21/data/World/SkuScenes/…
    jd21_sub = os.path.join(search_root, "jd21")
    sku = os.path.join(jd21_sub, "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
    checked_paths.append(sku)
    if os.path.isfile(sku):
        return _found(jd21_sub, sku)

    # Case 2: search_root IS the jd21 folder
    sku = os.path.join(search_root, "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
    checked_paths.append(sku)
    if os.path.isfile(sku):
        return _found(search_root, sku)

    # Case 3: classic layout next to the scripts
    if search_root != SCRIPT_DIR:
        jd21_next = os.path.join(SCRIPT_DIR, "jd21")
        sku = os.path.join(jd21_next, "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
        checked_paths.append(sku)
        if os.path.isfile(sku):
            return _found(jd21_next, sku)

    # Case 4: recursive scan
    print(f"    Scanning {search_root} for JD2021 game data (this may take a moment)...")
    checked_paths.append(f"(recursive scan under {search_root})")
    sku_found = _scan_for_sku_scene(search_root)
    if sku_found:
        # sku is at  jd21_dir/data/World/SkuScenes/SkuScene_Maps_PC_All.isc
        jd21_dir = os.path.normpath(
            os.path.join(os.path.dirname(sku_found), '..', '..', '..'))
        return _found(jd21_dir, sku_found)

    # Resolution failed — print diagnostic output
    print("    [X] Could not locate JD2021 game data. Paths checked:")
    for p in checked_paths:
        print(f"       {p}")
    print("\n    Suggestions:")
    print("      - Install JD2021 to a short path (e.g. D:\\jd2021)")
    print("      - Avoid paths with spaces, accents, or special characters")
    print("      - Avoid Program Files or other protected directories")
    print("      - Make sure the jd21/ folder contains data/World/SkuScenes/")
    return None


def check_executable(name):
    """Check if an executable is available on PATH."""
    try:
        subprocess.run([name, "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# JDH_Downloader integration
# ---------------------------------------------------------------------------

JDH_DOWNLOADER_DIR = os.path.join(SCRIPT_DIR, "tools", "JDH_Downloader")


def _check_node_available():
    """Check that Node.js is available on PATH. Returns (ok, message)."""
    try:
        result = subprocess.run(["node", "--version"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return False, "node is installed but returned an error"
        node_ver = result.stdout.strip()
    except FileNotFoundError:
        return False, ("Node.js is not installed or not on PATH.\n"
                       "  Download it from: https://nodejs.org/")
    except subprocess.TimeoutExpired:
        return False, "node --version timed out"

    # Check minimum version (18+)
    try:
        major = int(node_ver.lstrip('v').split('.')[0])
        if major < 18:
            return False, (f"Node.js {node_ver} found but v18+ is required.\n"
                           "  Download from: https://nodejs.org/")
    except ValueError:
        pass  # Can't parse version, proceed anyway

    return True, f"Node.js {node_ver}"


def _check_downloader_setup():
    """Verify JDH_Downloader directory is properly set up.
    Returns (ok, message).
    """
    if not os.path.isdir(JDH_DOWNLOADER_DIR):
        return False, (f"JDH_Downloader not found at {JDH_DOWNLOADER_DIR}\n"
                       "  Ensure the tools/JDH_Downloader/ directory exists.")

    config_path = os.path.join(JDH_DOWNLOADER_DIR, "config.json")
    if not os.path.isfile(config_path):
        example = os.path.join(JDH_DOWNLOADER_DIR, "config.example.json")
        return False, (f"config.json not found in {JDH_DOWNLOADER_DIR}\n"
                       f"  Copy {example} to {config_path} and fill in your "
                       "Discord channel URL.")

    # Validate config shape early to fail with a clear message.
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return False, "config.json is invalid (expected a JSON object)"
        if not cfg.get("channelUrl"):
            return False, "config.json is missing 'channelUrl'"
        if not cfg.get("profileDir"):
            return False, "config.json is missing 'profileDir'"
    except (json.JSONDecodeError, OSError) as e:
        return False, f"Could not read config.json: {e}"

    def _resolve_npm_install_cmd():
        """Return a command list for `npm install`, even when npm.cmd is missing on PATH."""
        npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
        if npm_cmd:
            return [npm_cmd, "install"]

        # Fallback: invoke npm-cli.js directly through the discovered node executable.
        node_cmd = shutil.which("node")
        if not node_cmd:
            return None

        node_dir = os.path.dirname(node_cmd)
        candidates = [
            os.path.join(node_dir, "node_modules", "npm", "bin", "npm-cli.js"),
            os.path.join(node_dir, "..", "lib", "node_modules", "npm", "bin", "npm-cli.js"),
        ]
        for candidate in candidates:
            candidate = os.path.abspath(candidate)
            if os.path.isfile(candidate):
                return [node_cmd, candidate, "install"]
        return None

    def _resolve_playwright_install_cmd():
        """Return a command list to install Playwright Chromium browser binaries."""
        npx_cmd = shutil.which("npx") or shutil.which("npx.cmd")
        if npx_cmd:
            return [npx_cmd, "playwright", "install", "chromium"]

        npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
        if npm_cmd:
            return [npm_cmd, "exec", "playwright", "install", "chromium"]

        # Fallback through npm-cli.js when npx/npm shims are missing from PATH.
        node_cmd = shutil.which("node")
        if not node_cmd:
            return None
        node_dir = os.path.dirname(node_cmd)
        candidates = [
            os.path.join(node_dir, "node_modules", "npm", "bin", "npm-cli.js"),
            os.path.join(node_dir, "..", "lib", "node_modules", "npm", "bin", "npm-cli.js"),
        ]
        for candidate in candidates:
            candidate = os.path.abspath(candidate)
            if os.path.isfile(candidate):
                return [node_cmd, candidate, "exec", "playwright", "install", "chromium"]
        return None

    def _is_playwright_chromium_ready():
        """Return True only if Playwright is importable and Chromium binary exists."""
        check_script = (
            "const fs=require('fs');"
            "let pw;"
            "try{pw=require('playwright');}catch(e){process.exit(2);}"
            "const p=pw.chromium.executablePath();"
            "if(!p||!fs.existsSync(p)){process.exit(3);}"
            "process.exit(0);"
        )
        try:
            result = subprocess.run(
                ["node", "-e", check_script],
                cwd=JDH_DOWNLOADER_DIR,
                capture_output=True,
                text=True,
                timeout=20,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    # Check if node_modules exists; if not, run npm install
    node_modules = os.path.join(JDH_DOWNLOADER_DIR, "node_modules")
    if not os.path.isdir(node_modules):
        print("  JDH_Downloader dependencies not installed. Running npm install...")
        install_cmd = _resolve_npm_install_cmd()
        if not install_cmd:
            return False, (
                "npm not found on PATH and npm-cli.js fallback was not found.\n"
                "  Node.js seems installed, but npm is missing from this environment.\n"
                "  Reinstall Node.js LTS from https://nodejs.org/ and ensure npm is included."
            )
        try:
            result = subprocess.run(
                install_cmd,
                cwd=JDH_DOWNLOADER_DIR,
                timeout=120
            )
            if result.returncode != 0:
                return False, f"npm install failed (exit code {result.returncode}; see output above)"
            print("  npm install complete.")
        except FileNotFoundError:
            return False, ("npm invocation failed unexpectedly.\n"
                           "  Reinstall Node.js LTS from https://nodejs.org/")
        except subprocess.TimeoutExpired:
            return False, "npm install timed out"

    # Ensure Playwright Chromium browser binary is available even if node_modules
    # already existed (common after partial copies or cache cleanup).
    if not _is_playwright_chromium_ready():
        print("  Playwright Chromium is missing or incomplete. Installing browser binaries...")
        playwright_cmd = _resolve_playwright_install_cmd()
        if not playwright_cmd:
            return False, (
                "Could not find a command to run Playwright install.\n"
                "  Ensure Node.js/npm is installed correctly, then run:\n"
                "  npx playwright install chromium"
            )
        try:
            result = subprocess.run(
                playwright_cmd,
                cwd=JDH_DOWNLOADER_DIR,
                timeout=300,
            )
            if result.returncode != 0:
                return False, (
                    "Playwright Chromium install failed "
                    f"(exit code {result.returncode}; see output above)"
                )
        except FileNotFoundError:
            return False, "Failed to launch Playwright install command"
        except subprocess.TimeoutExpired:
            return False, "Playwright Chromium install timed out"

        if not _is_playwright_chromium_ready():
            return False, (
                "Playwright install completed but Chromium is still unavailable.\n"
                "  Try running manually in tools/JDH_Downloader:\n"
                "  npx playwright install chromium"
            )

    return True, "JDH_Downloader ready"


def fetch_html_via_downloader(codename, output_dir):
    """Run JDH_Downloader to fetch assets.html and nohud.html for a codename.

    Args:
        codename: The map codename (e.g. "TemperatureALT").
        output_dir: Directory where <codename>/ folder will be created
                    (typically MapDownloads/).

    Returns:
        (asset_html_path, nohud_html_path) on success.

    Raises:
        RuntimeError on any failure.
    """
    # Pre-flight: check Node.js
    ok, msg = _check_node_available()
    if not ok:
        raise RuntimeError(f"Node.js check failed: {msg}")
    print(f"  [OK] {msg}")

    # Pre-flight: check downloader setup
    ok, msg = _check_downloader_setup()
    if not ok:
        raise RuntimeError(f"JDH_Downloader setup failed: {msg}")
    print(f"  [OK] {msg}")

    codename = codename.strip().strip('"').strip("'")
    if not codename:
        raise RuntimeError("Codename is empty after trimming quotes/whitespace")

    fetch_script = os.path.join(JDH_DOWNLOADER_DIR, "fetch.mjs")
    abs_output_dir = os.path.abspath(output_dir)
    os.makedirs(abs_output_dir, exist_ok=True)

    print(f"  Fetching HTML for '{codename}' via JDH_Downloader...")
    print(f"  Output directory: {abs_output_dir}")
    print(f"  (A Chromium window will open. If not logged in, log in manually.)")

    try:
        result = subprocess.run(
            ["node", fetch_script, codename, "--output-dir", abs_output_dir],
            timeout=600,  # 10 min: allows 5 min login wait + command timeouts
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "JDH_Downloader timed out after 10 minutes.\n"
            "  The bot may be offline, or Discord login may have stalled."
        )
    except FileNotFoundError:
        raise RuntimeError("Could not run 'node'. Is Node.js installed?")

    if result.returncode != 0:
        raise RuntimeError(
            f"JDH_Downloader exited with code {result.returncode}.\n"
            "  Check the output above for details. Common causes:\n"
            "  - Bot is offline or not in the server\n"
            "  - Discord login session expired (delete .browser-profile and retry)\n"
            "  - Invalid codename"
        )

    # Verify output files exist. Some environments may place output in a
    # nearby folder (different cwd/base), so discover the freshest valid pair.
    expected_dir = os.path.join(abs_output_dir, codename)
    expected_asset = os.path.join(expected_dir, "assets.html")
    expected_nohud = os.path.join(expected_dir, "nohud.html")
    if os.path.isfile(expected_asset) and os.path.isfile(expected_nohud):
        print(f"  Fetch complete: {expected_dir}")
        return expected_asset, expected_nohud

    candidates = []
    seen_dirs = set()

    search_roots = [
        abs_output_dir,
        os.path.dirname(abs_output_dir),
        JDH_DOWNLOADER_DIR,
        SCRIPT_DIR,
    ]

    def _consider_pair(folder):
        folder_norm = os.path.normcase(os.path.normpath(folder))
        if folder_norm in seen_dirs:
            return
        seen_dirs.add(folder_norm)
        asset = os.path.join(folder, "assets.html")
        nohud = os.path.join(folder, "nohud.html")
        if os.path.isfile(asset) and os.path.isfile(nohud):
            try:
                score = max(os.path.getmtime(asset), os.path.getmtime(nohud))
            except OSError:
                score = 0
            name_match = (os.path.basename(folder).strip().lower() == codename.lower())
            candidates.append((1 if name_match else 0, score, asset, nohud))

    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue

        # Direct codename folder checks (exact and case-insensitive)
        exact = os.path.join(root, codename)
        _consider_pair(exact)
        try:
            for child in os.listdir(root):
                child_path = os.path.join(root, child)
                if os.path.isdir(child_path) and child.strip().lower() == codename.lower():
                    _consider_pair(child_path)
        except OSError:
            pass

        # Shallow recursive scan for fallback pair discovery
        try:
            root_path = Path(root)
            for asset in root_path.rglob("assets.html"):
                rel_depth = len(asset.relative_to(root_path).parts)
                if rel_depth > 4:
                    continue
                folder = str(asset.parent)
                _consider_pair(folder)
        except OSError:
            pass

    if candidates:
        # Prefer folder name match, then latest modification time.
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, asset_html, nohud_html = candidates[0]
        actual_dir = os.path.dirname(asset_html)
        if os.path.normcase(os.path.normpath(actual_dir)) != os.path.normcase(os.path.normpath(expected_dir)):
            print("  [WARN] Downloader output directory differed from expected path.")
            print(f"         Expected: {expected_dir}")
            print(f"         Found:    {actual_dir}")
        print(f"  Fetch complete: {actual_dir}")
        return asset_html, nohud_html

    raise RuntimeError(
        "JDH_Downloader reported success but no assets.html/nohud.html pair was found.\n"
        f"  Expected: {expected_dir}\n"
        "  Checked fallback roots:\n"
        f"    - {abs_output_dir}\n"
        f"    - {os.path.dirname(abs_output_dir)}\n"
        f"    - {JDH_DOWNLOADER_DIR}\n"
        f"    - {SCRIPT_DIR}"
    )


def _prompt_install(tool_name):
    """Ask user if they want to auto-install a missing dependency. Returns True if yes."""
    try:
        resp = input(f"    Install {tool_name} automatically? [y/N]: ").strip().lower()
        return resp in ('y', 'yes')
    except EOFError:
        return False


def _install_ffmpeg():
    """Download ffmpeg static build for Windows into the project tools/ffmpeg/ dir."""
    import ssl as _ssl
    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE

    FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    tools_dir = os.path.join(SCRIPT_DIR, "tools")
    ffmpeg_dir = os.path.join(tools_dir, "ffmpeg")
    os.makedirs(ffmpeg_dir, exist_ok=True)

    zip_path = os.path.join(tools_dir, "ffmpeg.zip")
    print(f"    Downloading ffmpeg from {FFMPEG_URL}...")
    print(f"    This may take a few minutes...")
    urllib_req = __import__('urllib.request', fromlist=['urlretrieve'])
    urllib_req.urlretrieve(FFMPEG_URL, zip_path)

    print(f"    Extracting ffmpeg...")
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(tools_dir)

    # Find the extracted folder (name varies by version) and move bin/ contents
    for entry in os.listdir(tools_dir):
        bin_path = os.path.join(tools_dir, entry, "bin")
        if entry.startswith("ffmpeg-") and os.path.isdir(bin_path):
            for exe in os.listdir(bin_path):
                shutil.move(os.path.join(bin_path, exe),
                            os.path.join(ffmpeg_dir, exe))
            shutil.rmtree(os.path.join(tools_dir, entry))
            break

    if os.path.exists(zip_path):
        os.remove(zip_path)

    # Add to PATH for this session
    os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')
    print(f"    ffmpeg installed to {ffmpeg_dir}")
    return True


def preflight_check(jd_dir, asset_html, nohud_html, auto_install=False,
                    interactive=True, require_html=True):
    """Run pre-flight dependency checks. Returns True if all critical checks pass.

    Args:
        jd_dir:       User-provided search root for finding JD2021 game data.
                      Can be the parent of jd21/, the jd21/ folder itself, or
                      any ancestor — resolve_game_paths() will scan if needed.
        auto_install: If True, auto-download ffmpeg without prompting.
        interactive:  If False (GUI mode), never call input(); return a
                      (False, True) tuple to signal that ffmpeg is missing.
    """
    print("--- Pre-flight Checks ---")

    # Environment diagnostics
    print(f"    Python:   {sys.version.split()[0]}")
    print(f"    OS:       {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"    Encoding: {sys.getfilesystemencoding()}")
    print(f"    CWD:      {os.getcwd()}")

    failures = 0
    ffmpeg_missing = False

    def ok(msg):
        print(f"  [OK] {msg}")

    def fail(msg):
        nonlocal failures
        failures += 1
        print(f"  [FAIL] {msg}")

    def warn(msg):
        print(f"  [WARN] {msg}")

    # Critical: ffmpeg — always look in project tools/ first
    tools_ffmpeg = os.path.join(SCRIPT_DIR, "tools", "ffmpeg")
    if os.path.isdir(tools_ffmpeg):
        os.environ['PATH'] = tools_ffmpeg + os.pathsep + os.environ.get('PATH', '')

    if check_executable("ffmpeg"):
        ok("ffmpeg found")
    else:
        should_install = auto_install or (interactive and _prompt_install("ffmpeg"))
        if should_install:
            try:
                _install_ffmpeg()
                if check_executable("ffmpeg"):
                    ok("ffmpeg installed and verified")
                else:
                    fail("ffmpeg installed but not working")
            except Exception as e:
                fail(f"ffmpeg auto-install failed: {e}")
        else:
            ffmpeg_missing = True
            fail("ffmpeg not found in PATH")

    # Critical: JD2021 game data — scan from the provided directory
    game_paths = resolve_game_paths(jd_dir)
    if game_paths:
        jd21_dir = game_paths['jd21_dir']
        ok(f"JD2021 game data ({jd21_dir})")
        ok("SkuScene registry file")

        # Path safety checks
        if ' ' in jd21_dir:
            warn("Game path contains spaces — this may cause issues with some tools")
        try:
            jd21_dir.encode('ascii')
        except UnicodeEncodeError:
            warn("Game path contains non-ASCII characters — this may cause issues")
        if 'Program Files' in jd21_dir:
            warn("Game is in Program Files — may need admin privileges")

        # Write permission test
        test_file = os.path.join(jd21_dir, "data", ".write_test")
        try:
            os.makedirs(os.path.dirname(test_file), exist_ok=True)
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            ok("Write permission to game directory")
        except PermissionError:
            fail("Cannot write to game directory — check permissions or run as admin")
        except OSError as e:
            fail(f"Cannot write to game directory — {e}")

        # Disk space check
        try:
            free = shutil.disk_usage(jd21_dir).free
            if free < DISK_SPACE_MIN_MB * 1024 * 1024:
                warn(f"Low disk space: {free // (1024*1024)} MB free")
            else:
                ok(f"Disk space: {free // (1024*1024)} MB free")
        except OSError:
            warn("Could not check disk space")
    else:
        fail(f"JD2021 game data not found under '{jd_dir}' — try a parent folder or click Clear Cache and re-scan")
        fail("SkuScene_Maps_PC_All.isc not found (game data missing)")

    # Critical: project scripts — always in SCRIPT_DIR, never in the game dir
    try:
        import ipk_unpack as _ipk_check
        ok("ipk_unpack (IPK unpacker)")
    except ImportError:
        fail("ipk_unpack.py not found in project root")

    if os.path.isfile(os.path.join(SCRIPT_DIR, "ckd_decode.py")):
        ok("ckd_decode.py")
    else:
        fail("ckd_decode.py not found in project root")

    try:
        from json_to_lua import convert_file as _lua_check
        ok("json_to_lua (CKD-to-Lua converter)")
    except ImportError:
        fail("json_to_lua.py not found in project root")

    try:
        from xtx_extractor import xtx_extract as _xtx_check
        ok("xtx_extractor (texture deswizzler)")
    except ImportError:
        fail("xtx_extractor/ package not found in project root")

    try:
        from PIL import Image
        ok("Pillow (image library)")
    except ImportError:
        fail("Pillow not installed (run: pip install Pillow)")

    # Critical: input HTML files (optional for manual/IPK modes)
    if require_html:
        if os.path.isfile(asset_html):
            ok("Asset HTML file")
        else:
            fail(f"Asset HTML file not found: {asset_html}")

        if os.path.isfile(nohud_html):
            ok("NOHUD HTML file")
        else:
            fail(f"NOHUD HTML file not found: {nohud_html}")
    else:
        warn("HTML file validation skipped for manual/IPK source mode")

    # Optional: ffplay
    if check_executable("ffplay"):
        ok("ffplay found")
    else:
        warn("ffplay not found (sync preview will be unavailable)")

    # Optional: ffprobe
    if check_executable("ffprobe"):
        ok("ffprobe found")
    else:
        warn("ffprobe not found (sync duration calculation will be unavailable)")

    print("-------------------------")

    if failures > 0:
        print(f"\nERROR: {failures} critical check(s) failed. Cannot proceed.")
        if not interactive and ffmpeg_missing:
            return False, True   # (passed, ffmpeg_missing)
        return False
    return True

# ---------------------------------------------------------------------------
# Marker-based pre-roll calculation (from UBIART-AMB-CUTTER approach)
# ---------------------------------------------------------------------------

# Calibration constant (ms) from UBIART-AMB-CUTTER: compensates for codec
# decode latency between the OGG seek position and actual audio output.
MARKER_OFFSET_MS = 85.0


def compute_marker_preroll(markers, start_beat, offset_ms=MARKER_OFFSET_MS):
    """Compute the precise OGG pre-roll duration from musictrack beat markers.

    The musictrack's ``markers`` array maps beat indices to tick positions.
    Dividing by 48 converts ticks to milliseconds.  ``start_beat`` (typically
    negative) indicates how many beats before beat-0 the audio file begins.

    Returns:
        Pre-roll duration in milliseconds, or None if data is insufficient.
    """
    idx = abs(start_beat)
    if not markers or idx >= len(markers) or idx == 0:
        return None
    return markers[idx] / 48.0 + offset_ms

def convert_audio(audio_path, map_name, target_dir, a_offset=0.0):
    wav_out = os.path.join(target_dir, f"Audio/{map_name}.wav")
    ogg_out = os.path.join(target_dir, f"Audio/{map_name}.ogg")

    if not os.path.exists(ogg_out):
        if audio_path.lower().endswith(".ogg"):
            print(f"    Copying menu preview OGG...")
            shutil.copy2(audio_path, ogg_out)
        else:
            print(f"    Converting to menu preview OGG...")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                            "-i", audio_path, ogg_out], check=True)

    if a_offset == 0.0:
        print(f"    Converting to 48kHz WAV (no offset)...")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-i", audio_path, "-ar", "48000", wav_out], check=True)
    elif a_offset < 0:
        trim_s = abs(a_offset)
        print(f"    Converting to 48kHz WAV (trimming first {trim_s:.3f}s)...")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-i", audio_path, "-ss", f"{trim_s:.6f}",
                        "-ar", "48000", wav_out], check=True)
    else:
        delay_ms = int(a_offset * 1000)
        print(f"    Converting to 48kHz WAV (padding {delay_ms}ms silence)...")
        af_filter = f"adelay={delay_ms}|{delay_ms},asetpts=PTS-STARTPTS"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-i", audio_path, "-af", af_filter,
                        "-ar", "48000", wav_out], check=True)

def generate_intro_amb(ogg_path, map_name, target_dir, a_offset, v_override=None,
                       marker_preroll_ms=None):
    """Generate an intro AMB WAV to cover pre-roll silence caused by negative videoStartTime.

    Strategy: AMB plays from t=0, covering the silence window before the main WAV starts.
    The AMB duration is based on abs(v_override) (the actual intro length), not abs(a_offset).
    When abs(v_override) > abs(a_offset), the OGG has no audio for the initial gap, so the
    AMB WAV is prepended with that many seconds of silence via adelay.
    A 200ms fade-out at the end eliminates the hard-cut volume snap.

    When marker_preroll_ms is provided (from musictrack beat markers), it replaces
    the hard-coded +1.355s heuristic with a precise, data-driven audio content duration.
    """
    map_lower = map_name.lower()
    amb_dir = os.path.join(target_dir, "Audio", "AMB")

    if a_offset >= 0 and (v_override is None or v_override >= 0):
        # No pre-roll silence. If an intro WAV exists from a previous run, silence it.
        if os.path.exists(amb_dir):
            for wav in glob.glob(os.path.join(amb_dir, "*_intro.wav")):
                with wave.open(wav, 'w') as wf:
                    wf.setnchannels(2)
                    wf.setsampwidth(2)
                    wf.setframerate(48000)
                    wf.writeframes(b'\x00\x00\x00\x00' * 4800)
        return

    os.makedirs(amb_dir, exist_ok=True)

    # Intro duration is driven by v_override (videoStartTime); fall back to a_offset if not given.
    # When |v_override| > |a_offset|, the OGG has no content for the leading gap, so we prepend
    # silence equal to that difference via adelay.
    intro_dur    = abs(v_override) if v_override is not None and v_override < 0 else abs(a_offset)
    audio_delay  = max(0.0, intro_dur - abs(a_offset))   # seconds of silence to prepend

    # AMB audio content length (from OGG t=0); total WAV = audio_delay + audio_content_dur
    if marker_preroll_ms is not None:
        # Data-driven: precise pre-roll length from musictrack beat markers
        audio_content_dur = marker_preroll_ms / 1000.0
        fade_start = audio_delay + audio_content_dur - 0.2  # 200ms fade before end
        print(f"    Using marker-based AMB duration: {audio_content_dur:.3f}s "
              f"(was {abs(a_offset) + 1.355:.3f}s with heuristic)")
    else:
        # Fallback: original heuristic for maps without marker data
        audio_content_dur = abs(a_offset) + 1.355
        fade_start = audio_delay + abs(a_offset) + 1.155
    amb_duration = audio_delay + audio_content_dur

    # Locate intro AMB files left by IPK processing (step 09).
    # The TPL name is the actor name used in the ISC; the WAV name may differ.
    # Priority: use the TPL name if one exists — otherwise create TPL+ILU from scratch.
    intro_wavs = glob.glob(os.path.join(amb_dir, "*_intro.wav"))
    intro_tpls = glob.glob(os.path.join(amb_dir, "*_intro.tpl"))

    if intro_tpls:
        # IPK-provided TPL+ILU already exist; derive the actor name from the TPL.
        # The WAV placeholder (possibly named differently) was created by step 09.
        intro_name = os.path.basename(intro_tpls[0]).replace('.tpl', '')
        intro_wav  = intro_wavs[0] if intro_wavs else os.path.join(amb_dir, f"{intro_name}.wav")
    else:
        # No TPL from IPK — create one (use existing WAV name if available).
        if intro_wavs:
            intro_wav  = intro_wavs[0]
            intro_name = os.path.basename(intro_wav).replace('.wav', '')
        else:
            intro_name = f"amb_{map_lower}_intro"
            intro_wav  = os.path.join(amb_dir, f"{intro_name}.wav")

        wav_rel_path  = f"world/maps/{map_lower}/audio/amb/{os.path.basename(intro_wav)}"

        ilu_content = f'''DESCRIPTOR =
{{
\t{{
\t\tNAME = "SoundDescriptor_Template",
\t\tSoundDescriptor_Template =
\t\t{{
\t\t\tname = "{intro_name}",
\t\t\tvolume = 0,
\t\t\tcategory = "amb",
\t\t\tlimitCategory = "",
\t\t\tlimitMode = 0,
\t\t\tmaxInstances = 4294967295,
\t\t\tfiles =
\t\t\t{{
\t\t\t\t{{
\t\t\t\t\tVAL = "{wav_rel_path}",
\t\t\t\t}},
\t\t\t}},
\t\t\tserialPlayingMode = 0,
\t\t\tserialStoppingMode = 0,
\t\t\tparams =
\t\t\t{{
\t\t\t\tNAME = "SoundParams",
\t\t\t\tSoundParams =
\t\t\t\t{{
\t\t\t\t\tloop = 0,
\t\t\t\t\tplayMode = 1,
\t\t\t\t\tplayModeInput = "",
\t\t\t\t\trandomVolMin = 0,
\t\t\t\t\trandomVolMax = 0,
\t\t\t\t\tdelay = 0,
\t\t\t\t\trandomDelay = 0,
\t\t\t\t\trandomPitchMin = 1,
\t\t\t\t\trandomPitchMax = 1,
\t\t\t\t\tfadeInTime = 0,
\t\t\t\t\tfadeOutTime = 0,
\t\t\t\t\tfilterFrequency = 0,
\t\t\t\t\tfilterType = 2,
\t\t\t\t\ttransitionSampleOffset = 0,
\t\t\t\t}},
\t\t\t}},
\t\t\tpauseInsensitiveFlags = 0,
\t\t\toutDevices = 4294967295,
\t\t\tsoundPlayAfterdestroy = 0,
\t\t}},
\t}},
}}
appendTable(component.SoundComponent_Template.soundList,DESCRIPTOR)'''

        tpl_content = f'''params=
{{
\tNAME="Actor_Template",
\tActor_Template=
\t{{
\t\tCOMPONENTS=
\t\t{{
\t\t}}
\t}}
}}
includeReference("EngineData/Misc/Components/SoundComponent.ilu")
includeReference("world/maps/{map_name}/audio/amb/{intro_name}.ilu")'''

        with open(os.path.join(amb_dir, f"{intro_name}.ilu"), 'w', encoding='utf-8') as f:
            f.write(ilu_content)
        with open(os.path.join(amb_dir, f"{intro_name}.tpl"), 'w', encoding='utf-8') as f:
            f.write(tpl_content)
        print(f"    Created intro AMB files: {intro_name}.tpl/.ilu")

    # Always inject AMB actor into audio ISC (regardless of whether files came from IPK)
    audio_isc_path = os.path.join(target_dir, f"Audio/{map_name}_audio.isc")
    if os.path.exists(audio_isc_path):
        with open(audio_isc_path, "r", encoding="utf-8") as f:
            isc_data = f.read()
        if intro_name not in isc_data:
            amb_actor = (
                f'\t\t<ACTORS NAME="Actor">\n'
                f'\t\t\t<Actor RELATIVEZ="0.000002" SCALE="1.000000 1.000000" xFLIPPED="0"'
                f' USERFRIENDLY="{intro_name}" POS2D="0.000000 0.000000" ANGLE="0.000000"'
                f' INSTANCEDATAFILE="" LUA="World/MAPS/{map_name}/audio/AMB/{intro_name}.tpl">\n'
                f'\t\t\t\t<COMPONENTS NAME="SoundComponent">\n'
                f'\t\t\t\t\t<SoundComponent />\n'
                f'\t\t\t\t</COMPONENTS>\n'
                f'\t\t\t</Actor>\n'
                f'\t\t</ACTORS>\n'
            )
            isc_data = isc_data.replace("\t\t<sceneConfigs>", amb_actor + "\t\t<sceneConfigs>")
            with open(audio_isc_path, "w", encoding="utf-8") as f:
                f.write(isc_data)
            print(f"    Injected intro AMB actor into audio ISC")

    # Generate the intro WAV with a 200ms fade-out at the tail end.
    # If the video intro is longer than the OGG pre-roll, prepend silence via adelay so
    # the audio content starts at the right moment relative to the video.
    # Uses -t to limit input duration instead of atrim for reliability.
    delay_ms = int(audio_delay * 1000)
    if delay_ms > 0:
        af_filter = (
            f"adelay={delay_ms}|{delay_ms},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={fade_start:.3f}:d=0.2"
        )
        print(f"    Intro audio delayed by {audio_delay:.3f}s (video intro longer than OGG pre-roll)")
    else:
        af_filter = f"afade=t=out:st={fade_start:.3f}:d=0.2"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-t", f"{audio_content_dur:.3f}", "-i", ogg_path,
         "-af", af_filter, "-ar", "48000", intro_wav],
        check=True
    )
    print(f"    Generated intro AMB: {os.path.basename(intro_wav)} ({amb_duration:.3f}s, fade from {fade_start:.3f}s)")


def extract_amb_audio(ogg_path, map_name, target_dir, state):
    """Extract real audio for AMB clips from the OGG, replacing silent placeholders.

    Uses SoundSetClip data from the mainsequence tape and marker-based timing
    to cut the correct segments from the original OGG file.

    Only processes intro AMBs (StartTime <= 0) because their audio content
    comes from the OGG pre-roll.
    """
    if not getattr(state, 'amb_sound_clips', None) or not ogg_path:
        return

    amb_dir = os.path.join(target_dir, "Audio", "AMB")
    if not os.path.isdir(amb_dir):
        return

    # Calculate pre-roll boundary
    marker_preroll_ms = getattr(state, 'marker_preroll_ms', None)
    if marker_preroll_ms is not None:
        preroll_s = marker_preroll_ms / 1000.0
    elif getattr(state, 'a_offset', None) is not None and state.a_offset < 0:
        preroll_s = abs(state.a_offset) + 1.355
    else:
        return

    if preroll_s <= 0:
        return

    intro_clips = [c for c in state.amb_sound_clips if c["start_time"] <= 0]
    for clip in intro_clips:
        wav_path = os.path.join(amb_dir, f"{clip['name']}.wav")
        # Only overwrite silent placeholders.  Step 09 creates 0.1s mono WAV stubs
        # which are ~9.6KB (48kHz × 2 bytes × 4800 samples + header).  Any real
        # pre-roll audio at 48kHz for 1+ seconds will be well above 50KB.
        if os.path.exists(wav_path) and os.path.getsize(wav_path) < 50000:
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error",
                     "-i", ogg_path,
                     "-t", f"{preroll_s:.3f}",
                     "-af", f"afade=t=out:st={max(0, preroll_s - 0.2):.3f}:d=0.2",
                     "-ar", "48000", wav_path],
                    check=True)
                print(f"    Extracted real AMB audio: {clip['name']}.wav "
                      f"({preroll_s:.3f}s from OGG)")
            except subprocess.CalledProcessError as e:
                print(f"    Warning: Failed to extract AMB audio for "
                      f"{clip['name']}: {e}")


def show_ffplay_preview(video_path, audio_path, v_override, a_offset):
    """Sync preview using an ffmpeg -> ffplay pipe, considering both offsets. Blocks until closed."""
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print(f"ERROR: Preview files missing!\nVideo: {video_path}\nAudio: {audio_path}")
        return

    net_offset = v_override - a_offset
    delay_ms = int(abs(net_offset) * 1000)

    if net_offset == 0.0:
        a_filt = "anull"
        v_filt = "null"
    elif net_offset < 0:
        # Video starts first. Delay audio.
        a_filt = f"adelay=delays={delay_ms}:all=1"
        v_filt = "null"
    else:
        # Audio starts first. Delay video.
        a_filt = "anull"
        v_filt = f"setpts=PTS+({net_offset}/TB)"

    # We use libx264/ultrafast and pcm_s16le to ensure the pipe is fast and compatible
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", f"[1:a]{a_filt}[a];[0:v]{v_filt}[v]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "pcm_s16le",
        "-f", "matroska", "-"
    ]

    ffplay_cmd = ["ffplay", "-i", "-", "-autoexit", "-loglevel", "quiet",
                  "-window_title", "SYNC PREVIEW - CLOSE TO CONTINUE"]

    print(f"\n    Launching sync preview (net delay: {net_offset:.3f}s)...")
    print("    Close the preview window to return to the menu.")

    try:
        # Suppress stderr from both processes to avoid version spam and broken pipe errors
        p_ffmpeg = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p_ffplay = subprocess.Popen(ffplay_cmd, stdin=p_ffmpeg.stdout, stderr=subprocess.DEVNULL)

        # Allow p_ffmpeg to receive a SIGPIPE if p_ffplay exits
        p_ffmpeg.stdout.close()

        # Wait for ffplay to close
        p_ffplay.wait()

        # Terminate ffmpeg if it's still running
        if p_ffmpeg.poll() is None:
            p_ffmpeg.terminate()
            p_ffmpeg.wait(timeout=5)

        print("    Preview closed.")

    except Exception as e:
        print(f"    ERROR: Preview session failed: {e}")
        # Clean up processes on error
        for p in [p_ffmpeg, p_ffplay]:
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass


def _build_preview_commands(video_path, audio_path, v_override, a_offset, window_handle=None):
    """Build ffmpeg and ffplay command lists for sync preview.

    Args:
        window_handle: If provided (int), embeds ffplay into that OS window handle
                       using ffplay's -wid flag (HWND on Windows).
    """
    net_offset = v_override - a_offset
    delay_ms = int(abs(net_offset) * 1000)

    if net_offset == 0.0:
        a_filt = "anull"
        v_filt = "null"
    elif net_offset < 0:
        trim_s = abs(net_offset)
        a_filt = f"atrim=start={trim_s},asetpts=PTS-STARTPTS"
        v_filt = "null"
    else:
        a_filt = f"adelay=delays={delay_ms}:all=1"
        v_filt = f"setpts=PTS+({net_offset}/TB)"

    ffmpeg_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", f"[1:a]{a_filt}[a];[0:v]{v_filt}[v]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "pcm_s16le",
        "-f", "matroska", "-"
    ]

    if window_handle is not None:
        ffplay_cmd = ["ffplay", "-i", "-", "-autoexit", "-loglevel", "quiet",
                      "-noborder", "-wid", str(window_handle)]
    else:
        ffplay_cmd = ["ffplay", "-i", "-", "-autoexit", "-loglevel", "quiet",
                      "-window_title", "SYNC PREVIEW - CLOSE TO CONTINUE"]

    return ffmpeg_cmd, ffplay_cmd, net_offset


def launch_preview_async(video_path, audio_path, v_override, a_offset, window_handle=None):
    """Launch ffplay preview and return process handles without blocking.

    Args:
        window_handle: If provided (int), embeds ffplay into that OS window handle.

    Returns:
        tuple: (p_ffmpeg, p_ffplay) Popen objects, or (None, None) on error.
    """
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print(f"ERROR: Preview files missing!\nVideo: {video_path}\nAudio: {audio_path}")
        return None, None

    ffmpeg_cmd, ffplay_cmd, net_offset = _build_preview_commands(
        video_path, audio_path, v_override, a_offset, window_handle)

    print(f"    Launching sync preview (net delay: {net_offset:.3f}s)...")

    try:
        p_ffmpeg = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p_ffplay = subprocess.Popen(ffplay_cmd, stdin=p_ffmpeg.stdout, stderr=subprocess.DEVNULL)
        p_ffmpeg.stdout.close()
        return p_ffmpeg, p_ffplay
    except Exception as e:
        print(f"    ERROR: Could not launch preview: {e}")
        return None, None


def kill_preview(p_ffmpeg, p_ffplay):
    """Terminate preview processes gracefully."""
    for p in [p_ffplay, p_ffmpeg]:
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Pipeline step functions
# ---------------------------------------------------------------------------

def _safe_rmtree(path):
    """Remove a directory tree, logging warnings on failure."""
    if os.path.exists(path):
        try:
            shutil.rmtree(path)
        except Exception as e:
            print(f"    Warning: Could not fully delete {path}: {e}")
            print("    Continuing anyway...")


def reprocess_audio(state, a_offset, v_override=None):
    """Reprocess audio files after offset adjustment.

    Shared by both the CLI sync loop and the GUI apply action.
    Converts audio, regenerates AMB intro, extracts AMB audio,
    and clears the game cache.

    Args:
        state: PipelineState with audio_path, map_name, target_dir, cache_dir, etc.
        a_offset: Audio offset in seconds (positive = pad, negative = trim).
        v_override: Video start time override (used for AMB timing).
    """
    if v_override is None:
        v_override = getattr(state, 'v_override', 0.0) or 0.0
    convert_audio(state.audio_path, state.map_name, state.target_dir, a_offset)
    generate_intro_amb(state.audio_path, state.map_name, state.target_dir,
                       a_offset, v_override,
                       marker_preroll_ms=getattr(state, 'marker_preroll_ms', None))
    extract_amb_audio(state.audio_path, state.map_name, state.target_dir, state)
    state.a_offset = a_offset
    if state.cache_dir and os.path.exists(state.cache_dir):
        _safe_rmtree(state.cache_dir)
        print(f"    Cleared game cache for {state.map_name}.")


def unregister_sku(jd21_dir, map_name):
    """Remove a map from SkuScene_Maps_PC_All.isc if present."""
    sku_isc = os.path.join(jd21_dir, "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
    if not os.path.exists(sku_isc):
        return

    with open(sku_isc, "r", encoding="utf-8") as f:
        sku_data = f.read()

    # Early exit if map name isn't in file at all
    if f'USERFRIENDLY="{map_name}"' not in sku_data and f'name="{map_name}"' not in sku_data:
        return

    print(f"    Removing old SkuScene registration for: {map_name}")
    
    # 1. Remove Actor blocks using a regex that captures <ACTORS...><Actor...USERFRIENDLY="name"...</ACTORS>
    # We use non-greedy .*? to match everything within the actor block safely.
    pattern_actor = r'[ \t]*<ACTORS NAME="Actor">\s*<Actor[^>]*USERFRIENDLY="' + re.escape(map_name) + r'"[^>]*>.*?</ACTORS>\s*'
    new_data, count_act = re.subn(pattern_actor, '\n', sku_data, flags=re.DOTALL)
    
    # 2. Remove CoverflowSkuSongs blocks
    pattern_cover = r'[ \t]*<CoverflowSkuSongs>\s*<CoverflowSong[^>]*name="' + re.escape(map_name) + r'"[^>]*>.*?</CoverflowSkuSongs>\s*'
    new_data, count_cov = re.subn(pattern_cover, '\n', new_data, flags=re.DOTALL)

    if count_act > 0 or count_cov > 0:
        # Clean up any excessive newlines left behind by the removal
        new_data = re.sub(r'\n{3,}', '\n\n', new_data)
        with open(sku_isc, "w", encoding="utf-8") as f:
            f.write(new_data)


def step_00_pre_install_cleanup(state):
    """Clean up any previous installation of this map, including bad codenames."""
    names_to_clean = [state.map_name]
    if state.original_map_name and state.original_map_name != state.map_name:
        names_to_clean.append(state.original_map_name)

    print("[0] Performing pre-install cleanup for target map...")
    for name in names_to_clean:
        # Delete main map directory
        map_dir = os.path.join(state.jd21_dir, "data", "World", "MAPS", name)
        if os.path.exists(map_dir):
            print(f"    Deleting previous map directory: {name}")
            _safe_rmtree(map_dir)

        # Delete cooked cache directories
        name_lower = name.lower()
        map_cache = os.path.join(state.jd21_dir, "data", "cache", "itf_cooked", "pc", "world", "maps", name_lower)
        auto_cache = map_cache + "_autodance"
        cine_cache = map_cache + "_cine"
        audio_cache = os.path.join(state.jd21_dir, "data", "cache", "itf_cooked", "pc", "world", "maps", name_lower, "audio")

        for cache_path in [map_cache, auto_cache, cine_cache, audio_cache]:
            if os.path.exists(cache_path):
                print(f"    Deleting cache: {os.path.basename(cache_path)}")
                _safe_rmtree(cache_path)

        # Unregister from SkuScene
        unregister_sku(state.jd21_dir, name)


def step_01_clean(state):
    """Clean previous build artifacts."""
    print("[1] Cleaning up if there is a previous build...")
    _safe_rmtree(state.target_dir)
    _safe_rmtree(state.cache_dir)
    if not getattr(state, "preserve_source_dirs", False):
        _safe_rmtree(state.extracted_zip_dir)
        _safe_rmtree(state.ipk_extracted)


def step_02_download(state):
    """Download assets from JDU servers and detect codename/audio/video paths."""
    if getattr(state, "skip_download", False):
        print("[2] Skipping remote download (manual/IPK source mode)...")
        if not state.codename:
            state.codename = state.map_name

        # Best-effort media auto-detection if caller did not pre-fill paths
        # or if the pre-filled paths no longer exist (stale from a previous run).
        if not state.audio_path or not os.path.isfile(state.audio_path):
            from source_analysis import _pick_audio
            state.audio_path = _pick_audio(state.download_dir, state.codename)
            # Also search inside ipk_extracted/ (IPK audio may be nested)
            if not state.audio_path and hasattr(state, 'ipk_extracted') and os.path.isdir(state.ipk_extracted):
                state.audio_path = _pick_audio(state.ipk_extracted, state.codename)

        if not state.video_path or not os.path.isfile(state.video_path):
            preferred_video, _actual = map_downloader.find_best_video_file(
                state.download_dir, state.codename or state.map_name, state.quality)
            if preferred_video:
                state.video_path = preferred_video
            else:
                webms = [f for f in glob.glob(os.path.join(state.download_dir, "*.webm"))
                         if "MapPreview" not in os.path.basename(f)
                         and "VideoPreview" not in os.path.basename(f)]
                if webms:
                    state.video_path = webms[0]
            # Also search inside ipk_extracted/ for video
            if not state.video_path and hasattr(state, 'ipk_extracted') and os.path.isdir(state.ipk_extracted):
                webms = glob.glob(os.path.join(state.ipk_extracted, "**", "*.webm"), recursive=True)
                webms = [f for f in webms
                         if "mappreview" not in os.path.basename(f).lower()
                         and "videopreview" not in os.path.basename(f).lower()]
                if webms:
                    state.video_path = webms[0]

        # For IPK mode with a file to unpack, audio/video may not exist yet
        # (they'll be extracted in step_04).  Defer the requirement check.
        has_pending_ipk = getattr(state, "manual_ipk_file", None) and not getattr(state, "skip_ipk_unpack", False)
        if not state.audio_path and not has_pending_ipk:
            raise RuntimeError("Audio file (.ogg/.wav/.wav.ckd) is required for manual/IPK install mode.")
        if not state.video_path and not has_pending_ipk:
            raise RuntimeError("Gameplay video (.webm) is required for manual/IPK install mode.")
        return

    print("[2] Downloading assets from JDU servers...")
    urls1 = map_downloader.extract_urls(state.asset_html) if state.asset_html and os.path.exists(state.asset_html) else []
    urls2 = map_downloader.extract_urls(state.nohud_html) if state.nohud_html and os.path.exists(state.nohud_html) else []
    map_downloader.download_files(urls1 + urls2, state.download_dir,
                                  quality=state.quality, interactive=False)

    # Auto-detect internal codename from downloaded files
    state.codename = state.map_name
    for f in os.listdir(state.download_dir):
        if "_MAIN_SCENE" in f and f.endswith(".zip"):
            state.codename = f.split("_MAIN_SCENE")[0]
            break
        elif f.endswith(".ogg") and "AudioPreview" not in f:
            state.codename = f[:-4]
            break

    print(f"    Detected Internal Codename: {state.codename}")

    # Check if necessary media exists, since auth links might expire
    audio_path = os.path.join(state.download_dir, f"{state.codename}.ogg")
    if not os.path.exists(audio_path):
        oggs = [f for f in glob.glob(os.path.join(state.download_dir, "*.ogg")) if "AudioPreview" not in f]
        if oggs:
            audio_path = oggs[0]
        else:
            raise RuntimeError("Full Audio missing! Check if NO-HUD links expired. Cannot proceed.")
    state.audio_path = audio_path

    video_path = None
    # Search for video in quality preference order starting from user's choice
    video_path, actual_quality = map_downloader.find_best_video_file(
        state.download_dir, state.codename, state.quality)
    if video_path and actual_quality != state.quality:
        print(f"    Note: Requested {state.quality} quality not found, using {actual_quality}")
    if not video_path:
        webms = [f for f in glob.glob(os.path.join(state.download_dir, "*.webm")) if "MapPreview" not in f and "VideoPreview" not in f]
        if webms:
            video_path = webms[0]
        else:
            raise RuntimeError("Full Video missing! Check if NO-HUD links expired. Cannot proceed.")
    state.video_path = video_path


def step_03_extract_scenes(state):
    """Extract scene ZIP archives, preferring DURANGO platform."""
    if getattr(state, "skip_scene_extract", False):
        print("[3] Skipping scene ZIP extraction (source already prepared)...")
        return

    print("[3] Extracting scene archives...")
    sys.stdout.flush()

    os.makedirs(state.extracted_zip_dir, exist_ok=True)

    # Collect all scene ZIPs and identify preferred platform
    scene_zips = []
    for f in os.listdir(state.download_dir):
        if "SCENE" in f and f.endswith(".zip"):
            scene_zips.append(f)

    # Prefer DURANGO > NX > SCARLETT > any
    PREFERRED_PLATFORMS = ["DURANGO", "NX", "SCARLETT"]
    selected = None
    for plat in PREFERRED_PLATFORMS:
        matches = [z for z in scene_zips if f"_MAIN_SCENE_{plat}" in z.upper()]
        if matches:
            selected = matches[0]
            break

    if selected:
        # Extract only the preferred platform scene
        scene_zip = os.path.join(state.download_dir, selected)
        print(f"    Extracting {selected}...")
        with zipfile.ZipFile(scene_zip, 'r') as z:
            z.extractall(state.extracted_zip_dir)
    else:
        # Fallback: extract all scene ZIPs (legacy behavior)
        for f in scene_zips:
            scene_zip = os.path.join(state.download_dir, f)
            print(f"    Extracting {f}...")
            with zipfile.ZipFile(scene_zip, 'r') as z:
                z.extractall(state.extracted_zip_dir)


def _detect_maps_in_ipk(ipk_extracted):
    """Scan an extracted IPK directory for map codenames.

    Returns a list of codename strings found under world/maps/.
    """
    maps_dirs = glob.glob(os.path.join(ipk_extracted, "**", "world", "maps"), recursive=True)
    codenames = set()
    for maps_dir in maps_dirs:
        if os.path.isdir(maps_dir):
            for entry in os.listdir(maps_dir):
                full = os.path.join(maps_dir, entry)
                if os.path.isdir(full) and not entry.startswith('.'):
                    codenames.add(entry)
    return sorted(codenames)


def step_04_unpack_ipk(state):
    """Unpack IPK archives."""
    has_manual_ipk = getattr(state, "manual_ipk_file", None) and os.path.isfile(state.manual_ipk_file)

    # When a specific IPK file is provided, always re-extract to avoid using
    # stale content from a previous IPK that shared the same extraction dir.
    if getattr(state, "skip_ipk_unpack", False) and os.path.isdir(state.ipk_extracted) and not has_manual_ipk:
        print("[4] Skipping IPK unpack (already prepared)...")
        return

    # Clear previous extraction if it exists and we're not skipping
    if os.path.isdir(state.ipk_extracted):
        print(f"[4] Clearing previous IPK extraction at {os.path.basename(state.ipk_extracted)}...")
        _safe_rmtree(state.ipk_extracted)
    os.makedirs(state.ipk_extracted, exist_ok=True)

    if getattr(state, "manual_ipk_file", None) and os.path.isfile(state.manual_ipk_file):
        print("[4] Unpacking selected IPK file...")
        try:
            ipk_unpack.extract(state.manual_ipk_file, state.ipk_extracted)
        except (AssertionError, OSError, struct.error) as e:
            logger.warning("    Warning: IPK extraction issue: %s", e)
    else:
        print("[4] Unpacking IPK archives...")
        ipk_files = glob.glob(os.path.join(state.extracted_zip_dir, "*.ipk"))
        for ipk in ipk_files:
            print(f"    Unpacking {os.path.basename(ipk)}...")
            try:
                ipk_unpack.extract(ipk, state.ipk_extracted)
            except (AssertionError, OSError, struct.error) as e:
                logger.warning("    Warning: IPK extraction issue: %s", e)

    # Detect bundle IPKs (multiple maps in one archive)
    detected_maps = _detect_maps_in_ipk(state.ipk_extracted)
    if len(detected_maps) > 1:
        print(f"    Bundle IPK detected: {len(detected_maps)} maps found: {', '.join(detected_maps)}")
        # Try to match the codename from the IPK filename
        target = state.codename.lower() if state.codename else ""
        matching = [m for m in detected_maps if m.lower() == target]
        if not matching:
            # Codename from IPK filename didn't match; use the first map
            # and store the full list so the GUI can offer a selection.
            state.bundle_maps = detected_maps
            state.codename = detected_maps[0]
            print(f"    Auto-selected first map: {state.codename}")
            print(f"    To install other maps from this bundle, re-run with the specific codename.")
        else:
            state.codename = matching[0]
            print(f"    Using matched codename: {state.codename}")
    elif len(detected_maps) == 1:
        # Single map -- update codename if it was derived from the IPK filename
        if state.codename.lower() != detected_maps[0].lower():
            print(f"    Codename correction: {state.codename} -> {detected_maps[0]}")
            state.codename = detected_maps[0]

    # Re-detect audio/video after extraction if not yet set (IPK mode defers
    # detection until the files are actually extracted).
    if not state.audio_path or not os.path.isfile(state.audio_path):
        from source_analysis import _pick_audio
        state.audio_path = _pick_audio(state.ipk_extracted, state.codename)
        if not state.audio_path:
            state.audio_path = _pick_audio(state.download_dir, state.codename)
        if state.audio_path:
            print(f"    Detected audio: {os.path.basename(state.audio_path)}")
        else:
            raise RuntimeError(
                "No audio file found after IPK extraction. "
                "Ensure the IPK contains .ogg, .wav, or .wav.ckd audio.")

    if not state.video_path or not os.path.isfile(state.video_path):
        webms = glob.glob(os.path.join(state.ipk_extracted, "**", "*.webm"), recursive=True)
        webms = [f for f in webms
                 if "mappreview" not in os.path.basename(f).lower()
                 and "videopreview" not in os.path.basename(f).lower()]
        if webms:
            state.video_path = webms[0]
        if not state.video_path:
            preferred_video, _ = map_downloader.find_best_video_file(
                state.download_dir, state.codename or state.map_name, state.quality)
            if preferred_video:
                state.video_path = preferred_video
        if state.video_path:
            print(f"    Detected video: {os.path.basename(state.video_path)}")
        else:
            raise RuntimeError(
                "No gameplay video (.webm) found after IPK extraction. "
                "Ensure a .webm file is in the source directory.")


def step_05_decode_menuart(state):
    """Decode MenuArt CKDs and copy raw PNG/JPGs."""
    print("[5] Decoding menu art textures...")

    # Only scan download_dir for loose textures if it looks like a map-specific
    # directory (not a drive root or the user's Desktop, which would be slow
    # and pick up irrelevant files).
    _download_looks_safe = (
        os.path.exists(state.download_dir)
        and len(os.path.basename(state.download_dir)) > 0
        and os.path.dirname(state.download_dir) != state.download_dir  # not a drive root
    )
    if _download_looks_safe:
        for file in os.listdir(state.download_dir):
            src = os.path.join(state.download_dir, file)
            dst = None
            if file.endswith(".tga.ckd") or file.endswith(".jpg") or file.endswith(".png") or file.endswith(".png.ckd"):
                if "Phone" in file or "1024" in file or state.codename.lower() in file.lower() or state.map_name.lower() in file.lower():
                    new_name = re.sub(re.escape(state.codename), state.map_name, file, flags=re.IGNORECASE) if state.codename.lower() in file.lower() else file
                    dst = os.path.join(state.target_dir, f"MenuArt/textures/{new_name}")

            if dst:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

    if hasattr(state, "ipk_extracted") and state.ipk_extracted and os.path.exists(state.ipk_extracted):
        import glob
        menuart_search_dir = getattr(state, 'override_menuart_dir', None)
        if menuart_search_dir and os.path.isdir(menuart_search_dir):
            menuart_sources = glob.glob(os.path.join(menuart_search_dir, "*.*"))
        else:
            menuart_sources = glob.glob(os.path.join(state.ipk_extracted, "**", "menuart", "textures", "*.*"), recursive=True)
        for src in menuart_sources:
            file = os.path.basename(src)
            if file.endswith(".ckd") or file.endswith(".png") or file.endswith(".jpg"):
                new_name = re.sub(re.escape(state.codename), state.map_name, file, flags=re.IGNORECASE) if state.codename.lower() in file.lower() else file
                dst = os.path.join(state.target_dir, f"MenuArt/textures/{new_name}")
                if not os.path.exists(dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)

    # Decode CKDs to actual TGAs/PNGs
    menuart_dir = os.path.join(state.target_dir, "MenuArt/textures")
    if os.path.isdir(menuart_dir):
        subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "ckd_decode.py"), "--batch", "--quiet",
                        menuart_dir, menuart_dir], check=False, capture_output=True,
                       timeout=120)
    else:
        print("    No MenuArt/textures directory to decode.")


def step_05b_validate_menuart(state):
    """Validate and fix cover TGA files after MenuArt decoding."""
    from PIL import Image

    tex_dir = os.path.join(state.target_dir, "MenuArt", "textures")
    if not os.path.isdir(tex_dir):
        print("    WARNING: MenuArt/textures directory not found!")
        return

    # Expected cover TGAs (lowercase as ISC references them)
    expected_covers = [
        f"{state.map_name}_cover_generic.tga",
        f"{state.map_name}_cover_online.tga",
        f"{state.map_name}_cover_albumbkg.tga",
        f"{state.map_name}_cover_albumcoach.tga",
        f"{state.map_name}_banner_bkg.tga",
        f"{state.map_name}_map_bkg.tga",
    ]

    # Build case-insensitive lookup of what actually exists
    actual_files = os.listdir(tex_dir)
    actual_lower_map = {f.lower(): f for f in actual_files}

    print("    --- MenuArt Diagnostic ---")
    found_tgas = {}
    for expected in expected_covers:
        actual = actual_lower_map.get(expected.lower())
        if actual:
            full_path = os.path.join(tex_dir, actual)
            size = os.path.getsize(full_path)
            print(f"    [OK]   {expected} ({size:,} bytes)")
            found_tgas[expected.lower()] = full_path

            # Fix case mismatch: rename if case differs from what ISC expects
            if actual != expected:
                correct_path = os.path.join(tex_dir, expected)
                os.rename(full_path, correct_path)
                found_tgas[expected.lower()] = correct_path
                print(f"           Renamed {actual} -> {expected} (case fix)")
        else:
            print(f"    [MISS] {expected}")

    # If cover_online is missing but cover_generic exists, copy it (and vice versa)
    online_key = f"{state.map_name}_cover_online.tga".lower()
    generic_key = f"{state.map_name}_cover_generic.tga".lower()

    if online_key not in found_tgas and generic_key in found_tgas:
        src = found_tgas[generic_key]
        dst = os.path.join(tex_dir, f"{state.map_name}_cover_online.tga")
        shutil.copy2(src, dst)
        found_tgas[online_key] = dst
        print(f"    [FIX]  Created cover_online.tga from cover_generic.tga")

    if generic_key not in found_tgas and online_key in found_tgas:
        src = found_tgas[online_key]
        dst = os.path.join(tex_dir, f"{state.map_name}_cover_generic.tga")
        shutil.copy2(src, dst)
        found_tgas[generic_key] = dst
        print(f"    [FIX]  Created cover_generic.tga from cover_online.tga")

    # Re-save all found cover TGAs through Pillow to ensure consistent
    # uncompressed TGA format (RGBA, 32-bit, no RLE compression)
    resaved = 0
    for key, path in found_tgas.items():
        if not path.lower().endswith('.tga'):
            continue
        try:
            img = Image.open(path)
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            img.save(path, format='TGA')
            resaved += 1
        except Exception as e:
            print(f"    [WARN] Could not re-save {os.path.basename(path)}: {e}")

    if resaved:
        print(f"    Re-saved {resaved} TGA(s) as uncompressed 32-bit RGBA")
    print("    --- End MenuArt Diagnostic ---")


def step_06_generate_configs(state):
    """Generate UbiArt config files (scenes, templates, tracks, manifests)."""
    print("[6] Generating UbiArt config files (scenes, templates, tracks, manifests)...")
    map_builder.setup_dirs(state.target_dir)

    # Check for non-ASCII characters in metadata (Title, Artist, Credits, etc.)
    if not hasattr(state, 'metadata_overrides') or state.metadata_overrides is None:
        state.metadata_overrides = {}
    problems = map_builder.check_metadata_encoding(state.ipk_extracted)
    if problems:
        non_ascii_fields = {k: v for k, v in problems.items() if k not in state.metadata_overrides}
        if non_ascii_fields:
            print(f"\n    [!] Non-ASCII characters detected in song metadata:")
            for field, val in non_ascii_fields.items():
                non_ascii = [c for c in val if ord(c) > 127]
                print(f"      {field}: '{val}'")
                print(f"        Non-ASCII chars: {non_ascii}")
            if getattr(state, '_interactive', True):
                print(f"\n    These characters may cause game engine errors.")
                for field, val in non_ascii_fields.items():
                    replacement = input(f"    Replace {field}? Enter new value [or leave blank to auto-strip, type 'ignore' to keep original]: ").strip()
                    if replacement.lower() == 'ignore':
                        state.metadata_overrides[field] = val
                        print(f"      Kept original: '{val}'")
                    elif replacement:
                        state.metadata_overrides[field] = replacement
                    else:
                        safe = ''.join(c for c in val if ord(c) < 128)
                        state.metadata_overrides[field] = safe
                        print(f"      Auto-stripped to: '{safe}'")
            else:
                # Non-interactive: auto-strip non-ASCII characters
                for field, val in non_ascii_fields.items():
                    safe = ''.join(c for c in val if ord(c) < 128)
                    state.metadata_overrides[field] = safe
                    print(f"      Auto-stripped {field} to: '{safe}'")

    # Extract musictrack marker data early (needed for IPK v_override synthesis
    # and marker-based pre-roll calculations later)
    _mt_override = getattr(state, 'override_musictrack', None)
    if _mt_override and os.path.isfile(_mt_override):
        mt_meta = map_builder.extract_musictrack_metadata_from_file(_mt_override)
    else:
        mt_meta = map_builder.extract_musictrack_metadata(state.ipk_extracted)
    if mt_meta:
        state.musictrack_start_beat = mt_meta["start_beat"]
        state.marker_preroll_ms = compute_marker_preroll(
            mt_meta["markers"], mt_meta["start_beat"])
        if state.marker_preroll_ms is not None:
            print(f"    Marker pre-roll: {state.marker_preroll_ms:.1f}ms "
                  f"(startBeat={state.musictrack_start_beat})")
        else:
            print(f"    Marker pre-roll: N/A (startBeat={mt_meta['start_beat']})")

        # Preview loop bounds (beat indices → seconds from beat-0)
        markers = mt_meta["markers"]
        pls = int(mt_meta.get("preview_loop_start", 0))
        ple = int(mt_meta.get("preview_loop_end", 0))
        if 0 < pls < len(markers) and 0 < ple < len(markers):
            state.preview_loop_start_sec = markers[pls] / 48.0 / 1000.0
            state.preview_loop_end_sec = markers[ple] / 48.0 / 1000.0
    else:
        print(f"    Warning: Could not extract musictrack metadata; "
              f"using fallbacks for AMB duration")

    # IPK maps: the binary audio already contains the full preroll
    # (beats startBeat..0..endBeat) and the markers array maps beat indices
    # to tick positions within that audio -- so audio must NOT be trimmed.
    #
    # However, the VIDEO needs a negative videoStartTime to tell the engine
    # where beat 0 falls within the video file.  X360 binary CKDs typically
    # store videoStartTime=0.0 because the console engine handled sync
    # differently.  We ALWAYS synthesise from markers for IPK sources when
    # the user has not manually overridden the value, to prevent the
    # "adding a brick in the past" assertion in the PC engine.
    if (state.source_type == "ipk_file"
            and state.v_override is None
            and mt_meta
            and mt_meta["start_beat"] < 0
            and mt_meta["markers"]):
        idx = abs(mt_meta["start_beat"])
        if idx < len(mt_meta["markers"]):
            synthesized = -(mt_meta["markers"][idx] / 48.0 / 1000.0)
            raw_vst = mt_meta.get("video_start_time", 0.0)
            state.v_override = synthesized
            print(f"    Synthesized video offset from markers: {state.v_override:.5f}s "
                  f"(IPK CKD videoStartTime was {raw_vst}, startBeat={mt_meta['start_beat']})")
        else:
            print(f"    Warning: startBeat index {idx} out of range for markers "
                  f"(len={len(mt_meta['markers'])}). Cannot synthesize v_override.")
    elif (state.source_type == "ipk_file"
            and state.v_override is None
            and mt_meta
            and mt_meta["start_beat"] >= 0):
        print(f"    IPK map has startBeat={mt_meta['start_beat']} (no pre-roll). "
              f"videoStartTime=0.0 is correct.")

    _overrides = {}
    if getattr(state, 'override_musictrack', None):
        _overrides["musictrack_path"] = state.override_musictrack
    if getattr(state, 'override_songdesc', None):
        _overrides["songdesc_path"] = state.override_songdesc

    video_start_time = map_builder.generate_text_files(
        state.map_name, state.ipk_extracted, state.target_dir, state.v_override,
        metadata_overrides=state.metadata_overrides or None,
        overrides=_overrides or None)

    if video_start_time is None:
        raise RuntimeError("Could not fetch video start time.")

    state.video_start_time = video_start_time
    print(f"    Video Start Time is: {video_start_time}")


def step_07_convert_tapes(state):
    """Convert choreography and karaoke tapes to Lua."""
    print("[7] Converting choreography and karaoke tapes to Lua...")
    for ty in ["dance", "karaoke"]:
        override_key = 'override_dtape' if ty == "dance" else 'override_ktape'
        override_path = getattr(state, override_key, None)
        if override_path and os.path.isfile(override_path):
            src_tapes = [override_path]
        else:
            src_tapes = glob.glob(os.path.join(state.ipk_extracted, f"**/*_tml_{ty}.?tape.ckd"), recursive=True)
        if src_tapes:
            dst_tape = os.path.join(state.target_dir, f"Timeline/{state.map_name}_TML_{ty.capitalize()}.{ty[0]}tape")
            tape_data = ubiart_lua.load_ckd_json(src_tapes[0])
            lua_str = ubiart_lua.process_tape(tape_data, tape_type=ty)
            with open(dst_tape, 'w', encoding='utf-8') as f:
                f.write(lua_str)
            print(f"    Converted {os.path.basename(src_tapes[0])} -> {os.path.basename(dst_tape)}")
        else:
            if ty == "karaoke":
                print(f"    Note: No karaoke tape found in source. "
                      f"This map will not display lyrics.")
            elif ty == "dance":
                print(f"    WARNING: No dance tape found in source! "
                      f"Choreography may be missing.")


def step_08_convert_cinematics(state):
    """Convert cinematic tapes to Lua."""
    print("[8] Converting cinematic tapes to Lua...")
    _mainseq_override = getattr(state, 'override_mainsequence', None)
    if _mainseq_override and os.path.isfile(_mainseq_override):
        tape_files = [_mainseq_override]
    else:
        tape_files = []
        for cine_dir in glob.glob(os.path.join(state.ipk_extracted, "**/cinematics"), recursive=True):
            tape_files.extend(glob.glob(os.path.join(cine_dir, "*.tape.ckd")))
    cine_converted = 0
    for tape_file in tape_files:
        tape_basename = os.path.basename(tape_file)
        output_name = tape_basename.replace(".ckd", "")
        if "mainsequence" in output_name.lower():
            output_name = f"{state.map_name}_MainSequence.tape"
        dst_path = os.path.join(state.target_dir, f"Cinematics/{output_name}")
        tape_data = ubiart_lua.load_ckd_json(tape_file)
        # Extract SoundSetClip metadata from mainsequence for AMB audio extraction
        if "mainsequence" in tape_basename.lower():
            for raw_clip in tape_data.get("Clips", []):
                if raw_clip.get("__class") == "SoundSetClip":
                    clip_name = raw_clip["SoundSetPath"].split("/")[-1].split(".")[0]
                    state.amb_sound_clips.append({
                        "name": clip_name,
                        "start_time": raw_clip["StartTime"],
                        "duration": raw_clip["Duration"],
                        "path": raw_clip["SoundSetPath"],
                    })
            if state.amb_sound_clips:
                intro_clips = [c for c in state.amb_sound_clips if c["start_time"] <= 0]
                print(f"    Found {len(state.amb_sound_clips)} SoundSetClip(s) "
                      f"({len(intro_clips)} intro)")
        lua_str = ubiart_lua.process_tape(tape_data, tape_type="cinematics")
        with open(dst_path, 'w', encoding='utf-8') as f:
            f.write(lua_str)
        print(f"    Converted {tape_basename} -> {output_name}")
        cine_converted += 1
    if cine_converted == 0:
        print("    No cinematic tapes found, keeping empty fallback.")


def step_09_process_amb(state):
    """Process ambient sound templates."""
    _amb_override = getattr(state, 'override_amb_dir', None)
    if _amb_override and os.path.isdir(_amb_override):
        amb_dirs = [_amb_override]
    else:
        amb_dirs = glob.glob(os.path.join(state.ipk_extracted, "**/audio/amb"), recursive=True)
    if amb_dirs:
        print("[9] Processing ambient sound templates...")
        for amb_dir_path in amb_dirs:
            dest_amb = os.path.join(state.target_dir, "Audio/AMB")
            os.makedirs(dest_amb, exist_ok=True)
            for amb_file in glob.glob(os.path.join(amb_dir_path, "*.tpl.ckd")):
                amb_data = ubiart_lua.load_ckd_json(amb_file)
                ilu_content, tpl_content, audio_file_paths = ubiart_lua.process_ambient_sound(
                    amb_data, state.map_name, os.path.basename(amb_file))
                base = os.path.basename(amb_file).replace('.tpl.ckd', '')
                with open(os.path.join(dest_amb, f"{base}.ilu"), 'w', encoding='utf-8') as f:
                    f.write(ilu_content)
                with open(os.path.join(dest_amb, f"{base}.tpl"), 'w', encoding='utf-8') as f:
                    f.write(tpl_content)
                print(f"    Generated AMB: {base}.ilu + {base}.tpl")
                # Generate silent WAV placeholders for any referenced audio files that don't exist
                # First, try to decode any .wav.ckd files from the IPK
                for rel_path in audio_file_paths:
                    abs_path = os.path.join(state.jd21_dir, "data", rel_path.replace("/", os.sep))
                    if not os.path.exists(abs_path):
                        # Try to find and decode a matching .wav.ckd in the amb source dir
                        wav_name = os.path.basename(rel_path)
                        ckd_candidate = os.path.join(amb_dir_path, wav_name + ".ckd")
                        decoded = None
                        if os.path.isfile(ckd_candidate):
                            from source_analysis import _extract_ckd_audio
                            decoded = _extract_ckd_audio(ckd_candidate, os.path.dirname(abs_path))
                        if decoded and os.path.isfile(decoded):
                            # Rename to expected path if needed
                            if os.path.abspath(decoded) != os.path.abspath(abs_path):
                                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                                shutil.move(decoded, abs_path)
                            print(f"    Decoded AMB audio: {os.path.basename(abs_path)}")
                        else:
                            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                            with wave.open(abs_path, 'w') as wf:
                                wf.setnchannels(1)
                                wf.setsampwidth(2)
                                wf.setframerate(48000)
                                wf.writeframes(b'\x00\x00' * 4800)  # 0.1s silence
                            print(f"    Created silent placeholder: {os.path.basename(abs_path)}")

            # Handle orphan WAV CKDs without matching TPL CKDs (e.g., Koi has
            # amb_koi_intro.wav.ckd but no amb_koi_intro.tpl.ckd).  Generate
            # synthetic TPL+ILU so the engine can reference the AMB actor.
            tpl_bases = {os.path.basename(f).replace('.tpl.ckd', '')
                         for f in glob.glob(os.path.join(amb_dir_path, "*.tpl.ckd"))}
            for wav_ckd in glob.glob(os.path.join(amb_dir_path, "*.wav.ckd")):
                base = os.path.basename(wav_ckd).replace('.wav.ckd', '')
                if base not in tpl_bases:
                    map_lower = state.map_name.lower()
                    wav_rel = f"world/maps/{map_lower}/audio/amb/{base}.wav"
                    # Generate synthetic ILU
                    ilu_content = (
                        f'DESCRIPTOR =\n{{\n'
                        f'\t{{\n\t\tNAME = "SoundDescriptor_Template",\n'
                        f'\t\tSoundDescriptor_Template =\n\t\t{{\n'
                        f'\t\t\tname = "{base}",\n\t\t\tvolume = 0,\n'
                        f'\t\t\tcategory = "amb",\n\t\t\tlimitCategory = "",\n'
                        f'\t\t\tlimitMode = 0,\n\t\t\tmaxInstances = 4294967295,\n'
                        f'\t\t\tfiles =\n\t\t\t{{\n\t\t\t\t{{\n'
                        f'\t\t\t\t\tVAL = "{wav_rel}",\n'
                        f'\t\t\t\t}},\n\t\t\t}},\n'
                        f'\t\t\tserialPlayingMode = 0,\n\t\t\tserialStoppingMode = 0,\n'
                        f'\t\t}},\n\t}},\n}}\n'
                    )
                    # Generate synthetic TPL
                    tpl_content = (
                        f'params =\n{{\n\tNAME = "Actor_Template",\n'
                        f'\tActor_Template =\n\t{{\n\t\tCOMPONENTS =\n\t\t{{\n'
                        f'\t\t\t{{\n\t\t\t\tNAME = "SoundComponent_Template",\n'
                        f'\t\t\t\tSoundComponent_Template =\n\t\t\t\t{{\n'
                        f'\t\t\t\t\tsoundList = {{}},\n'
                        f'\t\t\t\t\tSoundwichEvent = "",\n'
                        f'\t\t\t\t}},\n\t\t\t}},\n\t\t}},\n\t}},\n}}\n'
                    )
                    with open(os.path.join(dest_amb, f"{base}.ilu"), 'w', encoding='utf-8') as f:
                        f.write(ilu_content)
                    with open(os.path.join(dest_amb, f"{base}.tpl"), 'w', encoding='utf-8') as f:
                        f.write(tpl_content)
                    # Try to decode the CKD audio instead of a silent placeholder
                    from source_analysis import _extract_ckd_audio
                    decoded = _extract_ckd_audio(wav_ckd, dest_amb)
                    wav_abs = os.path.join(dest_amb, f"{base}.wav")
                    if decoded and os.path.isfile(decoded):
                        if os.path.abspath(decoded) != os.path.abspath(wav_abs):
                            shutil.move(decoded, wav_abs)
                        print(f"    Decoded orphan AMB audio: {base}.wav")
                    elif not os.path.exists(wav_abs):
                        with wave.open(wav_abs, 'w') as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(48000)
                            wf.writeframes(b'\x00\x00' * 4800)
                    print(f"    Generated synthetic AMB (no TPL CKD): {base}.ilu + {base}.tpl")

        # Inject AMB actors into the audio ISC so the engine actually loads them
        audio_isc_path = os.path.join(state.target_dir, f"Audio/{state.map_name}_audio.isc")
        if os.path.exists(audio_isc_path):
            amb_tpls = glob.glob(os.path.join(state.target_dir, "Audio/AMB/*.tpl"))
            if amb_tpls:
                with open(audio_isc_path, "r", encoding="utf-8") as f:
                    isc_data = f.read()
                amb_actors = ""
                for i, tpl in enumerate(amb_tpls):
                    amb_name = os.path.basename(tpl).replace('.tpl', '')
                    z = f"0.{i + 2:06d}"
                    amb_actors += f'''		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="{z}" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{amb_name}" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="World/MAPS/{state.map_name}/audio/AMB/{amb_name}.tpl">
				<COMPONENTS NAME="SoundComponent">
					<SoundComponent />
				</COMPONENTS>
			</Actor>
		</ACTORS>
'''
                isc_data = isc_data.replace("		<sceneConfigs>", amb_actors + "		<sceneConfigs>")
                with open(audio_isc_path, "w", encoding="utf-8") as f:
                    f.write(isc_data)
                print(f"    Injected {len(amb_tpls)} AMB actor(s) into audio ISC")
    else:
        print("[9] No ambient sound templates found in IPK. "
              "If this map has ambient effects (rain, intro sounds), "
              "they may be missing from the source.")


def step_10_decode_pictos(state):
    """Decode pictograms."""
    print("[10] Decoding pictograms...")
    _pictos_override = getattr(state, 'override_pictos_dir', None)
    if _pictos_override and os.path.isdir(_pictos_override):
        picto_src_dir = _pictos_override
    else:
        picto_src_dir = None
        for path in glob.glob(os.path.join(state.ipk_extracted, "**/pictos"), recursive=True):
            picto_src_dir = path
            break
    sys.stdout.flush()

    if picto_src_dir:
        picto_dst_dir = os.path.join(state.target_dir, "Timeline/pictos")
        os.makedirs(picto_dst_dir, exist_ok=True)
        for f in glob.glob(os.path.join(picto_src_dir, "*.png.ckd")):
            shutil.copy2(f, os.path.join(picto_dst_dir, os.path.basename(f)))
        subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "ckd_decode.py"), "--batch", "--quiet",
                        picto_dst_dir, picto_dst_dir], check=False, capture_output=True)
        for f in glob.glob(os.path.join(picto_dst_dir, "*.ckd")):
            os.remove(f)


def step_11_extract_moves(state):
    """Extract move files and autodance data."""
    print("[11] Extracting move files and autodance data...")
    _moves_override = getattr(state, 'override_moves_dir', None)
    for plat in ["nx", "wii", "durango", "scarlett", "orbis", "prospero", "wiiu", "x360"]:
        if _moves_override and os.path.isdir(_moves_override):
            plat_dir = os.path.join(_moves_override, plat)
            moves_src = [plat_dir] if os.path.isdir(plat_dir) else []
        else:
            moves_src = glob.glob(os.path.join(state.ipk_extracted, f"**/moves/{plat}"), recursive=True)
        for folder in moves_src:
            dest_moves = os.path.join(state.target_dir, f"Timeline/Moves/{plat.upper()}")
            os.makedirs(dest_moves, exist_ok=True)
            for f in glob.glob(os.path.join(folder, "*.*")):
                shutil.copy2(f, os.path.join(dest_moves, os.path.basename(f)))

    # The game engine resolves ClassifierPath gesture files using the active platform
    # folder (e.g. moves/PC/).  Different platforms use different binary formats:
    #   DURANGO/SCARLETT = Kinect 2 .gesture format (compatible with PC)
    #   ORBIS/ORBIS2     = PlayStation Camera .gesture format (INCOMPATIBLE with PC)
    #   WIIU/WII         = .msm skeleton files (platform-neutral)
    # Strategy:
    #   1. Copy .gesture files ONLY from Kinect-compatible platforms (DURANGO, SCARLETT)
    #   2. Copy .msm files from all platforms
    #   3. For any .gesture file that only exists on non-Kinect platforms (e.g. an
    #      ORBIS-exclusive numbered variant like "handstoheart0.gesture"), substitute
    #      it with the base Kinect gesture (strip trailing digits) so the file loads.
    pc_moves_dir = os.path.join(state.target_dir, "Timeline", "Moves", "PC")
    moves_root = os.path.join(state.target_dir, "Timeline", "Moves")
    KINECT_PLATFORMS = {"DURANGO", "SCARLETT", "X360"}
    total_copied = 0
    if os.path.isdir(moves_root):
        for plat_name in os.listdir(moves_root):
            if plat_name.upper() == "PC":
                continue
            plat_dir = os.path.join(moves_root, plat_name)
            if not os.path.isdir(plat_dir):
                continue
            # .gesture: Kinect platforms only (format-compatible with PC adapter)
            if plat_name.upper() in KINECT_PLATFORMS:
                for src in glob.glob(os.path.join(plat_dir, "*.gesture")):
                    dest = os.path.join(pc_moves_dir, os.path.basename(src))
                    if not os.path.exists(dest):
                        os.makedirs(pc_moves_dir, exist_ok=True)
                        shutil.copy2(src, dest)
                        total_copied += 1
            # .msm: all platforms (platform-neutral skeleton format)
            for src in glob.glob(os.path.join(plat_dir, "*.msm")):
                dest = os.path.join(pc_moves_dir, os.path.basename(src))
                if not os.path.exists(dest):
                    os.makedirs(pc_moves_dir, exist_ok=True)
                    shutil.copy2(src, dest)
                    total_copied += 1

        # For .gesture files that are exclusive to non-Kinect platforms (e.g. ORBIS),
        # substitute them with the base Kinect gesture by stripping trailing digits.
        # E.g. "brokenheart_handstoheart0.gesture" (ORBIS-only) → copy
        # "brokenheart_handstoheart.gesture" (DURANGO) under the numbered name.
        pc_gestures = {os.path.basename(f)
                       for f in glob.glob(os.path.join(pc_moves_dir, "*.gesture"))}
        for plat_name in os.listdir(moves_root):
            if plat_name.upper() in KINECT_PLATFORMS or plat_name.upper() == "PC":
                continue
            plat_dir = os.path.join(moves_root, plat_name)
            if not os.path.isdir(plat_dir):
                continue
            for src in glob.glob(os.path.join(plat_dir, "*.gesture")):
                fname = os.path.basename(src)
                if fname in pc_gestures or os.path.exists(os.path.join(pc_moves_dir, fname)):
                    continue
                stem = os.path.splitext(fname)[0]       # e.g. "brokenheart_handstoheart0"
                base = stem.rstrip("0123456789")        # e.g. "brokenheart_handstoheart"
                sub_src = os.path.join(pc_moves_dir, base + ".gesture")
                if base != stem and os.path.exists(sub_src):
                    os.makedirs(pc_moves_dir, exist_ok=True)
                    shutil.copy2(sub_src, os.path.join(pc_moves_dir, fname))
                    total_copied += 1

    if total_copied:
        print(f"    Merged {total_copied} missing gesture/msm file(s) into PC/")

    autodance_tpls = glob.glob(os.path.join(state.ipk_extracted, "**/autodance/*.tpl.ckd"), recursive=True)
    for f in autodance_tpls:
        dest_ad = os.path.join(state.target_dir, "Autodance")
        os.makedirs(dest_ad, exist_ok=True)
        dst_tpl = os.path.join(dest_ad, f"{state.map_name}_autodance.tpl")
        json_to_lua.convert_file(f, dst_tpl)

    # Convert autodance data CKDs (adtape, adrecording, advideo)
    for ext in ["adtape", "adrecording", "advideo"]:
        ad_ckds = glob.glob(os.path.join(state.ipk_extracted, f"**/autodance/*.{ext}.ckd"), recursive=True)
        for f in ad_ckds:
            dest_ad = os.path.join(state.target_dir, "Autodance")
            os.makedirs(dest_ad, exist_ok=True)
            dst_file = os.path.join(dest_ad, f"{state.map_name}.{ext}")
            json_to_lua.convert_file(f, dst_file)

    # Copy any other Autodance media if they exist (ogg, etc.)
    autodance_media = glob.glob(os.path.join(state.ipk_extracted, "**/autodance/*.*"), recursive=True)
    for f in autodance_media:
        if f.endswith(".ckd"):
            continue
        dest_ad = os.path.join(state.target_dir, "Autodance")
        os.makedirs(dest_ad, exist_ok=True)
        shutil.copy2(f, os.path.join(dest_ad, os.path.basename(f)))

    # Convert stape CKD (sequence tape with BPM/Signature data) if available
    stape_ckds = glob.glob(os.path.join(state.ipk_extracted, "**/*.stape.ckd"), recursive=True)
    if stape_ckds:
        dst_stape = os.path.join(state.target_dir, f"Audio/{state.map_name}.stape")
        json_to_lua.convert_file(stape_ckds[0], dst_stape)


def step_12_convert_audio(state):
    """Convert audio to 48kHz WAV with offset."""
    # Resolve default sync parameters if not explicitly set
    if state.v_override is None:
        state.v_override = state.video_start_time
    if state.a_offset is None:
        # For IPK maps, audio already contains full preroll -- no trimming
        # needed.  For HTML/fetch maps, use marker-based pre-roll as default
        # a_offset (more accurate than v_override for maps where
        # videoStartTime differs from the audio pre-roll).
        if state.source_type == "ipk_file":
            state.a_offset = 0.0
            print(f"    IPK map: no audio trim needed "
                  f"(markers encode preroll naturally)")
        elif state.marker_preroll_ms is not None:
            state.a_offset = -(state.marker_preroll_ms / 1000.0)
            print(f"    Using marker-based default a_offset: {state.a_offset:.3f}s "
                  f"(vs v_override: {state.v_override}s)")
        else:
            state.a_offset = state.v_override

    if state.audio_path:
        print(f"[12] Converting audio to 48kHz WAV...")
        convert_audio(state.audio_path, state.map_name, state.target_dir, state.a_offset)
        generate_intro_amb(state.audio_path, state.map_name, state.target_dir,
                           state.a_offset, state.v_override,
                           marker_preroll_ms=state.marker_preroll_ms)
        extract_amb_audio(state.audio_path, state.map_name, state.target_dir, state)


def step_13_copy_video(state):
    """Copy gameplay video to target."""
    if state.video_path:
        print(f"[13] Copying gameplay video...")
        main_vid = os.path.join(state.target_dir, f"VideosCoach/{state.map_name}.webm")
        if not os.path.exists(main_vid):
            shutil.copy2(state.video_path, main_vid)


def step_14_register_sku(state):
    """Register map in SkuScene_Maps_PC_All."""
    sku_isc = os.path.join(state.jd21_dir, "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
    if not os.path.exists(sku_isc):
        print(f"[14] ERROR: SkuScene file not found: {sku_isc}")
        return

    with open(sku_isc, "r", encoding="utf-8") as f:
        sku_data = f.read()

    if f'USERFRIENDLY="{state.map_name}"' in sku_data:
        print(f"[14] {state.map_name} is already registered in SkuScene.")
        return

    print(f"[14] Registering {state.map_name} in SkuScene...")

    # --- Actor XML block to insert before <sceneConfigs> ---
    actor_xml = (
        f'           <ACTORS NAME="Actor">\n'
        f'              <Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0"'
        f' USERFRIENDLY="{state.map_name}" POS2D="0 0" ANGLE="0.000000"'
        f' INSTANCEDATAFILE="world/maps/{state.map_name}/songdesc.act"'
        f' LUA="world/maps/{state.map_name}/songdesc.tpl">\n'
        f'                  <COMPONENTS NAME="JD_SongDescComponent">\n'
        f'                      <JD_SongDescComponent />\n'
        f'                  </COMPONENTS>\n'
        f'              </Actor>\n'
        f'           </ACTORS>\n'
    )

    # Use regex to find <sceneConfigs> with any leading whitespace
    new_data, count = re.subn(
        r'([ \t]*<sceneConfigs>)',
        actor_xml + r'\1',
        sku_data,
        count=1
    )
    if count == 0:
        print(f"[14] WARNING: Could not find <sceneConfigs> insertion point!")
        print(f"     The SkuScene file may have been modified by another tool.")
        return

    # --- Coverflow XML block to insert before </JD_SongDatabaseSceneConfig> ---
    coverflow_xml = (
        f'                          <CoverflowSkuSongs>\n'
        f'                            <CoverflowSong name="{state.map_name}"'
        f'  cover_path="world/maps/{state.map_name}/menuart/actors/{state.map_name}_cover_generic.act">\n'
        f'                              </CoverflowSong>\n'
        f'                          </CoverflowSkuSongs>\n'
        f'                          <CoverflowSkuSongs>\n'
        f'                            <CoverflowSong name="{state.map_name}"'
        f'  cover_path="world/maps/{state.map_name}/menuart/actors/{state.map_name}_cover_online.act">\n'
        f'                              </CoverflowSong>\n'
        f'                          </CoverflowSkuSongs>\n'
    )

    new_data, count2 = re.subn(
        r'([ \t]*</JD_SongDatabaseSceneConfig>)',
        coverflow_xml + r'\1',
        new_data,
        count=1
    )
    if count2 == 0:
        print(f"[14] WARNING: Could not find </JD_SongDatabaseSceneConfig> insertion point!")
        print(f"     Coverflow entries were NOT added. The map may not appear in the song menu.")

    # --- Post-insertion verification ---
    if f'USERFRIENDLY="{state.map_name}"' not in new_data:
        print(f"[14] ERROR: Registration verification failed — map name not found after insertion!")
        return

    with open(sku_isc, "w", encoding="utf-8") as f:
        f.write(new_data)
    print(f"[14] Successfully registered {state.map_name} in SkuScene.")


def configure_manual_source(
    state,
    source_type,
    source_dir,
    ipk_extracted=None,
    audio_path=None,
    video_path=None,
    codename=None,
    manual_ipk_file=None,
    override_musictrack=None,
    override_songdesc=None,
    override_dtape=None,
    override_ktape=None,
    override_mainsequence=None,
    override_moves_dir=None,
    override_pictos_dir=None,
    override_menuart_dir=None,
    override_amb_dir=None,
):
    """Configure a PipelineState for manual/IPK source workflows.

    This keeps the existing pipeline but skips remote download/extract stages
    when inputs are already available on disk.
    """
    state.source_type = source_type
    state.download_dir = os.path.abspath(source_dir)
    state.extracted_zip_dir = os.path.join(state.download_dir, "main_scene_extracted")
    state.ipk_extracted = os.path.abspath(ipk_extracted) if ipk_extracted else os.path.join(state.download_dir, "ipk_extracted")
    state.audio_path = os.path.abspath(audio_path) if audio_path else state.audio_path
    state.video_path = os.path.abspath(video_path) if video_path else state.video_path
    state.codename = (codename or state.map_name).strip()
    state.manual_ipk_file = os.path.abspath(manual_ipk_file) if manual_ipk_file else None

    # Per-asset override paths (manual mode file/folder selectors)
    state.override_musictrack = override_musictrack
    state.override_songdesc = override_songdesc
    state.override_dtape = override_dtape
    state.override_ktape = override_ktape
    state.override_mainsequence = override_mainsequence
    state.override_moves_dir = override_moves_dir
    state.override_pictos_dir = override_pictos_dir
    state.override_menuart_dir = override_menuart_dir
    state.override_amb_dir = override_amb_dir

    state.skip_download = True
    state.skip_scene_extract = True
    # Only skip IPK unpack if the extracted dir was explicitly provided AND
    # we don't have a new IPK file to unpack (avoid reusing stale extraction).
    state.skip_ipk_unpack = bool(
        ipk_extracted and os.path.isdir(state.ipk_extracted)
        and not manual_ipk_file)
    state.preserve_source_dirs = True


# ---------------------------------------------------------------------------
# All pipeline steps in order, for easy iteration
# ---------------------------------------------------------------------------
PIPELINE_STEPS = [
    ("Pre-install cleanup",                     step_00_pre_install_cleanup),
    ("Clean previous builds",                   step_01_clean),
    ("Download assets from JDU servers",        step_02_download),
    ("Extract scene archives",                  step_03_extract_scenes),
    ("Unpack IPK archives",                     step_04_unpack_ipk),
    ("Decode MenuArt textures",                 step_05_decode_menuart),
    ("Validate MenuArt covers",                 step_05b_validate_menuart),
    ("Generate UbiArt config files",            step_06_generate_configs),
    ("Convert choreography/karaoke tapes",      step_07_convert_tapes),
    ("Convert cinematic tapes",                 step_08_convert_cinematics),
    ("Process ambient sounds",                  step_09_process_amb),
    ("Decode pictograms",                       step_10_decode_pictos),
    ("Extract moves & autodance",               step_11_extract_moves),
    ("Convert audio",                           step_12_convert_audio),
    ("Copy gameplay video",                     step_13_copy_video),
    ("Register in SkuScene",                    step_14_register_sku),
]


def main():
    print("==================================================")
    print("           JD2021 Custom Map Installer            ")
    print("==================================================")
    print("[!] IMPORTANT: 'Asset' and 'NoHUD' HTML links expire")
    print("  after roughly 30 minutes! If your download fails,")
    print("  fetch fresh links from the server.")
    print("==================================================\n")

    # Load persistent settings for defaults
    settings = load_settings()

    parser = argparse.ArgumentParser(description="Fully Automated Just Dance 2021 Map Installer")
    parser.add_argument("--map-name", default=None, help="Map name (default: derived from asset-html parent folder)")
    parser.add_argument("--asset-html", default=None, help="Path to asset mapping HTML")
    parser.add_argument("--nohud-html", default=None, help="Path to nohud mapping HTML")
    parser.add_argument("--jd-dir", default=None, help="Base directory of JD tools / JD21 install (auto-detected if omitted)")
    parser.add_argument("--quality", choices=["ultra_hd", "ultra", "high_hd", "high", "mid_hd", "mid", "low_hd", "low"],
                        default=settings["default_quality"],
                        help=f"Video quality to download (default: {settings['default_quality']})")
    parser.add_argument("--video-override", type=float, default=None, help="Force a specific video start time")
    parser.add_argument("--audio-offset", type=float, default=None, help="Force a specific audio trim offset")
    parser.add_argument("--sync-config", default=None, help="Path to a JSON config file to load sync values from")
    parser.add_argument("--readjust", metavar="DOWNLOAD_DIR", default=None,
                        help="Re-adjust offset on an already-installed map. "
                             "Point to the map's download directory (must contain .ogg and .webm files).")
    parser.add_argument("--codename", default=None,
                        help="Fetch HTML from Discord via JDH_Downloader, then install. "
                             "Requires Node.js 18+ and tools/JDH_Downloader/config.json.")
    args = parser.parse_args()

    def _expand_and_clean_path(raw):
        if not raw:
            return None
        cleaned = clean_path(raw)
        return os.path.abspath(cleaned) if cleaned else None

    def _find_html_pair_in_dir(folder):
        """Return (asset_html, nohud_html) from a folder, or (None, None)."""
        if not folder or not os.path.isdir(folder):
            return None, None
        asset = None
        nohud = None
        try:
            for name in os.listdir(folder):
                lower = name.lower()
                full = os.path.join(folder, name)
                if not os.path.isfile(full) or not lower.endswith('.html'):
                    continue
                if "nohud" in lower and not nohud:
                    nohud = full
                elif "asset" in lower and not asset:
                    asset = full
        except OSError:
            return None, None

        # Fallback when names are unusual: pick two html files, prefer non-nohud as asset.
        if not (asset and nohud):
            htmls = []
            try:
                htmls = [os.path.join(folder, n) for n in os.listdir(folder)
                         if os.path.isfile(os.path.join(folder, n)) and n.lower().endswith('.html')]
            except OSError:
                pass
            if len(htmls) >= 2 and not nohud:
                for h in htmls:
                    if "nohud" in os.path.basename(h).lower():
                        nohud = h
                        break
            if len(htmls) >= 2 and not asset:
                for h in htmls:
                    if h != nohud:
                        asset = h
                        break
        return asset, nohud

    def _infer_missing_html_pair(asset_html, nohud_html):
        """Fill missing/supplied-as-directory HTML values with best-effort inference."""
        asset_html = _expand_and_clean_path(asset_html)
        nohud_html = _expand_and_clean_path(nohud_html)

        # If user passed a folder to either arg, use it as a map folder hint.
        for maybe_dir in (asset_html, nohud_html):
            if maybe_dir and os.path.isdir(maybe_dir):
                a2, n2 = _find_html_pair_in_dir(maybe_dir)
                if a2 and not asset_html:
                    asset_html = a2
                if n2 and not nohud_html:
                    nohud_html = n2
                if a2 and n2:
                    return a2, n2

        # If one file is provided, try to locate sibling counterpart.
        known = asset_html or nohud_html
        if known and os.path.isfile(known):
            sibling_dir = os.path.dirname(known)
            a2, n2 = _find_html_pair_in_dir(sibling_dir)
            if not asset_html:
                asset_html = a2
            if not nohud_html:
                nohud_html = n2

        return asset_html, nohud_html

    def _prompt_nonempty(prompt_text, default=None):
        while True:
            suffix = f" [{default}]" if default else ""
            raw = input(f"{prompt_text}{suffix}: ").strip()
            if not raw and default is not None:
                return default
            if raw:
                return raw
            print("    Please enter a value.")

    def _interactive_cli_wizard():
        """Guided mode for first-time CLI users who run without arguments."""
        print("\nNo arguments provided. Starting guided setup mode.")
        print("Choose an action:")
        print("  1) Fetch from Discord codename and install")
        print("  2) Install from existing assets.html + nohud.html")
        print("  3) Re-adjust offset for an already-installed map")
        print("  4) Exit")

        while True:
            choice = input("Choice [1-4]: ").strip()
            if choice in {"1", "2", "3", "4"}:
                break
            print("    Invalid choice. Enter 1, 2, 3, or 4.")

        if choice == "4":
            print("Exiting.")
            sys.exit(0)

        if choice == "1":
            args.codename = _prompt_nonempty("Enter codename (example: TemperatureALT)")
            default_jd = detect_jd_dir()
            jd_input = input(f"Game directory/search root [{default_jd}]: ").strip()
            args.jd_dir = _expand_and_clean_path(jd_input) if jd_input else default_jd
            q_default = settings.get("default_quality", "ultra_hd")
            q_input = input(f"Video quality [{q_default}] (ultra_hd/ultra/high_hd/high/mid_hd/mid/low_hd/low): ").strip().lower()
            if q_input in {"ultra_hd", "ultra", "high_hd", "high", "mid_hd", "mid", "low_hd", "low"}:
                args.quality = q_input
            return

        if choice == "2":
            map_folder = input("Map folder containing assets/nohud HTML (press Enter to provide files manually): ").strip()
            if map_folder:
                map_folder = _expand_and_clean_path(map_folder)
                a2, n2 = _find_html_pair_in_dir(map_folder)
                if a2 and n2:
                    args.asset_html, args.nohud_html = a2, n2
                    print(f"    Auto-detected HTML files in {map_folder}")
                else:
                    print("    Could not find both HTML files in that folder. Switching to manual file entry.")

            if not args.asset_html:
                args.asset_html = _expand_and_clean_path(_prompt_nonempty("Path to Asset HTML"))
            if not args.nohud_html:
                args.nohud_html = _expand_and_clean_path(_prompt_nonempty("Path to NOHUD HTML"))

            default_jd = detect_jd_dir()
            jd_input = input(f"Game directory/search root [{default_jd}]: ").strip()
            args.jd_dir = _expand_and_clean_path(jd_input) if jd_input else default_jd

            q_default = settings.get("default_quality", "ultra_hd")
            q_input = input(f"Video quality [{q_default}] (ultra_hd/ultra/high_hd/high/mid_hd/mid/low_hd/low): ").strip().lower()
            if q_input in {"ultra_hd", "ultra", "high_hd", "high", "mid_hd", "mid", "low_hd", "low"}:
                args.quality = q_input
            return

        # choice == "3"
        args.readjust = _expand_and_clean_path(
            _prompt_nonempty("Download folder containing .ogg and .webm"))
        default_jd = detect_jd_dir()
        jd_input = input(f"Game directory/search root [{default_jd}]: ").strip()
        args.jd_dir = _expand_and_clean_path(jd_input) if jd_input else default_jd

    def _prompt_install_inputs_only():
        """Prompt only for install-mode inputs (asset/nohud html + jd path)."""
        map_folder = input("Map folder containing assets/nohud HTML (press Enter to provide files manually): ").strip()
        if map_folder:
            map_folder = _expand_and_clean_path(map_folder)
            a2, n2 = _find_html_pair_in_dir(map_folder)
            if a2 and n2:
                args.asset_html, args.nohud_html = a2, n2
                print(f"    Auto-detected HTML files in {map_folder}")
            else:
                print("    Could not find both HTML files in that folder.")

        if not args.asset_html:
            args.asset_html = _expand_and_clean_path(_prompt_nonempty("Path to Asset HTML"))
        if not args.nohud_html:
            args.nohud_html = _expand_and_clean_path(_prompt_nonempty("Path to NOHUD HTML"))

        if not args.jd_dir:
            default_jd = detect_jd_dir()
            jd_input = input(f"Game directory/search root [{default_jd}]: ").strip()
            args.jd_dir = _expand_and_clean_path(jd_input) if jd_input else default_jd

    # Enter guided mode when run with no actionable args.
    has_action_args = any([
        args.codename, args.readjust, args.asset_html, args.nohud_html,
        args.map_name, args.sync_config, args.video_override is not None,
        args.audio_offset is not None,
    ])
    if not has_action_args and sys.stdin.isatty():
        _interactive_cli_wizard()

    # Infer missing HTMLs from sibling files/folders where possible.
    args.asset_html, args.nohud_html = _infer_missing_html_pair(args.asset_html, args.nohud_html)

    # --- FETCH-AND-INSTALL MODE (--codename) ---
    if args.codename:
        if args.asset_html or args.nohud_html:
            parser.error("--codename cannot be used with --asset-html / --nohud-html")
        if args.readjust:
            parser.error("--codename cannot be used with --readjust")

        print("--- JDH_Downloader: Fetching HTML from Discord ---")
        maps_dir = os.path.join(SCRIPT_DIR, "MapDownloads")
        try:
            asset_html, nohud_html = fetch_html_via_downloader(
                args.codename, maps_dir)
        except RuntimeError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        print("--- Fetch complete, starting installation ---\n")

        # Inject into args so the normal install path works unchanged
        args.asset_html = asset_html
        args.nohud_html = nohud_html
        if not args.map_name:
            args.map_name = args.codename

    # --- READJUST MODE: skip pipeline, go straight to sync refinement ---
    if args.readjust:
        _log_path = setup_cli_logging("readjust")
        try:
            state = reconstruct_state_for_readjust(args.readjust, jd_dir=args.jd_dir)
        except (FileNotFoundError, RuntimeError) as e:
            print(f"ERROR: {e}")
            sys.exit(1)

        # Allow CLI overrides
        if args.video_override is not None:
            state.v_override = args.video_override
        if args.audio_offset is not None:
            state.a_offset = args.audio_offset

        v_override = state.v_override
        a_offset = state.a_offset

        print(f"\n=== Offset Readjustment for {state.map_name} ===")
        # Fall through to the interactive sync loop below
    else:
        # --- NORMAL INSTALL MODE ---
        if not args.asset_html or not args.nohud_html:
            if sys.stdin.isatty():
                print("\nMissing HTML arguments. Trying interactive recovery...")
                _prompt_install_inputs_only()
                args.asset_html, args.nohud_html = _infer_missing_html_pair(args.asset_html, args.nohud_html)

            if not args.asset_html or not args.nohud_html:
                parser.error("--asset-html and --nohud-html are required for installation "
                             "(or use --codename to fetch from Discord, "
                             "--readjust for offset-only adjustment)")

        if not os.path.isfile(args.asset_html):
            print(f"ERROR: Asset HTML file not found: {args.asset_html}")
            sys.exit(1)
        if not os.path.isfile(args.nohud_html):
            print(f"ERROR: NOHUD HTML file not found: {args.nohud_html}")
            sys.exit(1)

        # Common user mistake: swapped asset/nohud inputs.
        a_name = os.path.basename(args.asset_html).lower()
        n_name = os.path.basename(args.nohud_html).lower()
        if "nohud" in a_name and "nohud" not in n_name:
            print("    Detected likely swapped HTML paths. Swapping automatically.")
            args.asset_html, args.nohud_html = args.nohud_html, args.asset_html

        # Derive map name from JDU asset URLs first (most reliable), fallback to folder name
        map_name = args.map_name
        if not map_name:
            if os.path.exists(args.asset_html):
                urls = map_downloader.extract_urls(args.asset_html)
                map_name = map_downloader.extract_codename_from_urls(urls)
                if map_name:
                    print(f"    Auto-detected map name from URLs: {map_name}")
            if not map_name:
                map_name = os.path.basename(os.path.dirname(os.path.abspath(args.asset_html)))
                print(f"    Auto-detected map name from folder: {map_name}")

        # Create pipeline state
        state = PipelineState(
            map_name=map_name,
            asset_html=args.asset_html,
            nohud_html=args.nohud_html,
            jd_dir=args.jd_dir,
            video_override=args.video_override,
            audio_offset=args.audio_offset,
            quality=args.quality,
            original_map_name=map_name # Assuming map_name is the original name here
        )

        # Load sync config from explicit path if provided (overrides pipeline-calculated values)
        saved = None
        if args.sync_config and os.path.isfile(args.sync_config):
            with open(args.sync_config, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            print(f"    Loaded sync config from {args.sync_config}")
            if saved:
                if state.v_override is None:
                    state.v_override = saved.get('v_override')
                if state.a_offset is None:
                    state.a_offset = saved.get('a_offset')
                if state.marker_preroll_ms is None:
                    state.marker_preroll_ms = saved.get('marker_preroll_ms')

        # Start logging to file — everything from here on is captured to both terminal and log
        _log_path = setup_cli_logging(state.map_name)

        print(f"--- Environment ---")
        print(f"Game Dir:    {state.jd21_dir}")
        print(f"Search Root: {state.jd_dir}")
        print(f"Map Name:    {state.map_name}")
        print(f"Asset HTML:  {state.asset_html}")
        if _log_path:
            print(f"Log file:    {_log_path}")
        print(f"-------------------")

        if settings["skip_preflight"]:
            print("    Pre-flight skipped (disabled in settings)")
        elif not preflight_check(state.jd_dir, state.asset_html, state.nohud_html):
            sys.exit(1)

        print(f"=== Starting Automation for {state.map_name} ===")

        # Run all pipeline steps
        for step_name, step_fn in PIPELINE_STEPS:
            if _interrupted:
                logger.warning("Interrupted before '%s'. Exiting.", step_name)
                sys.exit(130)
            try:
                step_fn(state)
            except RuntimeError as e:
                print(f"ERROR: {e}")
                sys.exit(1)

        print("=== Automation Complete! ===")
        time.sleep(1)  # Give terminal buffers a second to clear
        sys.stdout.flush()

        # --- INTERACTIVE CLI LOOP ---
        v_override = state.v_override
        a_offset = state.a_offset

    while True:
        print("\n" + "="*50)
        print(f" SYNC REFINEMENT: {state.map_name}")
        print(f" Current VIDEO_OVERRIDE: {v_override}s")
        print(f" Current AUDIO_OFFSET:   {a_offset}s")
        print("="*50)
        print("This is not a perfect tool, preview the video along with the audio to determine if its on beat or in sync")
        print("Is the audio matched with the video? Select an option:")
        print("0 - All good! (Exit)")
        print("1 - Sync Beatgrid: Use video's offset for audio trimming")
        print("2 - Sync Beatgrid: Pad audio to match video length (Length difference)")
        print("3 - Custom values")
        print("4 - Preview with ffplay")
        print("="*50)

        print("-" * 50, flush=True)
        choice = input("Choice [0-4]: ").strip()

        if choice == '0':
            sys.exit(0)
        elif choice == '1':
            a_offset = v_override
            reprocess_audio(state, a_offset, v_override)
            show_ffplay_preview(state.video_path, state.audio_path, v_override, a_offset)
        elif choice == '2':
            def get_dur(p):
                res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                      "-of", "default=noprint_wrappers=1:nokey=1", p],
                                     capture_output=True, text=True)
                return float(res.stdout.strip())

            v_dur = get_dur(state.video_path)
            a_dur = get_dur(state.audio_path)
            diff = v_dur - a_dur
            print(f"    Video: {v_dur:.2f}s, Audio: {a_dur:.2f}s")
            print(f"    Padding audio by: {diff:.3f}s")
            a_offset = diff
            reprocess_audio(state, a_offset, v_override)
            show_ffplay_preview(state.video_path, state.audio_path, v_override, a_offset)
        elif choice == '3':
            try:
                ov = input(f"New VIDEO_OVERRIDE (current {v_override}): ").strip()
                if ov: v_override = float(ov)
                oa = input(f"New AUDIO_OFFSET (current {a_offset}): ").strip()
                if oa: a_offset = float(oa)

                # Regenerate config if video_override changed
                map_builder.generate_text_files(
                    state.map_name, state.ipk_extracted, state.target_dir, v_override,
                    metadata_overrides=getattr(state, 'metadata_overrides', None))
                reprocess_audio(state, a_offset, v_override)
                show_ffplay_preview(state.video_path, state.audio_path, v_override, a_offset)
            except ValueError:
                print("Invalid number entered.")
        elif choice == '4':
            show_ffplay_preview(state.video_path, state.audio_path, v_override, a_offset)
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()
