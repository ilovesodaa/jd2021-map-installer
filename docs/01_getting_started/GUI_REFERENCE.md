# GUI Reference

> **Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This document describes the graphical user interface defined in `jd2021_installer/ui/main_window.py`.

---

## Overview

- **Main class:** `MainWindow` (subclass of `QMainWindow`)
- **Toolkit:** PyQt6
- **Current minimum window size (default config):** 1000 × 920
- **Window title:** "JD2021 Map Installer v2"
- **Entry point:** `python -m jd2021_installer.main`

---

## Reality Check: Legacy vs Current GUI

The older two-button/two-pane GUI description is deprecated.

Current V2 GUI is modular and mode-driven:
1. Left column: mode selection, configuration, actions, progress checklist.
2. Right column: embedded media preview, sync refinement controls, and live log console.
3. Bottom status bar: concise current status text.

---

## Window Layout

The main window uses a central `QHBoxLayout` with two responsive columns.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        JD2021 Map Installer v2                             │
├──────────────────────────┬──────────────────────────────────────────────────┤
│ Left Column              │ Right Column                                     │
│ (~40% width)             │ (~60% width)                                     │
│                          │                                                  │
│ [Mode Selector]          │ [Preview Widget]                                 │
│ [Configuration Panel]    │   - embedded video canvas                        │
│ [Action Panel]           │   - seek + preview controls                      │
│ [Progress Panel]         │                                                  │
│   - checklist            │ [Sync Refinement Widget]                         │
│   - progress bar         │   - audio/video offsets                          │
│                          │   - apply/pad/sync/nav controls                  │
│                          │                                                  │
│                          │ [Log Console]                                    │
├──────────────────────────┴──────────────────────────────────────────────────┤
│ Status Bar ("Ready", mode/install/readjust status, warnings)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Layout Details

- Left panel minimum width: ~380px.
- Right panel minimum width: ~500px.
- Stretch ratio defaults to roughly 4:6 (left:right).
- No user-facing splitter is used in current `MainWindow`; proportional sizing is layout-driven.

---

## Source Modes (Mode Selector)

The mode selector (`ModeSelectorWidget`) supports five ingestion modes:

1. **Fetch (Codename)**
   Input: one or more codenames (comma-separated).
   Requires Playwright Chromium availability.
2. **HTML File**
   Input: Asset HTML + NOHUD HTML.
   Includes warnings about expiring links and auto-pair detection.
3. **IPK Archive**
   Input: `.ipk` archive path.
4. **Batch (Directory)**
   Input: directory containing install candidates.
5. **Manual (Directory)**
   Input: manual file set/root folder for advanced workflows.

Mode changes reset stale targets and trigger mode-specific validation before install.

---

## Configuration Panel

`ConfigWidget` exposes:

1. **Game Directory**
   `Auto-Detect` via path discovery heuristics.
   `Browse...` manual directory selection.
2. **Video Quality**
   Quality tier selector used by extraction/install flow.

Configuration is persisted in `installer_settings.json` and reloaded at startup.

---

## Action Panel

`ActionWidget` contains the primary operator actions:

1. **Install Map**
2. **Pre-flight Check**
3. **Re-adjust Offset**
4. **Settings**
5. **Reset State**

### Pre-flight Check Coverage

Pre-flight validates:
1. Game directory existence and write access.
2. Presence of required map scene config under the selected game path.
3. Mode-specific source inputs.
4. Runtime dependencies (Python packages, media binaries, Playwright browser when Fetch mode is active).

---

## Progress and Logging

### Progress Panel (`ProgressLogWidget`)

Displays:
1. A step checklist with status icons (`WAITING`, `IN_PROGRESS`, `DONE`, `ERROR`).
2. A `QProgressBar` (0-100).

Representative checklist stages include extraction, normalization, decode/convert steps, AMB handling, tape conversion, and SkuScene registration.

### Log Console (`LogConsoleWidget`)

- Read-only `QPlainTextEdit` with placeholder text.
- Connected to a Qt-safe logging handler; worker logs are marshaled to UI safely.
- Includes both high-level progress and detailed diagnostics.

---

## Preview and Sync Refinement

### Preview Widget (`PreviewWidget`)

- Embedded preview canvas with seek controls and `Preview` / `Stop` behavior.
- Uses FFmpeg/FFplay-backed playback orchestration from background worker threads.
- Supports offset-aware relaunch when values change.

### Sync Refinement Widget (`SyncRefinementWidget`)

Controls:
1. Audio offset (ms)
2. Optional video offset override (ms)
3. Increment/decrement buttons for rapid tuning
4. `Pad Audio` utility
5. `Sync Beatgrid` helper
6. `Apply Offset`
7. Multi-map navigation (`Prev Map` / `Next Map`) in batch/readjust contexts

Readjust profiles can lock or disable specific controls (for example, IPK-focused readjust behavior differs from fetch/html behavior).

---

## Readjust Workflow (GUI Surface)

`Re-adjust Offset` opens a selector dialog backed by `map_readjust_index.json` metadata.

Users can:
1. Select one or more indexed maps.
2. Browse a source folder manually when available.
3. Load maps into preview + sync refinement.
4. Apply offsets in batch/per-map flow depending on context.

If source media no longer exists, readjust can be unavailable for that entry.

---

## Critical V2 Limitations and Quirks

### Intro AMB (Important)

Intro AMB generation/trigger attempts are currently under an emergency mitigation path. In practice, intro AMB is intentionally treated as disabled and silent intro placeholders are expected until redesign/parity work is finalized.

### IPK Video Timing

For many IPK maps, `videoStartTime` remains approximate by source design. Manual video offset refinement in the GUI is expected and normal.

### Dependency Sensitivity

Preview/install quality depends on local toolchain availability:
1. FFmpeg/FFprobe are required for key media operations.
2. vgmstream is required for specific decode paths (notably XMA2/X360 cases).
3. Playwright Chromium is required for Fetch mode.

The app includes dependency guardrails and install prompts, but missing/partial toolchains still produce degraded workflows.

### Path/Case Compatibility

Ambient/media path handling includes compatibility fallbacks for mixed path casing conventions (`Audio/AMB` vs `audio/amb` style layouts).

---

## Status Bar

`QStatusBar` remains the concise operation summary surface.

Default message: **"Ready"**.

Typical runtime messages include:
1. Mode changes
2. Pre-flight results
3. Install progress state
4. Readjust context state
5. Completion/failure summaries

---

## Thread Lifecycle

All heavy operations are worker-driven on `QThread` instances.

Typical lifecycle:

```
User triggers action (Install / Apply / Batch / Readjust)
                  │
                  ▼
1. Build worker for the specific task
2. Create QThread
3. worker.moveToThread(thread)
4. Connect signals:
        - thread.started  -> worker.run
        - worker.progress -> progress panel
        - worker.status   -> status/log handlers
        - worker.error    -> error/log handlers
        - worker.finished -> completion handlers + thread.quit
5. Lock interactive UI areas while active
6. thread.start()
                  │
                  ▼
7. Worker performs task off UI thread
8. Finished/error signals marshal back to main thread
9. UI unlock + status refresh + thread cleanup
```

**Key guarantee:** Workers do not update Qt widgets directly; UI updates flow through Qt signal-slot boundaries.

---

## API Methods (MainWindow Compatibility Surface)

| Method | Purpose |
|--------|---------|
| `append_log(text: str)` | Append/log text to the GUI console through logger routing |
| `set_progress(value: int)` | Update progress bar value via progress panel |
| `set_status(text: str)` | Update status bar message |
