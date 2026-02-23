# JDU Data Mapping Specification

This document details how raw data from the Just Dance Unlimited (JDU) JSON payloads is mapped, transformed, or ignored when porting maps to the Just Dance 2021 PC (UbiArt) engine.

---

## 1. Map Metadata (SongDesc)

| JDU Property | JD2021 PC Property | Transformation / Note |
|--------------|-------------------|-----------------------|
| `title` | `Title` | Direct string copy. |
| `artist` | `Artist` | Direct string copy. |
| `difficulty` | `Difficulty` | 1-4 scale mapped to UbiArt enum. |
| `sweatDifficulty`| `SweatDifficulty` | 1-3 scale. |
| `lyricsType` | `LyricsType` | **CRITICAL**: 0=None, 1=Karaoke. Must be correct for UI rendering. |
| `backgroundType` | `backgroundType` | Typically 0 (2D Video). |
| `coachNumbers` | `NumCoach` | Number of dancers (1-4). |
| `mainCoach` | `MainCoach` | Index of the primary coach (0-3, or -1 for default). Extracted from CKD. |
| `jdVersion` | `OriginalJDVersion`| Year of original release (e.g., 2014, 2015). |
| `DancerName` | `DancerName` | Extracted from CKD, defaults to `"Unknown Dancer"`. |
| `Credits` | `Credits` | Full rights/credits string from CKD. |
| `Energy` | `Energy` | Energy level indicator, defaults to 1. |
| `Status` | `Status` | Song status flag, defaults to 3. |
| `LocaleID` | `LocaleID` | Locale identifier, defaults to 4294967295 (all locales). |
| `MojoValue` | `MojoValue` | Mojo reward value, defaults to 0. |
| `CountInProgression` | `CountInProgression` | Progression counter, defaults to 1. |

---

## 2. Audio & Synchronization (MusicTrack)

### .TRK Logic
The timing markers in the original `musictrack.tpl.ckd` (JSON) are verbatim audio sample positions at **48kHz**.

- **`markers`**: Array of sample positions for every beat. 
- **`videoStartTime`**: Scientific offset in seconds (e.g., `-1.901000`). 
  - **DANGER**: Do not calculate this as `startBeat * beatDuration`. Use the original metadata value to ensure frame-perfect sync.
- **`startBeat`**: Number of pre-roll beats (e.g., `-4`).
- **`previewEntry`**: Beat index where the song select preview begins.
- **`volume`**: dB adjustment (usually 0).

### SFI (Sound Format Info)
JD2021 PC requires an explicit XML declaration of the sound format:
```xml
<SoundFormatInfo Format="PCM" IsStreamed="1" IsMusic="1" Platform="PC" />
```

---

## 3. Choreography Tapes (.dtape / .ktape)

### The Primitive Array Crash
The UbiArt engine (v280000) will crash if a tape contains raw primitive arrays. They MUST be wrapped in `VAL` tables.

- **JDU Source**: `"PartsScale": [1, 1, 1]`
- **JD2021 Target**: `PartsScale = { {VAL = 1.0}, {VAL = 1.0}, {VAL = 1.0} }`

### Tick Conversion
- **Resolution**: 24 ticks per beat.
- **Clip Mapping**: `StartTime` and `Duration` must be converted from JDU milliseconds/frames into engine ticks for `.dtape` and `.ktape` playback.

### MotionClip Processing (handled by `ubiart_lua.py`)

| JDU Data | JD2021 Lua Output | Note |
|----------|-------------------|------|
| `Color: [a, r, g, b]` (floats 0-1) | `Color = "0xRRGGBBAA"` | Hex string with channels reordered. Default `"0xffffffff"` if missing. |
| `MotionPlatformSpecifics: {platform: data}` | `MotionPlatformSpecifics = { {KEY="X360", VAL={...}}, ... }` | Dict converted to KEY/VAL array. Inner data runs through `remove_class`. |
| `TrackId: N` (per clip) | `Tracks = { {TapeTrack = {id=N}}, ... }` | Unique TrackIds collected across all clips. `Tracks` array built and inserted at tape level. |

### Degenerate TrackId Normalization
When every clip in a tape has a unique TrackId (a sign of bad source data), the pipeline groups clips by `__class` and assigns a deterministic shared ID per class (using `hash(class_name) & 0xFFFFFFFF`). This prevents the engine from creating hundreds of individual tracks.

### Falsy Value Removal
After conversion, keys with default/empty values (`""`, `0`, `0.0`, `False`, `{}`, `[]`, `None`) are stripped from the output to produce cleaner, smaller Lua files.

---

## 3.5. Cinematic Tapes (.tape in `cinematics/`)

Cinematic tapes contain animation clips that require additional processing beyond standard choreography tapes:

