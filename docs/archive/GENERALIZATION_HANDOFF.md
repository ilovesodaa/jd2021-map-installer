# Generalization Handoff: Converting Any JDU Song to JD2021

**Date:** 2026-02-22  
**Context:** The pipeline currently works for Starships. This document defines every change required to make it reusable for any JDU song. The next agent should implement these changes.

---

## Overview: Current vs Target Architecture

| | Current (Starships-only) | Target (Generic) |
|---|---|---|
| Entry point | `build_starships.bat` | `convert_song.py <MAPNAME>` or interactive CLI |
| Config generator | `build_starships_fix.py` (hardcoded) | `build_map_config.py` (parameterized) |
| Media restorer | `restore_starships_media.py` (hardcoded hashes) | `restore_map_media.py` (reads per-song `mapping.json`) |
| Orchestrator | `build_starships.bat` | Python orchestrator inside `convert_song.py` |

---

## Part 1: Hardcoded Values That Must Be Parameterized

### In `build_starships_fix.py`

**Global config (top of file) — trivially parameterized:**
```python
MAP_NAME = "Starships"          # → CLI arg
SRC_DIR = r"d:\jd2021pc\Starships"  # → derived: d:\jd2021pc\{MAP_NAME}
TARGET_DIR = r"d:\jd2021pc\jd21\data\World\MAPS\Starships"  # → derived
```

**In `SongDesc.tpl` — must be read from source CKD, NOT hardcoded:**
```python
Artist = "Nicki Minaj"      # → read from songdesc.tpl.ckd
NumCoach = 1                # → read from songdesc.tpl.ckd (affects loops below)
DancerName = "Unknown Dancer"  # → read from songdesc.tpl.ckd
Title = "{MAP_NAME}"        # → read from songdesc.tpl.ckd
Credits = "Credits Here"    # → read from songdesc.tpl.ckd
ChoreoCreator = "..."       # → read from songdesc.tpl.ckd
Difficulty = 2              # → read from songdesc.tpl.ckd
SweatDifficulty = 1         # → read from songdesc.tpl.ckd
BackgroundType = 0          # → read from songdesc.tpl.ckd (key: backgroundType)
LyricsType = 0              # → read from songdesc.tpl.ckd
OriginalJDVersion = 2021    # → read from songdesc.tpl.ckd
DefaultColors = ...         # → read from songdesc.tpl.ckd
```

**How to read the songdesc CKD:**
```python
sd_path = os.path.join(SRC_DIR, f"ipk_extracted/cache/itf_cooked/pc/world/maps/{map_lower}/songdesc.tpl.ckd")
with open(sd_path, 'rb') as f:
    raw = f.read()
start, end = raw.find(b'{'), raw.rfind(b'}') + 1
sd = json.loads(raw[start:end].decode('utf-8', 'ignore').strip())
sd_comp = sd['COMPONENTS'][0]  # Keys are directly on the component, NOT inside 'JD_SongDescTemplate'
artist = sd_comp.get('Artist', '')
num_coach = sd_comp.get('NumCoach', 1)
# etc.
```

**Multi-coach handling — currently hardcoded to 1 coach:**
- `PhoneImages` block: currently only has `coach1`. Must loop from 1 to `NumCoach`.
- `MenuArt/textures` actor in ISC: currently only references `coach_1`. Must loop.
- `art` list in `build_starships_fix.py` line ~513: `['banner_bkg', 'coach_1', 'cover_albumbkg', ...]` — `coach_1` through `coach_{NumCoach}` must be dynamic.
- `restore_map_media.py`: CKD hash entries for `Coach_2`, `Coach_3`, `Coach_4`, and `Phone_Coach_2` etc. must be included when present.

**USERFRIENDLY string in ISC (line ~761) — hardcoded artist/title:**
```xml
USERFRIENDLY="{MAP_NAME} : Nicki Minaj - Starships"
```
→ Must become: `USERFRIENDLY="{MAP_NAME} : {artist} - {title}"`

**MapName in stape (line ~797) — also hardcoded as string literal:**
```python
MapName = "Starships",
```
→ Already uses f-string formatting elsewhere; just needs consistency.

