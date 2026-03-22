# V2 Missing Functionality Report

> **Date:** 2026-03-23  
> **Scope:** `C:\Github\jd2021-map-installerV1` (V1) vs `C:\Github\jd2021-map-installer` (V2)

---

## Overview

V2 is a clean PyQt6 modular refactor of V1's monolithic Tkinter codebase. The architecture (data models, Extract → Normalize → Install pipeline, QThread workers) is solid, but many V1 pipeline steps and game-file writers are **not yet implemented** in V2. This report catalogs every functional gap.

---

## 1. Game File Writers — Incomplete

V1's `map_builder.py` generates **12+ file types** across 6 subdirectories. V2's `game_writer.py` only writes **3 of them**.

| File Type | V1 | V2 | Status |
|---|---|---|---|
| `.trk` (MusicTrack) | ✅ | ✅ | Done |
| `SongDesc.tpl` + `.act` | ✅ | ✅ | Done |
| `audio.isc` + `musictrack.tpl` + `sequence.tpl` + `.stape` | ✅ | ✅ | Done |
| `ConfigMusic.sfi` | ✅ | ✅ | Done |
| `Timeline/*.tpl` + `*.act` + `*_tml.isc` (Dance/Karaoke) | ✅ | ❌ | **Missing** |
| `VideosCoach/*.mpd` + `video_player_*.act` + `*_video.isc` | ✅ | ❌ | **Missing** |
| `MenuArt/Actors/*.act` + `*_menuart.isc` | ✅ | ❌ | **Missing** |
| `Autodance/*.isc` + `*.tpl` + `*.act` (stubs) | ✅ | ❌ | **Missing** |
| `Cinematics/*_cine.isc` | ✅ | ❌ | **Missing** |
| `*_MAIN_SCENE.isc` (root scene file) | ✅ | ❌ | **Missing** |

> [!CAUTION]
> Without the MAIN_SCENE ISC, Timeline files, VideosCoach config, and MenuArt actors, **an installed map will not load in JD2021** even if the .trk and SongDesc are correct.

---

## 2. Pipeline Steps — Collapsed / Missing

V1 has a **15-step** pipeline. V2 collapses this into 3 generic steps ("Extract", "Normalize", "Install") with most individual operations absent.

| # | V1 Step | V2 Equivalent | Status |
|---|---|---|---|
| 00 | Pre-install cleanup | — | **Missing** |
| 01 | Clean previous builds | — | **Missing** |
| 02 | Download assets from JDU | `WebPlaywrightExtractor` | ✅ Fetch mode |
| 03 | Extract scene archives | `_extract_scene_zips()` | ✅ |
| 04 | Unpack IPK archives | `ArchiveIPKExtractor` | ✅ |
| 05 | Decode MenuArt textures (XTX→TGA) | — | **Missing** |
| 05b | Validate MenuArt covers | — | **Missing** |
| 06 | Generate UbiArt config files | `write_game_files()` (partial) | ⚠️ Partial |
| 07 | Convert choreography/karaoke tapes | — | **Missing** |
| 08 | Convert cinematic tapes | — | **Missing** |
| 09 | Process ambient sounds | — | **Missing** |
| 10 | Decode pictograms | — | **Missing** |
| 11 | Extract moves & autodance | — | **Missing** |
| 12 | Convert audio (OGG→WAV, XMA2 decode) | `decode_xma2_audio()` exists but never called in pipeline | ⚠️ Stub |
| 13 | Copy gameplay video (quality select) | `copy_video()` exists but never called in pipeline | ⚠️ Stub |
| 14 | Register in SkuScene | — | **Missing** |

> [!IMPORTANT]
> **SkuScene registration** (step 14) is critical — maps won't appear in the song list without the ISC entry in `SkuScene_Maps_PC_All.isc`.

---

## 3. Offset Calculation Not Applied

**User-reported bug confirmed by code inspection.**

V2's `SyncRefinementWidget` emits a `combined_offset` signal in **milliseconds**, but the handler in `main_window.py` adds it directly to `video_start_time` which is in **seconds**:

```python
# main_window.py line 495
self._current_map.video_start_time_override = original + offset_ms
```

This adds milliseconds to a seconds-based value, producing wildly incorrect results.

V1 also performs:
- **Marker-based preroll calculation** (`compute_marker_preroll()`) — not in V2
- **Audio padding via FFmpeg** (silence prepend/trim) — V2 only modifies the .trk value  
- **Per-source offset logic** (IPK vs JDU have different offset semantics) — not in V2

---

## 4. HTML / Batch / Manual Modes — Not Implemented

The `ModeSelectorWidget` provides the UI for all 5 modes, but `_resolve_extractor()` only supports **Fetch** and **IPK**:

```python
# main_window.py line 564
# HTML, Batch, Manual are not fully implemented yet
QMessageBox.information(
    self, "Not Implemented",
    f"The '{self._current_mode}' mode is not yet fully implemented.",
)
```

### HTML Mode
- V1: Accepts asset + nohud HTML files → extracts URLs → downloads → installs
- V2: UI exists (`mode_selector.py` lines 166-198) but no extractor wires to it

### Batch Mode
- V1: Iterates subfolders with HTML files or pre-downloaded assets, installs each map
- V2: UI exists but returns "Not Implemented"

### Manual Mode
- V1: Per-file/folder selectors (audio, video, musictrack, songdesc, tapes, asset dirs) + "Scan" auto-populate
- V2: Full UI exists but no backend. Also missing the JDU/IPK submode switch and the Scan button

