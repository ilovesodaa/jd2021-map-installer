# Video Reference

> **Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This document covers the NOHUD video quality system in JD2021 Map Installer v2: available tiers, selection/fallback behavior, and technical analysis of source video files.

---

## V2 Operational Notes (Read First)

These constraints affect video/audio behavior in current v2 builds:

1. **IPK video timing remains approximate by design.**
  X360/IPK source metadata often does not provide a reliable lead-in, so generated defaults can still require manual Video Offset tuning.
2. **Intro AMB playback is temporarily disabled globally.**
  Intro AMB outputs are currently forced to silent placeholders as a temporary mitigation. This is expected behavior in active v2 builds.
3. **Runtime dependencies are required for stable media workflows.**
  FFmpeg/FFprobe and vgmstream are required for full decode/preview/convert coverage; missing tools can degrade sync and media validation workflows. Fetch mode also requires Playwright Chromium.
4. **Dedicated preview assets are optional in current runtime wiring.**
  Current installs remain playable and preview-capable without `AudioPreview` / `MapPreview` files; preview loop behavior is typically driven by `.trk` marker fields over main media. See [ASSETS.md](ASSETS.md) for exact with/without differences.

---

## Available Quality Tiers

The pipeline supports 8 logical quality tiers. The concrete filename variant differs by source family (JDU vs JDNext).

| Tier | Suffix Pattern | Description |
|------|---------------|-------------|
| `ULTRA_HD` | `_ULTRA.hd.webm` | Highest quality (HD variant of Ultra) |
| `ULTRA` | `_ULTRA.webm` | Ultra quality |
| `HIGH_HD` | `_HIGH.hd.webm` | High HD |
| `HIGH` | `_HIGH.webm` | High |
| `MID_HD` | `_MID.hd.webm` | Medium HD |
| `MID` | `_MID.webm` | Medium |
| `LOW_HD` | `_LOW.hd.webm` | Low HD |
| `LOW` | `_LOW.webm` | Lowest quality |

### JDNext Variant Mapping

JDNext uses explicit `hd`, `vp9`, and sometimes `vp8` variant filenames. The installer maps JDNext links into the same 8 logical tiers:

| Logical Tier | JDNext Preferred Variant | Typical JDNext URL pattern |
|---|---|---|
| `ULTRA_HD` | `hd` | `/video_ultra.hd.webm/...` |
| `ULTRA` | `vp9` | `/video_ultra.vp9.webm/...` |
| `HIGH_HD` | `hd` | `/video_high.hd.webm/...` |
| `HIGH` | `vp9` | `/video_high.vp9.webm/...` |
| `MID_HD` | `hd` | `/video_mid.hd.webm/...` |
| `MID` | `vp9` | `/video_mid.vp9.webm/...` |
| `LOW_HD` | `hd` | `/video_low.hd.webm/...` |
| `LOW` | `vp9` | `/video_low.vp9.webm/...` |

Notes:
- If both `hd` and legacy `vp8` exist for the same `*_HD` tier, `hd` is preferred.
- JDNext non-HD tiers are VP9 by design unless compatibility fallback mode is enabled.

---

## Quality Selection Behavior

### Fallback Chain

When the requested quality is not available on the CDN, the pipeline falls back through tiers in wrap-around order starting from the requested tier:

```
Requested: HIGH_HD
Search order: HIGH_HD -> HIGH -> MID_HD -> MID -> LOW_HD -> LOW -> ULTRA_HD -> ULTRA
```

The first available tier is selected. If it differs from the requested tier, a status message is logged.

### JDNext VP9 Handling Modes

For JDNext links, behavior is controlled by `vp9_handling_mode`:

| Mode | Behavior |
|---|---|
| `reencode_to_vp8` | Keeps requested JDNext VP9 tier, then re-encodes VP9 -> VP8 during install for compatibility. |
| `fallback_compatible_down` | Avoids VP9 tiers and picks the next compatible `*_HD` tier down (no VP9 re-encode path). |

Compatibility-down examples:

```
Requested: ULTRA   -> search ULTRA_HD -> HIGH_HD -> MID_HD -> LOW_HD
Requested: HIGH    -> search MID_HD -> LOW_HD
Requested: MID_HD  -> search MID_HD -> LOW_HD
```

### Existing Video Detection

Before downloading, the pipeline checks whether a video of a different quality already exists in the map download directory.

| Mode | Behavior |
|------|----------|
| **Interactive CLI path (where used)** | Prompts to reuse, redownload, or stop |
| **GUI / non-interactive workers (default v2 usage)** | Reuses existing video automatically |

Batch workflows additionally detect the quality of already-downloaded files and prefer reuse to avoid unnecessary redownloads.

### Post-Download Fallback

If download fails (commonly expired links / HTTP 403 / HTTP 404), the pipeline searches local `.webm` files using the same quality fallback chain and continues with the best available local match.

---

## Setting Quality

### GUI (Primary v2 path)

