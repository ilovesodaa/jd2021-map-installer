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
| `mainCoach` | `MainCoach` | Index of the primary coach (0-3). |
| `jdVersion` | `OriginalJDVersion`| Year of original release (e.g., 2014, 2015). |

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

## 7. Default Colors & Lyric Highlight

JDU often exposes a `DefaultColors` block (either as a JSON object stored in a `.tpl.ckd` payload or as a hex string). The automation extracts `DefaultColors["lyrics"]` when present and injects it into the generated `SongDesc.tpl` so the in-engine lyric highlight matches the original JDU presentation.

- Source formats supported:
  - JSON arrays: `[r, g, b, a]` where components are floats in the range 0.0-1.0.
  - Hex strings: `0xAARRGGBB` (already in engine format).

- Conversion rule (array -> hex):

  Given `[r,g,b,a]` with values 0..1, convert each channel to 0..255 by `int(round(channel * 255))` and produce `0xAARRGGBB` where alpha is first.

  Example:

  - JDU: `[1, 0.721569, 0.066667, 0.231373]`
  - Channel ints: R=255, G=184, B=17, A=59
  - Engine hex: `0xFFB8113B`

- Notes:
  - Some `.tpl.ckd` files are plaintext JSON despite the `.ckd` extension; the pipeline attempts to detect and parse JSON first before applying CKD-specific decoding.
  - If `lyrics` color is absent, the pipeline falls back to a default highlight (configurable in `map_builder.py`).