---

## 5. Normalizer — `musictrack.tpl.ckd not found` Error

**User-reported error confirmed:**

```
[ERROR] ExtractAndNormalize failed: musictrack.tpl.ckd not found
```

The normalizer looks for `*musictrack*.tpl.ckd` in the extracted directory. This fails because:

1. **Scene ZIPs extract to a nested subdirectory** — e.g., `cache/RainOnMe/world/maps/rainonme/…/musictrack.tpl.ckd`. The normalizer searches `cache/RainOnMe/` but the glob may not match if the ZIP extracts into a deep path that doesn't follow the expected pattern.
2. **The glob pattern assumes the CKD is directly under the output dir** — V1 has explicit path munging to handle nested extraction results.

---

## 6. Preview / Sync Refinement — Partially Wired

| Feature | V1 | V2 |
|---|---|---|
| Embedded FFplay video preview | ✅ (via PreviewManager) | ⚠️ Signal exists, `PreviewWidget.launch()` wired but implementation unclear |
| Sync Beatgrid button | ✅ (copies VO → AO) | ❌ Missing |
| Video Offset enable/disable checkbox | ✅ | ❌ Missing |
| Multi-map navigation (Prev/Next) | ✅ (bundle, batch, readjust) | ❌ Missing |
| Per-delta ±buttons (1, 0.1, 0.01, 0.001) | ✅ | ❌ Replaced with spin boxes |
| IPK sync warning (manual video adjust needed) | ✅ | ❌ Missing |

---

## 7. Other Missing Features

| Feature | V1 | V2 |
|---|---|---|
| **CLI mode** (`map_installer.py main()` with argparse) | ✅ | ❌ |
| **Pre-flight check** (ffmpeg, ffplay, game dir, disk space) | ✅ (thorough) | ⚠️ Minimal (only checks dir exists) |
| **Game path auto-discovery** (`resolve_game_paths()` with recursive scan + cache) | ✅ | ❌ |
| **SkuScene ISC read/write** (register/unregister maps) | ✅ | ❌ |
| **Quickstart guide dialog** | ✅ | ❌ |
| **Tooltips on all buttons** | ✅ (ToolTip class) | ❌ |
| **Bundle IPK support** (multi-map IPK with select-all UI) | ✅ | ❌ |
| **`source_analysis.py`** (auto-detect source type, pick audio/video) | ✅ | ❌ |
| **`clean_data.py`** (data sanitization utilities) | ✅ | ❌ |
| **`json_to_lua.py`** (CKD JSON → Lua conversion) | ✅ | ❌ |
| **`ubiart_lua.py`** (UbiArt Lua format handling) | ✅ | ❌ |
| **Map name sanitization** (non-ASCII character handling dialog) | ✅ | ❌ |
| **Metadata encoding check** (non-ASCII in Title/Artist/Credits) | ✅ | ❌ |
| **Download cleanup** (ask/delete/keep after install) | ✅ | ❌ |
| **Graceful Ctrl+C handling** (SIGINT handler) | ✅ | ❌ |
| **Settings dialog** fields (quickstart toggle, preflight popup) | ✅ | ⚠️ Partial |
| **Reset State** button (full state clear) | ✅ | ⚠️ Partial |
| **Re-adjust Offset** (from already-installed map via .trk read) | ✅ (reads existing .trk value) | ⚠️ Only re-normalizes raw directory |
| **Per-map file logging** | ✅ | ✅ Done |
| **stdout→logger redirect** (`StdoutToLogger`) | ✅ | ❌ |

---

## 8. Priority Action Items

### Critical (Map won't load without these)

1. **Implement remaining game file writers** — Timeline, VideosCoach, MenuArt, Autodance, Cinematics, MAIN_SCENE ISC
2. **Implement SkuScene registration** — append ISC entry to `SkuScene_Maps_PC_All.isc`
3. **Fix offset units** — convert ms → seconds before applying to `video_start_time_override`
4. **Fix normalizer path resolution** — handle nested ZIP extraction paths for `musictrack.tpl.ckd`
5. **Wire media copy steps** — actually copy video and audio into the game directory during install

### High (Major V1 features missing)

6. **Implement HTML mode extractor** — read local HTML files → extract URLs → download
7. **Implement batch mode** — iterate map subfolders
8. **Implement manual mode backend** — wire existing UI inputs to pipeline
9. **Port tape converters** — dance tape (dtape→Lua), karaoke tape (ktape→Lua), cinematic tape
10. **Port pictogram decoder** — CKD textures to PNG/TGA
11. **Port MenuArt texture decoder** — XTX/CKD to TGA
12. **Port ambient sound processing** — extract `SoundSetClip` data from mainsequence tape

### Medium (Important for usability)

13. **Game path auto-discovery** — port `resolve_game_paths()` with recursive scan
14. **Bundle IPK support** — multi-map detection + selection UI
15. **Pre-flight validation** — check ffmpeg/ffplay availability, disk space
16. **Move extraction** — extract dance moves from CKD to classifier files
17. **Audio conversion** — OGG→WAV for game engine

### Low (Nice-to-have)

18. **Quickstart guide dialog**
19. **CLI mode** (argparse entry point)
20. **Metadata encoding checks + dialog**
21. **Multi-map navigation** in sync refinement
22. **Download cleanup dialog**
