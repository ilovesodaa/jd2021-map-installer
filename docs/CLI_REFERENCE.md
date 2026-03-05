# JD2021 Map Installer -- CLI Reference

This document describes the command-line interfaces provided by `map_installer.py` (single map installation) and `batch_install_maps.py` (batch installation).

---

## Single Map CLI (`map_installer.py`)

Entry point: `main()` (line 1719).

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--map-name` | No | Derived from asset-html URLs or parent folder | Map name / codename |
| `--asset-html` | Yes | -- | Path to asset mapping HTML |
| `--nohud-html` | Yes | -- | Path to nohud mapping HTML |
| `--jd-dir` | No | Auto-detected | Base directory of JD tools / JD21 install |
| `--quality` | No | `ultra_hd` | Video quality (see choices below) |
| `--video-override` | No | None | Force a specific video start time (float) |
| `--audio-offset` | No | None | Force a specific audio trim offset (float) |
| `--sync-config` | No | None | Path to a JSON config file to load sync values from |

**Quality choices:** `ultra_hd`, `ultra`, `high_hd`, `high`, `mid_hd`, `mid`, `low_hd`, `low`

### Map Name Detection

The map codename is resolved in the following order:

1. Extract the codename from JDU asset URLs found in the HTML file. This is the most reliable method.
2. Fall back to the parent folder name of the asset HTML file.

### Pipeline Execution

- Runs all 16 steps sequentially (defined in the `PIPELINE_STEPS` list at line 1699).
- Ctrl+C is handled gracefully: sets the `_interrupted` flag and stops after the current step finishes.
- Logging is set up via `setup_cli_logging(map_name)`.
- A preflight check runs before the pipeline begins.
- If a `--sync-config` JSON file is provided, the values `v_override`, `a_offset`, and `marker_preroll_ms` are loaded from it.

### Interactive Sync Refinement Loop (line 1813)

After the pipeline completes, the CLI enters a `while True` loop presenting the following options:

| Option | Action |
|---|---|
| 0 | Exit (all good) |
| 1 | Sync Beatgrid -- set `a_offset = v_override` |
| 2 | Sync Beatgrid -- pad audio to match video duration difference (uses `ffprobe`) |
| 3 | Custom values -- manually enter `v_override` and `a_offset`, regenerates configs |
| 4 | Preview with `ffplay` (launches an `ffmpeg` pipe to `ffplay`, blocks until window is closed) |

Options 1 through 3 call `reprocess_audio()` and then launch the preview.

---

## Batch Installation (`batch_install_maps.py`)

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `maps_dir` (positional) | No | `MapDownloads/` in script directory | Path to folder containing map subfolders |
| `--jd21-path` | No | Auto-detected | Path to JD installation root |
| `--quality` | No | `ultra_hd` | Video quality for all maps (same choices as single CLI) |
| `--skip-existing` | No | Off | Skip maps that already have an installed folder in `MAPS/` |
| `--only MAP [MAP ...]` | No | None | Only install these specific map names |
| `--exclude`, `--ignore MAP [MAP ...]` | No | None | Skip these specific map names |
| `--ignore-non-ascii` | No | Off | Skip maps that contain non-ASCII characters in their name |
| `--interactive` | No | On | Prompt for string replacement when non-ASCII metadata is found |
| `--auto-strip` | No | Off | Silently auto-strip non-ASCII metadata instead of prompting |

### Folder Structure Expected

```
maps_dir/
  SongA/
    assets.html
    nohud.html
  SongB/
    assets.html
    nohud.html
```

Each subfolder under `maps_dir` represents one map and must contain both `assets.html` and `nohud.html`.

### Two-Phase Execution

The batch installer splits work into two phases to account for CDN link expiration:

- **Phase 1 (Download):** Runs steps 01-02 for each map while CDN links are still fresh.
- **Phase 2 (Process):** Runs steps 03-14 for each map that was successfully downloaded. These steps are entirely local and do not depend on remote resources.

### Features

- Auto-detects the codename from asset URLs.
- Auto-detects existing video quality from already-downloaded files.
- Supports `--readjust DOWNLOAD_DIR` for offset readjustment, loading settings from `installer_settings.json`.
- Runs the preflight check using the first map's HTML files.
- Ctrl+C is handled with graceful interruption.
- Prints per-phase and final summary with OK / FAILED / SKIPPED counts.
- Operates in non-interactive mode (`state._interactive = False`), so no `input()` calls are made.

---

## Preflight Check (`map_installer.py:391`)

The preflight check runs before any pipeline work begins. It verifies the following, in order:

**Diagnostics (informational):**

- Python version
- Operating system
- Encoding
- Current working directory

**Critical checks:**

- `ffmpeg` is available (offers automatic installation if missing)
- JD2021 game data is found via the `resolve_game_paths()` cascade
- SkuScene registry file exists
- Path safety: no spaces, non-ASCII characters, or `Program Files` in paths
- Write permission to the game directory
- Disk space (warns if below 500 MB)

**Project dependency checks:**

- `ipk_unpack`
- `ckd_decode`
- `json_to_lua`
- `xtx_extractor`
- `Pillow` (Python library)

**Input file checks:**

- Asset HTML file exists
- NOHUD HTML file exists

**Optional tool checks:**

- `ffplay` (used for sync preview)
- `ffprobe` (used for duration calculation)
