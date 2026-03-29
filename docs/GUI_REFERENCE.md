# GUI Reference

This document describes the graphical user interface defined in `ui/main_window.py`.

---

## Overview

- **Main class:** `MainWindow` (subclass of `QMainWindow`)
- **Toolkit:** PyQt6
- **Minimum window size:** 1000 × 650
- **Window title:** "JD2021 Map Installer v2"
- **Entry point:** `python -m jd2021_installer.main`

---

## Window Layout

The main window uses a `QVBoxLayout` containing a horizontal `QSplitter` (controls + log), a `QProgressBar`, and a `QStatusBar`.

```
┌──────────────────────────────────────────────────────────────┐
│                    JD2021 Map Installer v2                    │
├──────────────────────┬───────────────────────────────────────┤
│                      │                                       │
│   Left Panel         │         Right Panel                   │
│   (Controls)         │         (Log Output)                  │
│                      │                                       │
│   ┌────────────────┐ │   ┌───────────────────────────────┐   │
│   │ Title Label    │ │   │                               │   │
│   └────────────────┘ │   │   QTextEdit (read-only)       │   │
│   ┌────────────────┐ │   │   "Log output will appear     │   │
│   │ Load HTML/URLs │ │   │    here..."                   │   │
│   └────────────────┘ │   │                               │   │
│   ┌────────────────┐ │   │                               │   │
│   │ Load IPK       │ │   │                               │   │
│   └────────────────┘ │   │                               │   │
│   ┌────────────────┐ │   │                               │   │
│   │ Install Map    │ │   └───────────────────────────────┘   │
│   │  (disabled)    │ │                                       │
│   └────────────────┘ │                                       │
│                      │                                       │
├──────────────────────┴───────────────────────────────────────┤
│   [████████████████████████░░░░░░░░░░░░░░░]  Progress Bar    │
├──────────────────────────────────────────────────────────────┤
│   Ready                                        Status Bar    │
└──────────────────────────────────────────────────────────────┘
```

### Splitter Proportions

The left panel (controls) occupies ~350px and the right panel (log) occupies ~650px by default. The user can drag the splitter to adjust.

---

## Controls (Left Panel)

### Title Label

A bold 18px label: **"JD2021 Map Installer"**.

### Load HTML / URLs

`QPushButton` — Opens a file dialog for selecting asset HTML and/or NOHUD HTML files. Initializes a `WebPlaywrightExtractor` with the selected files.

### Load IPK Archive

`QPushButton` — Opens a file dialog for selecting an Xbox 360 `.ipk` file. Initializes an `ArchiveIPKExtractor` with the selected file.

### Install Map

`QPushButton` — Starts the full extraction → normalization → installation pipeline. **Disabled by default** until a source is loaded.

When clicked:
1. The button and other controls are **disabled**.
2. An `ExtractAndNormalizeWorker` is created and moved to a new `QThread`.
3. The thread starts, triggering the worker's `run()` method.
4. Progress, status, and error signals update the UI in real time.
5. On completion, the `finished` signal re-enables controls.

---

## Log Output (Right Panel)

A `QTextEdit` widget in **read-only** mode with placeholder text: *"Log output will appear here..."*

All pipeline output is routed here via the `append_log()` method, which the workers' `status` signals connect to. This provides a live, scrollable log of the entire extraction → normalization → installation process.

---

## Progress Bar

A `QProgressBar` at the bottom of the main layout. Updated via the `set_progress(value)` method, which workers call through their `progress` signal (0–100).

| Value | Phase |
|-------|-------|
| 0 | Idle |
| 10 | Extraction started |
| 50 | Normalization started |
| 100 | Complete |

---

## Status Bar

A `QStatusBar` showing the current operation status. Updated via `set_status(text)`.

Default message: **"Ready"**.

During pipeline execution, shows messages like:
- *"Extracting map data..."*
- *"Normalizing map data..."*
- *"Installing {codename}..."*
- *"Installation complete!"*

---

## Thread Lifecycle

The complete QThread lifecycle for a map installation:

```
User clicks "Install Map"
        │
        ▼
1. Create worker (ExtractAndNormalizeWorker or InstallMapWorker)
2. Create QThread
3. worker.moveToThread(thread)
4. Connect signals:
   - thread.started  → worker.run
   - worker.progress → MainWindow.set_progress
   - worker.status   → MainWindow.set_status / append_log
   - worker.error    → MainWindow.append_log
   - worker.finished → thread.quit
   - worker.finished → worker.deleteLater
   - thread.finished → thread.deleteLater
5. Disable UI inputs
6. thread.start()
        │
        ▼ (background thread)
7. worker.run() executes
   - Emits progress/status signals throughout
   - On exception: logs traceback, emits error signal
   - Emits finished signal with result
        │
        ▼ (main thread, via signal)
8. Handle result
9. Re-enable UI inputs
10. Update status bar
```

**Key guarantee:** The worker never directly accesses any widget. All UI updates go through signal-slot connections that Qt automatically marshals to the main thread.

---

## API Methods

| Method | Purpose |
|--------|---------|
| `append_log(text: str)` | Append text to the log output panel |
| `set_progress(value: int)` | Set the progress bar value (0–100) |
| `set_status(text: str)` | Update the status bar message |
