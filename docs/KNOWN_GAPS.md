# Known Gaps and Remaining Work

This document describes known limitations, unresolved issues, and potential improvements identified through code analysis. It replaces the previous `TODO_FINDINGS.md`.

---

## Resolved Items

The following items from the original findings have been implemented in the codebase:

### Status Override for JD2021 Maps (Resolved)

**Original issue:** Maps originally from JD2021 appeared locked (`Status = 12`, ObjectiveLocked).

**Resolution:** `map_builder.py:193` now overrides `Status = 12` to `Status = 3` (Available) during SongDesc generation. This makes JD2021-original maps immediately playable.

### Download Throttling / Rate Limiting (Resolved)

**Original issue:** No protection against CDN throttling.

**Resolution:** `map_downloader.py` now implements:
- Browser-like User-Agent header (Chrome 131)
- Retry logic with exponential backoff (3 retries, base delay 2s)
- HTTP 429 handling with `Retry-After` header support
- Inter-request delay of 0.5s between sequential downloads

---

## Active Gaps

### 1. NX Platform Mode for Joycons

**Status:** Partially implemented infrastructure, needs completion.

**What exists:**
- NX scene archives are downloaded and extracted
- NX platform move folders are already copied to `Timeline/Moves/NX/`
- Scene archive selection lists NX in its preference order
- The game has joycon input handlers (`input_menu_nx_joycon_left.isg`, etc.)
- `SkuScene_Maps_NX_All.isc` exists in the game files

**What is missing:**
- NX `.gesture` files are extracted but not merged into a usable location (gesture merge only copies from DURANGO/SCARLETT Kinect platforms into `PC/`)
- Maps are only registered in `SkuScene_Maps_PC_All.isc`, not in `SkuScene_Maps_NX_All.isc`
- No user preference (checkbox/flag) to opt into NX mode

**Open questions:**
- What controller setup do users have? (Actual Joy-Cons via Bluetooth, or emulated input?)
- Do users need NX gesture files (motion scoring) or just controller button mapping?
- Has anyone gotten joycon scoring working manually to inform the implementation?
- Should NX mode be opt-in or default?

### 2. Mid-Song AMB Sounds Remain Silent

**Status:** By design, but documented as a limitation.

AMB sounds that play mid-song (`SoundSetClip`s with `StartTime > 0`) are kept as silent WAV placeholders. Their real audio content is hosted on JDU servers and cannot be downloaded through the pipeline. Only intro AMBs (`StartTime <= 0`) are populated with real audio from the OGG pre-roll.

This is inherent to the CDN access model and cannot be fixed without direct access to the individual AMB audio assets.

### 3. No Multi-Audio-Track Support

**Status:** Known limitation.

Maps with more than one audio stream (e.g., alternate language tracks) are not supported. The pipeline assumes a single OGG audio file per map.

### 4. WAV Scheduling Jitter (Fallback Maps)

**Status:** Minor edge case.

When musictrack marker data is available, intro AMB duration is derived precisely. When marker data is absent, a heuristic tail of 1.355s is used. On systems with unusually high audio pipeline latency, this heuristic gap may still be audible. This has not been observed in practice.

The marker-based primary path does not have this limitation since its timing is derived from actual audio data.

### 5. ORBIS Gesture Format Incompatibility

**Status:** Mitigated with substitution, not fully resolved.

PlayStation (ORBIS) `.gesture` files use a binary format incompatible with the PC Kinect adapter. The pipeline substitutes ORBIS-exclusive gesture variants by stripping trailing digits and copying the base Kinect gesture (e.g., `handstoheart0.gesture` from ORBIS → copy `handstoheart.gesture` from DURANGO under the numbered name).

This substitution works for most cases but may produce incorrect gesture recognition for ORBIS-exclusive choreography variants that differ significantly from the base Kinect gesture.

### 6. mapsObjectives.ilu Not Patched

**Status:** Not needed currently, but may matter.

The game file `mapsObjectives.ilu` ties specific maps to unlock conditions. While the Status override (setting `Status = 3`) is sufficient to make maps playable, maps referenced in `mapsObjectives.ilu` may still show objective-related UI elements. No issues have been reported from this.

---

## Potential Improvements

These are not bugs or gaps, but improvements identified through code analysis:

### Parallel Downloads
The current downloader processes files sequentially with a 0.5s inter-request delay. Parallel downloading (e.g., 3-4 concurrent downloads) could significantly speed up Phase 1 of batch installs.

### Progress Reporting for Downloads
The download function (`map_downloader.download_files()`) does not report download progress (bytes received vs total). Large video files can take several minutes to download with no feedback.

### Cleanup Automation
The GUI prompts for cleanup after "Apply & Finish" but the CLI sync loop does not offer cleanup. Adding cleanup as a CLI option would improve consistency.
