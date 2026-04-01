# Manual Map Porting Guide (Just Dance 2021 PC)

> **Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This guide provides a technical breakdown of manually porting a Just Dance Unlimited (JDU) map into the Just Dance 2021 PC engine (UbiArt). The automated V2 installer pipeline handles this end-to-end in GUI workflows (Fetch, HTML, IPK, Batch, Manual source), but this guide remains useful when you need to inspect generated output, reproduce one step manually, or debug parity-sensitive edge cases.

## Current V2 Behavior Notice (Read First)

1. **Intro AMB in automated V2 installs is currently under a temporary mitigation policy.**
    - Intro AMB attempt logic is intentionally disabled in current V2 runtime behavior.
    - Silent intro placeholders are expected in affected maps during automated install.
2. **IPK `videoStartTime` remains approximate in many cases.**
    - Manual post-install sync refinement is expected for video alignment.
3. **Runtime dependencies are mandatory for full fidelity.**
    - FFmpeg/FFprobe is required for media conversion and probing.
    - vgmstream is required for some X360/XMA2 decode paths.
    - Missing tools cause fallback behavior, degraded previews, or partial installs.

---

## Table of Contents

1. [Asset Acquisition](#1-asset-acquisition)
2. [Directory Structure](#2-directory-structure)
3. [Understanding File Formats](#3-understanding-file-formats)
4. [Step-by-Step Conversion](#4-step-by-step-conversion)
5. [Critical Timing & Sync](#5-critical-timing--sync)
6. [Game Integration](#6-game-integration)
7. [Troubleshooting Guide](#7-troubleshooting-guide)
8. [Appendix: Batch Preparation](#appendix-batch-preparation)

---

## 1. Asset Acquisition

Before starting, acquire the following original JDU files (via JDHelper or similar):

| Category | Typical File types | Purpose |
|----------|-------------------|---------|
| **Core Media** | `.ogg`, `.webm` | Gameplay audio and video. |
| **Data IPK** | `*_main_scene_pc.ipk` | Contains timing, choreography, and templates. |
| **Textures** | `.png.ckd`, `.tga.ckd` | Menu art, coach textures, and pictograms. |

### Runtime Dependencies (V2)

Manual conversion and debugging assumes the same dependency baseline as the installer:

| Tool | Why it matters |
|------|----------------|
| **FFmpeg / FFprobe** | WAV/preview conversion, probing, timing-sensitive media transforms. |
| **vgmstream** | Decode support for specific console-era audio payloads (for example XMA2 paths). |
| **Playwright Chromium** | Required for Fetch mode in installer workflows (not needed for purely local manual conversion). |

If these are missing, validate environment setup first (`setup.bat` in repository workflow), then retry.

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
│   ├── [MapName].wav            # Full audio (MUST be 48kHz PCM, trimmed to abs(vst))
│   ├── [MapName].ogg            # Original compressed audio (for song select preview)
│   ├── [MapName].trk            # CRITICAL: Beat timing data (Lua)
│   ├── [MapName]_musictrack.tpl # Audio template
│   ├── [MapName]_sequence.tpl   # Sequence template
│   ├── [MapName]_audio.isc      # Audio scene
│   ├── [MapName].stape          # Sequence tape (BPM/signature data per section)
│   ├── ConfigMusic.sfi          # Audio format declaration (XML)
│   └── AMB/
│       ├── amb_[mapname]_intro.wav  # Optional/manual intro AMB audio (see V2 note in Section 4.3)
│       ├── amb_[mapname]_intro.ilu  # Sound descriptor
│       └── amb_[mapname]_intro.tpl  # Sound actor template
│
├── Timeline/
│   ├── [MapName]_tml.isc
│   ├── [MapName]_TML_Dance.dtape
│   ├── [MapName]_TML_Dance.tpl
│   ├── [MapName]_TML_Dance.act
│   ├── [MapName]_TML_Karaoke.ktape
│   ├── [MapName]_TML_Karaoke.tpl
│   ├── [MapName]_TML_Karaoke.act
│   ├── pictos/
│   │   └── *.png
│   └── Moves/
│       ├── PC/             # Must contain the union of all platform gesture files
│       ├── DURANGO/        # Xbox One Kinect .gesture files
│       ├── ORBIS/          # PS4 .gesture files (incompatible format with PC)
│       └── WIIU/           # .msm skeleton files
│
├── Cinematics/
│   ├── [MapName]_cine.isc
│   ├── [MapName]_mainsequence.tpl
│   ├── [MapName]_mainsequence.act
│   └── [MapName]_MainSequence.tape
│
├── Autodance/
│   ├── [MapName]_autodance.tpl
│   ├── [MapName]_autodance.act
│   └── [MapName]_autodance.isc
│
├── VideosCoach/
│   ├── [MapName].webm
│   ├── [MapName].mpd
│   ├── [MapName]_video.isc
│   └── video_player_main.act
│
└── MenuArt/
    ├── [MapName]_menuart.isc
    ├── Actors/
    └── textures/
```

---

## 3. Understanding File Formats

### .TRK (Music Track Timing)
Lua-format file defining sample-perfect beat markers.
```lua
structure = { MusicTrackStructure = {
    markers = { { VAL = 0 }, { VAL = 23040 }, ... }, -- Sample positions @ 48kHz
    startBeat = -5,
    endBeat = 333,
    videoStartTime = -2.145000, -- Seconds before beat 0; also delays WAV by this amount
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

### 4.2 Convert Audio
Use FFmpeg to convert your OGG to WAV at 48kHz. You must also trim to `abs(a_offset)` seconds so the WAV begins at the right position when the engine delays it. `a_offset` is derived from the musictrack marker data (see AUDIO_TIMING.md Section 4); when marker data is unavailable it equals `abs(videoStartTime)`.
```bash
# Example: a_offset = -2.060 (marker-based) or -2.145 (equals videoStartTime as fallback)
ffmpeg -i input.ogg -ss 2.060 -ar 48000 output.wav
```
If the sample rate isn't exactly 48,000Hz, the `.trk` markers will drift, causing massive desync.

### 4.3 Generate Intro AMB
> **V2 Status (April 2026):** Automated intro AMB attempts are temporarily disabled in the current installer mitigation policy. In standard V2 installs, silent intro placeholders are expected.

For manual porting only: because `videoStartTime < 0` causes the WAV to be delayed, the gap can be covered by an AMB sound actor. The AMB sources audio from the same OGG (making any overlap inaudible) and fades out before or at the handoff point.

The automated pipeline calculates duration from marker data (primary) or falls back to `abs(videoStartTime) + 1.355s` (heuristic to cover engine scheduling jitter). For manual porting, use the heuristic fallback:

```bash
# Heuristic formula: abs(videoStartTime) + 1.355s
# For videoStartTime = -2.145:
#   amb_duration = 2.145 + 1.355 = 3.500s
#   fade_start   = 2.145 + 1.155 = 3.300s
ffmpeg -t 3.500 -i input.ogg -af "afade=t=out:st=3.300:d=0.2" -ar 48000 amb_mapname_intro.wav
```

See **[AUDIO_TIMING.md](../03_media/AUDIO_TIMING.md)** for the full explanation including the marker-based primary formula.

For maps where `videoStartTime = 0`, no intro AMB is needed.

### 4.4 Decode Textures
UbiArt CKD textures have a 44-byte binary header followed by a DDS or XTX payload.
1. Strip the header.
2. Convert DDS/XTX to TGA or PNG (using Pillow or XTX-Extractor).
3. Place in `MenuArt/textures/` or `Timeline/pictos/`.

### 4.5 Convert JSON Tapes to Lua
JDU uses JSON natively, but JD2021 PC expects Lua. The conversion involves both syntax transformation and UbiArt-specific data processing:

**Syntax changes:**
- Replace `[...]` with `{ ... }`
- Replace `"key":` with `key =`
- Booleans must be lowercase: `true` / `false`
- Floats should use 6 decimal places for consistency
- Strings must escape `"`, `\n`, and `\r`

**UbiArt-specific processing (handled by ``parsers/binary_ckd.py``):**
- **MotionClip Color**: Convert `[a, r, g, b]` float arrays to hex strings (e.g., `"0x0e8cd3ff"`)
- **MotionPlatformSpecifics**: Convert platform dict to KEY/VAL array format
- **Tracks array**: Build `Tracks = { {TapeTrack = {id = X}}, ... }` from unique TrackIds across all clips
- **Degenerate TrackId normalization**: When every clip has a unique ID (bad source data), group by clip class and assign shared deterministic IDs
- **Primitive arrays**: Must be wrapped as `{ {VAL = 1}, {VAL = 2} }` to prevent engine crashes

### 4.6 Convert Cinematic Tapes
If the extracted IPK contains files in a `cinematics/` folder (e.g., `*_mainsequence.tape.ckd`), convert them with additional processing:
- **Curve data**: `[x, y]` keyframe values in cinematic clips must be emitted as `vector2dNew(x, y)`
- **ActorIndices resolution**: Integer actor references must be resolved against the tape's `ActorPaths` array

### 4.7 Process Ambient Sounds from IPK
If the extracted IPK has files in an `audio/amb/` folder (e.g., `amb_mapname_intro.tpl.ckd`), process each into:
- `.ilu` (sound descriptor): Lua sound list + `appendTable` call
- `.tpl` (actor template): Wrapper referencing SoundComponent and the `.ilu`

Then inject a SoundComponent actor into the audio `.isc` for each AMB file.

If no AMB exists in the IPK but the map has `videoStartTime < 0`, you can manually create the three intro AMB files from scratch (see step 4.3). For automated V2 installs, this intro path is currently intentionally suppressed by mitigation logic.

---

## 5. Critical Timing & Sync

### The Timing Chain
The engine resolves timing in this order:
1. **Audio Position** (Sample #) → **Beat Number** (via `.trk` markers)
2. **Beat Number** → **Tick Number** (24 ticks per beat)
3. **Tick Number** → **Clip Execution** (via Tape files)

### videoStartTime and Pre-Roll Silence
The `videoStartTime` is typically negative (e.g., `-2.145`). This value controls both the video start offset AND the WAV audio delay. The engine uses the exact same value for both. **Do not calculate this synthetically**; always extract from the original JDU metadata.

Because the WAV is delayed by `abs(videoStartTime)`, every ported map will have silence during the pre-roll period unless an intro AMB is provided. See **[AUDIO_TIMING.md](../03_media/AUDIO_TIMING.md)**.

In current automated V2 behavior, that silence can be expected due to temporary intro AMB mitigation, and is not by itself evidence of a failed install.

### Why the WAV Must Be Trimmed
The first sample of the WAV corresponds to marker 0 = beat `startBeat`. If `startBeat = -5` and the OGG starts 2.060 seconds before the song's beat -5 content (per marker calculation), then the OGG must be trimmed by `abs(a_offset)` seconds before being used as the WAV, so that sample 0 of the WAV actually corresponds to beat -5 of the music.

---

## 6. Game Integration

1. **Deployment**: Copy your `[MapName]` folder to `jd21/data/World/MAPS/`.
2. **Registration**:
   - Open `SkuScene_Maps_PC_All.isc`
   - Add an Actor entry with a `JD_SongDescComponent` component, referencing your map's `songdesc.act` and `songdesc.tpl`
   - Add two `CoverflowSong` entries (one for `cover_generic.act`, one for `cover_online.act`) for the song select carousel
3. **Validation**: Launch the game; if the title is missing, check your `SongDesc` actor configuration.

---

## 7. Troubleshooting Guide

| Issue | Root Cause | Fix |
|-------|------------|-----|
| **Silence at map start (automated V2 install)** | Current mitigation disables intro AMB attempt logic | Expected behavior in April 2026 builds; use sync/readjust flow for timing work and monitor release notes for AMB redesign status |
| **Silence at map start (manual porting)** | No intro AMB for pre-roll period on `videoStartTime < 0` map | Generate `amb_{mapname}_intro.wav` from OGG and add AMB actor to audio ISC |
| **Crash at Coach Select** | Missing Cinematics chain | Create `_cine.isc` → `_MainSequence.tpl` structure |
| **Progressive Desync** | Wrong audio sample rate | Re-convert audio with `-ar 48000` |
| **Audio too late / too early** | Incorrect audio trim offset | Match `-ss` seek value to `abs(a_offset)` (marker-derived, or `abs(videoStartTime)` as fallback) |
| **Pictos / karaoke appear too early** | `videoStartTime` set to 0 on a pre-roll map | Restore original negative `videoStartTime`; use intro AMB for audio coverage |
| **Video timing still off after install (IPK maps)** | Source metadata does not always provide exact lead-in | Perform manual video offset tuning in sync/readjust workflow |
| **Black Video** | Incorrect DASH MPD | Ensure namespace is `urn:mpeg:DASH:schema:MPD:2011` |
| **Missing Title** | SkuScene Registration | Verify the map entry in `SkuScene_Maps_PC_All.isc` |
| **Autodance error after Apply** | Sync refinement regenerated empty stub over converted data | Reinstall the map; the pipeline now protects autodance files from overwrite |
| **Kinect gesture load failure** | ORBIS (PS4) `.gesture` files copied to PC/ | Only use `.gesture` files from DURANGO/SCARLETT (Kinect format); substitute ORBIS-exclusive variants with the base Kinect gesture |
| **"Can't find gesture resource"** | Missing gesture file in PC/ Moves folder | Ensure PC/ contains the union of `.gesture` (from DURANGO) and `.msm` (from WIIU) files from all platforms |
| **Preview/decode failures for some maps** | Missing FFmpeg/FFprobe or missing vgmstream runtime | Re-run dependency setup and confirm both toolchains are available before reinstall/readjust |

---

## Appendix: Batch Preparation

If you plan to convert many maps, prepare a single parent directory where each child folder contains the two HTML exports (`assets.html` and `nohud.html`) captured from JDHelper.

In V2, this source layout is typically consumed through GUI Batch mode (or HTML mode) rather than legacy script-first flow.

```
my_maps/
    Albatraoz/
        assets.html
        nohud.html
    BadRomance/
        assets.html
        nohud.html
```

Batch flow in V2:
1. Launch the installer GUI.
2. Select **Batch Directory** mode.
3. Point to the parent folder (`my_maps/`).
4. Run install, then use sync/readjust for final timing polish as needed.

If the installer cannot detect your JD path, set it explicitly in installer settings and verify write access to the target `jd21` tree.
