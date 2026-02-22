import os
import shutil
import subprocess
import glob
import zipfile
import argparse
import sys

# Import our individual scripts
import map_downloader
import map_builder

def convert_audio(audio_path, map_name, target_dir, a_offset):
    wav_out = os.path.join(target_dir, f"Audio/{map_name}.wav")
    ogg_out = os.path.join(target_dir, f"Audio/{map_name}.ogg")
    
    if not os.path.exists(ogg_out):
        print(f"    [8b] Copying pristine Menu Preview OGG...")
        shutil.copy2(audio_path, ogg_out)
        
    if a_offset == 0.0:
        print(f"    [8a] Converting pristine Gameplay WAV (no offset)...")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path, "-ar", "48000", wav_out], check=True)
    else:
        print(f"    [8a] Trimming offset {a_offset}s for Gameplay WAV...")
        if a_offset < 0:
            af_filter = f"atrim=start={abs(a_offset)},asetpts=PTS-STARTPTS"
        else:
            af_filter = f"adelay={int(a_offset * 1000)}|{int(a_offset * 1000)},asetpts=PTS-STARTPTS"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path, "-af", af_filter, "-ar", "48000", wav_out], check=True)

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

    ffplay_cmd = ["ffplay", "-i", "-", "-autoexit", "-window_title", "SYNC PREVIEW - CLOSE TO CONTINUE"]

    print(f"\nLaunching Sync Preview (Net Delay: {net_offset:.3f}s)...")
    print("Close the preview window to return to the menu.")
    
    try:
        # Start ffmpeg process. We don't hide stderr here so we can see errors!
        p_ffmpeg = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE)
        # Start ffplay process, reading from ffmpeg's stdout
        p_ffplay = subprocess.Popen(ffplay_cmd, stdin=p_ffmpeg.stdout)

        
        # Allow p_ffmpeg to receive a SIGPIPE if p_ffplay exits
        p_ffmpeg.stdout.close()
        
        # Wait for ffplay to close
        p_ffplay.wait()
        
        # Terminate ffmpeg if it's still running
        if p_ffmpeg.poll() is None:
            p_ffmpeg.terminate()
            
    except Exception as e:
        print(f"ERROR: Preview session failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="Fully Automated Just Dance 2021 Map Installer")
    parser.add_argument("--map-name", required=True, help="E.g. Rockabye")
    parser.add_argument("--asset-html", required=True, help="Path to asset mapping HTML")
    parser.add_argument("--nohud-html", required=True, help="Path to nohud mapping HTML")
    parser.add_argument("--jd-dir", default=r"d:\jd2021pc", help="Base directory of JD tools / JD21 install")
    parser.add_argument("--video-override", type=float, default=None, help="Force a specific video start time")
    parser.add_argument("--audio-offset", type=float, default=None, help="Force a specific audio trim offset")
    args = parser.parse_args()
    
    map_name = args.map_name
    map_lower = map_name.lower()
    jd_dir = args.jd_dir
    
    map_dir = os.path.join(jd_dir, map_name)
    download_dir = os.path.join(map_dir, "downloads")
    
    target_dir = os.path.join(jd_dir, f"jd21\\data\\World\\MAPS\\{map_name}")
    cache_dir = os.path.join(jd_dir, f"jd21\\data\\cache\\itf_cooked\\pc\\world\\maps\\{map_lower}")
    
    print(f"=== Starting Automation for {map_name} ===")
    print("[0] Cleaning up old builds...")
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
    print("[1] Downloading Files...")
    urls1 = map_downloader.extract_urls(args.asset_html) if os.path.exists(args.asset_html) else []
    urls2 = map_downloader.extract_urls(args.nohud_html) if os.path.exists(args.nohud_html) else []
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
    print("[2] Extracting Scene Archives...")
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
    print("[3] Unpacking Cooked IPKs...")
    ipk_files = glob.glob(os.path.join(extracted_zip_dir, "*.ipk"))
    ipk_extracted = os.path.join(map_dir, "ipk_extracted")
    for ipk in ipk_files:
        print(f"    Unpacking {os.path.basename(ipk)}...")
        subprocess.run([sys.executable, os.path.join(jd_dir, r"ubiart-archive-tools\ipk_unpacker.py"), ipk, ipk_extracted], check=False)
    
    # 4. Decode MenuArt CKDs & Copy Raw PNG/JPGs (Must happen before config generation so Coach PNGs can be counted!)
    print("[4] Decoding MenuArt textures...")
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
    subprocess.run([sys.executable, os.path.join(jd_dir, "ckd_decode.py"), "--batch", 
                    os.path.join(target_dir, "MenuArt/textures"), os.path.join(target_dir, "MenuArt/textures")], check=False)

    # 5. Generate Text Files (ISCs, TPLs, TRKs, MPDs)
    print("[5] Generating Config Files...")
    map_builder.setup_dirs(target_dir)
    # this will return video start time
    video_start_time = map_builder.generate_text_files(map_name, ipk_extracted, target_dir, args.video_override)
    
    if video_start_time is None:
        print("ERROR: Could not fetch video start time.")
        sys.exit(1)
        
    print(f"    Video Start Time is: {video_start_time}")
                    
    # 6. Convert Tapes (JSON to Lua)
    print("[6] Converting Choreography Tapes...")
    for ty in ["dance", "karaoke"]:
        src_tapes = glob.glob(os.path.join(ipk_extracted, f"**/*_tml_{ty}.?tape.ckd"), recursive=True)
        if src_tapes:
            dst_tape = os.path.join(target_dir, f"Timeline/{map_name}_TML_{ty.capitalize()}.{ty[0]}tape")
            subprocess.run([sys.executable, os.path.join(jd_dir, "json_to_lua.py"), src_tapes[0], dst_tape], check=True)
    
    # 7. Decode Pictos
    print("[7] Decoding Pictograms...")
    picto_src_dir = None
    for path in glob.glob(os.path.join(ipk_extracted, "**/pictos"), recursive=True):
        picto_src_dir = path
        break
    sys.stdout.flush()
        
    if picto_src_dir:
        for f in glob.glob(os.path.join(picto_src_dir, "*.png.ckd")):
            dst = os.path.join(target_dir, "Timeline/pictos", os.path.basename(f)[:-4]) # remove .ckd
            subprocess.run([sys.executable, os.path.join(jd_dir, "ckd_decode.py"), f, dst], check=False)
            
    # 7.5 Copy Gestures & Autodance files
    print("[7.5] Extracting Moves and Autodance files...")
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
        subprocess.run([sys.executable, os.path.join(jd_dir, "json_to_lua.py"), f, dst_tpl], check=True)
            
    # Copy any other Autodance media if they exist (ogg, etc.), ignoring generic cooked configs
    autodance_media = glob.glob(os.path.join(ipk_extracted, "**/autodance/*.*"), recursive=True)
    for f in autodance_media:
        if f.endswith(".ckd"): continue # We only want straight media files here
        dest_ad = os.path.join(target_dir, "Autodance")
        os.makedirs(dest_ad, exist_ok=True)
        shutil.copy2(f, os.path.join(dest_ad, os.path.basename(f)))
            
    # 8. Convert Audio
    v_override = args.video_override if args.video_override is not None else video_start_time
    a_offset = args.audio_offset if args.audio_offset is not None else v_override
    
    if audio_path:
        print(f"[8] Processing Audio...")
        convert_audio(audio_path, map_name, target_dir, a_offset)

    # 9. Copy Video
    if video_path:
        print(f"[9] Copying Video from {video_path}...")
        main_vid = os.path.join(target_dir, f"VideosCoach/{map_name}.webm")
        if not os.path.exists(main_vid):
            shutil.copy2(video_path, main_vid)
        
    # 10. Register in SkuScene_Maps_PC_All
    sku_isc = os.path.join(jd_dir, r"jd21\data\World\SkuScenes\SkuScene_Maps_PC_All.isc")
    if os.path.exists(sku_isc):
        with open(sku_isc, "r", encoding="utf-8") as f:
            sku_data = f.read()
            
        if f'USERFRIENDLY="{map_name}"' not in sku_data:
            print(f"[10] Registering {map_name} in SkuScene...")
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
            print(f"[10] {map_name} is already registered in SkuScene.")
        
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
            break
        elif choice == '1':
            a_offset = v_override
            convert_audio(audio_path, map_name, target_dir, a_offset)
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
            except ValueError:
                print("Invalid number entered.")
        elif choice == '4':
            show_ffplay_preview(video_path, audio_path, v_override, a_offset)
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()
