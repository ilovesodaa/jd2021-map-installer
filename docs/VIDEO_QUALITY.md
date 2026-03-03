# Video Quality Tiers

This document describes the video quality selection system in the JD2021 Map Installer.

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