**musictrack CKD path — lowercase song name embedded in path:**
```python
ckd_json_path = os.path.join(SRC_DIR, "ipk_extracted/cache/itf_cooked/pc/world/maps/starships/audio/starships_musictrack.tpl.ckd")
```
→ Must become: `f"ipk_extracted/cache/.../maps/{map_lower}/audio/{map_lower}_musictrack.tpl.ckd"`

---

### In `restore_starships_media.py`

**All hash-to-path mappings are 100% Starships-specific.** Every song from JDHelper has different hashes. The entire `mappings` dict must come from a per-song `mapping.json` file.

**Proposed `mapping.json` format** (place in `{MAP_NAME}/` folder alongside downloads):
```json
{
  "map_name": "Starships",
  "video_main": "0ac1f08ec9cd2070cb1f70295661efa3.webm",
  "video_preview": "67913811d9fdd089443181e2672b619e.webm",
  "audio_main": "80f47be6f8293430ae764027a56847a4.ogg",
  "cover_phone": "6d162ce9e558fb6d4059e9d383112398.jpg",
  "cover_1024": "361e165f9e893979b0aff0de0a89ade8.png",
  "coach_1_phone": "f62544a48195680424c3b82c4059057d.png",
  "coach_2_phone": null,
  "coach_3_phone": null,
  "coach_4_phone": null,
  "ckd_coach_1": "dbe3c08891c1859cc22bd27c962e2268.ckd",
  "ckd_coach_2": null,
  "ckd_coach_3": null,
  "ckd_coach_4": null,
  "ckd_cover_generic": "8c69e5b8d670d7f19880388e995ff064.ckd",
  "ckd_cover_online": "86e08b8e5c89f8389db5723f136b81d7.ckd",
  "ckd_cover_albumbkg": "7285efe8d585ac76b882c2115989a4f8.ckd",
  "ckd_cover_albumcoach": "370d94f300a9f5c48d372f3fad0cec8e.ckd",
  "ckd_map_bkg": "440d6ce474051538b9d98b0d0dab2341.ckd",
  "ckd_banner_bkg": "650d843e8d21e55a4cd58a17d6588005.ckd"
}
```

The `downloadMapping.html` (provided by JDHelper) already contains all hash↔filename relationships. A helper script `parse_download_mapping.py` could auto-generate `mapping.json` from it by parsing the HTML embed fields.

---

### In `build_starships.bat`

Hardcoded paths need to become variables driven by a single `MAP_NAME` parameter:
```bat
set MAP_NAME=Starships           # → %1 from command line arg
set MAP_NAME_LOWER=starships     # → auto-lowercased (PowerShell: $MAP_NAME.ToLower())
set MAP_DIR=d:\jd2021pc\jd21\data\World\MAPS\%MAP_NAME%
set CACHE_DIR=d:\jd2021pc\jd21\data\cache\itf_cooked\pc\world\maps\%MAP_NAME_LOWER%
set SRC_DIR=d:\jd2021pc\%MAP_NAME%
set PICTO_SRC=%SRC_DIR%\ipk_extracted\cache\itf_cooked\pc\world\maps\%MAP_NAME_LOWER%\timeline\pictos
```

---

## Part 2: Known Path Inconsistency — `ipk_extracted_fixed`

In `build_starships.bat`, steps 5 (tape conversion) use a **different** source path than steps 6 (picto decoding):

```bat
# Step 5 uses:
d:\jd2021pc\ipk_extracted_fixed\cache\itf_cooked\pc\world\maps\starships\timeline\...

# Step 6 uses:
d:\jd2021pc\Starships\ipk_extracted\cache\itf_cooked\pc\world\maps\starships\timeline\pictos
```

`ipk_extracted_fixed` is a separate top-level folder, not inside `Starships/`. This is from an older manual IPK extraction. For generalization, **all extracted IPK data should live under `{MAP_NAME}/ipk_extracted/`**, using the same structure JDHelper/ubiart-archive-tools produces.

**Action:** Update step 5 to use `d:\jd2021pc\%SRC_DIR%\ipk_extracted\...` consistently, and verify the dtape/ktape files are present there for Starships before removing the old path.

---

## Part 3: Recommended Implementation Plan

