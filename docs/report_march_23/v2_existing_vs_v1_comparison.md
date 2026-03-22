# V2 Existing Features — Comparison with V1

> **Date:** 2026-03-23  
> **Scope:** Features that **already exist in V2** and how they differ from V1.  
> **Purpose:** Decide whether each difference is intentional (keep V2 approach) or a regression (fix toward V1 behavior).

---

## Legend

| Tag | Meaning |
|---|---|
| ✅ **V2 Original** | V2 does it differently by design — likely keep |
| ⚠️ **Needs Correction** | V2 has a bug or missed V1 behavior — fix toward V1 |
| 🔄 **Refine** | V2 approach is valid but needs polish or completion |

---

## 1. IPK Extraction — `archive_ipk.py` vs `ipk_unpack.py`

**Verdict: ✅ V2 Original (minor improvements)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Core logic | Identical binary struct parsing | Identical — direct port | None |
| Compression | zlib → lzma → raw fallback | Same chain | None |
| Path traversal protection | Yes | Yes | None |
| Output dir handling | Falls back to `target_file.stem` if no dir given | Always requires `output_dir` argument | ✅ Cleaner API |
| Logging | Tracks raw vs compressed count, logs both | Only logs total count | 🔄 Minor — V1 has slightly richer diagnostics |
| Error handling | Uses `assert` for magic check, `FileNotFoundError` | Custom `IPKExtractionError`, proper exception wrapping | ✅ Better in V2 |
| BaseExtractor pattern | N/A — standalone function | Wrapped in `ArchiveIPKExtractor` class with codename inference | ✅ Better architecture |
| Codename inference | Done externally by `source_analysis.py` | Infers from first non-hidden subdir name | ⚠️ Fragile — V1's `source_analysis.py` was more reliable |

**Action:** Keep V2 approach. Optionally add V1's raw/compressed count logging.

---

## 2. Binary CKD Parser — `binary_ckd.py` vs `binary_ckd_parser.py`

**Verdict: ✅ V2 Original (significantly improved)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Architecture | File-path-based, returns raw dicts | In-memory bytes, returns typed dataclasses | ✅ V2 is stateless + type-safe |
| Reader class | Custom `BinaryReader` with manual pos tracking | Identical approach but returns models | Same core logic |
| MusicTrack parser | Returns dict with keys like `markers`, `signatures` | Returns `MusicTrackStructure` dataclass | ✅ Structured |
| SongDesc parser | Returns dict | Returns `SongDescription` dataclass | ✅ Structured |
| DTape parser | Returns dict with raw clip lists | Returns `DanceTape` with typed `MotionClip`, `PictogramClip`, `GoldEffectClip` | ✅ Structured |
| KTape parser | Returns dict | Returns `KaraokeTape` with typed `KaraokeClip` | ✅ |
| Cinematic tape | Returns dict | Returns `CinematicTape` with `SoundSetClip`, `TapeReferenceClip` | ✅ |
| Autodance / SoundComponent | Returns dict | Returns dict (same — placeholder) | Same |
| Preview field sanity check | None | Validates `preview_entry/loop_start/loop_end` bounds | ✅ V2 is more robust |
| Error handling | Prints warnings, may silently return partial data | Raises `BinaryCKDParseError` with context | ✅ V2 is more explicit |
| Path replacement | `jd2015` → `maps` hardcoded | Same `jd2015` → `maps` replacement | Same |
| `is_older` marker format check | Missing — assumes one format | Checks `ms_unk1 == 0x6C` for older format with preview metadata | ✅ More robust |

**Action:** Keep V2. This is a clear improvement.

---

## 3. Web Extractor — `web_playwright.py` vs Node.js `fetch.mjs`

