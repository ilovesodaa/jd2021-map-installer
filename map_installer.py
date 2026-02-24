import os
import shutil
import subprocess
import glob
import wave
import zipfile
import argparse
import sys

# Import our individual scripts
import map_downloader
import map_builder
import ubiart_lua

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

def check_executable(name):
    """Check if an executable is available on PATH."""
    try:
        subprocess.run([name, "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False

def preflight_check(jd_dir, asset_html, nohud_html):
    """Run pre-flight dependency checks. Returns True if all critical checks pass."""
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
    if check_executable("ffmpeg"):
        ok("ffmpeg found")
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
        fail("XTX-Extractor/ directory not found (see GETTING_STARTED.md Step 2)")

    # Critical: Pillow
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

def generate_intro_amb(ogg_path, map_name, target_dir, a_offset):
    """Generate an intro AMB WAV to cover pre-roll silence caused by negative videoStartTime.

    Strategy: AMB plays from t=0, covering the silence window before the main WAV starts.
    Both AMB and WAV source the same OGG, so any overlap is inaudible (identical content).
    A 200ms fade-out at the end of the AMB eliminates the hard-cut volume snap.
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

    # Duration: abs(offset) + 1.355s tail; 200ms fade-out starting 1.155s past the handoff
    amb_duration = abs(a_offset) + 1.355
    fade_start   = abs(a_offset) + 1.155

    # Locate an existing intro WAV placeholder (created by IPK AMB processing)
    intro_wavs = glob.glob(os.path.join(amb_dir, "*_intro.wav"))
    if intro_wavs:
        intro_wav = intro_wavs[0]
    else:
        # No AMB came from the IPK — create the full set of files from scratch
        intro_name    = f"amb_{map_lower}_intro"
        intro_wav     = os.path.join(amb_dir, f"{intro_name}.wav")
        wav_rel_path  = f"world/maps/{map_lower}/audio/amb/{intro_name}.wav"

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

        # Inject AMB actor into audio ISC (only if not already present)
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
        print(f"    Created intro AMB files: {intro_name}.tpl/.ilu")

    # Generate the intro WAV with a 200ms fade-out at the tail end
    af_filter = f"atrim=end={amb_duration:.3f},asetpts=PTS-STARTPTS,afade=t=out:st={fade_start:.3f}:d=0.2"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", ogg_path,
         "-af", af_filter, "-ar", "48000", intro_wav],
        check=True
    )
    print(f"    Generated intro AMB: {os.path.basename(intro_wav)} ({amb_duration:.3f}s, fade from {fade_start:.3f}s)")


def show_ffplay_preview(video_path, audio_path, v_override, a_offset):
    """Sync preview using an ffmpeg -> ffplay pipe, considering both offsets."""
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print(f"ERROR: Preview files missing!\nVideo: {video_path}\nAudio: {audio_path}")
        return

    import subprocess
    # Logic: net_offset = v_override - a_offset
    # If negative: Video starts before Audio.
    # If positive: Audio starts before Video.
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

def main():
    parser = argparse.ArgumentParser(description="Fully Automated Just Dance 2021 Map Installer")
    parser.add_argument("--map-name", required=True, help="E.g. Rockabye")
    parser.add_argument("--asset-html", required=True, help="Path to asset mapping HTML")
    parser.add_argument("--nohud-html", required=True, help="Path to nohud mapping HTML")
    parser.add_argument("--jd-dir", default=None, help="Base directory of JD tools / JD21 install (auto-detected if omitted)")
    parser.add_argument("--video-override", type=float, default=None, help="Force a specific video start time")
    parser.add_argument("--audio-offset", type=float, default=None, help="Force a specific audio trim offset")
    args = parser.parse_args()
    
    # Clean and detect paths
    map_name = args.map_name.strip()
    map_lower = map_name.lower()
    
    asset_html = clean_path(args.asset_html)
    nohud_html = clean_path(args.nohud_html)
    jd_dir = detect_jd_dir(args.jd_dir)
    
    print(f"--- Environment ---")
    print(f"JD Base Dir: {jd_dir}")
    print(f"Map Name:    {map_name}")
    print(f"Asset HTML:  {asset_html}")
    print(f"-------------------")

    if not preflight_check(jd_dir, asset_html, nohud_html):
        sys.exit(1)
    
    # Download directory should be where the asset HTML is
    download_dir = os.path.dirname(asset_html)
    map_dir = download_dir  # For compatibility with rest of script
    
    target_dir = os.path.join(jd_dir, f"jd21\\data\\World\\MAPS\\{map_name}")
    cache_dir = os.path.join(jd_dir, f"jd21\\data\\cache\\itf_cooked\\pc\\world\\maps\\{map_lower}")
    
    print(f"=== Starting Automation for {map_name} ===")
    print("[1] Cleaning up if there is a previous build...")
    def safe_rmtree(path):
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
            except Exception as e:
                print(f"    Warning: Could not fully delete {path}: {e}")
                print("    Continuing anyway...")

    safe_rmtree(target_dir)
    safe_rmtree(cache_dir)
        
    extracted_zip_dir = os.path.join(map_dir, "main_scene_extracted")
    ipk_extracted = os.path.join(map_dir, "ipk_extracted")
    
    safe_rmtree(extracted_zip_dir)
    safe_rmtree(ipk_extracted)
    
    # 1. Download Files
    print("[2] Downloading assets from JDU servers...")
    urls1 = map_downloader.extract_urls(asset_html) if asset_html and os.path.exists(asset_html) else []
    urls2 = map_downloader.extract_urls(nohud_html) if nohud_html and os.path.exists(nohud_html) else []
    downloaded = map_downloader.download_files(urls1 + urls2, download_dir)
    
    # Auto-detect internal codename from downloaded files
    codename = map_name
    for f in os.listdir(download_dir):
        if "_MAIN_SCENE" in f and f.endswith(".zip"):
            codename = f.split("_MAIN_SCENE")[0]
            break
        elif f.endswith(".ogg") and "AudioPreview" not in f:
            codename = f[:-4]
            break
            
    print(f"    Detected Internal Codename: {codename}")
    
    # Check if necessary media exists, since auth links might expire
    audio_path = os.path.join(download_dir, f"{codename}.ogg")
    if not os.path.exists(audio_path):
        # Fallback to look for hash name from mapped dict if we knew it, or any .ogg not AudioPreview
        oggs = [f for f in glob.glob(os.path.join(download_dir, "*.ogg")) if "AudioPreview" not in f]
        if oggs: audio_path = oggs[0]
        else:
            print("ERROR: Full Audio missing! Check if NO-HUD links expired. Cannot proceed.")
            sys.exit(1)
            
    video_path = None
    for qual in ["ULTRA", "HIGH", "MID", "LOW"]:
        vp = os.path.join(download_dir, f"{codename}_{qual}.webm")
        if os.path.exists(vp): video_path = vp; break
    if not video_path:
        # Check hash named webms
        webms = [f for f in glob.glob(os.path.join(download_dir, "*.webm")) if "MapPreview" not in f and "VideoPreview" not in f]
        if webms: video_path = webms[0]
        else:
            print("ERROR: Full Video missing! Check if NO-HUD links expired. Cannot proceed.")
            sys.exit(1)
    
    # 2. Unzip SCENES
    print("[3] Extracting scene archives...")
    sys.stdout.flush()
    
    extracted_zip_dir = os.path.join(map_dir, "main_scene_extracted")
    os.makedirs(extracted_zip_dir, exist_ok=True)
    
    for f in os.listdir(download_dir):
        if "SCENE" in f and f.endswith(".zip"):
            scene_zip = os.path.join(download_dir, f)
            print(f"    Extracting {f}...")
            with zipfile.ZipFile(scene_zip, 'r') as z:
                z.extractall(extracted_zip_dir)
    
    # 3. Unpack IPK
    print("[4] Unpacking IPK archives...")
    ipk_files = glob.glob(os.path.join(extracted_zip_dir, "*.ipk"))
    ipk_extracted = os.path.join(map_dir, "ipk_extracted")
    for ipk in ipk_files:
        print(f"    Unpacking {os.path.basename(ipk)}...")
        subprocess.run([sys.executable, os.path.join(jd_dir, r"ubiart-archive-tools\ipk_unpacker.py"), ipk, ipk_extracted], check=False, capture_output=True)
    
    # 4. Decode MenuArt CKDs & Copy Raw PNG/JPGs (Must happen before config generation so Coach PNGs can be counted!)
    print("[5] Decoding menu art textures...")
    import fnmatch
    import re
    for file in os.listdir(download_dir):
        src = os.path.join(download_dir, file)
        dst = None
        if fnmatch.fnmatch(file, "*.tga.ckd") or file.endswith(".jpg") or file.endswith(".png"):
            if "Phone" in file or "1024" in file or codename.lower() in file.lower() or map_name.lower() in file.lower():
                new_name = re.sub(re.escape(codename), map_name, file, flags=re.IGNORECASE) if codename.lower() in file.lower() else file
                dst = os.path.join(target_dir, f"MenuArt/textures/{new_name}")
        
        if dst:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            
    # Decode CKDs to actual TGAs/PNGs
    subprocess.run([sys.executable, os.path.join(jd_dir, "ckd_decode.py"), "--batch", "--quiet",
                    os.path.join(target_dir, "MenuArt/textures"), os.path.join(target_dir, "MenuArt/textures")], check=False)

    # 5. Generate Text Files (ISCs, TPLs, TRKs, MPDs)
    print("[6] Generating UbiArt config files (scenes, templates, tracks, manifests)...")
    map_builder.setup_dirs(target_dir)
    # this will return video start time
    video_start_time = map_builder.generate_text_files(map_name, ipk_extracted, target_dir, args.video_override)
    
    if video_start_time is None:
        print("ERROR: Could not fetch video start time.")
        sys.exit(1)
        
    print(f"    Video Start Time is: {video_start_time}")
                    
    # 6. Convert Tapes (JSON to Lua) via UbiArt-aware converter
    print("[7] Converting choreography and karaoke tapes to Lua...")
    for ty in ["dance", "karaoke"]:
        src_tapes = glob.glob(os.path.join(ipk_extracted, f"**/*_tml_{ty}.?tape.ckd"), recursive=True)
        if src_tapes:
            dst_tape = os.path.join(target_dir, f"Timeline/{map_name}_TML_{ty.capitalize()}.{ty[0]}tape")
            tape_data = ubiart_lua.load_ckd_json(src_tapes[0])
            lua_str = ubiart_lua.process_tape(tape_data, tape_type=ty)
            with open(dst_tape, 'w', encoding='utf-8') as f:
                f.write(lua_str)
            print(f"    Converted {os.path.basename(src_tapes[0])} -> {os.path.basename(dst_tape)}")

    # 6.5. Convert Cinematic Tapes (overwrites empty fallback from map_builder if real data exists)
    print("[8] Converting cinematic tapes to Lua...")
    cinematics_dirs = glob.glob(os.path.join(ipk_extracted, "**/cinematics"), recursive=True)
    cine_converted = 0
    for cine_dir in cinematics_dirs:
        for tape_file in glob.glob(os.path.join(cine_dir, "*.tape.ckd")):
            tape_basename = os.path.basename(tape_file)
            output_name = tape_basename.replace(".ckd", "")
            if "mainsequence" in output_name.lower():
                output_name = f"{map_name}_MainSequence.tape"
            dst_path = os.path.join(target_dir, f"Cinematics/{output_name}")
            tape_data = ubiart_lua.load_ckd_json(tape_file)
            lua_str = ubiart_lua.process_tape(tape_data, tape_type="cinematics")
            with open(dst_path, 'w', encoding='utf-8') as f:
                f.write(lua_str)
            print(f"    Converted {tape_basename} -> {output_name}")
            cine_converted += 1
    if cine_converted == 0:
        print("    No cinematic tapes found, keeping empty fallback.")

    # 6.6. Process Ambient Sounds
    amb_dirs = glob.glob(os.path.join(ipk_extracted, "**/audio/amb"), recursive=True)
    if amb_dirs:
        print("[9] Processing ambient sound templates...")
        for amb_dir in amb_dirs:
            dest_amb = os.path.join(target_dir, "Audio/AMB")
            os.makedirs(dest_amb, exist_ok=True)
            for amb_file in glob.glob(os.path.join(amb_dir, "*.tpl.ckd")):
                amb_data = ubiart_lua.load_ckd_json(amb_file)
                ilu_content, tpl_content, audio_file_paths = ubiart_lua.process_ambient_sound(
                    amb_data, map_name, os.path.basename(amb_file))
                base = os.path.basename(amb_file).replace('.tpl.ckd', '')
                with open(os.path.join(dest_amb, f"{base}.ilu"), 'w', encoding='utf-8') as f:
                    f.write(ilu_content)
                with open(os.path.join(dest_amb, f"{base}.tpl"), 'w', encoding='utf-8') as f:
                    f.write(tpl_content)
                print(f"    Generated AMB: {base}.ilu + {base}.tpl")
                # Generate silent WAV placeholders for any referenced audio files that don't exist
                for rel_path in audio_file_paths:
                    abs_path = os.path.join(jd_dir, "jd21", "data", rel_path.replace("/", os.sep))
                    if not os.path.exists(abs_path):
                        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                        with wave.open(abs_path, 'w') as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(48000)
                            wf.writeframes(b'\x00\x00' * 4800)  # 0.1s silence
                        print(f"    Created silent placeholder: {os.path.basename(abs_path)}")

        # Inject AMB actors into the audio ISC so the engine actually loads them
        audio_isc_path = os.path.join(target_dir, f"Audio/{map_name}_audio.isc")
        if os.path.exists(audio_isc_path):
            amb_tpls = glob.glob(os.path.join(target_dir, "Audio/AMB/*.tpl"))
            if amb_tpls:
                with open(audio_isc_path, "r", encoding="utf-8") as f:
                    isc_data = f.read()
                amb_actors = ""
                for i, tpl in enumerate(amb_tpls):
                    amb_name = os.path.basename(tpl).replace('.tpl', '')
                    z = f"0.{i + 2:06d}"
                    amb_actors += f'''		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="{z}" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{amb_name}" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="World/MAPS/{map_name}/audio/AMB/{amb_name}.tpl">
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

    # 7. Decode Pictos
    print("[10] Decoding pictograms...")
    picto_src_dir = None
    for path in glob.glob(os.path.join(ipk_extracted, "**/pictos"), recursive=True):
        picto_src_dir = path
        break
    sys.stdout.flush()

    if picto_src_dir:
        picto_dst_dir = os.path.join(target_dir, "Timeline/pictos")
        os.makedirs(picto_dst_dir, exist_ok=True)
        # Copy all CKD pictos to target, then batch decode in one call
        for f in glob.glob(os.path.join(picto_src_dir, "*.png.ckd")):
            shutil.copy2(f, os.path.join(picto_dst_dir, os.path.basename(f)))
        subprocess.run([sys.executable, os.path.join(jd_dir, "ckd_decode.py"), "--batch", "--quiet",
                        picto_dst_dir, picto_dst_dir], check=False)
        # Remove source CKDs from target after decoding
        for f in glob.glob(os.path.join(picto_dst_dir, "*.ckd")):
            os.remove(f)
            
    # 7.5 Copy Gestures & Autodance files
    print("[11] Extracting move files and autodance data...")
    for plat in ["nx", "wii", "durango", "scarlett", "orbis", "prospero", "wiiu"]:
        moves_src = glob.glob(os.path.join(ipk_extracted, f"**/moves/{plat}"), recursive=True)
        for folder in moves_src:
            dest_moves = os.path.join(target_dir, f"Timeline/Moves/{plat.upper()}")
            os.makedirs(dest_moves, exist_ok=True)
            for f in glob.glob(os.path.join(folder, "*.*")):
                shutil.copy2(f, os.path.join(dest_moves, os.path.basename(f)))
                
    autodance_tpls = glob.glob(os.path.join(ipk_extracted, "**/autodance/*.tpl.ckd"), recursive=True)
    for f in autodance_tpls:
        dest_ad = os.path.join(target_dir, "Autodance")
        os.makedirs(dest_ad, exist_ok=True)
        
        # Use existing map template name to seamlessly link with the map_builder .isc / .act
        dst_tpl = os.path.join(dest_ad, f"{map_name}_autodance.tpl")
        
        # Convert the official JSON property template to an engine-readable Lua template
        subprocess.run([sys.executable, os.path.join(jd_dir, "json_to_lua.py"), f, dst_tpl], check=True, capture_output=True)

    # Convert autodance data CKDs (adtape, adrecording, advideo)
    for ext in ["adtape", "adrecording", "advideo"]:
        ad_ckds = glob.glob(os.path.join(ipk_extracted, f"**/autodance/*.{ext}.ckd"), recursive=True)
        for f in ad_ckds:
            dest_ad = os.path.join(target_dir, "Autodance")
            os.makedirs(dest_ad, exist_ok=True)
            dst_file = os.path.join(dest_ad, f"{map_name}.{ext}")
            subprocess.run([sys.executable, os.path.join(jd_dir, "json_to_lua.py"), f, dst_file],
                          check=False, capture_output=True)

    # Copy any other Autodance media if they exist (ogg, etc.), ignoring generic cooked configs
    autodance_media = glob.glob(os.path.join(ipk_extracted, "**/autodance/*.*"), recursive=True)
    for f in autodance_media:
        if f.endswith(".ckd"): continue # We only want straight media files here
        dest_ad = os.path.join(target_dir, "Autodance")
        os.makedirs(dest_ad, exist_ok=True)
        shutil.copy2(f, os.path.join(dest_ad, os.path.basename(f)))

    # Convert stape CKD (sequence tape with BPM/Signature data) if available
    stape_ckds = glob.glob(os.path.join(ipk_extracted, "**/*.stape.ckd"), recursive=True)
    if stape_ckds:
        dst_stape = os.path.join(target_dir, f"Audio/{map_name}.stape")
        subprocess.run([sys.executable, os.path.join(jd_dir, "json_to_lua.py"),
                       stape_ckds[0], dst_stape], check=False, capture_output=True)

    # 8. Convert Audio
    v_override = args.video_override if args.video_override is not None else video_start_time
    a_offset = args.audio_offset if args.audio_offset is not None else v_override

    if audio_path:
        print(f"[12] Converting audio to 48kHz WAV...")
        convert_audio(audio_path, map_name, target_dir, a_offset)
        generate_intro_amb(audio_path, map_name, target_dir, a_offset)

    # 9. Copy Video
    if video_path:
        print(f"[13] Copying gameplay video...")
        main_vid = os.path.join(target_dir, f"VideosCoach/{map_name}.webm")
        if not os.path.exists(main_vid):
            shutil.copy2(video_path, main_vid)
        
    # 10. Register in SkuScene_Maps_PC_All
    sku_isc = os.path.join(jd_dir, r"jd21\data\World\SkuScenes\SkuScene_Maps_PC_All.isc")
    if os.path.exists(sku_isc):
        with open(sku_isc, "r", encoding="utf-8") as f:
            sku_data = f.read()
            
        if f'USERFRIENDLY="{map_name}"' not in sku_data:
            print(f"[14] Registering {map_name} in SkuScene...")
            # Inject Actor
            actor_xml = f'''           <ACTORS NAME="Actor">
              <Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}" POS2D="0 0" ANGLE="0.000000" INSTANCEDATAFILE="world/maps/{map_name}/songdesc.act" LUA="world/maps/{map_name}/songdesc.tpl">
                  <COMPONENTS NAME="JD_SongDescComponent">
                      <JD_SongDescComponent />
                  </COMPONENTS>
              </Actor>
          </ACTORS>\n'''
            sku_data = sku_data.replace("          <sceneConfigs>", actor_xml + "          <sceneConfigs>")
            
            # Inject Coverflow
            coverflow_xml = f'''                          <CoverflowSkuSongs>
                            <CoverflowSong name="{map_name}"  cover_path="world/maps/{map_name}/menuart/actors/{map_name}_cover_generic.act">
                              </CoverflowSong>
                          </CoverflowSkuSongs>
                          <CoverflowSkuSongs>
                            <CoverflowSong name="{map_name}"  cover_path="world/maps/{map_name}/menuart/actors/{map_name}_cover_online.act">
                              </CoverflowSong>
                          </CoverflowSkuSongs>\n'''
            sku_data = sku_data.replace("                      </JD_SongDatabaseSceneConfig>", coverflow_xml + "                      </JD_SongDatabaseSceneConfig>")
            
            with open(sku_isc, "w", encoding="utf-8") as f:
                f.write(sku_data)
        else:
            print(f"[14] {map_name} is already registered in SkuScene.")
        
    print("=== Automation Complete! ===")
    import time
    time.sleep(1) # Give terminal buffers a second to clear
    sys.stdout.flush()
    
    # --- INTERACTIVE CLI LOOP ---
    while True:
        print("\n" + "="*50)
        print(f" SYNC REFINEMENT: {map_name}")
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
            convert_audio(audio_path, map_name, target_dir, a_offset)
            generate_intro_amb(audio_path, map_name, target_dir, a_offset)
            show_ffplay_preview(video_path, audio_path, v_override, a_offset)
        elif choice == '2':
            # Get durations
            import json
            def get_dur(p):
                res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p], capture_output=True, text=True)
                return float(res.stdout.strip())

            v_dur = get_dur(video_path)
            a_dur = get_dur(audio_path)
            diff = v_dur - a_dur
            print(f"    Video: {v_dur:.2f}s, Audio: {a_dur:.2f}s")
            print(f"    Padding audio by: {diff:.3f}s")
            a_offset = diff
            convert_audio(audio_path, map_name, target_dir, a_offset)
            generate_intro_amb(audio_path, map_name, target_dir, a_offset)
            show_ffplay_preview(video_path, audio_path, v_override, a_offset)
        elif choice == '3':
            try:
                ov = input(f"New VIDEO_OVERRIDE (current {v_override}): ").strip()
                if ov: v_override = float(ov)
                oa = input(f"New AUDIO_OFFSET (current {a_offset}): ").strip()
                if oa: a_offset = float(oa)

                # Regenerate config if video_override changed
                map_builder.generate_text_files(map_name, ipk_extracted, target_dir, v_override)
                # Re-convert audio
                convert_audio(audio_path, map_name, target_dir, a_offset)
                generate_intro_amb(audio_path, map_name, target_dir, a_offset)
                show_ffplay_preview(video_path, audio_path, v_override, a_offset)
            except ValueError:
                print("Invalid number entered.")
        elif choice == '4':
            show_ffplay_preview(video_path, audio_path, v_override, a_offset)
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()
