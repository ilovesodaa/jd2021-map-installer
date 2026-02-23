# JDU Data Mapping Specification

This document details how raw data from the Just Dance Unlimited (JDU) JSON payloads is mapped, transformed, or ignored when porting maps to the Just Dance 2021 PC (UbiArt) engine.

## 1. Map Metadata (SongDesc)

| JDU Property | JD2021 PC Property | Transformation / Note |
|--------------|-------------------|-----------------------|
| `title` | `Title` | Direct string copy. |
| `artist` | `Artist` | Direct string copy. |
| `difficulty` | `Difficulty` | 1-4 scale mapped to UbiArt enum. |
| `sweatDifficulty`| `SweatDifficulty` | 1-3 scale. |
| `lyricsType` | `LyricsType` | **CRITICAL**: Must match original (0=None, 1=Karaoke) to enable/disable UI rendering. |
| `backgroundType` | `backgroundType` | Usually 0 for 2D video maps. |
| `coachNumbers` | `NumCoach` | Defined by the number of active `CoachId` entries in the dance tape. |

## 2. Audio & Synchronization (MusicTrack)

- **`videoStartTime`**: This is the most important sync parameter. It defines the point in time (in seconds) where the gameplay choreography begins relative to the video file.
- **JD2021 Engine Requirement**: The engine uses this value to align the `TapeCase` components. If our audio is processed with an offset, the `videoStartTime` in the generated `MusicTrack.tpl` must be adjusted accordingly to maintain sync.

## 3. Choreography Tapes (.dtape / .ktape)

### Clip Conversion
JDU clips are stored in JSON arrays. When converting to Lua for JD2021:
- **`StartTime` & `Duration`**: Converted to engine ticks (usually milliseconds or frames depending on the map).
- **`Pitch`**: Specifically used in Karaoke for scoring and visual note height.

### The Primitive Array Crash (LogicDB)
The UbiArt engine in JD2021 will crash if it encounters raw primitive arrays (e.g., `PartsScale = {0,0,0}`).
- **Fix**: Every primitive value must be serialized as a table with a `VAL` key.
- **Example**: `PartsScale = { {VAL = 1.0}, {VAL = 1.0}, {VAL = 1.0} }`.

## 4. Autodance & Recording

- **Component Name**: The engine specifically looks for `JD_AutodanceComponent`. Any other name in the `.isc` or `.act` will result in a "class not found in factory" error.
- **Media Paths**:
  - `.adtape`: Scoring and Picto timings for the Autodance preview.
  - `.advideo`: Video encoding parameters.
  - `.adrecording`: Raw movement data captured from the original session.

## 5. Ignored Metadata
The following JDU properties are typically ignored as they are either purely cosmetic for the JDU menu or platform-specific for consoles:
- `assets`: Menu icons/banners are replaced by custom 2021-style cover art.
- `urls`: Used only during the download phase.
- `platformSpecifics`: Metadata for PS4, Xbox One, and WiiU is discarded in favor of PC-native paths.
- `skuConfigs`: Licensing and unlock logic is bypassed.
