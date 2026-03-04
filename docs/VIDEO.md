# Video Reference

This document covers the NOHUD video quality system in the JD2021 Map Installer: available tiers, selection/fallback behavior, and technical analysis of the source video files.

---

## Available Quality Tiers

The pipeline supports 8 video quality tiers, defined in `map_downloader.py:72`. Each tier corresponds to a specific URL/filename suffix pattern on the JDU CDN.

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

---

## Quality Selection Behavior

### Fallback Chain

When the requested quality is not available on the CDN, the pipeline falls back through the quality tiers in a wrap-around order starting from the requested tier:

```
Requested: HIGH_HD
Search order: HIGH_HD → HIGH → MID_HD → MID → LOW_HD → LOW → ULTRA_HD → ULTRA
```

The first available tier is selected. If the selected tier differs from the requested tier, a message is logged:

```
Requested quality HIGH_HD not available, using ULTRA
```

### Existing Video Detection

Before downloading, the pipeline checks if a video of a **different** quality already exists in the download directory. Behavior depends on the execution mode:

| Mode | Behavior |
|------|----------|
| **CLI (interactive)** | Prompts: `[R]euse existing / [D]ownload new / [S]top` |
| **GUI/Batch (non-interactive)** | Silently reuses existing video |

The batch installer additionally auto-detects the quality of any existing video file (`detect_existing_quality()` in `batch_install_maps.py:79`) and uses that quality instead of the global default, preventing unnecessary re-downloads.

### Post-Download Fallback

If the video fails to download (HTTP 403/404 — expired links), the pipeline searches for any existing `.webm` file on disk using the same quality fallback chain through `find_best_video_file()` (`map_downloader.py:90`).

---

## Setting Quality

### GUI

Select from the **Video Quality** dropdown in the Configuration section. Options: `ultra_hd`, `ultra`, `high_hd`, `high`, `mid_hd`, `mid`, `low_hd`, `low`.

### CLI (Single Map)

```bash
python map_installer.py --asset-html assets.html --nohud-html nohud.html --quality high_hd
```

### CLI (Batch)

```bash
python batch_install_maps.py MapDownloads --quality ultra
```

The batch quality applies to all maps unless an existing video of a different quality is already downloaded, in which case the existing quality is used.

---

## Quality Persistence

When a map config is saved (via "Apply & Finish" in GUI or the sync refinement loop), the selected quality is stored in `map_configs/{map_name}.json`:

```json
{
  "map_name": "Starships",
  "v_override": -2.145,
  "a_offset": -2.060,
  "quality": "ULTRA_HD",
  "codename": "Starships",
  "marker_preroll_ms": 2060.0,
  "installed_at": "2024-01-15T14:30:00"
}
```

On reinstallation, saved configs are loaded automatically, including the quality setting.

---

## File Size Considerations

Higher quality tiers produce significantly larger WebM files. `ULTRA_HD` videos typically range from 200–500 MB per map. If disk space is limited, consider using `HIGH` or `MID` tier.

The pipeline stores only one video quality per map at a time. Switching quality requires re-downloading the video (or having multiple quality files already present).

---

## NOHUD Video File Analysis

These are **NOHUD (No Heads-Up Display) coach videos** — background dance footage stripped of in-game overlays (score, arrows, coach UI, etc.). The 8 tiers above correspond to **4 quality levels × 2 variants** (`HD` and non-`HD`), plus one shared audio track.

**Common properties across all `.webm` files:**

- Codec: VP8
- Pixel format: yuv420p
- Frame rate: 25 fps
- Duration: ~194.36s

### File Reference Table

| File | Resolution | Bitrate | Size | VP8 Profile |
|---|---|---|---|---|
| `ULTRA HD.webm` | 1920×1080 | 8,822 kbps | 214 MB | 0 |
| `ULTRA.webm` | 1216×720 | 7,889 kbps | 192 MB | **2** |
| `HIGH HD.webm` | 1280×720 | 3,834 kbps | 93.1 MB | 0 |
| `HIGH.webm` | 1216×720 | 3,850 kbps | 93.5 MB | **2** |
| `MID HD.webm` | 768×432 | 1,902 kbps | 46.2 MB | 0 |
| `MID.webm` | 768×432 | 1,902 kbps | 46.2 MB | 0 |
| `LOW HD.webm` | 480×270 | 533 kbps | 12.9 MB | 0 |
| `LOW.webm` | 480×270 | 529 kbps | 12.9 MB | 0 |

### The Two Encoding Generations

The non-`HD` and `HD` files represent **two different encoding targets** — likely an **original game rip** vs. a **re-encoded/corrected version**.

#### The 1216-Wide Non-Standard Width

`HIGH.webm` and `ULTRA.webm` are **1216 pixels wide** — not a broadcast or web standard. Standard 720p is 1280×720.

This strongly suggests these non-HD videos were **cropped from their original source** — likely to remove letterboxing, pillarboxing, or a HUD-safe zone that the game rendered around the coach area. The `HD` variants correct this to proper standard resolutions (**1280×720** and **1920×1080**).

#### VP8 Profile Difference

- **Profile 0** (HD variants): Simpler, widely compatible — the standard for web/game use.
- **Profile 2** (ULTRA.webm, HIGH.webm): Supports more complex motion estimation. Often an artifact of the original game engine's encoder. Less universally supported on older or embedded decoders.

This further supports that the non-HD files are **original game-extracted rips**, while HD variants were re-encoded for better compatibility.

### MID and LOW: No Real Difference

For `MID` and `LOW`, both variants are **functionally identical** — same resolution, same profile, within ~0.1% file size of each other. The `HD` label is effectively meaningless at these tiers.

### Audio Gap

`AUDIO.ogg` (Vorbis, 224 kbps) is **~188.95s** — about **5.4 seconds shorter** than the video files (~194.36s).

The audio is intentionally not aligned 1:1 with the video and requires tuning via the installer's **audio offset sync feature**.

---

## Quick-Reference Q&A

| Question | Answer |
|---|---|
| Which variants to use? | **HD** for ULTRA and HIGH (correct aspect ratio, Profile 0). MID/LOW are interchangeable. |
| Why is ULTRA HD so much bigger? | 1920×1080 vs 1216×720 is ~2.3× the pixel count, reflected in the larger file size. |
| Why is audio shorter than video? | Intentional offset — handled by the installer's audio sync feature. |
