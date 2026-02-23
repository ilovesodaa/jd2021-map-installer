# Just Dance 2021 (PC Dev Build) — JDU Map Conversion Guide

## About the Source Files: JDHelper by rama

All original Just Dance Unlimited (JDU) files referenced in this guide are sourced using the JDHelper bot, created by rama. JDHelper allows you to download original JDU map files, which are essential for accurate conversions and modding.

**How to Access JDHelper:**
- Join the JDHelper Discord: https://discord.gg/DFzgkpWWkX
- Or invite the bot to your own server: https://top.gg/bot/755796344865685625

You must use JDHelper to obtain the original JDU files (audio, video, CKD, pictograms, etc.) before running the conversion scripts described in this guide.

## Converting "Starships" from Just Dance Unlimited to JD2021

This document covers every step of converting a Just Dance Unlimited (JDU) map into a playable map for the Just Dance 2021 PC development build (UbiArt engine). It uses **Starships** (Nicki Minaj, originally JD2014) as the case study, with **GetGetDown** as the working reference map.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Acquiring JDU Files](#2-acquiring-jdu-files)
3. [Understanding the File Formats](#3-understanding-the-file-formats)
4. [Understanding JD2021 Map Structure](#4-understanding-jd2021-map-structure)
5. [Build Pipeline Overview](#5-build-pipeline-overview)
6. [Step-by-Step Manual Conversion](#6-step-by-step-manual-conversion)
7. [Critical Timing Parameters](#7-critical-timing-parameters)
8. [Troubleshooting Guide](#8-troubleshooting-guide)
9. [File Reference Table](#9-file-reference-table)
10. [Tools Reference](#10-tools-reference)

---

## 1. Prerequisites

### Software Required

| Tool | Purpose |
|------|---------|
| **Python 3.10+** | Running build scripts |
| **Pillow** (`pip install Pillow`) | CKD texture decoding (DDS → PNG/TGA) |
| **ffmpeg** (in PATH) | OGG → WAV audio conversion |
| **Git + GitHub CLI** (optional) | Version control |
| **JD2021 PC Dev Build** | The target engine (`jd21/` directory) |

### Directory Structure

```
d:\jd2021pc\
├── build_starships.bat          # Master build script
├── build_starships_fix.py       # Config file generator
├── restore_starships_media.py   # Media file copier + audio converter
├── ckd_decode.py                # CKD texture decoder
├── json_to_lua.py               # JSON→Lua tape converter
├── make_dummy_pictos.py         # Placeholder picto generator (fallback)
├── inspect_ckd.py               # CKD header inspector
├── Starships/                   # Source JDU files
│   ├── *.ckd, *.webm, *.ogg    # Hash-named downloaded assets
│   ├── decoded/                 # Decoded menu art TGAs
│   └── ipk_extracted/           # Extracted IPK contents
├── jd21/                        # JD2021 game installation
│   └── data/World/MAPS/
│       ├── GetGetDown/          # Working reference map
│       └── Starships/           # Target output
├── JustDanceTools/              # Community conversion tools
├── XTX-Extractor/               # Nintendo Switch texture tools
└── ubiart-archive-tools/        # IPK pack/unpack tools
```

---

## 2. Acquiring JDU Files

### Step 1: Download from JD Unlimited Servers

JDU maps are downloaded as individual files with **hash-based filenames** (no extensions hint at content type). The download mapping links hash names to their actual purpose. For Starships, the key downloaded files are:

| Hash Filename | Actual Content | Size |
|---------------|---------------|------|
| `0ac1f08ec9cd2070cb1f70295661efa3.webm` | Coach gameplay video (VP9, 1080p) | ~50MB |
| `67913811d9fdd089443181e2672b619e.webm` | Map preview video (VP9) | ~5MB |
| `80f47be6f8293430ae764027a56847a4.ogg` | Full song audio (OGG Vorbis) | ~5MB |
| `b6ea5be7d5e70cda982f9d35fb6bfeba.ogg` | Audio preview clip | ~1MB |
| `dbe3c08891c1859cc22bd27c962e2268.ckd` | Coach texture (CKD/DDS) | ~1MB |
| `8c69e5b8d670d7f19880388e995ff064.ckd` | Cover generic texture | ~300KB |
| `86e08b8e5c89f8389db5723f136b81d7.ckd` | Cover online texture | ~300KB |
| `7285efe8d585ac76b882c2115989a4f8.ckd` | Album background texture | ~300KB |
| `370d94f300a9f5c48d372f3fad0cec8e.ckd` | Album coach texture | ~300KB |
| `440d6ce474051538b9d98b0d0dab2341.ckd` | Map background texture | ~300KB |
| `650d843e8d21e55a4cd58a17d6588005.ckd` | Banner background texture | ~300KB |
| `6d162ce9e558fb6d4059e9d383112398.jpg` | Phone cover image | ~50KB |
| `f62544a48195680424c3b82c4059057d.png` | Phone coach image | ~50KB |
| `361e165f9e893979b0aff0de0a89ade8.png` | 1024px cover image | ~200KB |

These files are placed in `Starships/` with their original hash filenames.

### Step 2: Download and Extract the IPK

The IPK file contains the "cooked" game data (choreography, timing, templates, pictograms). For Starships, the relevant IPK is `starships_main_scene_pc.ipk` found in one of the hash-named folders (e.g., `264daae6ae9cf87fd1971ecf2a7706fa/`).

**Extract using `ubiart-archive-tools`:**
```bash
python ipk_unpacker.py <path_to_ipk>
```

This produces `ipk_extracted/` with structure:
```
ipk_extracted/
├── cache/itf_cooked/pc/world/maps/starships/
│   ├── songdesc.act.ckd           # Song description actor
│   ├── songdesc.tpl.ckd           # Song description template (JSON!)
│   ├── starships_main_scene.isc.ckd
│   ├── audio/
│   │   ├── starships_musictrack.tpl.ckd  # CRITICAL: Timing data (JSON!)
│   │   └── starships_audio.isc.ckd
│   ├── cinematics/
│   │   ├── starships_mainsequence.tape.ckd
│   │   └── ...
│   ├── timeline/
│   │   ├── starships_tml_dance.dtape.ckd   # Choreography (JSON!)
│   │   ├── starships_tml_karaoke.ktape.ckd # Lyrics (JSON!)
│   │   └── pictos/
│   │       └── *.png.ckd           # 42 pictogram textures
│   └── videoscoach/
│       └── ...
└── world/maps/starships/
    ├── autodance/                   # Autodance audio (not needed)
    └── timeline/moves/             # Motion data (.msm, .gesture)
        ├── pc/*.msm
        └── durango/*.gesture
```

### Critical Discovery: Some CKD Files Are Already Plaintext JSON

Despite the `.ckd` extension, several files in the IPK extraction are **already plaintext JSON**, not binary:

- `starships_musictrack.tpl.ckd` — Contains all timing data (BPM, markers, videoStartTime)
- `starships_tml_dance.dtape.ckd` — Full choreography data
- `starships_tml_karaoke.ktape.ckd` — Karaoke lyrics and timing
- `songdesc.tpl.ckd` — Song metadata

**Only texture CKDs** (`.png.ckd`, menu art `.ckd`) are true binary files requiring `ckd_decode.py`.

> **Important:** These JSON CKD files may have a trailing `\x00` null byte. Strip it before parsing with `json.loads(data.strip('\x00'))`.

---

## 3. Understanding the File Formats

### CKD (Cooked Data)

Binary container format used by UbiArt engine. Structure:
- **Bytes 0-3:** Magic `\x00\x00\x00\x09`
- **Bytes 4-6:** Type marker (e.g., `TEX` for textures)
- **Bytes 7-43:** Additional header data
- **Byte 44+:** Payload (DDS texture data for PC, XTX for Nintendo Switch)

Only **texture CKDs** have this binary format. Template/tape CKDs from PC IPKs are often plaintext JSON.

### TRK (Music Track Timing)

Lua-format file defining beat markers (audio sample positions), song sections, and playback parameters. Generated from the musictrack template data.

Key fields:
```lua
structure = { MusicTrackStructure = {
    markers = { { VAL = 0 }, { VAL = 23040 }, ... },  -- Sample positions per beat
    signatures = { { MusicSignature = { beats = 4, marker = 0 } } },
    sections = { ... },  -- Song structure (intro, verse, chorus, etc.)
    startBeat = -4,       -- Pre-roll beats before beat 0
    endBeat = 449,        -- Last beat
    videoStartTime = -1.901000,  -- Seconds before beat 0 when video starts
    previewEntry = 84.0,  -- Beat to start song preview
    previewLoopStart = 84.0,
    previewLoopEnd = 244.0,
    volume = 0.000000,    -- Volume adjustment
    -- fade parameters...
}}
```

**The markers array is the most critical timing data.** Each value is the audio sample position (at 48kHz) where that beat occurs. The engine uses this to synchronize everything: video, choreography, karaoke, scoring.

### TPL/ACT (Template/Actor)

Lua-format files defining game objects:
- **TPL** = Template (class definition, references other files)
- **ACT** = Actor (instance with specific parameter values)

### ISC (Scene)

XML files defining scene graphs — which actors to load and how they relate.

### DTAPE/KTAPE (Dance/Karaoke Tapes)

Lua-format choreography data containing timed clips:
- **DTAPE** — `MotionClip` (body moves), `PictogramClip` (picto display), `GoldEffectClip` (gold moves)
- **KTAPE** — `KaraokeClip` (lyric display with pitch data)

`StartTime` values are in **ticks** (24 ticks per beat).

### MPD (DASH Video Manifest)

XML manifest for adaptive video streaming. The JD2021 engine uses DASH to select video quality. Key requirement:
- Namespace must be `urn:mpeg:DASH:schema:MPD:2011` (capital letters!)
- Profile must be `urn:webm:dash:profile:webm-on-demand:2012`
- BaseURL should use `jmcs://jd-contents/` scheme (forces engine fallback to direct `.webm` path)

### SFI (Sound Format Info)

XML file declaring audio format for the engine:
```xml
<SoundFormatInfo Format="PCM" IsStreamed="1" IsMusic="1" Platform="PC" />
```

---

## 4. Understanding JD2021 Map Structure

A complete JD2021 map requires the following directory structure under `World/MAPS/<MapName>/`:

```
Starships/
├── Starships_MAIN_SCENE.isc    # Root scene (links all sub-scenes)
├── SongDesc.tpl                 # Song metadata template
├── SongDesc.act                 # Song metadata actor
│
├── Audio/
│   ├── Starships.wav            # Full song audio (48kHz PCM)
│   ├── Starships.ogg            # Original compressed audio
│   ├── Starships.trk            # Beat timing data
│   ├── Starships_musictrack.tpl # Audio template (references .trk)
│   ├── Starships_Audio.isc      # Audio scene
│   ├── Starships.stape          # Sequence tape (empty)
│   ├── Starships_AudioPreview.ogg
│   ├── Starships_AudioPreview.wav
│   └── ConfigMusic.sfi          # Audio format declaration
│
├── Cinematics/
│   ├── Starships_cine.isc       # Cinematics scene
│   ├── Starships_MainSequence.tpl
│   ├── Starships_MainSequence.act
│   └── Starships_MainSequence.tape  # Empty (no ambient audio)
│
├── Timeline/
│   ├── Starships_tml.isc        # Timeline scene
│   ├── Starships_TML_Dance.tpl
│   ├── Starships_TML_Dance.act
│   ├── Starships_TML_Dance.dtape  # Choreography (Lua format)
│   ├── Starships_TML_Karaoke.tpl
│   ├── Starships_TML_Karaoke.act
│   ├── Starships_TML_Karaoke.ktape # Lyrics (Lua format)
│   └── pictos/
│       └── *.png                # 42 pictogram images (512x512)
│
├── VideosCoach/
│   ├── Starships.webm           # Coach gameplay video
│   ├── Starships.mpd            # DASH manifest (main)
│   ├── Starships_MapPreview.webm # Preview video (may not be used)
│   ├── Starships_MapPreview.mpd  # Preview DASH manifest
│   ├── Starships_video.isc      # Video scene
│   ├── Starships_video_map_preview.isc
│   ├── video_player_main.act    # Main video actor
│   └── video_player_map_preview.act # Preview video actor
│
└── MenuArt/
    ├── Starships_menuart.isc    # Menu art scene
    ├── Actors/
    │   ├── Starships_coach_1.act
    │   ├── Starships_cover_generic.act
    │   ├── Starships_cover_online.act
    │   ├── Starships_cover_albumbkg.act
    │   ├── Starships_cover_albumcoach.act
    │   ├── Starships_map_bkg.act
    │   └── Starships_banner_bkg.act
    └── textures/
        ├── Starships_coach_1.tga
        ├── Starships_cover_generic.tga
        ├── Starships_cover_online.tga
        ├── Starships_cover_albumbkg.tga
        ├── Starships_cover_albumcoach.tga
        ├── Starships_map_bkg.tga
        ├── Starships_banner_bkg.tga
        ├── Starships_Cover_Phone.jpg
        ├── Starships_Coach_1_Phone.png
        └── Starships_Cover_1024.png
```

### MAIN_SCENE.isc — The Root Scene

This is the entry point. It must contain:
1. `ENGINE_VERSION = 280000` (JD2021 engine version)
2. `JD_MapSceneConfig` actor with map name and sound context
3. Inline `SongDesc` actor
4. `SubSceneActor` entries linking to: Audio, Cinematics, Timeline, Video, Video Preview, and MenuArt ISCs

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
<Scene ENGINE_VERSION="280000" GRIDUNIT="0.5">
    <!-- SongDesc inline actor -->
    <Actor ... INSTANCEDATAFILE="World/MAPS/Starships/SongDesc.act" LUA="World/MAPS/Starships/SongDesc.tpl">
        <parentBind />
        <MARKERS />
    </Actor>
    
    <!-- Map config -->
    <Actor USERFRIENDLY="JD_MapSceneConfig">
        <COMPONENTS>
            <JD_MapSceneConfig MapName="Starships" SoundContext="Starships" ... />
        </COMPONENTS>
    </Actor>
    
    <!-- Sub-scenes -->
    <SubSceneActor USERFRIENDLY="Audio" INSTANCEDATAFILE="..." />
    <SubSceneActor USERFRIENDLY="Cinematics" INSTANCEDATAFILE="..." />
    <SubSceneActor USERFRIENDLY="Timeline" INSTANCEDATAFILE="..." />
    <SubSceneActor USERFRIENDLY="Video" INSTANCEDATAFILE="..." />
    <SubSceneActor USERFRIENDLY="VideoScreenPreview" ... />
    <SubSceneActor USERFRIENDLY="MenuArt" INSTANCEDATAFILE="..." />
</Scene>
</root>
```

### Key Structural Differences from JDU

| Aspect | JDU (Starships) | JD2021 (Required) |
|--------|-----------------|---------------------|
| Main Scene | Malformed XML with JSON fragments | Clean XML with SubSceneActors |
| Cinematics | Minimal/missing | Full chain: ISC → TPL → ACT → TAPE |
| Audio ISC | MusicTrack only | MusicTrack + Sequence actors |
| MenuArt ISC | Simple actor references | Full inline MaterialGraphicComponent |
| ConfigMusic.sfi | Missing | Required (declares PCM/Streamed) |
| Audio .stape | Missing | Required (even if empty) |
| MusicTrack URL | `jmcs://jd-contents/...` | Same (preserved) |
| Video channelID | Integer `1` | String `"Starships"` |
| Path casing | `world/maps/starships/` | `World/MAPS/Starships/` |

---

## 5. Build Pipeline Overview

The automated build (`build_starships.bat`) runs these steps:

| Step | Script | What It Does |
|------|--------|--------------|
| **[1]** | `build_starships.bat` | Deletes old Map and Cache directories |
| **[2]** | `build_starships_fix.py` | Generates ~30 config files (ISC, TPL, ACT, TRK, MPD, SFI, TAPE) |
| **[3]** | `restore_starships_media.py` | Copies hash-named files to correct paths, converts OGG→WAV at 48kHz |
| **[4]** | `ckd_decode.py --batch` | Decodes MenuArt CKD textures (DDS→TGA) |
| **[5]** | `json_to_lua.py` (×2) | Converts dtape and ktape from JSON to Lua format |
| **[6]** | `ckd_decode.py` (×42) | Decodes pictogram CKD textures (DDS→PNG) |

---

## 6. Step-by-Step Manual Conversion

If you want to do this manually instead of using the scripts:

### 6.1 Extract Original Timing Data

The most critical step. Open `ipk_extracted/cache/itf_cooked/pc/world/maps/starships/audio/starships_musictrack.tpl.ckd` in a text editor — it's JSON despite the `.ckd` extension.

Extract these values:

```json
{
    "startBeat": -4,
    "endBeat": 449,
    "videoStartTime": -1.901000,
    "previewEntry": 84,
    "previewLoopStart": 84,
    "previewLoopEnd": 244,
    "volume": 0,
    "markers": [0, 23040, 46080, ...],  // 450 values
    "sections": [
        {"marker": 0, "sectionType": 0},
        {"marker": 20, "sectionType": 1},
        // ... 15 sections total
    ]
}
```

**WARNING:** Using synthetic values (e.g., computing markers as `i * 23040`) will mostly work, but the original markers have ±1 sample rounding that matters for tight sync. Always use the original data.

### 6.2 Create .trk File

Convert the JSON markers to Lua format:

```lua
structure = { MusicTrackStructure = { markers = { { VAL = 0 }, { VAL = 23040 }, { VAL = 46080 }, ... }, signatures = { { MusicSignature = { beats = 4, marker = 0 } } }, sections = { { MusicSection = { sectionType = 0, marker = 0 } }, { MusicSection = { sectionType = 1, marker = 20 } }, ... }, startBeat = -4, endBeat = 449, fadeStartBeat = 0, useFadeStartBeat = 0, fadeEndBeat = 0, useFadeEndBeat = 0, videoStartTime = -1.901000, previewEntry = 84.0, previewLoopStart = 84.0, previewLoopEnd = 244.0, volume = 0.000000, fadeInDuration = 0, fadeInType = 0, fadeOutDuration = 0, fadeOutType = 0, entryPoints = { } } }
```

`videoStartTime` is the number of seconds **before beat 0** that the video starts playing. It's negative because beat 0 happens *after* the video begins. This is the single most important sync parameter.

### 6.3 Convert Audio

```bash
ffmpeg -y -i Starships.ogg -ar 48000 Starships.wav
```

**The `-ar 48000` flag is mandatory.** The .trk markers are sample positions calibrated for 48kHz audio. If the OGG happens to be 44.1kHz, the WAV will also be 44.1kHz without explicit resampling, and every beat marker will point to the wrong sample — audio will be ~8.8% too slow, causing catastrophic desync by the end of the song.

### 6.4 Convert Choreography Tapes (JSON → Lua)

The dtape and ktape files from the IPK are JSON but the JD2021 engine expects Lua format. Use `json_to_lua.py`:

```bash
python json_to_lua.py <input.dtape.ckd> <output.dtape>
python json_to_lua.py <input.ktape.ckd> <output.ktape>
```

This converts JSON syntax to Lua syntax:
- `"key":` → `key =`
- `[...]` → `{ ... }`
- `true/false` → `TRUE/FALSE`
- `null` → `nil`

### 6.5 Decode Textures

**Menu Art** (7 files):
```bash
python ckd_decode.py --batch <MenuArt/textures/> <MenuArt/textures/>
```
Input: `*.tga.ckd` → Output: `*.tga` (strips CKD header, converts DDS→TGA)

**Pictograms** (42 files):
```bash
python ckd_decode.py <picto.png.ckd> <output.png>
```
Input: `*.png.ckd` → Output: `*.png` (512×512 PNG)

The CKD decoder:
1. Validates magic bytes (`\x00\x00\x00\x09` + `TEX`)
2. Strips 44-byte header
3. Detects payload format (DDS for PC, XTX for Nintendo Switch)
4. Converts to output format via Pillow

### 6.6 Create the MAIN_SCENE.isc

This is the most complex manually-created file. It must link all sub-scenes and contain the SongDesc inline actor and JD_MapSceneConfig. See the code in `build_starships_fix.py` for the exact template — it's ~50 lines of XML.

Key requirements:
- `ENGINE_VERSION="280000"` on the Scene element
- Inline `SongDesc.act` actor with LUA reference to `SongDesc.tpl`
- JD_MapSceneConfig with `MapName="Starships"` and `SoundContext="Starships"`
- Six SubSceneActors for Audio, Cinematics, Timeline, Video, VideoPreview, MenuArt

### 6.7 Create the Cinematics Chain

Even though Starships has no ambient audio effects, the cinematics infrastructure is required:

1. `Starships_cine.isc` — Scene with one actor loading MainSequence
2. `Starships_MainSequence.tpl` — Template for MasterTape
3. `Starships_MainSequence.act` — Actor for MasterTape
4. `Starships_MainSequence.tape` — Empty tape (no clips)

### 6.8 Create Video MPD Manifests

The MPD must use the correct namespace and profile for the engine to parse it:

```xml
<?xml version="1.0"?>
<MPD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns="urn:mpeg:DASH:schema:MPD:2011"
     xsi:schemaLocation="urn:mpeg:DASH:schema:MPD:2011"
     type="static"
     mediaPresentationDuration="PT230S"
     minBufferTime="PT1S"
     profiles="urn:webm:dash:profile:webm-on-demand:2012">
  <Period id="0" start="PT0S" duration="PT230S">
    <AdaptationSet id="0" mimeType="video/webm" codecs="vp9" lang="eng"
                   maxWidth="1920" maxHeight="1080"
                   subsegmentAlignment="true" subsegmentStartsWithSAP="1"
                   bitstreamSwitching="true">
      <Representation id="0" bandwidth="4000000">
        <BaseURL>jmcs://jd-contents/Starships/Starships.webm</BaseURL>
        <SegmentBase indexRange="0-1000">
          <Initialization range="0-500" />
        </SegmentBase>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
```

**Why `jmcs://` URLs?** The engine tries DASH adaptive streaming first. The `jmcs://` scheme can't be resolved locally, so the engine falls back to the direct `.webm` path from the video actor file — which works for local playback.

### 6.9 Video Preview Setup

**Critical finding:** The preview video actor should point to the **main** video file, not a separate preview file. This matches how GetGetDown works:

```lua
-- video_player_map_preview.act
Video = "World/MAPS/Starships/videoscoach/Starships.webm",   -- MAIN video
dashMPD = "World/MAPS/Starships/videoscoach/Starships.mpd",  -- MAIN MPD
channelID = "Starships",
```

The `previewEntry`, `previewLoopStart`, and `previewLoopEnd` fields in the .trk control which portion of the video plays as a preview. The engine uses the main video file and seeks to the preview section.

### 6.10 Create MenuArt ISC with Inline Components

The MenuArt ISC requires full inline `MaterialGraphicComponent` definitions (not just actor references). Each texture actor needs:

```xml
<Actor USERFRIENDLY="Starships_coach_1" INSTANCEDATAFILE="..." LUA="...">
    <parentBind />
    <MARKERS />
    <COMPONENTS>
        <MaterialGraphicComponent ... >
            <material GFX_MAT_CAP="...texture path..." />
        </MaterialGraphicComponent>
    </COMPONENTS>
</Actor>
```

### 6.11 Create Supporting Files

Several small files are needed:

**ConfigMusic.sfi** (audio format declaration):
```xml
<SoundFormatInfos>
    <SoundFormatInfo Format="PCM" IsStreamed="1" IsMusic="1" Platform="PC" />
</SoundFormatInfos>
```

**Starships.stape** (empty sequence tape):
```lua
Clips = {
},
TapeClock = 0,
MapName = "Starships",
```

**Starships_musictrack.tpl** (audio template):
```lua
includeReference("World/MAPS/Starships/audio/Starships.trk")
params = {
    NAME = "Actor_Template",
    Actor_Template = {
        COMPONENTS = {{
            NAME = "MusicTrackComponent_Template",
            MusicTrackComponent_Template = {
                playAudioOnStart = true,
                path = "World/MAPS/Starships/audio/Starships.wav",
                url = "jmcs://jd-contents/Starships/Starships.ogg",
            },
        }},
    },
}
```

---

## 7. Critical Timing Parameters

### The Timing Chain

```
.trk markers (sample positions)
    ↓
Beat timeline (marker index = beat number)
    ↓
Tick timeline (24 ticks per beat)
    ↓
Tape clips (StartTime in ticks)
    ↓
MotionClip, PictogramClip, KaraokeClip, GoldEffectClip
```

### Parameter Summary for Starships

| Parameter | Value | Meaning |
|-----------|-------|---------|
| BPM | 125 | Beats per minute |
| Sample rate | 48,000 Hz | Audio sample rate |
| Samples/beat | 23,040 | Beat duration in samples |
| Beat duration | 0.48 seconds | Beat duration in time |
| Ticks/beat | 24 | Choreography resolution |
| `startBeat` | -4 | Pre-roll beats before beat 0 |
| `endBeat` | 449 | Last beat of the song |
| `videoStartTime` | -1.901 seconds | When video starts relative to beat 0 |
| `previewEntry` | Beat 84 | Preview starts (~40.3 seconds in) |
| `previewLoopEnd` | Beat 244 | Preview ends (~117.1 seconds in) |
| Total markers | 450 | Beats 0-449 |
| Total sections | 15 | Song structure markers |
| Max dtape tick | 10,464 | Last choreography event (beat 436) |

### Why Audio Sync Matters

The .trk markers are **audio sample positions**. Marker 0 = sample 0, Marker 1 = sample 23040, etc. These tell the engine: "beat N happens at sample position X in the .wav file."

If the .wav has the wrong sample rate:
- At 48kHz: marker 23040 = 0.480 seconds ✓ (correct)
- At 44.1kHz: marker 23040 = 0.522 seconds ✗ (8.8% drift per beat!)

By beat 449, the cumulative drift would be ~19 seconds. **Always convert with `-ar 48000`.**

### Why `videoStartTime` Matters

This value (-1.901 for Starships) tells the engine to start the video 1.901 seconds before beat 0. If wrong:
- Too negative (e.g., -2.88): Video starts ~1 second too early, visuals lead audio
- Not negative enough (e.g., -1.0): Video starts late, visuals lag behind audio

The original value from `starships_musictrack.tpl.ckd` must be used — computing it from `startBeat × beat_duration` gives the wrong answer because the video's leading content doesn't follow an exact beat alignment.

---

## 8. Troubleshooting Guide

### Problem: Game crashes at coach select
**Cause:** Missing Cinematics infrastructure (ISC, TPL, ACT, TAPE).
**Fix:** Create the complete Cinematics chain even if the tape is empty.

### Problem: Cover art doesn't show on first boot
**Cause:** Engine caches texture data. The TGA files from CKD decoding may not be picked up until second launch.
**Fix:** Start the game twice. This is normal behavior.

### Problem: Audio plays but video is black
**Cause:** MPD manifest has wrong namespace/profile, or uses relative URLs with fake byte ranges.
**Fix:** Use `urn:mpeg:DASH:schema:MPD:2011` namespace (capital letters), `urn:webm:dash:profile:webm-on-demand:2012` profile, and `jmcs://` BaseURLs.

### Problem: Song ends too early (cuts off before 2nd chorus)
**Cause:** `endBeat` in .trk is too low. The engine stops playback when it reaches `endBeat`.
**Fix:** Use the original `endBeat` value from `starships_musictrack.tpl.ckd` (449 for Starships).

### Problem: Video/scoring/karaoke in sync but audio is off
**Cause:** WAV file not at 48kHz. The .trk markers are sample positions calibrated for 48kHz.
**Fix:** Re-convert with `ffmpeg -y -i input.ogg -ar 48000 output.wav`.

### Problem: Video plays too early/late relative to audio
**Cause:** Wrong `videoStartTime` in .trk.
**Fix:** Use the original value from `starships_musictrack.tpl.ckd` (-1.901000 for Starships).

### Problem: Video preview shows black (only audio plays)
**Cause:** Preview video actor points to a separate preview file instead of the main video. The engine uses `previewEntry`/`previewLoopStart`/`previewLoopEnd` from the .trk to select the preview portion of the main video.
**Fix:** Point `video_player_map_preview.act` to the main `.webm` and `.mpd` files.

### Problem: Pictograms are missing/transparent
**Cause:** Using dummy 1×1 placeholder PNGs instead of real decoded textures.
**Fix:** Decode the 42 `.png.ckd` files from `ipk_extracted/timeline/pictos/` using `ckd_decode.py`.

### Problem: Karaoke timing is off
**Cause:** Using synthetic .trk markers instead of original data, or wrong `startBeat`.
**Fix:** Use the exact original markers and `startBeat` from `starships_musictrack.tpl.ckd`.

### Problem: Gold moves not scoring correctly
**Cause:** Same timing root cause as karaoke — synthetic vs. original markers.
**Fix:** Same as above.

---

## 9. File Reference Table

### Generated by `build_starships_fix.py` (~30 files)

| File | Purpose | Source of Data |
|------|---------|---------------|
| `Audio/Starships.trk` | Beat timing | `starships_musictrack.tpl.ckd` (JSON) |
| `Audio/Starships_musictrack.tpl` | Audio template | Generated (references .trk + .wav) |
| `Audio/Starships_Audio.isc` | Audio scene | Generated (template from GetGetDown) |
| `Audio/ConfigMusic.sfi` | Audio format | Generated (PCM/Streamed/Music) |
| `Audio/Starships.stape` | Empty sequence tape | Generated |
| `SongDesc.tpl` | Song metadata | Generated (hardcoded values + JDVersion) |
| `SongDesc.act` | Song metadata actor | Generated |
| `Starships_MAIN_SCENE.isc` | Root scene | Generated (links all sub-scenes) |
| `Cinematics/Starships_cine.isc` | Cinematics scene | Generated |
| `Cinematics/Starships_MainSequence.tpl` | Cinematics template | Generated |
| `Cinematics/Starships_MainSequence.act` | Cinematics actor | Generated |
| `Cinematics/Starships_MainSequence.tape` | Empty cinematics tape | Generated |
| `Timeline/Starships_tml.isc` | Timeline scene | Generated |
| `Timeline/Starships_TML_Dance.tpl` | Dance template | Generated |
| `Timeline/Starships_TML_Dance.act` | Dance actor | Generated |
| `Timeline/Starships_TML_Karaoke.tpl` | Karaoke template | Generated |
| `Timeline/Starships_TML_Karaoke.act` | Karaoke actor | Generated |
| `VideosCoach/Starships.mpd` | Main video DASH manifest | Generated |
| `VideosCoach/Starships_MapPreview.mpd` | Preview DASH manifest | Generated |
| `VideosCoach/video_player_main.act` | Main video actor | Generated |
| `VideosCoach/video_player_map_preview.act` | Preview video actor | Generated (→ main video) |
| `VideosCoach/Starships_video.isc` | Video scene | Generated |
| `VideosCoach/Starships_video_map_preview.isc` | Preview scene | Generated |
| `MenuArt/Starships_menuart.isc` | Menu art scene | Generated (inline components) |
| `MenuArt/Actors/*.act` (×7) | Menu art actors | Generated |

### Copied by `restore_starships_media.py`

| File | Source Hash | Purpose |
|------|------------|---------|
| `VideosCoach/Starships.webm` | `0ac1f08e...` | Coach gameplay video |
| `VideosCoach/Starships_MapPreview.webm` | `67913811...` | Preview video |
| `Audio/Starships.ogg` | `80f47be6...` | Full song audio |
| `Audio/Starships_AudioPreview.ogg` | `b6ea5be7...` | Preview audio |
| `MenuArt/textures/*.tga.ckd` (×7) | Various | Menu art textures (pre-decode) |
| `MenuArt/textures/*.jpg/*.png` (×3) | Various | Phone images |

### Converted by pipeline

| Output | Input | Tool |
|--------|-------|------|
| `Audio/Starships.wav` | `Starships.ogg` | ffmpeg (`-ar 48000`) |
| `Audio/Starships_AudioPreview.wav` | `Starships_AudioPreview.ogg` | ffmpeg (`-ar 48000`) |
| `MenuArt/textures/*.tga` (×7) | `*.tga.ckd` | `ckd_decode.py` |
| `Timeline/Starships_TML_Dance.dtape` | `starships_tml_dance.dtape.ckd` | `json_to_lua.py` |
| `Timeline/Starships_TML_Karaoke.ktape` | `starships_tml_karaoke.ktape.ckd` | `json_to_lua.py` |
| `Timeline/pictos/*.png` (×42) | `*.png.ckd` | `ckd_decode.py` |

---

## 10. Tools Reference

### `build_starships_fix.py`
Main config generator. Reads original timing data from `starships_musictrack.tpl.ckd` (JSON) and generates ~30 Lua/XML config files. Handles all the structural differences between JDU and JD2021 format.

### `restore_starships_media.py`
Maps hash-named JDU downloads (obtained via JDHelper) to their correct game paths. Converts OGG→WAV with explicit 48kHz resampling. This script does NOT handle pictograms or CKD decoding—those are managed by other tools/scripts in the pipeline. Ensure you have used JDHelper to acquire the original JDU files before running this script.

### `ckd_decode.py`
Decodes UbiArt CKD texture files. Supports:
- **PC CKDs**: Strip 44-byte header → DDS → Pillow → TGA/PNG
- **NX CKDs**: Strip header → XTX → deswizzle → DDS → Pillow → TGA/PNG
- Batch mode: `--batch <input_folder> [output_folder]`
- Single file: `<input.ckd> [output.tga]`

### `json_to_lua.py`
Converts JSON-format tapes (dtape, ktape) to Lua format for the UbiArt engine.

### `make_dummy_pictos.py`
Creates 1×1 transparent PNG placeholders (fallback when real pictos aren't decodable).

### `ubiart-archive-tools/ipk_unpacker.py`
Extracts IPK archive files from JDU downloads.

### `JustDanceTools/`
Community tools including font converters, texture converters, and deserializers for older JD formats (JD2014/2015 binary CKDs).

---

## Appendix: Lessons Learned

1. **Always use original timing data.** Synthetic BPM-derived markers seem correct but produce subtle sync issues. The original `starships_musictrack.tpl.ckd` contains the authoritative timing.

2. **CKD files from PC IPKs are often plaintext JSON.** Don't assume all `.ckd` files are binary — check with a text editor first. Only texture CKDs (with `TEX` magic bytes) need the binary decoder.

3. **Force 48kHz on all audio conversions.** The entire timing system is built on 48kHz sample positions. A 44.1kHz WAV will catastrophically desync.

4. **DASH MPD namespace casing matters.** `urn:mpeg:DASH:schema:MPD:2011` (capitals) works; `urn:mpeg:dash:schema:mpd:2011` (lowercase) doesn't.

5. **Video preview uses the MAIN video.** Don't point the preview actor at a separate preview file — point it at the main `.webm` and let the engine use `previewEntry`/`previewLoopEnd` to seek.

6. **The Cinematics chain is required even when empty.** The engine expects `_cine.isc` → `_MainSequence.tpl` → `_MainSequence.act` → `_MainSequence.tape` to exist.

7. **Path casing: `World/MAPS/MapName/`** — use consistent casing throughout all files. The engine does case-sensitive path lookups on some platforms.

8. **Don't compute `videoStartTime` from `startBeat`.** The value `startBeat × beat_duration` gives -1.92 for Starships, but the actual value is -1.901. The difference of 19ms matters for lip-sync and scoring precision.
