# Architecture

This document describes the internal architecture of the JD2021 Map Installer: how the components relate to each other, data flows through the pipeline, and the key design patterns used throughout.

---

## Component Map

```
                          User Input
                              |
               +--------------+--------------+
               |                             |
        gui_installer.py              map_installer.py
        (Tkinter GUI)                 (CLI + Core Pipeline)
               |                             |
               +----------+  +--------------+
                          |  |
                    PipelineState
                          |
     +--------------------+--------------------+
     |          |         |         |          |
map_downloader  ipk_unpack  ckd_decode  map_builder
     |          |         |         |
     |     ubiart_lua  json_to_lua  |
     |          |         |         |
     +----+----+----+----+----+----+
          |              |
      helpers.py    log_config.py
```

### Entry Points

| Entry Point | Description |
|---|---|
| `gui_installer.py` | Tkinter GUI. Launches the pipeline in a background thread. |
| `map_installer.py` | CLI entrypoint with `argparse`. Also the core pipeline module imported by both GUI and batch. |
| `batch_install_maps.py` | Two-phase batch processor. Imports `map_installer` and runs steps in download-then-process order. |

### Core Modules

| Module | Role |
|---|---|
| `map_installer.py` | Pipeline orchestrator. Defines `PipelineState`, all 16 step functions (`step_00` through `step_14` plus `step_05b`), audio processing, sync preview, game path discovery, preflight checks, SkuScene registration, and the CLI interactive sync loop. |
| `map_builder.py` | UbiArt config file generator. Produces `.isc`, `.tpl`, `.act`, `.trk`, `.mpd`, `.sfi`, and `.stape` files from CKD metadata. |
| `map_downloader.py` | CDN asset downloader. Extracts URLs from HTML, filters by quality tier and platform, downloads with retry logic. |
| `ubiart_lua.py` | UbiArt-specific Lua serializer for tape files. Handles MotionClip colors, cinematic curves, ambient sounds, and platform-specific motion data. |
| `json_to_lua.py` | Generic JSON-to-Lua converter for non-tape files (autodance templates, stape data). |
| `ipk_unpack.py` | IPK archive extractor. Reads the big-endian UbiArt archive format with zlib/lzma decompression. |
| `ckd_decode.py` | CKD texture decoder. Strips the 44-byte UbiArt header and converts XTX (Nintendo Switch) or DDS payloads to PNG/TGA. |

### Shared Utilities

| Module | Role |
|---|---|
| `helpers.py` | Shared constants (`TICKS_PER_MS`, `DISK_SPACE_MIN_MB`, `MAX_JD_VERSION`, etc.) and `load_ckd_json()` for reading CKD files as JSON. |
| `log_config.py` | Unified logging setup. Root logger `jd2021` with child loggers per module. Supports CLI (console+file) and GUI (queue-based `TextWidgetHandler`) modes. |

### External Dependencies

| Dependency | Where Used | Purpose |
|---|---|---|
| `xtx_extractor/` | `ckd_decode.py` | Deswizzles Nintendo Switch XTX textures to DDS. Bundled in the repository. |
| `Pillow` (PIL) | `ckd_decode.py`, `gui_installer.py`, `map_installer.py` (step 05b) | DDS-to-image conversion, TGA re-saving, embedded preview frame display. |
| `ffmpeg` | `map_installer.py` (audio conversion, AMB generation) | Audio format conversion, trimming, padding, fade effects. |
| `ffplay` | `map_installer.py`, `gui_installer.py` | Sync preview playback (CLI: piped video+audio; GUI: audio-only). |
| `ffprobe` | `map_installer.py`, `gui_installer.py` | Duration detection for pad-audio and preview seek bar. |

---

## PipelineState

`PipelineState` (`map_installer.py:77`) is the central data object that carries all intermediate state through the pipeline. Every step function receives a `PipelineState` instance and reads/writes its attributes.

### Key Attributes

