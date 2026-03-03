# Pipeline Reference

This document describes every step of the JD2021 Map Installer pipeline in detail: what each step does, what files it reads and writes, what can go wrong, and when a step is skipped.

---

## Pipeline Overview

The pipeline consists of 16 steps (numbered 00 through 14, plus 05b). Each step receives a `PipelineState` object (`map_installer.py:77`) that carries all intermediate data.

```
Step 00  Pre-install cleanup
Step 01  Clean previous builds
Step 02  Download assets from JDU servers
Step 03  Extract scene archives
Step 04  Unpack IPK archives
Step 05  Decode MenuArt textures
Step 05b Validate MenuArt covers
Step 06  Generate UbiArt config files
Step 07  Convert choreography/karaoke tapes
Step 08  Convert cinematic tapes
Step 09  Process ambient sounds
Step 10  Decode pictograms
Step 11  Extract moves & autodance
Step 12  Convert audio
Step 13  Copy gameplay video
Step 14  Register in SkuScene
```

After the pipeline completes, the CLI enters an interactive sync refinement loop, or the GUI exposes a sync refinement panel.

---

## Step 00 — Pre-install Cleanup

**Function:** `step_00_pre_install_cleanup(state)` (`map_installer.py:1055`)

**Purpose:** Remove any previous installation of this map from the game directory, including residual data from a failed or outdated install.

**Actions:**
1. For both `map_name` and `original_map_name` (if different due to sanitization):
   - Delete the map directory: `jd21/data/World/MAPS/{name}`
   - Delete cooked cache directories: `cache/itf_cooked/pc/world/maps/{name}`, plus `_autodance` and `_cine` suffixed variants
   - Unregister from SkuScene via `unregister_sku()` — uses regex to remove Actor and CoverflowSong XML blocks

**Inputs:** `state.jd21_dir`, `state.map_name`, `state.original_map_name`

**Outputs:** Clean game directory with no trace of the previous map installation.

**Failure modes:**
- Permission errors when deleting directories (logged as warnings, continues anyway)
- SkuScene file not found (silently skipped)

---

## Step 01 — Clean Previous Builds

**Function:** `step_01_clean(state)` (`map_installer.py:1085`)

**Purpose:** Remove build artifacts from a previous pipeline run in the working directory.

**Actions:**
1. Delete `target_dir` (`jd21/data/World/MAPS/{map_name}`)
2. Delete `cache_dir` (`jd21/data/cache/itf_cooked/pc/world/maps/{map_lower}`)
3. Delete `extracted_zip_dir` (`download_dir/main_scene_extracted`)
4. Delete `ipk_extracted` (`download_dir/ipk_extracted`)

**Failure modes:** Same as Step 00 — deletion failures are logged and tolerated.

---

## Step 02 — Download Assets

**Function:** `step_02_download(state)` (`map_installer.py:1094`)

**Purpose:** Download all required assets from JDU CDN servers and detect the map codename, audio file, and video file.

**Actions:**
1. Extract URLs from both `asset_html` and `nohud_html` via `map_downloader.extract_urls()`
2. Call `map_downloader.download_files()` with quality preference and `interactive=False`
   - Selects the best available video quality (falls back through 8 tiers)
   - Selects DURANGO mainscene ZIP (falls back to NX, then SCARLETT, then any)
   - Skips already-downloaded files
   - Retries failed downloads up to 3 times with exponential backoff
   - Handles HTTP 429 with `Retry-After` header
   - 0.5s delay between sequential downloads
3. Detect codename from downloaded filenames (looks for `*_MAIN_SCENE*.zip` or `*.ogg`)
4. Locate audio file (`.ogg`, excluding `AudioPreview`)
5. Locate video file (`.webm`, excluding `MapPreview`/`VideoPreview`) using quality preference order

**Inputs:** `state.asset_html`, `state.nohud_html`, `state.download_dir`, `state.quality`

**Outputs:** `state.codename`, `state.audio_path`, `state.video_path`

**Failure modes:**
- **Missing audio:** Raises `RuntimeError("Full Audio missing!")` — usually means NOHUD links expired
- **Missing video:** Raises `RuntimeError("Full Video missing!")` — same cause
- **HTTP 403/404:** Links have expired. In interactive mode, offers to reuse existing video; otherwise raises `RuntimeError`
- **Network errors:** Retried up to 3 times, then logged as error

