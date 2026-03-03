# Initial Findings Report — Remaining Todo Items

## 1. JD2021 Original Maps: Locked Status

**Problem:** When a map that was originally released for JD2021 is installed via the pipeline, it appears with a "locked" status in-game instead of being immediately playable.

**Root Cause:** The `Status` field in `SongDesc.tpl`. JDU metadata for JD2021-original maps sets `Status = 12`, which maps to the `ObjectiveLocked` enum — meaning the game expects the player to unlock the song through normal gameplay progression. The pipeline currently imports this value verbatim.

For comparison, maps that work immediately use `Status = 3` (Available).

**Secondary Factor:** The game file `mapsObjectives.ilu` (in `jd21/data/World/`) ties specific maps to unlock conditions (e.g., play X songs to unlock Y). JD2021-original maps may be referenced there with objective-based lock gates.

**Fix Approach:**
- During `map_builder.py` SongDesc generation, detect if the map's `OriginalJDVersion` is `2021` (or if `Status == 12`) and override `Status` to `3` (Available).
- Optionally, also patch `mapsObjectives.ilu` to remove unlock conditions for installed maps, though overriding Status alone should be sufficient since the engine checks Status first.

**Complexity:** Low. Single field override during map building.

---

## 2. Download Throttling / Rate Limiting

**Problem:** The downloader (`map_downloader.py`) has no protection against CDN throttling or rate limiting, which could cause failed downloads.