| Attribute | Set By | Used By | Description |
|---|---|---|---|
| `map_name` | Constructor | All steps | Sanitized map name (ASCII-safe). |
| `original_map_name` | Constructor | Step 00 | Pre-sanitization name for cleanup of old installs. |
| `jd21_dir` | Constructor (via `resolve_game_paths`) | Steps 00, 01, 09, 12, 14 | Resolved path to the `jd21/` game data directory. |
| `target_dir` | Constructor | Steps 01-14 | Output directory: `jd21/data/World/MAPS/{map_name}`. |
| `cache_dir` | Constructor | Steps 00, 01, 12 | Game cache path for the map. |
| `download_dir` | Constructor | Steps 02-04 | Directory where CDN assets are downloaded. |
| `codename` | Step 02 | Steps 05-13 | Internal JDU codename detected from downloaded filenames. |
| `audio_path` | Step 02 | Steps 12, sync | Path to the OGG audio file. |
| `video_path` | Step 02 | Steps 13, sync | Path to the WebM video file. |
| `video_start_time` | Step 06 | Step 12 | `videoStartTime` extracted from musictrack CKD. |
| `v_override` | Step 12 / User | Sync, AMB generation | Video start time override (may differ from extracted value). |
| `a_offset` | Step 12 / User | Audio conversion, AMB | Audio offset in seconds (negative = trim, positive = pad). |
| `musictrack_start_beat` | Step 06 | AMB calculation | `startBeat` from musictrack (typically negative). |
| `marker_preroll_ms` | Step 06 | Steps 12, AMB | Precise pre-roll duration from marker data. |
| `amb_sound_clips` | Step 08 | Step 09, AMB extraction | SoundSetClip metadata from mainsequence tape. |
| `metadata_overrides` | GUI/Step 06 | Step 06 | User-provided replacements for non-ASCII metadata fields. |
| `_interactive` | Constructor | Steps with `input()` | `True` for CLI, `False` for GUI/batch. Controls whether `input()` is called. |
| `quality` | Constructor | Step 02 | Video quality tier (e.g., `ULTRA_HD`). |

---

## Data Flow

### Single Map Install (CLI or GUI)

```
1. User provides: asset.html, nohud.html, game directory
                    |
2. PipelineState created (paths resolved, codename unknown)
                    |
3. Preflight Check (ffmpeg, game data, scripts, disk space, permissions)
                    |
4. Pipeline Steps 00-14 execute sequentially:
   [00] Pre-install cleanup (delete old map dir + cache + SkuScene entry)
   [01] Clean build artifacts (target_dir, cache, extracted dirs)
   [02] Download assets (CDN -> download_dir; detect codename, audio, video)
   [03] Extract scene ZIPs (prefer DURANGO > NX > SCARLETT platform)
   [04] Unpack IPK archives (zlib/lzma decompression)
   [05] Decode MenuArt textures (CKD -> XTX/DDS -> PNG/TGA)
  [05b] Validate MenuArt covers (case fix, missing cover fallback, TGA re-save)
   [06] Generate UbiArt configs (ISC/TPL/ACT/TRK/MPD from CKD metadata)
   [07] Convert dance/karaoke tapes (CKD JSON -> UbiArt Lua via ubiart_lua.py)
   [08] Convert cinematic tapes (curves, ActorIndices; extract SoundSetClip data)
   [09] Process AMB sounds (IPK templates -> ILU/TPL + silent WAV placeholders)
   [10] Decode pictograms (CKD -> PNG)
   [11] Extract moves + autodance (gesture merge, CKD -> Lua conversion)
   [12] Convert audio (OGG -> 48kHz WAV + intro AMB + AMB audio extraction)
   [13] Copy video (WebM -> target VideosCoach/)
   [14] Register in SkuScene (Actor + CoverflowSong XML injection)
                    |
5. Sync Refinement (interactive adjustment of v_override and a_offset)
                    |
6. Apply & Finish (regenerate configs + audio, save map_config JSON)
```

### Batch Install (Two-Phase)

```
Phase 1 - Download (network-dependent):
  For each map:
    step_01_clean()
    step_02_download()

Phase 2 - Process (local-only):
  For each successfully downloaded map:
    steps 03-14
```

This separation prevents CDN link expiration when installing many maps, since JDHelper auth tokens have a ~30 minute lifetime.

---

## Dual Interface Pattern

Both the GUI and CLI share the same pipeline code. The key differences:

| Aspect | CLI (`map_installer.py`) | GUI (`gui_installer.py`) |
|---|---|---|
| Pipeline execution | Main thread, synchronous | Background `threading.Thread`, async |
| User prompts | `input()` calls | Tkinter dialogs (`messagebox`, `simpledialog`) |
| `_interactive` flag | `True` | `False` (prevents `input()` in pipeline code) |
| Progress feedback | `print()` to terminal | `print()` captured by `StdoutToLogger` -> queue -> `TextWidgetHandler` -> `tk.Text` widget |
| Sync refinement | Text menu loop (`while True`) | GUI panel with increment buttons and embedded preview |
| Preview | `ffmpeg | ffplay` pipe to external window | `ffmpeg` -> raw RGB24 pipe -> PIL -> Tkinter canvas + `ffplay` audio-only |
| Logging setup | `setup_cli_logging()` (console+file) | `setup_gui_logging()` (TextWidgetHandler) + per-install file handler |