---

## Step 03 — Extract Scene Archives

**Function:** `step_03_extract_scenes(state)` (`map_installer.py:1139`)

**Purpose:** Extract the mainscene ZIP archive containing IPK files, CKD assets, and platform-specific data.

**Actions:**
1. Scan `download_dir` for files matching `*SCENE*.zip`
2. Select preferred platform: DURANGO > NX > SCARLETT > any
3. Extract selected ZIP to `extracted_zip_dir`

**Platform preference rationale:** DURANGO (Xbox One) uses Kinect gesture files that are format-compatible with the PC adapter. NX (Switch) and ORBIS (PS4) use incompatible gesture binary formats.

**Inputs:** `state.download_dir`, `state.extracted_zip_dir`

**Failure modes:** ZIP extraction errors propagate as exceptions.

---

## Step 04 — Unpack IPK Archives

**Function:** `step_04_unpack_ipk(state)` (`map_installer.py:1176`)

**Purpose:** Extract the contents of UbiArt IPK archive files.

**Actions:**
1. Find all `*.ipk` files in `extracted_zip_dir`
2. Extract each via `ipk_unpack.extract()` to `ipk_extracted`
   - IPK format: big-endian header with magic `\x50\xEC\x12\xBA`
   - Decompression: tries zlib first, then lzma, then raw copy
   - Path traversal protection: rejects paths containing `..`

**Inputs:** `state.extracted_zip_dir`, `state.ipk_extracted`

**Failure modes:** IPK extraction issues logged as warnings (continues with next file).

---

## Step 05 — Decode MenuArt Textures

**Function:** `step_05_decode_menuart(state)` (`map_installer.py:1188`)

**Purpose:** Copy and decode cover art textures for the song select menu.

**Actions:**
1. Scan `download_dir` for files matching:
   - `*.tga.ckd` files containing `Phone`, `1024`, or the codename/map_name
   - `*.jpg` and `*.png` files matching the same criteria
2. Copy matching files to `target_dir/MenuArt/textures/`
3. Rename files if codename differs from map_name
4. Run `ckd_decode.py --batch --quiet` on the textures directory to convert CKDs to images

**Texture pipeline:** CKD → strip 44-byte header → XTX (deswizzle via xtx_extractor) → DDS → Pillow → PNG/TGA. PC CKDs with DDS payload skip the XTX step.

**Inputs:** `state.download_dir`, `state.target_dir`, `state.codename`, `state.map_name`

---

## Step 05b — Validate MenuArt Covers

**Function:** `step_05b_validate_menuart(state)` (`map_installer.py:1209`)

**Purpose:** Ensure all required cover TGA files exist with correct naming, format, and case.

**Actions:**
1. Check for 6 expected cover files:
   - `{map_name}_cover_generic.tga`
   - `{map_name}_cover_online.tga`
   - `{map_name}_cover_albumbkg.tga`
   - `{map_name}_cover_albumcoach.tga`
   - `{map_name}_banner_bkg.tga`
   - `{map_name}_map_bkg.tga`
2. Fix case mismatches by renaming files to match expected case
3. Copy `cover_generic` ↔ `cover_online` if one is missing but the other exists
4. Re-save all found TGAs through Pillow as uncompressed 32-bit RGBA to ensure engine compatibility

**Failure modes:** Missing covers are logged as `[MISS]` but do not halt the pipeline; the map will load with blank cover art.

---

## Step 06 — Generate UbiArt Config Files

**Function:** `step_06_generate_configs(state)` (`map_installer.py:1289`)

**Purpose:** Generate all UbiArt engine configuration files from CKD metadata.

**Actions:**
1. Create directory structure via `map_builder.setup_dirs()`
2. Check for non-ASCII characters in Title/Artist/Credits/DancerName via `check_metadata_encoding()`
   - Interactive: prompts user for replacement values
   - Non-interactive: auto-strips non-ASCII characters
3. Call `map_builder.generate_text_files()` which produces:

