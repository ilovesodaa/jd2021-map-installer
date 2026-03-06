# JD2021 Map Installer GUI Reference

This document describes the graphical user interface defined in `gui_installer.py`.

## Overview

- **Main class:** `MapInstallerGUI`
- **Minimum window size:** 1000x900
- **Window title:** "JD2021 Map Installer"
- **Toolkit:** Tkinter

---

## Install Panel

The top section of the GUI contains all source configuration and installation controls.

### Mode Selector

A combobox selects the installation source mode. Changing the mode swaps the visible input fields and adjusts button visibility.

| Mode | Description | Visible Fields |
|---|---|---|
| **fetch** | Enter a codename to auto-fetch from Discord. | Codename entry |
| **html** | Provide saved Asset HTML and NOHUD HTML files. | Asset HTML + NOHUD HTML entries with Browse buttons |
| **ipk** | Install from an Xbox 360 `.ipk` archive. | IPK File entry with Browse button |
| **manual** | Point at a pre-extracted folder with audio/video. | Source Folder + Audio + Video entries with Browse buttons |
| **batch** | Batch-install multiple maps from a folder of subfolders. | Maps Folder entry with Browse button |

**Manual submode** — When `manual` is selected, an additional Submode combobox appears with options: `auto`, `unpacked_ipk`, `downloaded_assets`.

### Mode-Specific Behavior

- **Fetch mode**: Analyze/Prepare buttons are hidden. Enter a codename and click Install directly.
- **IPK mode**: Video Quality dropdown is hidden (IPK archives contain only one video quality). Audio/video entries are hidden (both are inside the IPK).
- **HTML mode**: Shows a warning label about 30-minute link expiration.
- **All non-fetch modes**: Analyze and Prepare buttons are shown.

### Analyze / Prepare Workflow

For non-fetch modes, the workflow is:

1. **Select a source** (file or folder depending on mode).
2. **Click Analyze** — Inspects the source to detect map codename, available audio/video files, and source type.
3. **Click Prepare** — Downloads or extracts assets as needed (e.g., unpacks IPK, downloads from CDN links).
4. **Click Install** — Runs the full installation pipeline.

A status label next to the buttons shows the current state (e.g., "Mode: ipk. Select a source file and click Analyze.").

### Common Fields

- **Game Directory** — Path to the Just Dance 2021 installation folder. Auto-detected from cache (`installer_paths.json`) or script directory. Browse button for manual selection.
- **Video Quality** — Dropdown with 8 tiers: `ultra_hd`, `ultra`, `high_hd`, `high`, `mid_hd`, `mid`, `low_hd`, `low`. Hidden in IPK mode. Default loaded from `installer_settings.json`.

### Button Row

| Button | Action |
|---|---|
| **Install** | Runs the installation pipeline for the currently selected mode. Disabled until preflight passes (unless `skip_preflight` is enabled in settings). |
| **Pre-flight Check** | Validates file paths, ffmpeg/ffplay availability, game directory, and required tools. |
| **Clear Path Cache** | Deletes `installer_paths.json` to force re-scan of the game directory. |
| **Re-adjust Offset** | Re-opens sync refinement for an already-installed map. Select the map's download folder. |
| **Settings** | Opens the settings dialog (preflight, notifications, cleanup, quality defaults). |
| **Reset State** | Clears all inputs, progress, preview, and pipeline state without restarting the app. Also clears hidden audio/video entries from previous runs. |

---

## Installation Progress (Left Panel)

Displays pipeline step status with checkmarks. Steps are listed from the `PIPELINE_STEPS` list in `map_installer.py`. Each step shows one of:
- `[  ]` — Pending
- `[>>]` — Running
- Checkmark — Complete
- `[!!]` — Failed

---

## Preview Section (Right Panel)

Embedded video/audio preview for sync validation.

- **Video canvas**: 480x270 black container. Displays "No Preview" overlay when no video is loaded.
- **Frame rendering**: FFmpeg pipes raw RGB24 frames to PIL. Rendered on a Tkinter canvas at `PREVIEW_FPS = 24` fps, synced to wall clock.
- **Audio**: Separate ffplay process handles audio playback. Supports `-af adelay` for positive audio offsets.
- **Media controls**: Seek bar, current/total time labels, play/pause/stop buttons. Seek UI updates every `PREVIEW_POLL_FRAMES = 6` frames (~250ms).
- **Preview Manager**: `gui_preview.py` defines a `PreviewManager` class that handles all media lifecycle (launch, stop, seek, duration probing).