### stdout Capture (GUI)

The GUI intercepts `sys.stdout` and `sys.stderr` with `StdoutToLogger`, a file-like wrapper that buffers lines and routes them through the `jd2021.gui` logger. This captures stray `print()` calls from pipeline code and third-party libraries, displaying them in the log text widget.

---

## Logging Architecture

```
jd2021 (root)
├── jd2021.map_installer
├── jd2021.map_builder
├── jd2021.map_downloader
├── jd2021.gui
├── jd2021.ckd_decode
├── jd2021.ipk_unpack
├── jd2021.ubiart_lua
├── jd2021.json_to_lua
├── jd2021.helpers
└── jd2021.batch_install
```

| Mode | Console Handler | File Handler | GUI Handler |
|---|---|---|---|
| CLI | `%(message)s` (plain, matches `print()` style) | `%(asctime)s [%(levelname)-5s] %(name)s: %(message)s` | N/A |
| GUI | N/A | Same detailed format (per-install file) | `%(message)s` -> queue -> `tk.Text` widget (polled every 50ms) |

Log files are written to `logs/install_{map_name}_{timestamp}.log`.

---

## Game Path Discovery

`resolve_game_paths()` (`map_installer.py:263`) locates the JD2021 game data directory through a cascading search:

1. **Cache**: Load from `installer_paths.json` (skipped if `use_cache=False`).
2. **search_root/jd21/**: Classic layout where the project sits beside `jd21/`.
3. **search_root itself**: User pointed directly at the `jd21/` folder.
4. **SCRIPT_DIR/jd21/**: Fallback if `search_root` was wrong but classic layout exists.
5. **Recursive scan**: Walk `search_root` looking for `SkuScene_Maps_PC_All.isc`.

The result is cached to `installer_paths.json` for future runs. The cache is validated by checking that the `SkuScene_Maps_PC_All.isc` file still exists on disk.

---

## Audio Synchronization Model

The engine couples two behaviors to `videoStartTime`:
1. Video seeks to `videoStartTime` seconds at map start.
2. WAV playback is delayed by `abs(videoStartTime)` seconds.

This creates a silence gap of `abs(videoStartTime)` seconds at the start of any map with `videoStartTime < 0`. The pipeline fills this gap with an intro AMB sound that plays from `t=0`.

Two independent sync parameters control timing:

| Parameter | Source | Purpose |
|---|---|---|
| `v_override` | From `videoStartTime` in musictrack CKD | Controls video pre-roll length and WAV delay. |
| `a_offset` | Marker-based calculation (primary) or equals `v_override` (fallback) | Controls OGG trim point for WAV conversion. |

See **[AUDIO_TIMING.md](AUDIO_TIMING.md)** for the full technical explanation.

---

## Key Design Decisions

### Status Override for JD2021 Maps
Maps originally released for JD2021 have `Status = 12` (ObjectiveLocked) in their JDU metadata. The pipeline overrides this to `Status = 3` (Available) during SongDesc generation (`map_builder.py:193`) so maps are immediately playable.

### JDVersion Capping
`JDVersion` and `OriginalJDVersion` are capped to `MAX_JD_VERSION` (2021) to prevent `GameManagerConfig` crashes when installing maps from JD2022+ that reference config entries not present in the 2021 engine.

### Autodance Protection
During sync refinement, `map_builder.generate_text_files()` is re-called to regenerate configs. The `_write_autodance_stubs()` function checks if the autodance TPL is already >1KB (indicating real converted data from Step 11) and skips overwriting it.

### Platform Scene Preference
The downloader and extractor both prefer the DURANGO (Xbox One) scene archive over NX (Switch) and SCARLETT (Xbox Series). This is because DURANGO uses Kinect gesture files that are format-compatible with the PC adapter, while ORBIS (PS4) gesture files use an incompatible format.

### Degenerate TrackId Normalization
When every clip in a tape has a unique TrackId (a sign of bad source data), `ubiart_lua.py` groups clips by `__class` and assigns deterministic shared IDs via `hash(class_name) & 0xFFFFFFFF`. This prevents the engine from creating hundreds of individual tracks.

### SSL Verification Disabled
`map_downloader.py` disables SSL certificate verification globally (`ssl._create_default_https_context = ssl._create_unverified_context`). This is intentional for Ubisoft CDN compatibility - some systems fail to verify the CDN's certificates.