| File | Format | Contents |
|------|--------|----------|
| `{MapName}_MAIN_SCENE.isc` | XML | Root scene linking all sub-scenes |
| `SongDesc.tpl` | Lua | Song metadata (title, artist, difficulty, colors, etc.) |
| `SongDesc.act` | Lua | Song metadata actor instance |
| `Audio/{MapName}.trk` | Lua | Beat timing markers, videoStartTime, startBeat |
| `Audio/{MapName}_musictrack.tpl` | Lua | MusicTrack template |
| `Audio/{MapName}_sequence.tpl` | Lua | Sequence template |
| `Audio/{MapName}_audio.isc` | XML | Audio scene |
| `Audio/ConfigMusic.sfi` | XML | Sound format info |
| `Timeline/{MapName}_tml.isc` | XML | Timeline scene |
| `Timeline/{MapName}_TML_Dance.tpl` | Lua | Dance tape template |
| `Timeline/{MapName}_TML_Dance.act` | Lua | Dance tape actor |
| `Timeline/{MapName}_TML_Karaoke.tpl` | Lua | Karaoke tape template |
| `Timeline/{MapName}_TML_Karaoke.act` | Lua | Karaoke tape actor |
| `Cinematics/{MapName}_cine.isc` | XML | Cinematics scene |
| `Cinematics/{MapName}_mainsequence.tpl` | Lua | Main sequence template |
| `Cinematics/{MapName}_mainsequence.act` | Lua | Main sequence actor |
| `MenuArt/{MapName}_menuart.isc` | XML | MenuArt scene |
| `MenuArt/Actors/*.act` | Lua | Cover/banner actor instances |
| `VideosCoach/{MapName}_video.isc` | XML | Video scene |
| `VideosCoach/{MapName}.mpd` | XML | DASH manifest |
| `VideosCoach/video_player_main.act` | Lua | Video player actor |
| `Autodance/{MapName}_autodance.tpl` | Lua | Autodance template (stub) |
| `Autodance/{MapName}_autodance.act` | Lua | Autodance actor |
| `Autodance/{MapName}_autodance.isc` | XML | Autodance scene |

4. Extract `videoStartTime` → `state.video_start_time`
5. Extract musictrack marker metadata → `state.musictrack_start_beat`, `state.marker_preroll_ms`

**Key transformations:**
- `Status = 12` (ObjectiveLocked) overridden to `Status = 3` (Available) for immediate playability
- `JDVersion` and `OriginalJDVersion` capped to `MAX_JD_VERSION` (2021) to prevent engine crashes
- DefaultColors extracted with case-insensitive key matching from CKD

**Failure modes:** Raises `RuntimeError` if `videoStartTime` cannot be extracted.

---

## Step 07 — Convert Choreography/Karaoke Tapes

**Function:** `step_07_convert_tapes(state)` (`map_installer.py:1349`)

**Purpose:** Convert dance and karaoke tapes from CKD JSON to UbiArt Lua.

**Actions:**
1. For each tape type (`dance`, `karaoke`):
   - Find `*_tml_{type}.?tape.ckd` in `ipk_extracted`
   - Parse JSON via `load_ckd_json()`
   - Process via `ubiart_lua.process_tape()`:
     - Collect unique TrackIds from all clips
     - Convert MotionClip Color arrays to `0xRRGGBBAA` hex strings
     - Convert MotionPlatformSpecifics to KEY/VAL format
     - Normalize degenerate TrackIds (all-unique → group by class)
     - Build Tracks array
     - Apply `remove_class()` and `remove_falsy()` transformations
   - Write Lua output to `Timeline/{MapName}_TML_{Type}.{x}tape`

**Inputs:** `state.ipk_extracted`, `state.target_dir`, `state.map_name`

**Skip condition:** If no tape CKD files are found for a given type, that type is silently skipped.

---

## Step 08 — Convert Cinematic Tapes

**Function:** `step_08_convert_cinematics(state)` (`map_installer.py:1363`)

**Purpose:** Convert cinematic tapes and extract SoundSetClip metadata for AMB processing.

**Actions:**
1. Find all `*.tape.ckd` files in `cinematics/` subdirectories of `ipk_extracted`
2. For `mainsequence` tapes:
   - Extract `SoundSetClip` data (name, start_time, duration, path) → `state.amb_sound_clips`
3. Process via `ubiart_lua.process_tape(tape_type="cinematics")`:
   - Resolve `ActorIndices` against `ActorPaths` (integer indices → path strings wrapped in VAL)
   - Process curve data: `[x, y]` values → `vector2dNew(x, y)` objects
   - Remove top-level `ActorPaths` after resolution
