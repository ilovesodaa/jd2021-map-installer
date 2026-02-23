# Manual Map Porting Guide (Just Dance 2021 PC)

This guide provides a comprehensive technical breakdown of manually porting a Just Dance Unlimited (JDU) map into the Just Dance 2021 PC engine (UbiArt). This process bridges the gap between basic video parsing and a fully integrated, natively-scored level with Autodance and controller tracking.

---

## Table of Contents

1. [Asset Acquisition](#1-asset-acquisition)
2. [Directory Structure](#2-directory-structure)
3. [Understanding File Formats](#3-understanding-file-formats)
4. [Step-by-Step Conversion](#4-step-by-step-conversion)
5. [Critical Timing & Sync](#5-critical-timing--sync)
6. [Game Integration](#6-game-integration)
7. [Troubleshooting Guide](#7-troubleshooting-guide)

---

## 1. Asset Acquisition

Before starting, acquire the following original JDU files (via JDHelper or similar):

| Category | Typical File types | Purpose |
|----------|-------------------|---------|
| **Core Media** | `.ogg`, `.webm` | Gameplay audio and video. |
| **Data IPK** | `*_main_scene_pc.ipk` | Contains timing, choreography, and templates. |
| **Textures** | `.png.ckd`, `.tga.ckd` | Menu art, coach textures, and pictograms. |

---

## 2. Directory Structure

A complete JD2021 map requires the following structure under `World/MAPS/[MapName]/`. **Case sensitivity matters.**

```
[MapName]/
├── [MapName]_MAIN_SCENE.isc    # Root scene linking all sub-scenes
├── SongDesc.tpl                 # Song metadata template
├── SongDesc.act                 # Song metadata actor
│
├── Audio/
│   ├── [MapName].wav            # Full audio (MUST be 48kHz PCM)
│   ├── [MapName].ogg            # Original compressed audio
│   ├── [MapName].trk            # CRITICAL: Beat timing data (Lua)
│   ├── [MapName]_musictrack.tpl # Audio template
│   ├── [MapName]_sequence.tpl   # Sequence template
│   ├── [MapName]_Audio.isc      # Audio scene
│   ├── [MapName].stape          # Sequence tape (required, can be empty)
│   ├── ConfigMusic.sfi          # Audio format declaration (XML)
│   └── AMB/                     # Ambient sound files (if present)
│       ├── set_amb_*.ilu        # Sound descriptors
│       └── set_amb_*.tpl        # Sound actor templates
│
├── Timeline/
│   ├── [MapName]_tml.isc        # Timeline scene
│   ├── [MapName]_TML_Dance.dtape   # Choreography (Lua)
│   ├── [MapName]_TML_Dance.tpl     # Dance tape template
│   ├── [MapName]_TML_Dance.act     # Dance tape actor
│   ├── [MapName]_TML_Karaoke.ktape # Lyrics (Lua)
│   ├── [MapName]_TML_Karaoke.tpl   # Karaoke tape template
│   ├── [MapName]_TML_Karaoke.act   # Karaoke tape actor
│   ├── pictos/
│   │   └── *.png                # Decoded pictogram images
│   └── Moves/
│       └── [PLATFORM]/          # Platform-specific gesture files (.msm, .gesture)
│
├── Cinematics/
│   ├── [MapName]_cine.isc       # Cinematics scene
│   ├── [MapName]_mainsequence.tpl  # Main sequence template
│   ├── [MapName]_mainsequence.act  # Main sequence actor
│   └── [MapName]_MainSequence.tape # Cinematic clips (Lua, may be empty)
│
├── Autodance/
│   ├── [MapName]_autodance.tpl  # Autodance template
│   ├── [MapName]_autodance.act  # Autodance actor
│   └── [MapName]_autodance.isc  # Autodance scene
│
├── VideosCoach/
│   ├── [MapName].webm           # Gameplay video
│   ├── [MapName].mpd            # DASH manifest
│   ├── [MapName]_video.isc      # Video scene
│   └── video_player_main.act    # Video actor
│
└── MenuArt/
    ├── [MapName]_menuart.isc    # Menu art scene with inline components
    ├── Actors/                  # Actor files for menu art
    └── textures/
        └── [MapName]_coach_1.tga # Decoded menu textures
```

---

## 3. Understanding File Formats

### .TRK (Music Track Timing)
Lua-format file defining sample-perfect beat markers.
```lua
structure = { MusicTrackStructure = {
    markers = { { VAL = 0 }, { VAL = 23040 }, ... }, -- Sample positions @ 48kHz
    startBeat = -4,
    endBeat = 500,
    videoStartTime = -1.901000, -- Seconds before beat 0
    previewEntry = 84.0,
}}
```

### .ISC (Scene Graph)
XML files defining which actors to load. The `MAIN_SCENE.isc` must have `ENGINE_VERSION="280000"`.

### .DTAPE / .KTAPE (Choreography)
Lua tables containing timed events (Clips) defined in **ticks** (24 ticks per beat).

---

## 4. Step-by-Step Conversion

### 4.1 Extract Original Timing
Open the JDU `musictrack.tpl.ckd` with a text editor. Even with the `.ckd` extension, it is often plaintext JSON. Extract `markers`, `videoStartTime`, and `startBeat`.

### 4.2 Convert Audio (High Precision)
Use FFmpeg to convert your OGG to WAV. You **must** force 48kHz:
```bash
ffmpeg -i input.ogg -ar 48000 output.wav
```
If the sample rate isn't exactly 48,000Hz, the `.trk` markers will drift, causing massive desync.

### 4.3 Decode Textures
UbiArt CKD textures have a 44-byte binary header followed by a DDS or XTX payload.
1. Strip the header.
2. Convert DDS/XTX to TGA or PNG (using Pillow or XTX-Extractor).
3. Place in the `MenuArt/textures/` or `Timeline/pictos/` directories.

### 4.4 Convert JSON Tapes to Lua
JDU uses JSON natively, but JD2021 PC expects Lua. The conversion involves both syntax transformation and UbiArt-specific data processing:

**Syntax changes:**
- Replace `[...]` with `{ ... }`
- Replace `"key":` with `key =`
- Booleans must be lowercase: `true` / `false`
- Floats should use 6 decimal places for consistency (e.g., `0.300000`)
- Strings must escape `"`, `\n`, and `\r`

**UbiArt-specific processing (handled by `ubiart_lua.py`):**
- **MotionClip Color**: Convert `[a, r, g, b]` float arrays to hex strings (e.g., `"0x0e8cd3ff"`)
- **MotionPlatformSpecifics**: Convert platform dict to KEY/VAL array format
- **Tracks array**: Build `Tracks = { {TapeTrack = {id = X}}, ... }` from unique TrackIds across all clips
- **Degenerate TrackId normalization**: When every clip has a unique ID (bad data), group by clip class and assign shared deterministic IDs
- **Primitive arrays**: Must be wrapped as `{ {VAL = 1}, {VAL = 2} }` to prevent engine crashes

### 4.5 Convert Cinematic Tapes
If the extracted IPK contains files in a `cinematics/` folder (e.g., `*_mainsequence.tape.ckd`), convert them with additional processing:

- **Curve data**: Cinematic clips (AlphaClip, RotationClip, TranslationClip, SizeClip, ScaleClip, ColorClip, etc.) contain curve keyframes where `[x, y]` arrays must be emitted as `vector2dNew(x, y)` in Lua
- **ActorIndices resolution**: Clips reference actors by index; these must be dereferenced against the tape's top-level `ActorPaths` array and replaced with resolved path strings
- If no cinematic tapes exist, keep the empty fallback tape generated by `map_builder.py`

### 4.6 Process Ambient Sounds
If the extracted IPK has files in an `audio/amb/` folder (e.g., `set_amb_*.tpl.ckd`), process each into two files:
- `.ilu` (sound descriptor): Contains the sound list data as Lua with an `appendTable` call
- `.tpl` (actor template): Wrapper that includes the SoundComponent and references the `.ilu` file

---

## 5. Critical Timing & Sync

### The Timing Chain
The engine resolves timing in this order:
1. **Audio Position** (Sample #) -> **Beat Number** (via `.trk` markers).
2. **Beat Number** -> **Tick Number** (24 ticks per beat).
3. **Tick Number** -> **Clip Execution** (via Tape files).

### Video Start Time
The `videoStartTime` is usually negative (e.g., `-1.901`). This means the video begins ~1.9 seconds before beat 0. **Do not calculate this synthetically**; extract the exact value from the original JDU metadata.

---

## 6. Game Integration

1. **Deployment**: Copy your `[MapName]` folder to `jd21/data/World/MAPS/`.
2. **Registration**: 
   - Open `SkuScene_Maps_PC_All.isc`.
   - Add a `JD_SongDescTemplate` entry referencing your map's `SongDesc.tpl`.
3. **Validation**: Launch the game; if the title is missing, check your `SongDesc` actor configuration.

---

## 7. Troubleshooting Guide

| Issue | Root Cause | Fix |
|-------|------------|-----|
| **Crash at Coach Select** | Missing Cinematics chain | Create `_cine.isc` -> `_MainSequence.tpl` structure. |
| **Progressive Desync** | Wrong Audio Sample Rate | Re-convert audio with `-ar 48000`. |
| **Black Video** | Incorrect DASH MPD | Ensure namespace is `urn:mpeg:DASH:schema:MPD:2011`. |
| **Missing Title** | SkuScene Registration | Verify the map entry in `SkuScene_Maps_PC_All.isc`. |
| **Autodance Error** | Component Naming | Ensure component name is `JD_AutodanceComponent`. |

---
*For automated conversion, refer to the root `README.md` and the `map_installer.py` script. The automation suite now includes auto-detection of the `jd2021` directory and automatic path normalization to prevent common syntax errors.*

## Appendix A — Batch Preperation (assets.html + nohud.html)

If you plan to convert many maps, prepare a single parent directory where each child's folder contains the two HTML exports (`assets.html` and `nohud.html`) captured from JDHelper. The `batch_install_maps.py` script will scan this directory and launch an installer for each valid map folder.

Example layout:

```
my_maps/
    BadRomance/
        assets.html
        nohud.html
    Starships/
        assets.html
        nohud.html
```

To run the batch installer:

```bash
python batch_install_maps.py "C:\path\to\my_maps"
```

If the script cannot find your JD installation automatically it will prompt you to input the path (or you can pass `--jd21-path`).

### Verifying `SongDesc.tpl` DefaultColors

After installation, open `jd21/data/World/MAPS/<MapName>/SongDesc.tpl` and look for the `DefaultColors` block. All color keys present in the original JDU metadata (`lyrics`, `theme`, `songcolor_1a`, `songcolor_1b`, `songcolor_2a`, `songcolor_2b`, and any extras) are extracted and converted to hex. The pipeline uses case-insensitive key matching, so CKD keys like `songcolor_1a` correctly map to fallback `songColor_1A` without creating duplicates.

Example snippet:

```
DefaultColors =
{
    { KEY = "lyrics", VAL = "0x2e3fffff" },
    { KEY = "theme", VAL = "0xFFFFFFFF" },
    { KEY = "songcolor_1a", VAL = "0xFF0BC7FF" },
    { KEY = "songcolor_1b", VAL = "0xFF000000" },
    ...
}
```

If a color key is absent from the CKD, the pipeline uses a hardcoded fallback value.

### Troubleshooting batch runs

- If terminals open but installers do nothing, confirm that each map folder contains both required HTML files.
- If `map_installer.py` cannot find `map_builder.py` or other modules, run the batch script from the project root or pass `--jd21-path` pointing to `d:\jd2021pc\jd21`.