**Verdict: ✅ V2 Original (major rewrite)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Runtime | Node.js + Puppeteer (`fetch.mjs`) | Python + Playwright | ✅ Removes Node.js dependency |
| Invocation | Subprocess call to `node fetch.mjs` | Direct async function call via `asyncio.run()` | ✅ No IPC overhead |
| Browser profile | Managed externally | Managed via `browser_profile_dir` config | ✅ Integrated |
| Login handling | Polls for textbox with timeout | Same approach via `_wait_for_login()` | Same logic |
| Command flow | `/assets jdu <code>` → `/nohud <code>` | Same 2-command flow | Same |
| Embed stability check | Not present | 3×500ms stability check before accepting bot response | ✅ More reliable |
| CDN link validation | Downloads all links blindly | `_has_valid_cdn_links()` validates before accepting | ✅ Better error detection |
| Retry logic | No retry on failed embed | `_fetch_command_with_retry()` retries up to 2× | ✅ More resilient |
| URL classification | Basic quality matching | Full `_classify_urls()` with quality fallback, platform preference for scene ZIPs | ✅ Smarter |
| Download retry | No retry | Retry with exponential backoff, 429 handling, inter-request delay | ✅ More robust |
| HTML caching | Saves HTML to disk | Saves to `cache/<codename>/assets.html` and `nohud.html` | Same |
| Scene ZIP extraction | Done as separate pipeline step | Built into extractor via `_extract_scene_zips()` | 🔄 Works but couples extraction with downloading |
| Multi-codename | One codename per run | Loops over `self._codenames` list | ✅ Supports comma-separated input |
| HTML file mode | Reads local HTML → extracts URLs → downloads | Same via `extract_urls_from_file()` but **not wired in `_resolve_extractor()`** | ⚠️ Backend exists, GUI not wired |

**Action:** Keep V2. Wire HTML mode inputs to the extractor constructor in `_resolve_extractor()`.

---

## 4. Normalizer — `normalizer.py` vs V1 inline parsing

**Verdict: 🔄 Refine (logic correct, file discovery broken)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Architecture | Inline in `map_installer.py` — mixed with pipeline logic | Standalone `normalizer.py` with `normalize()` entry point | ✅ Clean separation |
| CKD loading | Loads file, detects JSON vs binary, parses | Same dual-format detection via `_load_ckd()` | Same |
| MusicTrack discovery | Explicit path from known directory structure | Recursive glob `**/musictrack*.tpl.ckd` | ⚠️ Glob may miss files in deep nested ZIP extractions |
| SongDesc discovery | Explicit path | Recursive glob `**/songdesc*.tpl.ckd` | Same risk as above |
| Media discovery | `source_analysis.py` — exhaustive search with quality ranking | `_discover_media()` — finds first `.ogg`, `.webm`, `.jpg`/`.png` | ⚠️ Less thorough — no quality ranking, misses `AudioPreview` exclusion in some code paths |
| Tape discovery | Separate steps per tape type | `_extract_dance_tape()`, `_extract_karaoke_tape()`, `_extract_cinematic_tape()` with graceful `None` fallback | ✅ More fault-tolerant |
| Codename inference | `source_analysis.py` / user input | Optional param + fallback to directory name | 🔄 Less robust than V1's `source_analysis.py` |
| Output | `PipelineState` dict with raw paths | `NormalizedMapData` dataclass | ✅ Typed |

**Known Bug:** `musictrack.tpl.ckd not found` — the recursive glob doesn't find the file when scene ZIPs extract into deeply nested directories (e.g., `world/maps/rainonme/audio/`). V1 explicitly builds the expected path.

**Action:** Fix the glob to search more aggressively, or accept an explicit path when provided (Manual mode).

---

## 5. Game File Writer — `game_writer.py` vs `map_builder.py`

**Verdict: 🔄 Refine (correct for implemented files, missing many file types)**

### What's implemented and how it differs:

| File | V1 | V2 | Diff |
|---|---|---|---|
| `.trk` | Writes `MusicTrackStructure` Lua table | Same format, uses `MusicTrackStructure` dataclass | ✅ Same output |
| Preview field clamping | No bounds check | Clamps `preview_entry`, `loop_start`, `loop_end` to marker count | ✅ Safer |
| `SongDesc.tpl` | Large Lua string with hardcoded field names | Same structure, generates from `SongDescription` dataclass | ✅ Same output |
| `SongDesc.act` | Inline `PhoneImage` paths from hardcoded templates | Same, generates from `sd.phone_images` or fallback template | Same |
| `color_array_to_hex` | Inline hex conversion | Extracted as utility function | ✅ Cleaner |
| `lua_long_string` | Not present — uses f-string escaping | Proper Lua long-string `[==[…]==]` with level adjustment | ✅ Handles edge cases V1 misses |
| `Audio/*.isc` | Writes `musictrack.tpl`, `sequence.tpl`, `<map>.stape`, audio ISC | Same | Same |
| `ConfigMusic.sfi` | Writes SFI with audio config | Same | Same |
| `videoStartTime` | Uses raw value from CKD or post-offset-applied value | Uses `effective_video_start_time` (respects `video_start_time_override`) | ✅ More flexible |
| **Directory setup** | Creates dirs during each write step | `setup_dirs()` creates all dirs upfront | ✅ Cleaner |

