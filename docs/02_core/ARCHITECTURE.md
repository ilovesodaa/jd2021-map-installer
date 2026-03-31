# Architecture
**Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This document describes the internal architecture of the JD2021 Map Installer v2: how components relate to each other, how data flows through the pipeline, and the key design patterns used throughout.

---

## Current Limitations and Behavioral Notes (Read First)

1. Intro AMB behavior is intentionally limited right now.
   Intro AMB attempts are temporarily disabled by a global mitigation path, and silent intro placeholders are expected until the AMB redesign is completed and parity-validated.
2. IPK video start timing remains approximate by design.
   Many IPK sources do not carry reliable lead-in metadata, so manual video offset tuning is expected after install.
3. Dependency health directly affects behavior.
   Missing FFmpeg/FFprobe or vgmstream can degrade conversion and preview paths; missing Playwright Chromium blocks Fetch workflows.
4. Parity work is ongoing.
   Core V2 pipeline is stable, but map-specific edge-case regressions are still possible in complex parity-sensitive paths.

---

## Component Map

                                 User Input
                                   │
                              main.py
                     QApplication + setup_logging()
                                   │
                          ui/main_window.py
                            MainWindow (PyQt6)
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
    Source Ingestion         Install/Write           Readjust/Sync
    (mode-driven)             Pipeline               Workflow Layer
          │                        │                        │
    ui/workers/pipeline_workers.py and related worker modules
    ┌──────────────────────────────────────────────────────────────┐
    │ ExtractAndNormalizeWorker (QObject on QThread)              │
    │ InstallMapWorker (QObject on QThread)                       │
    │ Readjust-oriented workers (batch/apply/index-aware)         │
    └───────────────────────┬──────────────────────────────────────┘
                            │
          ┌─────────────────┼──────────────────┐
          │                 │                  │
      extractors/        parsers/         installers/
      - web/fetch        - normalizer     - game writer
      - archive_ipk      - binary_ckd     - media processor
      - batch/manual                       - ambient handling
                                            - scene registration
                            │
                      NormalizedMapData
                            │
                  UbiArt-ready game files

### Entry Point

| Module | Description |
|--------|-------------|
| main.py | Creates QApplication, configures logging, and shows MainWindow. Entry via python -m jd2021_installer.main. |

### Core Modules

| Package | Module | Role |
|---------|--------|------|
| core/ | models.py | Data models including NormalizedMapData and typed structures for song description, music track, tapes, clips, sections, signatures, colors, and media. |
| core/ | config.py | AppConfig (Pydantic v2 BaseModel): paths, quality tiers, download behavior, engine constants, FFmpeg paths, runtime options. Supports JD2021_ environment overrides. |
| core/ | exceptions.py | Typed exception hierarchy rooted at JDInstallerError for extraction, parsing, normalization, and installation failures. |
| extractors/ | base.py | BaseExtractor contract for extraction and codename resolution. |
| extractors/ | web_playwright.py | Fetch and HTML ingestion path with URL extraction, codename detection, quality/platform selection, retries, and Playwright-assisted workflows. |
| extractors/ | archive_ipk.py | IPK extraction path with decompression and path safety protections. |
| parsers/ | normalizer.py | Canonical normalize entrypoint. Loads CKD data (JSON-first, binary fallback), discovers media, validates, and emits NormalizedMapData. |
| parsers/ | binary_ckd.py | Binary CKD parser for cooked structures (musictrack, songdesc, dance/karaoke/cinematic tapes, related payloads). |
| installers/ | game_writer.py | Writes core UbiArt map outputs such as trk, tpl, act, isc, stape, sfi and related map assets. |
| installers/ | media_processor.py | Media operations and wrappers around FFmpeg/FFprobe/Pillow for audio/video/image conversion, preview generation, and cover outputs. |
| ui/ | main_window.py | MainWindow (QMainWindow): orchestrates mode selection, worker lifecycle, progress/status/error handling, and post-install sync/readjust actions. |
| ui/workers/ | pipeline worker modules | Background QObject workers on QThread for extraction, normalization, installation, and readjust/apply operations. |

---

## Source Ingestion Modes

V2 supports multiple source modes in active UI flows:

1. Fetch by codename.
2. HTML export mode.
3. IPK archive mode.
4. Batch directory mode.
5. Manual source-folder mode.

All ingestion paths normalize into the same canonical model so downstream writing and media processing remain consistent.

