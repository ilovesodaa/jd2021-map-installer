# Architecture

This document describes the internal architecture of the JD2021 Map Installer v2: how the components relate to each other, data flows through the pipeline, and the key design patterns used throughout.

---

## Component Map

```
                          User Input
                              │
                         main.py
                    QApplication + setup_logging()
                              │
                     ui/main_window.py
                       MainWindow (PyQt6)
                              │
                  ┌───────────┴───────────┐
                  │                       │
         "Load HTML/URLs"          "Load IPK Archive"
                  │                       │
          ui/workers/pipeline_workers.py
          ┌───────────────────────────────┐
          │  ExtractAndNormalizeWorker     │ ← QObject on QThread
          │  InstallMapWorker             │ ← QObject on QThread
          └──────┬────────────┬───────────┘
                 │            │
    ┌────────────┘            └────────────┐
    │                                      │
extractors/                           parsers/
├── base.py (BaseExtractor ABC)       ├── normalizer.py
├── web_playwright.py                 └── binary_ckd.py
└── archive_ipk.py                         │
         │                                 │
         └──────── raw files ──────────────┘
                       │
              NormalizedMapData
                       │
              installers/
              ├── game_writer.py
              └── media_processor.py
                       │
              UbiArt game files
```

### Entry Point

| Module | Description |
|--------|-------------|
| `main.py` | Creates `QApplication`, configures logging, and shows `MainWindow`. Entry via `python -m jd2021_installer.main`. |

### Core Modules

| Package | Module | Role |
|---------|--------|------|
| `core/` | `models.py` | All data models: `NormalizedMapData`, `SongDescription`, `MusicTrackStructure`, `DanceTape`, `KaraokeTape`, `CinematicTape`, and their sub-models (clips, signatures, sections, colors, media). |
| `core/` | `config.py` | `AppConfig` (Pydantic `BaseModel`): paths, quality tiers, download settings, UbiArt engine constants, FFmpeg paths. Supports env vars with prefix `JD2021_`. |
| `core/` | `exceptions.py` | Typed exception hierarchy rooted at `JDInstallerError`. Branches: `ExtractionError`, `ParseError`, `NormalizationError`, `InstallationError`, each with specific subclasses. |
| `extractors/` | `base.py` | `BaseExtractor` ABC defining `extract(output_dir) → Path` and `get_codename() → str`. |
| `extractors/` | `web_playwright.py` | `WebPlaywrightExtractor`: downloads assets from HTML files or live-scrapes via Playwright. Includes URL extraction, codename detection, quality-based video selection, and retry logic. |
| `extractors/` | `archive_ipk.py` | `ArchiveIPKExtractor`: extracts `.ipk` archives (big-endian UbiArt format, zlib/lzma decompression, path-traversal protection). |
| `parsers/` | `normalizer.py` | `normalize(directory, codename)`: the single public normalizer entry-point. Loads CKD files (JSON-first, binary fallback), discovers media assets, validates, and produces `NormalizedMapData`. |
| `parsers/` | `binary_ckd.py` | Stateless binary CKD parser. `BinaryReader` for big-endian sequential reads. Dispatches on Actor header CRC to parse musictracks, songdescs, dtapes, ktapes, and cinematic tapes into typed dataclasses. |
| `installers/` | `game_writer.py` | `write_game_files(map_data, target_dir)`: generates UbiArt `.trk`, `.tpl`, `.act`, `.isc`, `.stape`, `.sfi` files from `NormalizedMapData`. |
| `installers/` | `media_processor.py` | FFmpeg/Pillow wrappers: `run_ffmpeg()`, `run_ffprobe()`, `copy_video()`, `generate_map_preview()`, `copy_audio()`, `generate_audio_preview()`, `convert_image()`, `generate_cover_tga()`. |
| `ui/` | `main_window.py` | `MainWindow(QMainWindow)`: split-panel layout with controls (left) and log output (right), progress bar, status bar. |
| `ui/workers/` | `pipeline_workers.py` | `ExtractAndNormalizeWorker` and `InstallMapWorker`: `QObject` workers that run on `QThread` and communicate via `pyqtSignal`. |

---

## Concurrency Model

The GUI must remain responsive during heavy I/O operations (downloading, parsing, file writing). V2 achieves this with the **QThread + moveToThread** pattern:

```
Main Thread (Qt Event Loop)          Background QThread
─────────────────────────────       ──────────────────────────
MainWindow                          ExtractAndNormalizeWorker
  │                                   │
  ├── creates worker + thread         │
  ├── worker.moveToThread(thread)     │
  ├── thread.started → worker.run    ──→ run() executes
  │                                   │
  │  ← progress.emit(50) ──────────  ├── emit progress signal
  │  ← status.emit("Extracting...")  ├── emit status signal
  │  ← error.emit("Failed: ...")     ├── emit error signal (on exception)
  │  ← finished.emit(map_data) ────  └── emit finished signal
  │                                   │
  ├── worker.finished → thread.quit   │
  ├── re-enable UI inputs             │
  └── display results                 │
```