### Quality differences in matching files:

| Area | V1 Behavior | V2 Behavior | Impact |
|---|---|---|---|
| `videoStartTime` in `.trk` | `float *= ticks_per_ms` conversion | Writes `effective_video_start_time` directly | ⚠️ **Units unclear** — V1 multiplies by 48 (ticks_per_ms), V2 writes the raw value. If CKD stores seconds, V2 may write wrong units |
| `SongDesc.act` `RELATIVEZ` | Hardcoded `0.200000` | Hardcoded `0.200000` | Same |
| `SongDesc.tpl` credits | Escaped inline | Uses `lua_long_string()` | ✅ V2 handles special chars better |
| `SongDesc.tpl` `status` | Hardcoded `3` | Uses `sd.status` (defaults to `3`) | ✅ More flexible |
| `SongDesc.tpl` `localeID` | Hardcoded `4294967295` | Uses `sd.locale_id` (defaults to `4294967295`) | ✅ More flexible |

**Action:** Verify the `videoStartTime` unit conversion — this is likely a bug if V1 was multiplying by ticks and V2 is not.

---

## 6. Preview Widget — `preview_widget.py` vs V1's Tkinter Preview

**Verdict: ✅ V2 Original (complete rewrite, superior)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Framework | Tkinter canvas + FFplay `-wid` window embedding | QLabel + FFmpeg pipe (rawvideo rgb24) + FFplay audio | ✅ V2 is cross-platform, no window embedding hacks |
| Frame rendering | OS-native window embedding (fragile on modern Windows) | Decodes frames via FFmpeg pipe → `QImage` → `QPixmap` at 24 FPS | ✅ More reliable |
| Seek bar | None | Full slider with time labels, ±5s buttons, play/pause/stop | ✅ Major improvement |
| Position tracking | By polling FFplay | By counting frames from FFmpeg pipe | ✅ More accurate |
| Audio sync | `-wid` flag — coupled to video window | Separate FFplay process launched on first frame | 🔄 Slight audio drift possible due to process start timing |
| Aspect ratio | Fixed canvas size | `_AspectRatioLabel` auto-scales on resize | ✅ Responsive |
| Audio offset handling | Via FFmpeg filter `-af adelay` | Same approach | Same |
| Cleanup | Kill subprocess on close | `request_stop()` flag + `terminate` + `kill` fallback with timeout | ✅ More thorough |
| Duration probe | Not probed | `_probe_duration()` via ffprobe | ✅ Shows total duration |

**Action:** Keep V2. Optionally test audio sync drift.

---

## 7. Sync Refinement Widget — `sync_refinement.py` vs V1's Inline Sync Panel

**Verdict: 🔄 Refine (UI exists, wiring incomplete)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Audio offset control | Entry field + ±delta buttons (1, 0.1, 0.01, 0.001) | `QDoubleSpinBox` (range ±5000ms, step 10ms) | 🔄 V2 lacks fine-grained delta buttons — spin box step of 10ms may be too coarse |
| Video offset control | Entry field + ±delta buttons + enable/disable checkbox | `QDoubleSpinBox` (range ±5000ms, step 10ms) | ⚠️ Missing enable/disable checkbox |
| Combined offset display | Computed and shown | `QLineEdit` read-only display | Same concept |
| Sync Beatgrid button | Copies Video Offset → Audio Offset | Not present | ⚠️ Missing |
| Pad Audio button | Not present in V1 | V2 has `pad_audio_requested` signal, probes media durations | ✅ V2 improvement |
| Preview button | Starts/stops FFplay | Toggle button, wired to `PreviewWidget.launch()` | ✅ Working |
| Apply button | Commits offset, rewrites .trk, clears cache | Commits to `video_start_time_override`, rewrites via `ApplyAndFinishWorker` | ⚠️ Unit mismatch — see §8 |
| Reset | Not explicitly present | `reset()` method zeros both spinboxes | ✅ |

