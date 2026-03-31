# Pipeline Reference

**Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This document describes the JD2021 Map Installer v2 data pipeline: how map data flows from source ingestion (Fetch/HTML/IPK/Batch/Manual) through extraction, normalization, and installation into playable UbiArt engine files.

## Current Behavior Notes (April 2026)

> [!IMPORTANT]
> **Intro AMB is temporarily disabled in current V2 behavior.**
> Intro ambient playback is intentionally forced to silent placeholder behavior as an emergency stability mitigation. Do not expect intro AMB parity with legacy behavior at this time.

> [!NOTE]
> **IPK-derived video timing may require manual tuning.**
> For many IPK maps, `videoStartTime` is approximate by design due to source metadata limitations. Manual post-install offset adjustment is expected.

> [!WARNING]
> **Runtime dependencies are required for full pipeline coverage.**
> Missing or misconfigured FFmpeg/FFprobe, vgmstream, or Playwright Chromium can cause degraded behavior, fallback processing, or workflow failures.

---

## Pipeline Overview

V2 replaces the legacy monolithic flow with a three-phase architecture:

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│   EXTRACTION    │ ───→ │  NORMALIZATION   │ ───→ │  INSTALLATION   │
│                 │      │                  │      │                 │
│ WebPlaywright   │      │  normalizer.py   │      │ game_writer.py  │
│ ArchiveIPK      │      │  binary_ckd.py   │      │ media_processor │
│                 │      │                  │      │                 │
│ Raw files in    │      │ NormalizedMapData │      │ UbiArt configs  │
│ output_dir      │      │ (canonical model)│      │ .trk/.tpl/.act  │
└─────────────────┘      └──────────────────┘      └─────────────────┘
```

Each phase is orchestrated by a `QObject` worker running on a `QThread`, communicating with the GUI through Qt signals.

Pipeline execution is launched from multiple UI modes (Fetch by codename, HTML, IPK, Batch directory, Manual source). Source mode affects extraction strategy, but all successful paths converge into the same normalization and installation contracts.

---

## Phase 1 — Extraction

**Worker:** `ExtractAndNormalizeWorker` (first half)

**Purpose:** Fetch raw map data from a source and place it into a temporary directory.

### Web Extraction (`WebPlaywrightExtractor`)

Handles HTML files exported from JDHelper, direct URL lists, and fetch-driven URL discovery.

**Steps:**
1. Collect URLs from `asset_html`, `nohud_html`, and/or direct URL list.
2. Extract codename from URL pattern (`/public/map/{MapName}/...`).
3. Classify URLs into video, audio, mainscene ZIP, and other assets.
4. Select best video quality (falls back through 8 tiers: `ULTRA_HD` → `LOW`).
5. Select preferred mainscene platform (DURANGO → NX → SCARLETT → any).
6. Download files with retry logic (exponential backoff, HTTP 429 handling, 0.5s inter-request delay).
7. Skip already-downloaded files.

**Inputs:** HTML file paths or URL list, quality preference, `AppConfig`.

**Outputs:** Raw files in `output_dir` (CKDs, OGG, WebM, ZIPs).

**Errors:** `WebExtractionError` if no URLs are provided. `DownloadError` for network failures (with `url` and `http_code` attributes).

### IPK Extraction (`ArchiveIPKExtractor`)

Handles Xbox 360 `.ipk` archive files.

**Steps:**
1. Validate IPK magic bytes (`\x50\xEC\x12\xBA`).
2. Read big-endian file headers (offset, size, compressed size, paths).
3. Decompress each entry (tries zlib first, then lzma, then raw copy).
4. Apply path-traversal protection (rejects paths that escape `output_dir`).
5. Infer codename from the first subdirectory in the extracted archive.

**Inputs:** Path to `.ipk` file.

**Outputs:** Extracted files in `output_dir`.

**Errors:** `IPKExtractionError` for invalid files or extraction failures.

### Live Scraping (`scrape_live()`)

Live/experimental mode using Playwright to scrape JDU asset pages:

1. Launch headless Chromium via `playwright.async_api`.
2. Navigate to page URL and wait for `networkidle`.
3. Extract page content and parse URLs.
4. Return URL list for the standard download pipeline.

Runs in an `asyncio` event loop inside a `QThread` worker.

Operational caveat:
- Link expiry and remote endpoint behavior can break fetch sessions even when local code is healthy. Retry and fallback logic reduce, but do not eliminate, this fragility.

---

## Phase 2 — Normalization

**Worker:** `ExtractAndNormalizeWorker` (second half)

**Entry point:** `normalizer.normalize(directory, codename)`

**Purpose:** Transform raw extracted files into a single canonical `NormalizedMapData` dataclass, regardless of source format.

### CKD Loading Strategy

For each CKD type, the normalizer:
1. Searches the directory recursively using glob patterns (e.g., `*musictrack*.tpl.ckd`).
2. Filters by codename if provided (matches directory components).
3. Prefers non-legacy files over `main_legacy` variants.
4. Attempts **JSON parsing first** (strips null padding, decodes UTF-8).
5. Falls back to the **binary CKD parser** on JSON failure.

### Data Extraction

| Component | Glob Pattern | Output Model |
|-----------|-------------|--------------|
| Music Track | `*musictrack*.tpl.ckd` | `MusicTrackStructure` (markers, signatures, sections, timing) |
| Song Description | `*songdesc*.tpl.ckd` | `SongDescription` (title, artist, difficulty, colors, tags) |
| Dance Tape | `*dtape*ckd` | `DanceTape` (MotionClips, PictogramClips, GoldEffectClips) |
| Karaoke Tape | `*ktape*ckd` | `KaraokeTape` (KaraokeClips with lyrics, pitch, tolerances) |
| Media Assets | `*.webm`, `*.ogg`, `*.jpg`, `*.png` | `MapMedia` (video, audio, cover, coaches, pictograms) |

### Binary CKD Parser

The stateless parser (`binary_ckd.py`) handles legacy binary (cooked) UbiArt files:

- **Dispatch:** Filename-based for tapes (`dtape`, `ktape`, `.tape.ckd`), Actor header CRC-based for TPL files.
- **Reader:** `BinaryReader` class for big-endian sequential reads (`u32`, `i32`, `f32`, `u16`, `len_string`, `interned_string`, `split_path`).
- **Known CRCs:** `MusicTrackComponent_Template` (0x02883A7E), `JD_SongDescTemplate` (0x8AC2B5C6), `Actor_Template` (0x1B857BCE), `AutodanceComponent_Template` (0x51EA2CD0), `SoundComponent_Template` (0xD94D6C53).

### Validation

After normalization, the following checks are applied:
- `MusicTrackStructure.markers` must not be empty → raises `ValidationError`.
- Preview fields (entry, loop start, loop end) are sanity-checked against marker count.

Source-shape caveats:
- Some IPK-derived maps rely on cache-like layouts (`cache/`, `itf_cooked`) for pictogram/texture discovery when canonical paths are incomplete.
- Path casing and folder-shape differences are handled with fallbacks, especially around audio/ambient-related assets.

**Output:** `NormalizedMapData` — the single canonical representation of a map.

---

## Phase 3 — Installation

**Worker:** `InstallMapWorker`

**Entry point:** `game_writer.write_game_files(map_data, target_dir, config)`

**Purpose:** Generate all UbiArt engine configuration files from `NormalizedMapData`.

### Directory Setup

Creates the standard map directory structure:
```
{target_dir}/
├── Audio/
├── Timeline/
│   ├── pictos/
│   └── Moves/
├── Cinematics/
├── VideosCoach/
├── MenuArt/
│   ├── Actors/
│   └── textures/
└── Autodance/
```

### Generated Files

| File | Format | Contents |
|------|--------|----------|
| `Audio/{MapName}.trk` | Lua | Beat timing markers, signatures, sections, videoStartTime |
| `SongDesc.tpl` | Lua | Full song metadata (title, artist, difficulty, colors, tags, phone images) |
| `SongDesc.act` | Lua | Song description actor instance |
| `Audio/{MapName}_musictrack.tpl` | Lua | MusicTrack template referencing `.trk` |
| `Audio/{MapName}_sequence.tpl` | Lua | Sequence template with TapeCase |
| `Audio/{MapName}.stape` | Lua | Sequence tape |
| `Audio/{MapName}_audio.isc` | XML | Audio scene with MusicTrack + TapeCase actors |
| `Audio/ConfigMusic.sfi` | XML | Sound format info (PC/Durango/NX/ORBIS) |

### Key Transformations

- **Status override:** `Status = 12` (ObjectiveLocked) → `Status = 3` (Available).
- **JDVersion mapping:** Runtime `JDVersion` is normalized to a stable engine branch (`2016` or `2021`), while `OriginalJDVersion` preserves the map's numeric source year.
- **Coach count inference:** If `num_coach < 1`, counts `coach_*.png/.tga` files in `MenuArt/textures/`.
- **Color conversion:** `[R,G,B,A]` float arrays → `0xRRGGBBAA` hex strings.
- **Lua long strings:** Handles nested brackets in metadata values.

Behavior caveats:
- **Intro ambient behavior:** Current V2 generation keeps intro ambient effectively silent by policy (temporary mitigation).
- **IPK video sync expectation:** `videoStartTime` is frequently a best-effort value for IPK sources; in-app readjustment is the intended follow-up step.

**Errors:** `GameWriterError` wraps any file generation failure.

### Media Processing

`media_processor.py` provides supporting operations:

| Function | Purpose |
|----------|---------|
| `run_ffmpeg()` | Execute FFmpeg subprocess with error handling and timeout |
| `run_ffprobe()` | Execute FFprobe for media inspection |
| `get_video_duration()` | Probe video duration in seconds |
| `copy_video()` / `copy_audio()` | Copy media files with directory creation |
| `generate_map_preview()` | Create map preview video clip (VP9, 1Mbps) |
| `generate_audio_preview()` | Create audio preview with fade-out (Vorbis) |
| `convert_image()` | Pillow-based format conversion with optional resize |
| `generate_cover_tga()` | Convert cover to 720×720 TGA for game engine |

Dependency notes:
- `ffmpeg`/`ffprobe` must be available for preview generation, timing probes, and many media transforms.
- `vgmstream` is required for parts of the legacy/X360 audio decode path.
- Dependency gaps can trigger fallback behavior, reduced output quality, or hard failure depending on operation.

---

## Worker Orchestration

### ExtractAndNormalizeWorker

```python
progress.emit(10)    # Starting extraction
extractor.extract(output_dir)
progress.emit(50)    # Extraction complete, starting normalization
normalize(extracted_dir, codename)
progress.emit(100)   # Normalization complete
finished.emit(map_data)  # NormalizedMapData or None on error
```

### InstallMapWorker

```python
progress.emit(20)    # Starting installation
write_game_files(map_data, target_dir, config)
progress.emit(100)   # Installation complete
finished.emit(True)  # success=True, or False on error
```

### Error Handling

All workers catch exceptions in their `run()` method:
1. Log the full traceback via `logger.error()`.
2. Emit the error message via `error.emit(str(e))`.
3. Emit `finished.emit(None)` or `finished.emit(False)` to signal failure.

The `MainWindow` connects to these signals to display errors in the log panel and re-enable UI controls.

---

## Related Operational Flows

This reference focuses on the extraction-normalization-installation core. In current V2 usage, two adjacent flows are also important:

1. **Post-install sync/readjust:** Users commonly refine offsets after install (especially IPK maps).
2. **Batch install + batch apply:** Multi-map processing and subsequent offset updates are part of normal operator workflow.

These flows are orchestrated in `MainWindow` and reuse outputs from the core pipeline described above.