**Key rules:**
- Workers **never** touch widgets directly — all communication is through signals.
- The `finished` signal carries the result (`NormalizedMapData` or `bool`) so the main thread can proceed.
- Exception tracebacks are logged via `logger.error()` and the error message is emitted through the `error` signal.

---

## Scraping Model

`WebPlaywrightExtractor` supports two modes:

1. **HTML file mode** (current) — reads pre-saved HTML files, extracts URLs via regex, downloads assets with `urllib.request`.
2. **Live scraping mode** (via `scrape_live()`) — launches headless Chromium via `playwright.async_api`, navigates to a page, waits for `networkidle`, and extracts URLs from the page content.

Live scraping runs in an `asyncio` event loop. Since Qt's event loop and `asyncio` cannot share the same thread, the Playwright coroutine is executed inside a `QThread` worker, which runs its own `asyncio.run()`.

---

## Data Flow

### Single Map Install

```
1. User provides: HTML files (or IPK path) via GUI
                    │
2. MainWindow creates appropriate extractor:
   - WebPlaywrightExtractor (for HTML/URLs)
   - ArchiveIPKExtractor (for .ipk files)
                    │
3. ExtractAndNormalizeWorker runs on QThread:
   ┌────────────────────────────────────┐
   │  Extraction Phase                  │
   │  extractor.extract(output_dir)     │
   │  → downloads/extracts raw files    │
   │                                    │
   │  Normalization Phase               │
   │  normalizer.normalize(dir, code)   │
   │  → loads CKDs, discovers media     │
   │  → produces NormalizedMapData      │
   └────────────────┬───────────────────┘
                    │
4. InstallMapWorker runs on QThread:
   ┌────────────────────────────────────┐
   │  Installation Phase                │
   │  write_game_files(data, target)    │
   │  → generates .trk/.tpl/.act/.isc   │
   │  → media processing (FFmpeg/Pillow)│
   └────────────────┬───────────────────┘
                    │
5. Finished signal → UI re-enabled
```

---

## Exception Hierarchy

```
JDInstallerError
├── ExtractionError
│   ├── IPKExtractionError
│   ├── WebExtractionError
│   └── DownloadError (url, http_code)
├── ParseError
│   └── BinaryCKDParseError
├── NormalizationError
│   └── ValidationError
└── InstallationError
    ├── MediaProcessingError
    ├── GameWriterError
    └── InsufficientDiskSpaceError
```

All pipeline stages raise typed exceptions so the GUI can present precise error messages. Exceptions bubble up through the worker's `try/except` block and are emitted via the `error` signal.

---

## Logging Architecture

```
jd2021 (root)
├── jd2021.ui.main_window
├── jd2021.ui.workers
├── jd2021.extractors.base
├── jd2021.extractors.web_playwright
├── jd2021.extractors.archive_ipk
├── jd2021.parsers.normalizer
├── jd2021.parsers.binary_ckd
├── jd2021.installers.game_writer
└── jd2021.installers.media_processor
```

The root logger `jd2021` is configured in `main.py` with a `StreamHandler` writing to `sys.stdout`. Each module creates its own child logger via `logging.getLogger("jd2021.<module>")`.

---

## Key Design Decisions

### Status Override for JD2021 Maps
Maps originally released for JD2021 have `Status = 12` (ObjectiveLocked) in their JDU metadata. The game writer overrides this to `Status = 3` (Available) so maps are immediately playable.

### JDVersion Capping
`JDVersion` and `OriginalJDVersion` are capped between `min_jd_version` (2014) and `max_jd_version` (2021) to prevent `GameManagerConfig` crashes when installing maps from JD2022+ that reference config entries not present in the 2021 engine.

### Platform Scene Preference
The extractor prefers DURANGO (Xbox One) scene archives over NX (Switch) and SCARLETT (Xbox Series). DURANGO uses Kinect gesture files that are format-compatible with the PC adapter, while ORBIS (PS4) uses an incompatible format.

### SSL Verification Disabled
`web_playwright.py` disables SSL certificate verification globally for Ubisoft CDN compatibility — some systems fail to verify the CDN's certificates.

### JSON-First CKD Loading
The normalizer tries to parse CKD files as JSON first (after stripping null padding), falling back to the binary parser only when JSON parsing fails. This supports both modern JSON CKDs and legacy binary formats transparently.
