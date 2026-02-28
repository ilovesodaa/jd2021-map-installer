import os
import shutil
import subprocess
import glob
import wave
import zipfile
import argparse
import sys
import fnmatch
import re
import datetime
import time
import json

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


class TeeOutput:
    """Writes to both the original stream and a log file simultaneously."""

    def __init__(self, original, log_file):
        self.original = original
        self.log_file = log_file

    def write(self, text):
        try:
            self.original.write(text)
        except UnicodeEncodeError:
            self.original.write(text.encode('ascii', errors='replace').decode('ascii'))
        self.log_file.write(text)
        self.log_file.flush()

    def flush(self):
        self.original.flush()
        self.log_file.flush()


def setup_log_file(map_name):
    """Create a timestamped log file in the project logs/ dir."""
    logs_dir = os.path.join(SCRIPT_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join(logs_dir, f"install_{map_name}_{timestamp}.log")
    return open(log_path, "w", encoding="utf-8", buffering=1)


def sanitize_map_name(map_name, interactive=True):
    """Check for non-ASCII or problematic characters. Prompt for replacement if found."""
    try:
        map_name.encode('ascii')
        return map_name  # All ASCII, no issues
    except UnicodeEncodeError:
        pass

    non_ascii = [c for c in map_name if ord(c) > 127]
    print(f"\n    ⚠ Map name '{map_name}' contains non-standard characters: {non_ascii}")
    print(f"    These characters can cause file path and game engine issues.")

    if interactive:
        replacement = input(f"    Enter a replacement name (or press Enter to keep '{map_name}'): ").strip()
        if replacement:
            print(f"    Using replacement name: {replacement}")
            return replacement

    # Non-interactive fallback: strip non-ASCII chars
    safe_name = ''.join(c for c in map_name if ord(c) < 128)
    if safe_name and safe_name != map_name:
        print(f"    Auto-stripped to: {safe_name}")
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

        # Sync parameters (may be overridden during refinement)
        self.v_override = video_override
        self.a_offset = audio_offset


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


CONFIG_DIR_NAME = "map_configs"


def _config_dir():
    """Return the path to the project map_configs/ dir, creating it if needed."""
    d = os.path.join(SCRIPT_DIR, CONFIG_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def load_map_config(map_name):
    """Load a saved config JSON for a map. Returns dict or None."""
    config_path = os.path.join(_config_dir(), f"{map_name}.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"    Found previous config for {map_name}, using saved sync values")
            print(f"      v_override={data.get('v_override')}, a_offset={data.get('a_offset')}, quality={data.get('quality')}")
            return data
        except Exception as e:
            print(f"    Warning: Could not load config for {map_name}: {e}")
    return None


def save_map_config(map_name, v_override, a_offset, quality="ULTRA", codename=None):
    """Save a sync config JSON for a map."""
    config_path = os.path.join(_config_dir(), f"{map_name}.json")
    data = {
        "map_name": map_name,
        "v_override": v_override,
        "a_offset": a_offset,
        "quality": quality,
        "codename": codename or map_name,
        "installed_at": datetime.datetime.now().isoformat(),
    }
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print(f"    Config saved to {config_path}")
    return config_path


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
        except Exception:
            pass
    return None


def save_paths_cache(paths):
    """Persist discovered game-data paths to disk."""
    try:
        with open(PATHS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(paths, f, indent=2)
    except Exception:
        pass


def clear_paths_cache():
    """Delete the cached game-data paths. Returns True if anything was deleted."""
    if os.path.isfile(PATHS_CACHE_FILE):
        os.remove(PATHS_CACHE_FILE)
        return True
    return False


def _scan_for_sku_scene(search_root):
    """Walk search_root recursively to find SkuScene_Maps_PC_All.isc."""
    target = "SkuScene_Maps_PC_All.isc"
    skip = {'__pycache__', '.git', 'logs', 'map_configs', 'downloads',
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

    def _found(jd21_dir, sku):
        paths = {'jd21_dir': jd21_dir, 'sku_scene': sku}
        save_paths_cache(paths)
        return paths

    # Case 1: search_root/jd21/data/World/SkuScenes/…
    jd21_sub = os.path.join(search_root, "jd21")
    sku = os.path.join(jd21_sub, "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
    if os.path.isfile(sku):
        return _found(jd21_sub, sku)

    # Case 2: search_root IS the jd21 folder
    sku = os.path.join(search_root, "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
    if os.path.isfile(sku):
        return _found(search_root, sku)

    # Case 3: classic layout next to the scripts
    if search_root != SCRIPT_DIR:
        jd21_next = os.path.join(SCRIPT_DIR, "jd21")
        sku = os.path.join(jd21_next, "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
        if os.path.isfile(sku):
            return _found(jd21_next, sku)

    # Case 4: recursive scan
    print(f"    Scanning {search_root} for JD2021 game data (this may take a moment)...")
    sku_found = _scan_for_sku_scene(search_root)
    if sku_found:
        # sku is at  jd21_dir/data/World/SkuScenes/SkuScene_Maps_PC_All.isc
        jd21_dir = os.path.normpath(
            os.path.join(os.path.dirname(sku_found), '..', '..', '..'))
        return _found(jd21_dir, sku_found)

    return None


def check_executable(name):
    """Check if an executable is available on PATH."""
    try:
        subprocess.run([name, "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


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
                    interactive=True):
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
        ok(f"JD2021 game data ({game_paths['jd21_dir']})")
        ok("SkuScene registry file")
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

    if os.path.isfile(os.path.join(SCRIPT_DIR, "json_to_lua.py")):
        ok("json_to_lua.py")
    else:
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

    # Critical: input HTML files
    if os.path.isfile(asset_html):
        ok("Asset HTML file")
    else:
        fail(f"Asset HTML file not found: {asset_html}")

    if os.path.isfile(nohud_html):
        ok("NOHUD HTML file")
    else:
        fail(f"NOHUD HTML file not found: {nohud_html}")

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

def convert_audio(audio_path, map_name, target_dir, a_offset=0.0):
    wav_out = os.path.join(target_dir, f"Audio/{map_name}.wav")
    ogg_out = os.path.join(target_dir, f"Audio/{map_name}.ogg")

    if not os.path.exists(ogg_out):
        print(f"    Copying menu preview OGG...")
        shutil.copy2(audio_path, ogg_out)

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

def generate_intro_amb(ogg_path, map_name, target_dir, a_offset, v_override=None):
    """Generate an intro AMB WAV to cover pre-roll silence caused by negative videoStartTime.

    Strategy: AMB plays from t=0, covering the silence window before the main WAV starts.
    The AMB duration is based on abs(v_override) (the actual intro length), not abs(a_offset).
    When abs(v_override) > abs(a_offset), the OGG has no audio for the initial gap, so the
    AMB WAV is prepended with that many seconds of silence via adelay.
    A 200ms fade-out at the end eliminates the hard-cut volume snap.
    """
    map_lower = map_name.lower()
    amb_dir = os.path.join(target_dir, "Audio", "AMB")

    if a_offset >= 0:
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
    audio_content_dur = abs(a_offset) + 1.355
    amb_duration      = audio_delay + audio_content_dur
    fade_start        = audio_delay + abs(a_offset) + 1.155  # = intro_dur + 1.155

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
        a_filt = f"adelay=delays={delay_ms}:all=1"
        v_filt = "null"
    else:
        a_filt = "anull"
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
    _safe_rmtree(state.extracted_zip_dir)
    _safe_rmtree(state.ipk_extracted)


def step_02_download(state):
    """Download assets from JDU servers and detect codename/audio/video paths."""
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
    preferred_idx = map_downloader.QUALITY_ORDER.index(state.quality) if state.quality in map_downloader.QUALITY_ORDER else 0
    search_order = map_downloader.QUALITY_ORDER[preferred_idx:] + map_downloader.QUALITY_ORDER[:preferred_idx]
    for qual in search_order:
        pattern = map_downloader.QUALITY_PATTERNS[qual]  # e.g. "_ULTRA.hd.webm"
        vp = os.path.join(state.download_dir, f"{state.codename}{pattern}")
        if os.path.exists(vp):
            if qual != state.quality:
                print(f"    Note: Requested {state.quality} quality not found, using {qual}")
            video_path = vp
            break
    if not video_path:
        webms = [f for f in glob.glob(os.path.join(state.download_dir, "*.webm")) if "MapPreview" not in f and "VideoPreview" not in f]
        if webms:
            video_path = webms[0]
        else:
            raise RuntimeError("Full Video missing! Check if NO-HUD links expired. Cannot proceed.")
    state.video_path = video_path


def step_03_extract_scenes(state):
    """Extract scene ZIP archives, preferring DURANGO platform."""
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


def step_04_unpack_ipk(state):
    """Unpack IPK archives."""
    print("[4] Unpacking IPK archives...")
    ipk_files = glob.glob(os.path.join(state.extracted_zip_dir, "*.ipk"))
    for ipk in ipk_files:
        print(f"    Unpacking {os.path.basename(ipk)}...")
        try:
            ipk_unpack.extract(ipk, state.ipk_extracted)
        except Exception as e:
            print(f"    Warning: IPK extraction issue: {e}")


def step_05_decode_menuart(state):
    """Decode MenuArt CKDs and copy raw PNG/JPGs."""
    print("[5] Decoding menu art textures...")
    for file in os.listdir(state.download_dir):
        src = os.path.join(state.download_dir, file)
        dst = None
        if fnmatch.fnmatch(file, "*.tga.ckd") or file.endswith(".jpg") or file.endswith(".png"):
            if "Phone" in file or "1024" in file or state.codename.lower() in file.lower() or state.map_name.lower() in file.lower():
                new_name = re.sub(re.escape(state.codename), state.map_name, file, flags=re.IGNORECASE) if state.codename.lower() in file.lower() else file
                dst = os.path.join(state.target_dir, f"MenuArt/textures/{new_name}")

        if dst:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

    # Decode CKDs to actual TGAs/PNGs
    subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "ckd_decode.py"), "--batch", "--quiet",
                    os.path.join(state.target_dir, "MenuArt/textures"),
                    os.path.join(state.target_dir, "MenuArt/textures")], check=False, capture_output=True)


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
    video_start_time = map_builder.generate_text_files(
        state.map_name, state.ipk_extracted, state.target_dir, state.v_override)

    if video_start_time is None:
        raise RuntimeError("Could not fetch video start time.")

    state.video_start_time = video_start_time
    print(f"    Video Start Time is: {video_start_time}")


def step_07_convert_tapes(state):
    """Convert choreography and karaoke tapes to Lua."""
    print("[7] Converting choreography and karaoke tapes to Lua...")
    for ty in ["dance", "karaoke"]:
        src_tapes = glob.glob(os.path.join(state.ipk_extracted, f"**/*_tml_{ty}.?tape.ckd"), recursive=True)
        if src_tapes:
            dst_tape = os.path.join(state.target_dir, f"Timeline/{state.map_name}_TML_{ty.capitalize()}.{ty[0]}tape")
            tape_data = ubiart_lua.load_ckd_json(src_tapes[0])
            lua_str = ubiart_lua.process_tape(tape_data, tape_type=ty)
            with open(dst_tape, 'w', encoding='utf-8') as f:
                f.write(lua_str)
            print(f"    Converted {os.path.basename(src_tapes[0])} -> {os.path.basename(dst_tape)}")


def step_08_convert_cinematics(state):
    """Convert cinematic tapes to Lua."""
    print("[8] Converting cinematic tapes to Lua...")
    cinematics_dirs = glob.glob(os.path.join(state.ipk_extracted, "**/cinematics"), recursive=True)
    cine_converted = 0
    for cine_dir in cinematics_dirs:
        for tape_file in glob.glob(os.path.join(cine_dir, "*.tape.ckd")):
            tape_basename = os.path.basename(tape_file)
            output_name = tape_basename.replace(".ckd", "")
            if "mainsequence" in output_name.lower():
                output_name = f"{state.map_name}_MainSequence.tape"
            dst_path = os.path.join(state.target_dir, f"Cinematics/{output_name}")
            tape_data = ubiart_lua.load_ckd_json(tape_file)
            lua_str = ubiart_lua.process_tape(tape_data, tape_type="cinematics")
            with open(dst_path, 'w', encoding='utf-8') as f:
                f.write(lua_str)
            print(f"    Converted {tape_basename} -> {output_name}")
            cine_converted += 1
    if cine_converted == 0:
        print("    No cinematic tapes found, keeping empty fallback.")


def step_09_process_amb(state):
    """Process ambient sound templates."""
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
                for rel_path in audio_file_paths:
                    abs_path = os.path.join(state.jd21_dir, "data", rel_path.replace("/", os.sep))
                    if not os.path.exists(abs_path):
                        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                        with wave.open(abs_path, 'w') as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(48000)
                            wf.writeframes(b'\x00\x00' * 4800)  # 0.1s silence
                        print(f"    Created silent placeholder: {os.path.basename(abs_path)}")

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
        print("[9] No ambient sound templates found, skipping.")


def step_10_decode_pictos(state):
    """Decode pictograms."""
    print("[10] Decoding pictograms...")
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
    for plat in ["nx", "wii", "durango", "scarlett", "orbis", "prospero", "wiiu"]:
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
    KINECT_PLATFORMS = {"DURANGO", "SCARLETT"}
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
        subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "json_to_lua.py"), f, dst_tpl],
                       check=True, capture_output=True)

    # Convert autodance data CKDs (adtape, adrecording, advideo)
    for ext in ["adtape", "adrecording", "advideo"]:
        ad_ckds = glob.glob(os.path.join(state.ipk_extracted, f"**/autodance/*.{ext}.ckd"), recursive=True)
        for f in ad_ckds:
            dest_ad = os.path.join(state.target_dir, "Autodance")
            os.makedirs(dest_ad, exist_ok=True)
            dst_file = os.path.join(dest_ad, f"{state.map_name}.{ext}")
            subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "json_to_lua.py"), f, dst_file],
                           check=False, capture_output=True)

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
        subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, "json_to_lua.py"),
                        stape_ckds[0], dst_stape], check=False, capture_output=True)