---

## Log Output

Dark-themed text widget showing pipeline output.

- `TextWidgetHandler` routes log records to the widget via a queue polled every 50ms.
- `StdoutToLogger` captures stray `print()` calls and routes them through the logging system.
- Console-style appearance: dark background (`#1e1e1e`), light text (`#cccccc`), Consolas font.

---

## Sync Refinement Section

Appears at the bottom. Controls are disabled until the pipeline completes, then enabled automatically.

### Controls

- **VIDEO_OFFSET** — Checkbutton + value display + increment/decrement buttons.
  - Disabled by default. Checking it enables manual video start time override.
  - When enabled, shows a warning popup (unless `suppress_popup=True`).
  - For IPK maps, auto-enabled after installation (with popup suppressed).
  - Increment/decrement buttons: `-1`, `-0.1`, `-0.01`, `-0.001`, `+0.001`, `+0.01`, `+0.1`, `+1`.

- **AUDIO_OFFSET** — Label + value display + same increment/decrement buttons.
  - Positive values pad the audio with silence at the start.
  - Negative values trim the audio from the beginning.

### Action Buttons

| Button | Action |
|---|---|
| **Sync Beatgrid** | Copies VIDEO_OFFSET to AUDIO_OFFSET (1:1 alignment). Only enabled when VIDEO_OFFSET is checked. |
| **Pad Audio** | Uses ffprobe to measure video/audio duration difference and sets AUDIO_OFFSET to pad audio with silence so both end at the same time. |
| **Preview** | Launches embedded video + audio preview with current offset values. |
| **Stop Preview** | Kills the preview processes. |
| **Apply & Finish** | Applies the current offsets, re-runs audio conversion, regenerates AMB files, and writes the final game files. Prompts for post-install cleanup. |

### IPK-Specific Sync Warning

After installing an IPK map, an orange bold warning label appears at the top of the Sync Refinement section:

> "IPK maps require manual Video Offset adjustment. X360 binaries do not store video timing data, so the calculated offset is an approximation. Enable VIDEO_OFFSET and adjust until the video matches the beat."

VIDEO_OFFSET is auto-enabled for IPK maps. The completion dialog also explains the need for manual adjustment.

### Auto-Preview

After pipeline completion, the preview launches automatically so users can immediately validate sync timing.

---

## Settings Dialog

Accessible via the **Settings** button. Managed by `gui_settings.py`.

Settings are persisted to `installer_settings.json` and include:
- Default video quality
- Skip preflight check
- Suppress offset notification popup
- Post-install cleanup preferences

---

## Map Config Persistence

Per-map sync settings (video offset, audio offset, quality) are saved automatically. When reinstalling a map that was previously configured, the saved offsets are reloaded and applied to the Sync Refinement panel.

---

## Stale State Handling

When browsing for a new IPK file (or any primary source file), the GUI:
1. Clears the internal `_source_spec` so the old map's analysis is discarded.
2. Clears hidden `mode_audio_entry` and `mode_video_entry` to prevent carrying over the previous map's audio/video paths.
3. For IPK mode, always passes empty strings for audio/video to `analyze_ipk_file_mode`, forcing fresh auto-detection from the IPK contents.

The **Reset State** button performs a full cleanup of all entries and internal state.

---

## Key Behaviors

- The pipeline runs in a background `threading.Thread` — the GUI remains responsive during installation.
- The `_interactive` flag is set to `False` to prevent `input()` calls during GUI operation.
- Non-ASCII metadata is handled via `tkinter.simpledialog`.
- `ToolTip` class provides hover tooltips with a delay of `TOOLTIP_DELAY_MS` (default 500ms).
- On window close: kills preview processes, restores `stdout`/`stderr`, and destroys the window.
- FFmpeg auto-install is offered if it is missing during preflight.
- Log files are written to `logs/install_{map_name}_{timestamp}.log`.