### Step 1 — Create `mapping.json` for Starships (proof of concept)
Manually create `d:\jd2021pc\Starships\mapping.json` with the format above (values already known). This becomes the template for future songs.

### Step 2 — Refactor `restore_starships_media.py` → `restore_map_media.py`
```python
import argparse, json, os, shutil, subprocess

parser = argparse.ArgumentParser()
parser.add_argument('map_name')
parser.add_argument('--base-dir', default=r'd:\jd2021pc')
args = parser.parse_args()

src = os.path.join(args.base_dir, args.map_name)
target = os.path.join(args.base_dir, 'jd21', 'data', 'World', 'MAPS', args.map_name)

with open(os.path.join(src, 'mapping.json')) as f:
    m = json.load(f)

# Build dest paths from mapping, skip null entries
# ...
```

### Step 3 — Refactor `build_starships_fix.py` → `build_map_config.py`
- Add `map_name` as the first positional CLI arg.
- Derive all lowercase/path variables from it.
- Read artist, title, num_coach, difficulty, etc. from `songdesc.tpl.ckd`.
- Loop coach-dependent sections over `range(1, num_coach + 1)`.
- Keep `--video-start-time-override` flag (already implemented).

### Step 4 — Refactor `build_starships.bat` → `convert_song.bat <MAPNAME>`
Or, preferably, replace with a Python orchestrator `convert_song.py` that calls all pipeline steps in order with proper error handling.

### Step 5 — Optional: `parse_download_mapping.py`
Parse `downloadMapping.html` from JDHelper to auto-generate `mapping.json`. This eliminates manual hash lookup for each new song. The HTML embed contains all field names (Coach 1:, Coach 2:, AudioPreview:, etc.) and their download URLs with hash filenames.

---

## Part 4: Per-Song Inconsistencies to Watch For

| Inconsistency | Description | Handling |
|---|---|---|
| Coach count | 1–4 coaches; affects PhoneImages, MenuArt actors, CKD list | Read `NumCoach` from songdesc CKD |
| No MapPreview video | Some songs may not have a standalone preview `.webm` | Fall back to main video (already done for Starships) |
| NX vs PC CKDs | JDHelper provides NX (Nintendo Switch) CKDs for menu art; these need XTX deswizzle, not just DDS | `ckd_decode.py` already handles both — confirm it auto-detects |
| Missing pictos | Some older JDU songs may have fewer entries or missing picto CKDs | Add file-existence check in bat/script; fall back to dummy pictos |
| `videoStartTime` sync | Per-platform encoding difference; PC may need empirical offset | `--video-start-time-override` flag now available |
| Title vs MapName | Some songs have a `Title` field different from `MapName` in songdesc | Use `Title` for display strings, `MapName` for file paths |
| Case sensitivity | JDU paths use Title Case (`Starships`); IPK subpaths use lowercase (`starships`) | Always derive lowercase from `MAP_NAME.lower()` |
| `ipk_extracted_fixed` path | Legacy path used in current bat for tapes | Standardize to `{MAP_NAME}/ipk_extracted/` |
| Songs with duo/trio lyrics | `LyricsType` != 0 | Karaoke tape may have multiple color tracks; no special handling needed, just ensure ktape converts correctly |
| Missing `songdesc.tpl.ckd` fields | Older JDU maps may lack some fields (e.g. `DefaultColors`) | Use `.get()` with sensible defaults |

---

## Summary of Immediate Next Actions for the Next Agent

1. **Create `d:\jd2021pc\Starships\mapping.json`** using the format in Part 1.
2. **Create `restore_map_media.py`** that reads `mapping.json` (generalized version of `restore_starships_media.py`).
3. **Create `build_map_config.py`** that reads metadata from `songdesc.tpl.ckd` and takes `MAP_NAME` as a CLI arg (generalized version of `build_starships_fix.py`).
4. **Create `convert_song.py`** or update `build_starships.bat` to be `convert_song.bat <MAPNAME>` — the all-in-one orchestrator.
5. **(Optional)** Create `parse_download_mapping.py` to auto-generate `mapping.json` from JDHelper's HTML file.
6. **Fix `ipk_extracted_fixed` path inconsistency** in the bat/orchestrator.