---

## Concurrency Model

The GUI remains responsive during heavy I/O (download, extraction, parsing, media conversion, write) through the QThread plus moveToThread pattern.

    Main Thread (Qt Event Loop)            Background QThread
    MainWindow                              Worker QObject
      │                                       │
      ├─ create worker + thread               │
      ├─ worker.moveToThread(thread)          │
      ├─ thread.started -> worker.run()    -> run executes
      │                                       │
      │ <- progress/status signals -----------┤
      │ <- error signal on exception ---------┤
      │ <- finished signal with result -------┘
      │
      ├─ thread.quit / cleanup
      ├─ re-enable UI actions
      └─ continue to next phase or readjust flow

Key rules:
1. Workers never update widgets directly.
2. UI and worker communication is signal-based only.
3. Exceptions are logged and surfaced through typed error/status signals.

---

## Data Flow

### Standard Install Flow (Single Map)

    1. User selects source mode and input
       - Fetch codename / HTML / IPK / manual source
    2. MainWindow resolves extractor and run context
    3. ExtractAndNormalizeWorker:
       - extraction/download/decompression
       - normalization to NormalizedMapData
    4. InstallMapWorker:
       - game file synthesis
       - media conversion/copy
       - ambient handling path
       - scene registration
    5. UI receives completion:
       - preview/sync controls enabled
       - optional offset apply
       - readjust index upserted

### Batch Install Flow

    1. User selects batch directory.
    2. Worker scans valid candidates (IPK and/or compatible folders).
    3. For each map: extract -> normalize -> install -> register.
    4. UI returns installed map set for review and optional batch offset apply.

### Readjust Flow

    1. User opens readjust from index or source root.
    2. App reloads map context and media discovery.
    3. User edits offsets and applies per-map or batch.
    4. Readjust index is pruned/upserted for future discoverability.

---

## Exception Hierarchy

    JDInstallerError
    ├── ExtractionError
    │   ├── IPKExtractionError
    │   ├── WebExtractionError
    │   └── DownloadError
    ├── ParseError
    │   └── BinaryCKDParseError
    ├── NormalizationError
    │   └── ValidationError
    └── InstallationError
        ├── MediaProcessingError
        ├── GameWriterError
        └── InsufficientDiskSpaceError

Typed exceptions keep stage failures explicit and improve user-facing diagnostics from worker error signals.

---

## Logging Architecture

Logger namespace is rooted at jd2021 with child loggers per subsystem (UI, workers, extractors, parsers, installers). Root setup is initialized at startup, and worker tracebacks are logged before user-visible error emission.

---

## Dependency and Runtime Model

1. Runtime is Windows-first local desktop execution.
2. FFmpeg and FFprobe are required for core media conversion and preview reliability.
3. vgmstream is required for specific decode paths (including X360/XMA2-oriented scenarios).
4. Playwright Chromium runtime is required for Fetch workflows.
5. setup.bat is the primary bootstrap path for dependencies and helper tool setup.
6. Missing dependencies trigger fallback/degraded behavior and should be treated as first-line troubleshooting.

---

## Key Design Decisions

### Canonical Normalization Contract
All source modes converge to NormalizedMapData before install. This keeps downstream generation deterministic and mode-agnostic.

### JSON-First CKD Loading
CKD parsing attempts JSON first (after null-padding cleanup) and falls back to binary parsing when needed, supporting mixed modern/legacy input sets.

### Scene Registration and Idempotence
Map registration is integrated into install flow and designed to avoid duplicate registration side-effects across repeat installs.

### Status and Version Safety Mapping
Game-facing status/version fields are mapped for runtime compatibility while preserving meaningful source metadata where possible.

### Platform Asset Preference Strategy
Platform variant selection favors compatibility with JD2021 PC integration constraints, with retries/fallbacks for source quality and availability.

### AMB Safety Mitigation (Temporary)
Intro AMB behavior is intentionally constrained right now to avoid unstable outcomes in affected paths; silent intro placeholders are expected until redesign lands.

---

## Deprecated or Narrow Historical Narratives

The earlier architecture narrative that framed the app as mostly HTML plus IPK ingestion is now obsolete for operational documentation.
V2 production reality is multi-mode with integrated readjust workflows and broader post-install lifecycle handling.
Any legacy docs that imply a single narrow ingestion path should be treated as historical reference only.