# Known Gaps and Remaining Work

This document describes known limitations, unresolved issues, and potential improvements identified through code analysis.

---

## Resolved Items

The following items from the original findings have been implemented in the codebase:

### Status Override for JD2021 Maps (Resolved)

**Original issue:** Maps originally from JD2021 appeared locked (`Status = 12`, ObjectiveLocked).

**Resolution:** `map_builder.py` now overrides `Status = 12` to `Status = 3` (Available) during SongDesc generation.

### Download Throttling / Rate Limiting (Resolved)

**Original issue:** No protection against CDN throttling.

**Resolution:** `map_downloader.py` now implements browser-like User-Agent, retry logic with exponential backoff, HTTP 429 handling, and inter-request delay.

### Binary CKD Parsing (Resolved)

**Original issue:** Legacy Xbox 360 and older UbiArt CKD files used a cooked binary format unreadable by the JSON-based pipeline.

**Resolution:** `binary_ckd_parser.py` now parses binary (big-endian) CKD files for musictracks, songdescs, choreography/karaoke tapes, cinematic tapes, autodance templates, and sound components. `helpers.load_ckd_json()` falls back to this parser when JSON parsing fails, making binary CKD support transparent throughout the pipeline.

### X360 Texture Decoding (Resolved)

**Original issue:** Xbox 360 textures used tiled memory layout and byte-swapped pixels, appearing garbled when extracted.

**Resolution:** `ckd_decode.py` now detects X360 texture payloads (52-byte GPU descriptor), performs 16-bit word byte-swap, and applies Xenia-derived tiled-to-linear conversion (Tiled2D algorithm) for DXT1/DXT3/DXT5 block-compressed formats.

### Orphan AMB WAV CKD Handling (Resolved)

**Original issue:** Some IPK maps (e.g., Koi) contained `amb_*_intro.wav.ckd` files without matching `amb_*_intro.tpl.ckd` templates, causing the AMB audio to be silently skipped.

**Resolution:** Step 09 (`step_09_process_amb`) now detects orphan WAV CKDs and generates synthetic TPL and ILU wrappers, allowing `generate_intro_amb` and `extract_amb_audio` to populate them with real audio content.

### Karaoke Binary Field Order (Resolved)

**Original issue:** Binary CKD karaoke entries (entry class 80) had fields read in the wrong order, causing each syllable to appear on its own line.

**Resolution:** `binary_ckd_parser.py` now reads class 80 fields correctly: `IsEndOfLine`, `ContentType`, `StartTimeTolerance`, `EndTimeTolerance`, `SemitoneTolerance`.

### Autodance Video Structure (Resolved)

**Original issue:** Autodance stub wrote empty `video_structure = {}`, causing game assertion: "no valid video structure for song".

**Resolution:** `map_builder.py` now generates a minimal valid `JD_AutodanceVideoStructure` with all required fields.

---

## Active Gaps

### 1. IPK Video Offset Is Approximate

**Status:** Inherent limitation — cannot be fully resolved from available data.

Xbox 360 binary CKDs store `videoStartTime = 0.0`. The pipeline synthesizes a default from musictrack markers: `-(markers[abs(startBeat)] / 48.0 / 1000.0)`. This accounts for audio preroll but NOT for video lead-in (extra video frames before audio starts).

Video lead-in varies per map (0s for TGIF, ~1.7s for Koi, ~1.2s for MrBlueSky) and is not encoded in any binary metadata. All community tools (JustDanceEditor, ferris_dancing, Unity2UbiArt) pass `videoStartTime` through as-is rather than synthesizing it.

**Mitigation:** The GUI auto-enables VIDEO_OFFSET for IPK maps and shows a warning that manual adjustment is expected. The marker-based formula gets users in the ballpark.

### 2. NX Platform Mode for Joycons

**Status:** Partially implemented infrastructure, needs completion.

**What exists:**
- NX scene archives are downloaded and extracted
- NX platform move folders are already copied to `Timeline/Moves/NX/`
- Scene archive selection lists NX in its preference order

**What is missing:**
- NX `.gesture` files are extracted but not merged into a usable location
- Maps are only registered in `SkuScene_Maps_PC_All.isc`, not in `SkuScene_Maps_NX_All.isc`
- No user preference (checkbox/flag) to opt into NX mode

### 3. Mid-Song AMB Sounds Remain Silent

**Status:** By design, but documented as a limitation.

AMB sounds that play mid-song (`SoundSetClip`s with `StartTime > 0`) are kept as silent WAV placeholders. Their real audio content is hosted on JDU servers and cannot be downloaded. Only intro AMBs (`StartTime <= 0`) are populated with real audio.

For IPK maps, AMB WAV CKDs found inside the archive are extracted and used when available. Orphan WAV CKDs get synthetic TPL/ILU wrappers. However, mid-song AMBs that reference external audio assets remain silent.

### 4. No Multi-Audio-Track Support

**Status:** Known limitation.

Maps with more than one audio stream (e.g., alternate language tracks) are not supported. The pipeline assumes a single OGG/WAV audio file per map.

### 5. WAV Scheduling Jitter (Fallback Maps)

**Status:** Minor edge case.

When musictrack marker data is available, intro AMB duration is derived precisely. When marker data is absent, a heuristic tail of 1.355s is used. The marker-based primary path (used for both HTML/Fetch and IPK maps) does not have this limitation.

### 6. ORBIS Gesture Format Incompatibility

**Status:** Mitigated with substitution, not fully resolved.

PlayStation (ORBIS) `.gesture` files use a binary format incompatible with the PC Kinect adapter. The pipeline substitutes ORBIS-exclusive gesture variants by stripping trailing digits and copying the base Kinect gesture. This works for most cases but may produce incorrect recognition for ORBIS-exclusive choreography variants.

### 7. mapsObjectives.ilu Not Patched

**Status:** Not needed currently, but may matter.

The game file `mapsObjectives.ilu` ties specific maps to unlock conditions. The Status=3 override is sufficient to make maps playable, but maps referenced in `mapsObjectives.ilu` may still show objective-related UI.

---

## Potential Improvements

These are not bugs or gaps, but improvements identified through code analysis:

### Parallel Downloads
The current downloader processes files sequentially with a 0.5s inter-request delay. Parallel downloading could speed up Phase 1 of batch installs.

### Progress Reporting for Downloads
The download function does not report download progress (bytes received vs total). Large video files can take several minutes to download with no feedback.

### Cleanup Automation
The GUI prompts for cleanup after "Apply & Finish" but the CLI sync loop does not offer cleanup. Adding cleanup as a CLI option would improve consistency.

### Video Lead-In Detection for IPK Maps
Investigating whether ffprobe scene detection or video keyframe analysis could estimate the video lead-in duration automatically, reducing the need for manual VIDEO_OFFSET adjustment on IPK maps.