4. Write to `Cinematics/{output_name}`

**Skip condition:** If no cinematic tapes exist, prints "No cinematic tapes found, keeping empty fallback."

---

## Step 09 — Process Ambient Sounds

**Function:** `step_09_process_amb(state)` (`map_installer.py:1400`)

**Purpose:** Process ambient sound templates from the extracted IPK into engine-ready files.

**Actions:**
1. Find `audio/amb/*.tpl.ckd` in `ipk_extracted`
2. For each AMB template:
   - Parse via `load_ckd_json()`
   - Process via `ubiart_lua.process_ambient_sound()`:
     - Extract sound list and audio file paths
     - Generate `.ilu` (sound descriptor with `appendTable` call)
     - Generate `.tpl` (actor template with `includeReference`)
   - Create silent WAV placeholders for referenced audio files (0.1s mono, 48kHz)
3. Inject AMB actors into `Audio/{MapName}_audio.isc`

**Outputs:** `Audio/AMB/*.ilu`, `Audio/AMB/*.tpl`, silent placeholder WAVs

**Skip condition:** If no `audio/amb/` directory exists in IPK, prints "[9] No ambient sound templates found, skipping."

---

## Step 10 — Decode Pictograms

**Function:** `step_10_decode_pictos(state)` (`map_installer.py:1457`)

**Purpose:** Decode pictogram textures from CKD to PNG.

**Actions:**
1. Find `pictos/` directory in `ipk_extracted`
2. Copy `*.png.ckd` files to `Timeline/pictos/`
3. Run `ckd_decode.py --batch --quiet` to decode CKDs to PNGs
4. Clean up source `.ckd` files from the output directory

---

## Step 11 — Extract Moves & Autodance

**Function:** `step_11_extract_moves(state)` (`map_installer.py:1477`)

**Purpose:** Extract gesture/move files and convert autodance data.

**Actions:**

**Move extraction:**
1. Copy platform-specific move files (`nx`, `wii`, `durango`, `scarlett`, `orbis`, `prospero`, `wiiu`) to `Timeline/Moves/{PLATFORM}/`
2. Merge into `PC/` directory:
   - `.gesture` files from Kinect-compatible platforms only (DURANGO, SCARLETT)
   - `.msm` files from all platforms (platform-neutral skeleton format)
3. Substitute ORBIS-exclusive gestures: strip trailing digits from filename (e.g., `handstoheart0.gesture` → `handstoheart.gesture`) and copy the base Kinect gesture under the numbered name

**Autodance conversion:**
4. Convert `autodance/*.tpl.ckd` via `json_to_lua.convert_file()`
5. Convert `.adtape.ckd`, `.adrecording.ckd`, `.advideo.ckd` via `json_to_lua.convert_file()`
6. Copy any non-CKD autodance media (OGG files, etc.)

**Stape conversion:**
7. Convert `*.stape.ckd` (sequence tape with BPM/signature data) via `json_to_lua.convert_file()`

---

## Step 12 — Convert Audio

**Function:** `step_12_convert_audio(state)` (`map_installer.py:1585`)

**Purpose:** Convert the OGG audio to 48kHz WAV and generate intro AMB coverage.

**Actions:**
1. Resolve default sync parameters if not explicitly set:
   - `v_override` defaults to `video_start_time` (from Step 06)
   - `a_offset` defaults to marker-based pre-roll (if available) or `v_override`
2. Convert OGG to WAV via `convert_audio()`:
   - `a_offset == 0`: straight conversion at 48kHz
   - `a_offset < 0`: trim first `abs(a_offset)` seconds, convert to 48kHz
   - `a_offset > 0`: pad with `a_offset * 1000`ms silence, convert to 48kHz
3. Copy OGG to `Audio/{MapName}.ogg` (for song select preview)
4. Generate intro AMB via `generate_intro_amb()`:
   - Creates AMB WAV covering the silence window from `t=0` to `t=abs(v_override)`
   - Sources audio from the same OGG (making overlap inaudible)
   - 200ms linear fade-out at the end
   - Creates `.tpl`/`.ilu` files if they don't exist from IPK processing
   - Injects AMB actor into audio ISC
5. Extract real AMB audio via `extract_amb_audio()`:
   - Overwrites silent placeholder WAVs for SoundSetClips with `StartTime <= 0`
   - Uses marker-based pre-roll duration for timing