Select **Video Quality** in the Configuration section.

Available values:
- `ultra_hd`
- `ultra`
- `high_hd`
- `high`
- `mid_hd`
- `mid`
- `low_hd`
- `low`

### CLI / Scripted Invocation (Advanced)

The project is now GUI-first in normal operation (`RUN.bat` or `python -m jd2021_installer.main`).

If you run internal/scripted pipeline entry points, pass quality with the corresponding `--quality` option for that flow. Prefer documented GUI workflows unless you are maintaining or testing internals.

---

## Quality Persistence

Video preferences are persisted in `installer_settings.json` using:
- `video_quality`
- `vp9_handling_mode`

Example:

```json
{
  "video_quality": "ULTRA_HD",
  "vp9_handling_mode": "fallback_compatible_down",
  "v_override": -2.145,
  "a_offset": -2.060,
  "marker_preroll_ms": 2060.0
}
```

On later installs/reinstalls, these global settings are loaded automatically.

---

## File Size Considerations

Higher tiers produce much larger WebM files. `ULTRA_HD` commonly lands in the ~200-500 MB range per map.

If disk space is constrained, `HIGH` or `MID` are practical defaults.

In standard workflows, one quality tier is used per map install target. Switching tier usually requires redownloading unless multiple tier files are already present locally.

---

## NOHUD Video File Analysis

These are **NOHUD (No Heads-Up Display) coach videos**: dance footage without gameplay overlays (score, arrows, coach UI, etc.). The 8 logical tiers represent **4 quality levels x 2 slots** (`*_HD` and non-`HD`) plus one shared audio stream.

For JDU, non-HD slots are typically VP8 (`_ULTRA.webm`, `_HIGH.webm`, etc.).
For JDNext, non-HD slots are typically VP9 (`video_ULTRA.vp9.webm`, etc.) unless compatibility-down mode is used.

**Common `.webm` properties:**

- Codec: VP8
- Pixel format: yuv420p
- Frame rate: 25 fps
- Duration: ~194.36s

### File Reference Table

| File | Resolution | Bitrate | Size | VP8 Profile |
|---|---|---|---|---|
| `ULTRA HD.webm` | 1920x1080 | 8,822 kbps | 214 MB | 0 |
| `ULTRA.webm` | 1216x720 | 7,889 kbps | 192 MB | **2** |
| `HIGH HD.webm` | 1280x720 | 3,834 kbps | 93.1 MB | 0 |
| `HIGH.webm` | 1216x720 | 3,850 kbps | 93.5 MB | **2** |
| `MID HD.webm` | 768x432 | 1,902 kbps | 46.2 MB | 0 |
| `MID.webm` | 768x432 | 1,902 kbps | 46.2 MB | 0 |
| `LOW HD.webm` | 480x270 | 533 kbps | 12.9 MB | 0 |
| `LOW.webm` | 480x270 | 529 kbps | 12.9 MB | 0 |

### The Two Encoding Generations

The non-`HD` and `HD` files appear to represent two encoding targets: likely original extracted assets vs. re-encoded/corrected assets.

#### The 1216-Wide Non-Standard Width

`HIGH.webm` and `ULTRA.webm` are 1216 pixels wide, which is non-standard for typical web/video delivery (720p standard width is 1280).

This is consistent with source cropping (for example HUD-safe or letterbox-area removal). `HD` variants normalize this to standard frames (1280x720 and 1920x1080).

#### VP8 Profile Difference

- **Profile 0** (HD variants): broad compatibility and typical decode behavior.
- **Profile 2** (`ULTRA.webm`, `HIGH.webm`): more complex profile, commonly seen in legacy engine-generated encodes.

This again supports the interpretation that non-HD files are closer to original extracted game encodes, while HD files are compatibility-focused re-encodes.

### MID and LOW: Minimal Practical Difference

For `MID` and `LOW`, `HD` and non-`HD` are effectively equivalent in practice (same resolution/profile and near-identical size/bitrate).

### Audio Gap

`AUDIO.ogg` (Vorbis, ~224 kbps) is typically shorter than the corresponding NOHUD video (roughly 5+ seconds in common sets).

Audio/video are intentionally not 1:1 duration-matched at source level. Final play sync is handled through installer timing controls (`v_override`, `a_offset`, marker preroll handling) plus user readjust when needed.

---

## Quick-Reference Q&A

| Question | Answer |
|---|---|
| Which variants should I use? | Prefer **HD** for ULTRA/HIGH (standard aspect output, Profile 0). MID/LOW variants are mostly interchangeable. |
| Why is ULTRA_HD much larger? | 1920x1080 contains about 2.3x the pixel count of 1216x720, reflected in output size and bitrate. |
| Why is video sync still off on some IPK maps? | IPK `videoStartTime` metadata is often incomplete/approximate, so manual Video Offset tuning is expected for some maps. |
| Why are intro ambient sections silent? | Current v2 policy temporarily disables intro AMB playback and writes silent intro placeholders. |