**Action:** Add Sync Beatgrid button. Consider finer step options on the spinboxes.

---

## 8. Offset Application — `main_window.py` vs V1's `_on_sync_apply`

**Verdict: ⚠️ Needs Correction (unit mismatch bug)**

### V1 Behavior
```python
# V1: Offsets are in milliseconds; videoStartTime in CKD is in seconds
# V1 converts and applies via FFmpeg re-padding
new_vst = original_vst + (offset_ms / 1000.0)  # convert ms → s
```

### V2 Behavior
```python
# V2: main_window.py line 495
original = self._current_map.music_track.video_start_time  # in seconds (from CKD)
self._current_map.video_start_time_override = original + offset_ms  # BUG: adds ms to seconds
```

The spinbox values are in **milliseconds** (range ±5000ms) but `music_track.video_start_time` is in **seconds** (typically -3.0 to 5.0). Adding `offset_ms` directly corrupts the value.

Additionally:
- V1 rewrites the `.ogg` audio file via FFmpeg (silence padding/trimming) as part of offset application
- V2 only re-generates the `.trk` file with the updated `videoStartTime` — no FFmpeg audio pass
- V2's approach is simpler (config-only) but fundamentally different in that it doesn't physically alter media timing

**Action:** Fix the ms→s conversion. Decide whether the config-only approach is sufficient or if FFmpeg audio re-padding is needed.

---

## 9. Settings Persistence — `settings_dialog.py` / `config.py` vs V1's JSON settings

**Verdict: ✅ V2 Original (Pydantic model, cleaner)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Storage format | Plain JSON dict | Pydantic `AppConfig` serialized to JSON | ✅ Validated fields |
| File name | `installer_settings.json` | `installer_settings.json` | Same |
| Settings UI | Tkinter `Toplevel` dialog | PyQt6 `QDialog` | ✅ Framework aligned |
| Fields | skip_preflight, suppress_offset, cleanup_behavior, default_quality, show_preflight_popup, show_quickstart, quickstart_seen | Same + `discord_channel_url`, `browser_profile_dir`, `fetch_login_timeout_s`, `fetch_bot_response_timeout_s` | ✅ V2 has more fields |
| Quality naming | lowercase `ultra_hd` | UPPERCASE `ULTRA_HD` | ⚠️ Compatibility break if loading V1 settings file |
| Quickstart "re-enable" logic | When re-enabled, resets `quickstart_seen = False` so it shows again | Not implemented — re-enabling the checkbox does nothing next launch | 🔄 Minor logic gap |
| Post-apply cleanup | `prompt_cleanup()` — granular file-by-file cleanup (preserves .ogg/.webm, deletes CKDs/ZIPs) | `ApplyAndFinishWorker` — `shutil.rmtree()` on entire cache dir | ⚠️ V2 is destructive — deletes everything instead of selectively preserving reusable files |
| Config-on-save flow | Dialog calls `map_installer.save_settings()` | Dialog returns new config to `MainWindow._on_settings()` which calls `_save_settings()` | ✅ Cleaner separation |

**Action:**
1. Add quickstart re-enable logic
2. Make cleanup more granular (preserve audio/video, delete intermediates)
3. Consider case-insensitive quality string loading for V1 settings compat

---

## 10. Main Window / Pipeline Orchestration — `main_window.py` vs `gui_installer.py`