**Current State:**
- Uses raw `urllib.request.urlretrieve` with no custom headers
- No `User-Agent` header set (Python's default `Python-urllib/X.Y` is easily flagged)
- No retry logic on failure
- No handling for HTTP 429 (Too Many Requests)
- No delays between sequential downloads
- Downloads happen in a tight loop — multiple files back-to-back

**Fix Approach (easiest first):**
1. **Set a browser-like User-Agent** — simplest change, often sufficient to bypass basic CDN blocking. Add a custom opener with a realistic UA string before downloading.
2. **Add retry with exponential backoff** — wrap downloads in a retry loop (e.g., 3 attempts, doubling wait time on each failure, with special handling for 429 responses using the `Retry-After` header).
3. **Add inter-request delay** — small sleep (0.5–1s) between sequential downloads to avoid triggering rate limits.

**Note:** A single realistic UA should be sufficient — rotation is only needed if the CDN fingerprints and bans specific UAs, which is unlikely for asset CDNs.

**Complexity:** Low to medium. The UA fix is a few lines; retry logic is a small wrapper function.

---

## 3. NX Platform Mode for Joycons

**Problem:** Users want to be able to install maps with Nintendo Switch (NX) joycon support for simulated joycon input.

**Current State — Already partially implemented:**
- NX scene archives (`*_MAIN_SCENE_NX.zip`) are already downloaded by the pipeline
- NX platform folders are already extracted from IPKs (`map_installer.py` line 1468 explicitly includes `"nx"`)
- The game already has joycon input handlers (`input_menu_nx_joycon_left.isg`, etc.)
- `SkuScene_Maps_NX_All.isc` already exists in the game files
- Scene archive selection already lists NX in its preference order: `["DURANGO", "NX", "SCARLETT"]`

**What's Missing:**

| Gap | Description |
|-----|-------------|
| Gesture merging | NX `.gesture` files are extracted but **not merged** — the merge logic only copies from `DURANGO`/`SCARLETT` (Kinect platforms) into `PC/`. NX gestures stay in `NX/` folder but aren't used. |
| NX registration | Maps are only registered in `SkuScene_Maps_PC_All.isc`, not in `SkuScene_Maps_NX_All.isc` |
| User preference | No checkbox/flag to opt into NX support |

**Fix Approach:**
1. Add a GUI checkbox "Download NX files for joycon support" (or CLI flag `--enable-nx`)
2. When enabled, keep the `NX/` moves folder separate (don't merge into `PC/`), and copy `.msm` files into it
3. Register the map in `SkuScene_Maps_NX_All.isc` alongside the existing PC registration
4. The NX scene archive download and extraction already work — no changes needed there

**Complexity:** Medium. The infrastructure is ~95% in place. Main work is the merge logic change and NX SKU registration.

Claude questions for other members:
1. What controller setup are people using? Are they using actual Nintendo Switch Joy-Cons connected to PC via Bluetooth, or a different controller that emulates joycon input? This matters because the game's NX input handlers (input_menu_nx_joycon_left.isg, etc.) expect specific input mappings.
2. Do they want NX gestures (motion-based moves) or just the NX controller button mapping? The codebase has NX .gesture files in the extracted data, but the merge logic currently only copies DURANGO/SCARLETT gestures into PC/. If they want motion-based scoring via joycons, the NX gestures need to be used instead. If they just want controller compatibility, the existing PC gestures might work fine.
3. Has anyone already gotten joycon scoring working manually with JD2021 on PC? If so, what files did they modify and what was the folder structure? Specifically:
- Did they need to register maps in SkuScene_Maps_NX_All.isc?
- Did they need to replace PC/ gesture/move files with NX/ versions?
- Did they need to modify any game config to enable NX input mode?
4. Should NX mode be the default, or opt-in? The TODO suggests a checkbox/CLI flag. Is this something most users would want enabled, or only a subset? This determines whether it should be a checkbox (opt-in) or a default behavior.
---

## 4. Delete Downloaded Files After Apply

**Problem:** After a user applies their final offset and is satisfied with the result, they may want to delete the downloaded source files to save disk space. However, deleting too early means reinstallation or offset adjustment would require re-downloading everything.

**File Categories:**

| Category | Path Pattern | Safe to Delete? | Why |
|----------|-------------|-----------------|-----|
| Scene ZIPs | `MapDownloads/{map}/*_MAIN_SCENE_*.zip` | Yes | Already extracted |
| Extracted scene dirs | `MapDownloads/{map}/*_MAIN_SCENE_*/` | Yes | Already processed into target |
| MenuArt raw materials | `MapDownloads/{map}/*.ckd` (textures) | Yes | Already decoded to PNG/TGA |
| OGG audio | `MapDownloads/{map}/*.ogg` | **No** | Needed for offset re-adjustment (WAV re-trim, AMB regeneration) |
| Gameplay video | `MapDownloads/{map}/*.webm` | **No** | Needed if user wants to change video quality/override |
| IPK extracted dir | `MapDownloads/{map}/ipk_extracted/` | **No** | Contains tapes, moves, templates needed for re-conversion |
| Asset/NOHUD HTML | `MapDownloads/{map}/*.html` | **No** | Contains download links (though they expire, useful for reference) |

**Fix Approach:**
1. After "Apply & Finish", prompt user: "Delete downloaded source files to save space?"
2. Show a strong warning: "This is irreversible. If you need to reinstall or adjust the offset later, you will need fresh asset and NOHUD links from JDHelper."
3. If confirmed, delete: scene ZIPs, extracted scene directories, decoded CKD intermediates
4. Optionally offer two tiers: "Delete safe files only" (ZIPs/extracted scenes) vs "Delete everything" (all downloads including OGG/video/IPK)
5. The warning should emphasize that JDHelper links expire, so getting new ones means going back to the Discord bot

**Complexity:** Low. File deletion logic is straightforward; the UX warning is the important part.

---

## Priority Assessment

| Item | Impact | Complexity | Suggested Priority |
|------|--------|------------|-------------------|
| Original maps locked (Status override) | High — broken UX for JD2021 maps | Low | **1st** |
| Download throttling | Medium — prevents failed installs | Low-Medium | **2nd** |
| Delete downloaded files | Low — convenience/disk space | Low | **3rd** |
| NX joycon mode | Medium — new feature | Medium | **4th** |