def step_12_convert_audio(state):
    """Convert audio to 48kHz WAV with offset."""
    # Resolve default sync parameters if not explicitly set
    if state.v_override is None:
        state.v_override = state.video_start_time
    if state.a_offset is None:
        state.a_offset = state.v_override

    if state.audio_path:
        print(f"[12] Converting audio to 48kHz WAV...")
        convert_audio(state.audio_path, state.map_name, state.target_dir, state.a_offset)
        generate_intro_amb(state.audio_path, state.map_name, state.target_dir, state.a_offset, state.v_override)


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
        f'          </ACTORS>\n'
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
    parser = argparse.ArgumentParser(description="Fully Automated Just Dance 2021 Map Installer")
    parser.add_argument("--map-name", default=None, help="Map name (default: derived from asset-html parent folder)")
    parser.add_argument("--asset-html", required=True, help="Path to asset mapping HTML")
    parser.add_argument("--nohud-html", required=True, help="Path to nohud mapping HTML")
    parser.add_argument("--jd-dir", default=None, help="Base directory of JD tools / JD21 install (auto-detected if omitted)")
    parser.add_argument("--quality", choices=["ultra_hd", "ultra", "high_hd", "high", "mid_hd", "mid", "low_hd", "low"],
                        default="ultra_hd", help="Video quality to download (default: ultra_hd)")
    parser.add_argument("--video-override", type=float, default=None, help="Force a specific video start time")
    parser.add_argument("--audio-offset", type=float, default=None, help="Force a specific audio trim offset")
    parser.add_argument("--sync-config", default=None, help="Path to a JSON config file to load sync values from")
    args = parser.parse_args()

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
    )

    # Load saved sync config (explicit path takes priority, then auto-detect)
    saved = None
    if args.sync_config and os.path.isfile(args.sync_config):
        with open(args.sync_config, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        print(f"    Loaded sync config from {args.sync_config}")
    else:
        saved = load_map_config(state.map_name)

    if saved:
        if state.v_override is None:
            state.v_override = saved.get('v_override')
        if state.a_offset is None:
            state.a_offset = saved.get('a_offset')

    # Start logging to file — everything from here on is captured to both terminal and log
    _log_file = setup_log_file(state.map_name)
    sys.stdout = TeeOutput(sys.stdout, _log_file)

    print(f"--- Environment ---")
    print(f"Game Dir:    {state.jd21_dir}")
    print(f"Search Root: {state.jd_dir}")
    print(f"Map Name:    {state.map_name}")
    print(f"Asset HTML:  {state.asset_html}")
    print(f"Log file:    {_log_file.name}")
    print(f"-------------------")

    if not preflight_check(state.jd_dir, state.asset_html, state.nohud_html):
        sys.exit(1)

    print(f"=== Starting Automation for {state.map_name} ===")

    # Run all pipeline steps
    for step_name, step_fn in PIPELINE_STEPS:
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
            save_map_config(state.map_name, v_override, a_offset,
                            quality=state.quality, codename=state.codename)
            sys.exit(0)
        elif choice == '1':
            a_offset = v_override
            convert_audio(state.audio_path, state.map_name, state.target_dir, a_offset)
            generate_intro_amb(state.audio_path, state.map_name, state.target_dir, a_offset, v_override)
            _safe_rmtree(state.cache_dir)
            print("    Cleared game cache.")
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
            convert_audio(state.audio_path, state.map_name, state.target_dir, a_offset)
            generate_intro_amb(state.audio_path, state.map_name, state.target_dir, a_offset, v_override)
            _safe_rmtree(state.cache_dir)
            print("    Cleared game cache.")
            show_ffplay_preview(state.video_path, state.audio_path, v_override, a_offset)
        elif choice == '3':
            try:
                ov = input(f"New VIDEO_OVERRIDE (current {v_override}): ").strip()
                if ov: v_override = float(ov)
                oa = input(f"New AUDIO_OFFSET (current {a_offset}): ").strip()
                if oa: a_offset = float(oa)

                # Regenerate config if video_override changed
                map_builder.generate_text_files(state.map_name, state.ipk_extracted, state.target_dir, v_override)
                # Re-convert audio
                convert_audio(state.audio_path, state.map_name, state.target_dir, a_offset)
                generate_intro_amb(state.audio_path, state.map_name, state.target_dir, a_offset, v_override)
                _safe_rmtree(state.cache_dir)
                print("    Cleared game cache.")
                show_ffplay_preview(state.video_path, state.audio_path, v_override, a_offset)
            except ValueError:
                print("Invalid number entered.")
        elif choice == '4':
            show_ffplay_preview(state.video_path, state.audio_path, v_override, a_offset)
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()