### Curve Data
Clip types like `AlphaClip`, `RotationClip`, `TranslationClip`, `SizeClip`, `ScaleClip`, `ColorClip`, `MaterialGraphicDiffuseAlphaClip`, `MaterialGraphicDiffuseColorClip`, `MaterialGraphicUVTranslationClip`, and `ProportionClip` contain nested `Curve.Keys` arrays where each keyframe value is a `[x, y]` pair. These must be emitted as `vector2dNew(x, y)` in the Lua output for the engine to interpret them as 2D vectors.

### ActorIndices Resolution
Cinematic clips reference actors via `ActorIndices` (integer array). The tape's top-level `ActorPaths` array maps these indices to actual actor path strings. During conversion:
1. Each clip's `ActorIndices` is dereferenced against `ActorPaths`
2. Resolved paths are written as `ActorPaths = { {VAL = "path/to/actor"}, ... }` on the clip
3. The top-level `ActorPaths` array is removed from the tape

### Fallback
If no cinematic `.tape.ckd` files exist in the extracted IPK, the pipeline keeps the empty fallback tape generated by `map_builder.py`.

---

## 3.6. Ambient Sounds (`audio/amb/`)

Some maps include ambient sound templates (e.g., intro sounds). These are `.tpl.ckd` files in the `audio/amb/` folder of the extracted IPK. Each is processed into two files:

| Output File | Contents |
|------------|----------|
| `.ilu` (descriptor) | Lua sound list data + `appendTable(component.SoundComponent_Template.soundList, DESCRIPTOR)` call |
| `.tpl` (template) | Actor_Template wrapper with `includeReference` to the SoundComponent and the `.ilu` file |

These are placed in the map's `Audio/AMB/` directory.

---

## 4. Video & DASH Manifests

The engine uses DASH for video quality fallback. To work locally, the manifest must follow these strict technical rules:

| XML Element | Requirement | Note |
|-------------|-------------|------|
| **Namespace** | `urn:mpeg:DASH:schema:MPD:2011` | **MUST** be capitalized. |
| **Profile** | `urn:webm:dash:profile:webm-on-demand:2012` | Required for WebM support. |
| **BaseURL** | `jmcs://jd-contents/[MapName]/[MapName].webm` | Forces engine to local file fallback. |

---

## 5. Autodance & Recording

The engine looks for a specific actor chain to enable recaps:
- **Template**: `JD_AutodanceComponent_Template`
- **Actor Component**: `JD_AutodanceComponent`
- **Tapes**:
  - `.adtape`: Scoring/Title/Picto timings for the recap.
  - `.advideo`: Video encoding parameters for the exporter.
  - `.adrecording`: Raw controller movement data (6-axis/IMU).

---

## 6. Ignored / Discarded Data

The following JDU properties are safely ignored:
- **`assets`**: JDU menu icons are replaced by native PC MenuArt actors.
- **`urls`**: Only used for initial acquisition.
- **`skuConfigs`**: Licensing logic is bypassed.
- **`platformSpecifics`**: Metadata for older consoles (WiiU/PS3) is discarded.
- **`previewAudio`**: Orphaned; the engine plays the main audio file from the `previewEntry` beat marker.

---
*Reference: This mapping is derived from high-precision analysis of the "Starships" and "GetGetDown" case studies.*

---

## 7. Default Colors

JDU exposes a `DefaultColors` block in the `songdesc.tpl.ckd` payload containing song-specific theme colors. The automation extracts **all** color keys (`lyrics`, `theme`, `songcolor_1a`, `songcolor_1b`, `songcolor_2a`, `songcolor_2b`, and any extras) and injects them into the generated `SongDesc.tpl`.

### Key matching

CKD color keys may use different casing than the hardcoded fallbacks (e.g., CKD has `songcolor_1a` while fallback is `songColor_1A`). The pipeline performs **case-insensitive matching** to avoid duplicates. CKD values and key names take priority; fallback hex values are used only when a key is absent from the CKD entirely.

### Conversion rules

- **Source format**: `[component, component, component, component]` where each component is a float in 0.0-1.0 range.
  - For `map_builder.py` (`color_array_to_hex`): Components are taken in array order and concatenated as hex.
  - For `ubiart_lua.py` (`argb_hex`, used in MotionClip Colors): Input is `[a, r, g, b]`, output is `0xRRGGBBAA` (channels reordered).
- **Hex strings**: If the CKD already contains a hex string (e.g., `0xFFB8113B`), it is passed through unchanged.

### Fallback values

| Key | Fallback Hex |
|-----|-------------|
| `lyrics` | `0xFF1B34AA` |
| `theme` | `0xFFFFFFFF` |
| `songColor_1A` | `0x00D1D0D0` |
| `songColor_1B` | `0xF50005D0` |
| `songColor_2A` | `0x00D1D0D0` |
| `songColor_2B` | `0xF50005D0` |

- Notes:
  - Some `.tpl.ckd` files are plaintext JSON despite the `.ckd` extension; the pipeline attempts to detect and parse JSON first before applying CKD-specific decoding.
  - Extra color keys from the CKD that are not in the fallback table are included in the output with no fallback (conversion only).