**Verdict: ✅ V2 Original (much cleaner, but less complete)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Framework | Tkinter — single-threaded with `after()` polling | PyQt6 — QThread workers with signal/slot | ✅ Cleaner concurrency |
| Layout | Grid-based, hardcoded column/row numbers | Column layout (left fixed 450px, right expanding) | 🔄 Different but functional |
| Pipeline steps display | 15-step checklist with individual status icons | 3-step checklist ("Extract", "Normalize", "Install") | 🔄 Less granular — user sees less progress detail |
| Mode dispatch | `if/elif` chain for all 5 modes | `_resolve_extractor()` — only IPK and Fetch implemented | ⚠️ HTML/Batch/Manual return "Not Implemented" |
| Worker lifecycle | Manual thread management, gc crash risk | `moveToThread` + `deleteLater` chain | ✅ Proper lifecycle |
| Thread tracking | None — gc crash was reported bug | `self._active_threads: set[QThread]` with explicit cleanup | ✅ Better |
| File logging | Not present in GUI — only CLI | Per-map `FileHandler` to `logs/` directory | ✅ V2 improvement |
| Pre-flight | Thorough (ffmpeg, ffplay, game dir, disk space, Node.js) | Minimal (game dir exists, target not empty) | ⚠️ Much less thorough |
| Re-adjust offset | Opens file dialog → reads existing .trk → loads into sync panel | Opens file dialog → runs full `normalize()` → loads into sync panel | 🔄 V2 re-normalizes instead of reading .trk directly — slower but gets full data model |
| Game dir persistence | Settings JSON | Settings JSON → applied on load to `ConfigWidget` | Same |
| Quickstart on launch | Shows once, persisted via `quickstart_seen` | Config field exists but dialog not shown | ⚠️ Not implemented |

**Action:** Keep V2 architecture. Implement the remaining mode dispatchers and quickstart dialog.

---

## 11. Data Models — `core/models.py` (V2 only)

**Verdict: ✅ V2 Original (no V1 equivalent — major improvement)**

V1 passes raw dicts throughout the pipeline. V2 introduces typed dataclasses:

| Model | Purpose | V1 Equivalent |
|---|---|---|
| `NormalizedMapData` | Canonical map representation | `PipelineState` (a mutable bag of fields) |
| `MusicTrackStructure` | Beat markers, signatures, sections | Raw dict from `parse_musictrack()` |
| `SongDescription` | Song metadata (title, artist, colors, tags) | Raw dict from `parse_songdesc()` |
| `DanceTape` / `KaraokeTape` / `CinematicTape` | Timeline clips | Raw dict/list |
| `MapMedia` | Paths to audio, video, images | Scattered across `PipelineState` fields |
| `DefaultColors` | RGBA color palette | Nested dict |
| `video_start_time_override` | Offset tracking without mutating original CKD data | V1 mutates the value directly |

**Action:** Keep V2. The `video_start_time_override` pattern is elegant — just fix the unit conversion bug.

---

## 12. Download System — `web_playwright.py` download functions

**Verdict: ✅ V2 Original (improved over V1)**

| Aspect | V1 | V2 | Diff |
|---|---|---|---|
| Download method | Python `urllib` with basic error handling | Python `urllib` with retry, backoff, 429 handling | ✅ More robust |
| Quality selection | Tries preferred quality, falls back linearly | `_classify_urls()` with circular fallback through `QUALITY_ORDER` | ✅ Smarter fallback |
| Scene ZIP platform preference | Hardcoded `DURANGO` | `SCENE_PLATFORM_PREFERENCE = ["DURANGO", "SCARLETT", "NX"]` with fallback | ✅ Configurable |
| File skip | Re-downloads everything | Skips existing files (`os.path.exists` check) | ✅ Resumable |
| SSL | Normal validation | `ssl._create_unverified_context` for Ubi CDN | 🔄 Necessary but could be scoped narrower |
| Progress callback | Print-based | `progress_callback(filename, current, total)` parameter | ✅ UI-friendly |

**Action:** Keep V2. Consider scoping the SSL workaround.

---

## Summary Decision Matrix

| Feature | Keep V2 | Fix Toward V1 | Refine V2 |
|---|---|---|---|
| IPK Extraction | ✅ | | |
| Binary CKD Parser | ✅ | | |
| Web Extractor (Playwright) | ✅ | | |
| Normalizer | | | 🔄 Fix file discovery |
| Game Writer (implemented files) | | ⚠️ Check videoStartTime units | 🔄 |
| Preview Widget | ✅ | | |
| Sync Refinement Widget | | ⚠️ Add Sync Beatgrid | 🔄 Finer step options |
| Offset Application | | ⚠️ Fix ms→s conversion | |
| Settings Dialog | ✅ | | 🔄 Quickstart + cleanup |
| Main Window / Pipeline | ✅ | | 🔄 Pre-flight, modes |
| Data Models | ✅ | | |
| Download System | ✅ | | |