**Key formula (marker-based a_offset):**
```
idx = abs(startBeat)
marker_preroll_ms = markers[idx] / 48.0 + 85.0
a_offset = -(marker_preroll_ms / 1000.0)
```

**Skip condition:** If `state.audio_path` is None, the step is skipped entirely.

---

## Step 13 — Copy Gameplay Video

**Function:** `step_13_copy_video(state)` (`map_installer.py:1611`)

**Purpose:** Copy the gameplay WebM video to the target directory.

**Actions:**
1. Copy `state.video_path` to `VideosCoach/{MapName}.webm`
2. Skipped if the destination file already exists

**Skip condition:** If `state.video_path` is None.

---

## Step 14 — Register in SkuScene

**Function:** `step_14_register_sku(state)` (`map_installer.py:1620`)

**Purpose:** Register the map in the game's song database so it appears in the song select menu.

**Actions:**
1. Open `SkuScene_Maps_PC_All.isc`
2. Check if map is already registered (by `USERFRIENDLY` attribute)
3. Inject Actor XML block before `<sceneConfigs>`:
   - References `songdesc.act` and `songdesc.tpl`
   - Component: `JD_SongDescComponent`
4. Inject two CoverflowSong XML blocks before `</JD_SongDatabaseSceneConfig>`:
   - One for `cover_generic.act`
   - One for `cover_online.act`
5. Verify registration by checking for `USERFRIENDLY="{map_name}"` in final data

**Failure modes:**
- SkuScene file not found: logs error, returns without registration
- `<sceneConfigs>` insertion point not found: logs warning
- `</JD_SongDatabaseSceneConfig>` not found: logs warning (map may not appear in menu)
- Verification failure: logs error

---

## Sync Refinement (Post-Pipeline)

After the 16 steps complete, both CLI and GUI offer interactive sync adjustment.

### CLI Sync Loop

The CLI presents a text menu (`map_installer.py:1813`):

| Option | Action |
|--------|--------|
| `0` | Exit (all good) |
| `1` | Sync Beatgrid: set `a_offset = v_override` |
| `2` | Sync Beatgrid: pad audio to match video duration difference |
| `3` | Custom values: manually enter `v_override` and `a_offset` |
| `4` | Preview with ffplay |

Options 1–3 call `reprocess_audio()` which re-runs `convert_audio()`, `generate_intro_amb()`, and `extract_amb_audio()`, then launches an ffplay preview. Option 3 also regenerates config files if `v_override` changed.

### GUI Sync Panel

The GUI provides:
- Increment/decrement buttons for `v_override` and `a_offset` (±0.001, ±0.01, ±0.1, ±1.0)
- Embedded video preview (ffmpeg → RGB24 pipe → PIL → Tkinter canvas) with audio-only ffplay
- Seek bar and playback controls
- "Apply & Finish" button that:
  1. Regenerates config files
  2. Reprocesses audio
  3. Saves map config to `map_configs/{map_name}.json`
  4. Clears game cache
  5. Prompts for optional cleanup of downloaded files

---

## Batch Mode

`batch_install_maps.py` runs the pipeline in two phases:

**Phase 1 — Download (network-dependent):**
- Steps 01–02 for each map, while CDN auth tokens are fresh

**Phase 2 — Process (local-only):**
- Steps 03–14 for each successfully downloaded map
- No network needed; safe to run after links expire

This prevents link expiration when installing many maps, since JDHelper auth tokens have a ~30 minute lifetime.

**CLI arguments:**
- `maps_dir` — path to folder containing map subfolders (default: `MapDownloads/`)
- `--jd21-path` — path to JD installation root
- `--quality` — video quality for all maps (default: `ultra_hd`)
- `--skip-existing` — skip maps already installed in MAPS/
- `--only MAP [MAP ...]` — only install specific maps
- `--exclude MAP [MAP ...]` — skip specific maps

---

## Reprocessing Audio

`reprocess_audio(state, a_offset, v_override)` (`map_installer.py:999`) is the shared function used by both CLI sync loop and GUI apply action. It:

1. Calls `convert_audio()` to regenerate the WAV
2. Calls `generate_intro_amb()` to regenerate the intro AMB
3. Calls `extract_amb_audio()` to update SoundSetClip placeholders
4. Updates `state.a_offset`
5. Clears the game cache directory
