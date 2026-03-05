# JD2021 Map Installer GUI Reference

This document describes the graphical user interface defined in `gui_installer.py`.

## Overview

- **Main class:** `MapInstallerGUI` (line 127)
- **Minimum window size:** 1000x900
- **Window title:** "JD2021 Map Installer"
- **Toolkit:** Tkinter

---

## Sections of the GUI

### Configuration Section

- Warning label about 30-minute link expiration.
- **Map Name** field -- auto-filled from Asset HTML, read-only unless detection fails.
- **Asset HTML** field with Browse button.
- **NOHUD HTML** field with Browse button.
- **Game Directory** field with Browse button -- auto-detected from cache or `SCRIPT_DIR`.
- **Video Quality** dropdown with options: `ultra_hd`, `ultra`, `high_hd`, `high`, `mid_hd`, `mid`, `low_hd`, `low` (default: `ultra_hd`).
- **Pre-flight Check** button -- validates file paths and tools before installing.
- **Install Map** button -- starts the pipeline in a background thread (disabled until preflight passes).
- **Clear Path Cache** button -- deletes `installer_paths.json`.

### Installation Progress Section (left panel)

- 16 step labels showing pipeline progress with checkmarks.
- Steps are listed from the `PIPELINE_STEPS` list.

### Preview Section (right panel)

- Black container 480x270 for embedded video preview.
- "No Preview" overlay displayed when no video is available.
- Media controls: seek bar, time labels, play/pause/stop buttons.
- Preview uses ffmpeg piping raw RGB24 frames to PIL, then rendered on a Tkinter canvas.
- Audio-only ffplay process handles audio playback.
- Frame rendering is synced to wall clock at `PREVIEW_FPS = 24` fps.
- Seek UI updates every `PREVIEW_POLL_FRAMES = 6` frames (approximately 250ms).

### Log Section

- `TextWidgetHandler` (line 78) routes logging records to a `tk.Text` widget via a queue.
- Queue is polled every 50ms.
- `StdoutToLogger` (line 105) captures stray `print()` calls and routes them through the logging system.

### Sync Refinement Section

This section appears after the pipeline completes.

- **v_override** (Video Override) control with `DoubleVar`.
- **a_offset** (Audio Offset) control with `DoubleVar`.
- **v_override enabled** checkbox (`BooleanVar`).
- Increment/decrement buttons for fine adjustment.
- **Preview** launch button.
- **Apply & Finish** button.

---

## Key Behaviors

- The pipeline runs in a background `threading.Thread`.
- The `_interactive` flag is set to `False` to prevent `input()` calls during GUI operation.
- Non-ASCII metadata is handled via `Tkinter.simpledialog`.
- `ToolTip` class (line 30) provides hover tooltips with a delay of `TOOLTIP_DELAY_MS = 500`ms.
- `StdoutToLogger` wraps `sys.stdout` and `sys.stderr` to capture `print()` output and forward it to logging.
- On window close: kills preview processes, restores `stdout`/`stderr`, and destroys the window.
- Post-apply cleanup prompt asks the user whether to delete ZIPs, extracted scenes, and CKDs.
- Global settings (default quality, offsets, etc.) are managed via `installer_settings.json` and the Settings dialog.
- FFmpeg auto-install is offered if it is missing during preflight.
