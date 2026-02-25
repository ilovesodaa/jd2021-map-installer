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

# Import our individual scripts
import map_downloader
import map_builder
import ubiart_lua


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


def setup_log_file(jd_dir, map_name):
    """Create a timestamped log file in {jd_dir}/logs/ and return the open file handle."""
    logs_dir = os.path.join(jd_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join(logs_dir, f"install_{map_name}_{timestamp}.log")
    return open(log_path, "w", encoding="utf-8", buffering=1)


class PipelineState:
    """Holds all intermediate state for a map installation pipeline run."""
    def __init__(self, map_name, asset_html, nohud_html, jd_dir=None,
                 video_override=None, audio_offset=None, quality="ultra_hd"):
        self.map_name = map_name.strip()
        self.map_lower = self.map_name.lower()
        self.asset_html = clean_path(asset_html)
        self.nohud_html = clean_path(nohud_html)
        self.jd_dir = detect_jd_dir(jd_dir)

        # Video quality preference
        self.quality = quality.upper()

        # Derived paths
        self.download_dir = os.path.dirname(self.asset_html)
        self.target_dir = os.path.join(
            self.jd_dir, "jd21", "data", "World", "MAPS", self.map_name)
        self.cache_dir = os.path.join(
            self.jd_dir, "jd21", "data", "cache", "itf_cooked", "pc", "world", "maps", self.map_lower)
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
    """
    Finds the JD2021 base directory.
    Priority:
    1. Provided path (if valid)
    2. Directory of this script (if it contains jd21 folder)
    3. Current working directory (if it contains jd21 folder)
    """
    candidates = []
    if provided_dir:
        cleaned = clean_path(provided_dir)
        candidates.append(cleaned)

    # Script's own directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(script_dir)

    # Current working directory
    cwd = os.getcwd()
    if cwd not in candidates:
        candidates.append(cwd)

    for cand in candidates:
        if cand and os.path.isdir(cand):
            # Signature check: Look for the 'jd21' data directory
            if os.path.exists(os.path.join(cand, "jd21")):
                return cand

    # Fallback to the first candidate or current script dir if nothing found
    return candidates[0] if candidates else script_dir


CONFIG_DIR_NAME = "map_configs"


def _config_dir(jd_dir):
    """Return the path to {jd_dir}/map_configs/, creating it if needed."""
    d = os.path.join(jd_dir, CONFIG_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def load_map_config(jd_dir, map_name):
    """Load a saved config JSON for a map. Returns dict or None."""
    config_path = os.path.join(_config_dir(jd_dir), f"{map_name}.json")
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


def save_map_config(jd_dir, map_name, v_override, a_offset, quality="ULTRA", codename=None):
    """Save a sync config JSON for a map."""
    config_path = os.path.join(_config_dir(jd_dir), f"{map_name}.json")
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


def _install_ffmpeg(jd_dir):
    """Download ffmpeg static build for Windows into {jd_dir}/tools/ffmpeg/."""
    import ssl as _ssl
    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE

    FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    tools_dir = os.path.join(jd_dir, "tools")
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


def _install_git_repo(jd_dir, repo_url, target_name, branch="main"):
    """Download a GitHub repo as a zip and extract it."""
    zip_path = os.path.join(jd_dir, f"{target_name}.zip")
    target = os.path.join(jd_dir, target_name)

    print(f"    Downloading {target_name}...")
    urllib_req = __import__('urllib.request', fromlist=['urlretrieve'])
    urllib_req.urlretrieve(repo_url, zip_path)

    print(f"    Extracting...")
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(jd_dir)

    # Rename extracted folder (e.g., repo-main -> target_name)
    extracted = os.path.join(jd_dir, f"{target_name}-{branch}")
    if os.path.isdir(extracted):
        if os.path.exists(target):
            shutil.rmtree(target)
        os.rename(extracted, target)

    if os.path.exists(zip_path):
        os.remove(zip_path)
    print(f"    {target_name} installed to {target}")
    return True


def _install_pillow():
    """Install Pillow via pip."""
    print(f"    Installing Pillow via pip...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "Pillow"],
        capture_output=True, text=True)
    if result.returncode == 0:
        print(f"    Pillow installed successfully.")
        return True
    else:
        print(f"    Pillow installation failed: {result.stderr}")
        return False

def preflight_check(jd_dir, asset_html, nohud_html, auto_install=False):
    """Run pre-flight dependency checks. Returns True if all critical checks pass.
    If auto_install is True, offer to install missing dependencies."""
    print("--- Pre-flight Checks ---")
    failures = 0

    def ok(msg):
        print(f"  [OK] {msg}")

    def fail(msg):
        nonlocal failures
        failures += 1
        print(f"  [FAIL] {msg}")

    def warn(msg):
        print(f"  [WARN] {msg}")

    # Critical: ffmpeg
    # Check local tools/ directory first, then PATH
    tools_ffmpeg = os.path.join(jd_dir, "tools", "ffmpeg")
    if os.path.isdir(tools_ffmpeg):
        os.environ['PATH'] = tools_ffmpeg + os.pathsep + os.environ.get('PATH', '')

    if check_executable("ffmpeg"):
        ok("ffmpeg found")
    else:
        if auto_install or _prompt_install("ffmpeg"):
            try:
                _install_ffmpeg(jd_dir)
                if check_executable("ffmpeg"):
                    ok("ffmpeg installed and verified")
                else:
                    fail("ffmpeg installed but not working")
            except Exception as e:
                fail(f"ffmpeg auto-install failed: {e}")
        else:
            fail("ffmpeg not found in PATH (install from https://ffmpeg.org)")

    # Critical: jd21 game data
    if os.path.isdir(os.path.join(jd_dir, "jd21")):
        ok("JD2021 game data (jd21/)")
    else:
        fail(f"jd21/ directory not found in {jd_dir}")

    # Critical: SkuScene registry
    sku_path = os.path.join(jd_dir, "jd21", "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
    if os.path.isfile(sku_path):
        ok("SkuScene registry file")
    else:
        fail(f"SkuScene_Maps_PC_All.isc not found at {sku_path}")

    # Critical: ubiart-archive-tools
    ipk_unpacker = os.path.join(jd_dir, "ubiart-archive-tools", "ipk_unpacker.py")
    if os.path.isfile(ipk_unpacker):
        ok("ubiart-archive-tools")
    else:
        if auto_install or _prompt_install("ubiart-archive-tools"):
            try:
                _install_git_repo(jd_dir,
                    "https://github.com/AntonioDePau/ubiart-archive-tools/archive/refs/heads/main.zip",
                    "ubiart-archive-tools", branch="main")
                if os.path.isfile(ipk_unpacker):
                    ok("ubiart-archive-tools installed")
                else:
                    fail("ubiart-archive-tools installed but ipk_unpacker.py not found")
            except Exception as e:
                fail(f"ubiart-archive-tools auto-install failed: {e}")
        else:
            fail(f"ubiart-archive-tools/ipk_unpacker.py not found (see GETTING_STARTED.md Step 2)")

    # Critical: ckd_decode.py
    if os.path.isfile(os.path.join(jd_dir, "ckd_decode.py")):
        ok("ckd_decode.py")
    else:
        fail("ckd_decode.py not found in project root")

    # Critical: json_to_lua.py
    if os.path.isfile(os.path.join(jd_dir, "json_to_lua.py")):
        ok("json_to_lua.py")
    else:
        fail("json_to_lua.py not found in project root")

    # Critical: XTX-Extractor
    if os.path.isdir(os.path.join(jd_dir, "XTX-Extractor")):
        ok("XTX-Extractor")
    else:
        if auto_install or _prompt_install("XTX-Extractor"):
            try:
                _install_git_repo(jd_dir,
                    "https://github.com/aboood40091/XTX-Extractor/archive/refs/heads/master.zip",
                    "XTX-Extractor", branch="master")
                if os.path.isdir(os.path.join(jd_dir, "XTX-Extractor")):
                    ok("XTX-Extractor installed")
                else:
                    fail("XTX-Extractor install failed")
            except Exception as e:
                fail(f"XTX-Extractor auto-install failed: {e}")
        else:
            fail("XTX-Extractor/ directory not found (see GETTING_STARTED.md Step 2)")

    # Critical: Pillow
    try:
        from PIL import Image
        ok("Pillow (image library)")
    except ImportError:
        if auto_install or _prompt_install("Pillow"):
            try:
                if _install_pillow():
                    ok("Pillow installed")
                else:
                    fail("Pillow installation failed")
            except Exception as e:
                fail(f"Pillow auto-install failed: {e}")
        else:
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
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path, "-ar", "48000", wav_out], check=True)
    else:
        print(f"    Converting to 48kHz WAV (offset: {a_offset}s)...")
        if a_offset < 0:
            af_filter = f"atrim=start={abs(a_offset)},asetpts=PTS-STARTPTS"
        else:
            af_filter = f"adelay={int(a_offset * 1000)}|{int(a_offset * 1000)},asetpts=PTS-STARTPTS"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path, "-af", af_filter, "-ar", "48000", wav_out], check=True)

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
    delay_ms = int(audio_delay * 1000)
    if delay_ms > 0:
        af_filter = (
            f"atrim=end={audio_content_dur:.3f},asetpts=PTS-STARTPTS,"
            f"adelay={delay_ms}|{delay_ms},"
            f"afade=t=out:st={fade_start:.3f}:d=0.2"
        )
        print(f"    Intro audio delayed by {audio_delay:.3f}s (video intro longer than OGG pre-roll)")
    else:
        af_filter = f"atrim=end={audio_content_dur:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={fade_start:.3f}:d=0.2"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", ogg_path,
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
    """Extract scene ZIP archives."""
    print("[3] Extracting scene archives...")
    sys.stdout.flush()

    os.makedirs(state.extracted_zip_dir, exist_ok=True)

    for f in os.listdir(state.download_dir):
        if "SCENE" in f and f.endswith(".zip"):
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
        subprocess.run([sys.executable, os.path.join(state.jd_dir, "ubiart-archive-tools", "ipk_unpacker.py"),
                        ipk, state.ipk_extracted], check=False, capture_output=True)


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
    subprocess.run([sys.executable, os.path.join(state.jd_dir, "ckd_decode.py"), "--batch", "--quiet",
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
                    abs_path = os.path.join(state.jd_dir, "jd21", "data", rel_path.replace("/", os.sep))
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
        subprocess.run([sys.executable, os.path.join(state.jd_dir, "ckd_decode.py"), "--batch", "--quiet",
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
    # folder (e.g. moves/PC/).  Dance tapes reference both .gesture and .msm files,
    # but different platforms ship different subsets — e.g. DURANGO has .gesture,
    # WIIU has .msm, and ORBIS may have unique .gesture files that other platforms
    # lack.  Merge gesture/msm files from ALL other platforms into PC/ so that
    # every ClassifierPath reference can be resolved.
    pc_moves_dir = os.path.join(state.target_dir, "Timeline", "Moves", "PC")
    moves_root = os.path.join(state.target_dir, "Timeline", "Moves")
    total_copied = 0
    if os.path.isdir(moves_root):
        for plat_name in os.listdir(moves_root):
            if plat_name.upper() == "PC":
                continue
            plat_dir = os.path.join(moves_root, plat_name)
            if not os.path.isdir(plat_dir):
                continue
            for ext in ("*.gesture", "*.msm"):
                for src in glob.glob(os.path.join(plat_dir, ext)):
                    dest = os.path.join(pc_moves_dir, os.path.basename(src))
                    if not os.path.exists(dest):
                        os.makedirs(pc_moves_dir, exist_ok=True)
                        shutil.copy2(src, dest)
                        total_copied += 1
    if total_copied:
        print(f"    Merged {total_copied} missing gesture/msm file(s) from other platforms into PC/")

    autodance_tpls = glob.glob(os.path.join(state.ipk_extracted, "**/autodance/*.tpl.ckd"), recursive=True)
    for f in autodance_tpls:
        dest_ad = os.path.join(state.target_dir, "Autodance")
        os.makedirs(dest_ad, exist_ok=True)
        dst_tpl = os.path.join(dest_ad, f"{state.map_name}_autodance.tpl")
        subprocess.run([sys.executable, os.path.join(state.jd_dir, "json_to_lua.py"), f, dst_tpl],
                       check=True, capture_output=True)

    # Convert autodance data CKDs (adtape, adrecording, advideo)
    for ext in ["adtape", "adrecording", "advideo"]:
        ad_ckds = glob.glob(os.path.join(state.ipk_extracted, f"**/autodance/*.{ext}.ckd"), recursive=True)
        for f in ad_ckds:
            dest_ad = os.path.join(state.target_dir, "Autodance")
            os.makedirs(dest_ad, exist_ok=True)
            dst_file = os.path.join(dest_ad, f"{state.map_name}.{ext}")
            subprocess.run([sys.executable, os.path.join(state.jd_dir, "json_to_lua.py"), f, dst_file],
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
        subprocess.run([sys.executable, os.path.join(state.jd_dir, "json_to_lua.py"),
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
    sku_isc = os.path.join(state.jd_dir, "jd21", "data", "World", "SkuScenes", "SkuScene_Maps_PC_All.isc")
    if os.path.exists(sku_isc):
        with open(sku_isc, "r", encoding="utf-8") as f:
            sku_data = f.read()

        if f'USERFRIENDLY="{state.map_name}"' not in sku_data:
            print(f"[14] Registering {state.map_name} in SkuScene...")
            actor_xml = f'''           <ACTORS NAME="Actor">
              <Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{state.map_name}" POS2D="0 0" ANGLE="0.000000" INSTANCEDATAFILE="world/maps/{state.map_name}/songdesc.act" LUA="world/maps/{state.map_name}/songdesc.tpl">
                  <COMPONENTS NAME="JD_SongDescComponent">
                      <JD_SongDescComponent />
                  </COMPONENTS>
              </Actor>
          </ACTORS>\n'''
            sku_data = sku_data.replace("          <sceneConfigs>", actor_xml + "          <sceneConfigs>")

            coverflow_xml = f'''                          <CoverflowSkuSongs>
                            <CoverflowSong name="{state.map_name}"  cover_path="world/maps/{state.map_name}/menuart/actors/{state.map_name}_cover_generic.act">
                              </CoverflowSong>
                          </CoverflowSkuSongs>
                          <CoverflowSkuSongs>
                            <CoverflowSong name="{state.map_name}"  cover_path="world/maps/{state.map_name}/menuart/actors/{state.map_name}_cover_online.act">
                              </CoverflowSong>
                          </CoverflowSkuSongs>\n'''
            sku_data = sku_data.replace("                      </JD_SongDatabaseSceneConfig>",
                                        coverflow_xml + "                      </JD_SongDatabaseSceneConfig>")

            with open(sku_isc, "w", encoding="utf-8") as f:
                f.write(sku_data)
        else:
            print(f"[14] {state.map_name} is already registered in SkuScene.")


# ---------------------------------------------------------------------------
# All pipeline steps in order, for easy iteration
# ---------------------------------------------------------------------------
PIPELINE_STEPS = [
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
        saved = load_map_config(state.jd_dir, state.map_name)

    if saved:
        if state.v_override is None:
            state.v_override = saved.get('v_override')
        if state.a_offset is None:
            state.a_offset = saved.get('a_offset')

    # Start logging to file — everything from here on is captured to both terminal and log
    _log_file = setup_log_file(state.jd_dir, state.map_name)
    sys.stdout = TeeOutput(sys.stdout, _log_file)

    print(f"--- Environment ---")
    print(f"JD Base Dir: {state.jd_dir}")
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
            save_map_config(state.jd_dir, state.map_name, v_override, a_offset,
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
