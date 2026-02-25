# JDU Unused Data: Improvement Opportunities

This document catalogs data available in JDU (Just Dance Unlimited) server payloads that our
installer pipeline currently ignores or simplifies. Each item is ranked by potential quality
improvement if implemented.

> **Related docs:**
> - `docs/JDU_DATA_MAPPING.md` -- field-level mapping of what IS used today

---

## Tier 1 -- High Impact

### 1.1 Stape BPM / Signature Data (SlotClips) -- IMPLEMENTED

> **Implemented:** The installer now converts `.stape.ckd` files via `json_to_lua.py`,
> overwriting the empty fallback stape with the full SlotClip data (BPM, Signature, timing
> per section). Falls back to the empty stape if no `.stape.ckd` exists or conversion fails.

**What JDU provides:**
Each `.stape.ckd` contains an array of `SlotClip` entries with per-section timing data:

```json
{
  "__class": "SlotClip",
  "Id": 886920941,
  "TrackId": 0,
  "IsActive": 1,
  "StartTime": 912,
  "Duration": 384,
  "Bpm": 118.812500,
  "Signature": "0101010101010101030303030300",
  "Guid": "003d0112-fa0b-4f77-8a32-2c93700f8rt6"
}
```

A typical map has 19-40+ SlotClips covering the full song, each with:
- `Bpm` -- beats per minute for that section
- `Signature` -- encoded beat pattern (affects rhythm UI display)
- `StartTime` / `Duration` -- section boundaries in ticks
- `Guid` -- unique identifier per section

**What we generate:**
An empty stape with just `TapeClock` and `MapName`:

```lua
params =
{
    NAME="Tape",
    Tape =
    {
        TapeClock = 0,
        MapName = "MapName"
    }
}
```

**Note:** The GetGetDown reference map also uses an empty stape (same as our generator output).
This means the JD2021 PC engine runs fine without SlotClip data, but the data could potentially
improve beat sync accuracy for sections with tempo changes, or enable future rhythm-based UI
features.

**Where in code:** `map_builder.py` `generate_text_files()` function (stape generation block)

**Effort:** Medium -- need to convert SlotClip JSON arrays through `json_to_lua.py` and insert
into the stape template. Requires testing whether the engine actually reads them.

---

### 1.2 Tags (Song Categorization) -- IMPLEMENTED

> **Implemented:** Tags are now extracted from the CKD `songdesc.tpl.ckd` payload and passed
> through to the generated `SongDesc.tpl`. Falls back to `["Main"]` when CKD has no Tags.

**What JDU provides:**
Real categorization tags per song in `songdesc.tpl.ckd`:

```json
"Tags": ["Extreme", "Main"]
```

Common tag values seen across maps: `"Main"`, `"Extreme"`, `"Cool"`, `"Happy"`, `"Calm"`,
`"Classic"`, `"Pop"`, `"Rock"`, etc. These affect how songs appear in the game's filter/category
menus.

**What we generate:**
Hardcoded to `["Main"]` regardless of actual song data:

```lua
Tags =
{
    {
        VAL = "Main"
    }
},
```

**Where in code:** `map_builder.py` `generate_text_files()` function (SongDesc generation block)

**Effort:** Trivial -- extract `Tags` array from the CKD JSON and format as Lua VAL entries
instead of hardcoding. A few lines of code in the SongDesc generation block.

**Impact:** Songs would appear in the correct filter categories (e.g., an intense song tagged
`"Extreme"` would show up under the Extreme filter instead of only under "Main").

---

### 1.3 MenuArt Shaders and Masks

**What JDU provides (in the ISC scene data):**
Menu art actors use `alpha_mul_b.msh` shader with mask textures for rounded-corner album covers:

```
shaderPath = "World/_COMMON/MatShader/alpha_mul_b.msh"
```

Plus a secondary texture channel (`back`) with a mask texture for corner rounding.

**What we generate:**
Single-layer shader without masking:

```lua
shaderPath = "World/_COMMON/MatShader/MultiTexture_1Layer.msh"
```

**What the reference map uses:**
GetGetDown also uses `MultiTexture_1Layer.msh` -- same as our generator. So our output matches
the on-disk reference. The `alpha_mul_b.msh` shader appears in JDU's embedded ISC data, which
uses `EMBED_SCENE="1"` (inline XML) vs our `EMBED_SCENE="0"` (separate files). Both approaches
are valid; the visual difference is subtle (rounded vs sharp corners on album art).

**Where in code:** `map_builder.py` `generate_text_files()` function (menuart shader assignment)

**Effort:** Medium -- would need to bundle the mask texture and switch shaders. Low priority
given that the reference map doesn't use it either.

---

## Tier 2 -- Medium Impact

### 2.1 MotionPlatformSpecifics for PC

> **Resolved (N/A):** JD2017 PC was the only native PC Just Dance release and shipped with
> mobile phone scoring only -- no PC-specific gesture or scoring calibration files exist in JDU.
> The absence of a `"PC"` key in `MotionPlatformSpecifics` is intentional. The engine falls back
> to console platform data, which works correctly with phone-based scoring. No action needed.

**What JDU provides:**
Each MotionClip in dance tapes contains a `MotionPlatformSpecifics` dictionary keyed by
platform:

```json
"MotionPlatformSpecifics": {
    "X360": { "ScoreScale": 1.0, "ScoreSmoothing": 0, "ScoringMode": 0, ... },
    "ORBIS": { "ScoreScale": 1.0, ... },
    "DURANGO": { ... }
}
```

**Current behavior:**
`ubiart_lua.py` passes `MotionPlatformSpecifics` through as-is (dict-to-KEY/VAL conversion).
There is no `"PC"` key in JDU data because PC uses mobile phone scoring, not controller/camera
gesture scoring.

---

### 2.2 Autodance FX Parameters -- RESOLVED

> **Resolved:** The installer converts `autodance/*.tpl.ckd` via `json_to_lua.py`
> in `step_11_extract_moves`, which overwrites the empty fallback TPL from `map_builder.py`.
> The CKD contains the full `AutoDanceFxDesc` structure with all 60+ effect parameters, and
> `json_to_lua.py` handles `__class` objects, nested dicts, and arrays correctly. A guard in
> `generate_text_files()` prevents sync refinement ("Apply") from overwriting the converted
> TPL with the empty stub. No additional changes needed.

**What JDU provides:**
Some maps include `AutoDanceFxDesc` data with 60+ visual effect parameters for the autodance
recap feature:

```json
{
  "__class": "AutoDanceFxDesc",
  "toonEnabled": true,
  "toonColorFactor": 0.8,
  "halftoneEnabled": false,
  "slimeEnabled": true,
  "refractionIndex": 1.33,
  "floorPlaneHeight": -0.5,
  ...
}
```

These control post-processing effects applied during autodance playback (toon shading, halftone,
slime overlay, refraction, floor plane rendering).

**Current behavior:**
The autodance TPL is generated with empty `recording_structure` and `video_structure`. If the
map's `.adrecording.ckd` and `.advideo.ckd` files are converted (added in recent fix), they may
contain some of this data, but FX parameters embedded in the main autodance TPL are not
extracted.

**Where in code:** `map_builder.py` `generate_text_files()` function (autodance TPL generation)

**Effort:** Complex -- the FX system has many interacting parameters and would need testing to
verify engine behavior. Low priority since autodance is a secondary feature.

---

### 2.3 PhoneImages Path Source -- IMPLEMENTED

> **Implemented:** PhoneImages paths are now read directly from the CKD `songdesc.tpl.ckd`
> payload (includes cover + all coaches). Falls back to path reconstruction from convention
> when CKD has no PhoneImages data.

**What JDU provides:**
Pre-computed phone image paths in `songdesc.tpl.ckd`:

```json
"PhoneImages": {
    "Cover": "world/maps/badromance/menuart/textures/badromance_cover_phone.jpg",
    "coach3": "world/maps/badromance/menuart/textures/badromance_coach_3_phone.png",
    "coach2": "world/maps/badromance/menuart/textures/badromance_coach_2_phone.png",
    "coach1": "world/maps/badromance/menuart/textures/badromance_coach_1_phone.png"
}
```

**What we generate:**
Paths are reconstructed from convention rather than using the CKD values:

```python
KEY = "cover",  VAL = "world/maps/{map_lower}/menuart/textures/{map_lower}_cover_phone.jpg"
KEY = "coach1", VAL = "world/maps/{map_lower}/menuart/textures/{map_lower}_coach_1_phone.png"
```

Source: `map_builder.py` `generate_text_files()` function (PhoneImages section).

**In practice:** The reconstructed paths match the CKD paths for all standard maps. This only
matters if a map uses non-standard naming, which hasn't been observed.

**Effort:** Trivial -- read PhoneImages from CKD and use directly instead of reconstructing.
Marginal reliability improvement.

---

## Tier 3 -- Low Impact

### 3.1 DoubleScoringType

**What JDU provides:** Integer field in songdesc indicating scoring mode for duo choreographies.
Currently not extracted; defaults to engine default.

### 3.2 SubArtist / SubTitle / SubCredits

**What JDU provides:** Additional metadata fields for featured artists, subtitle text, and
extended credits. Currently ignored; only `Artist`, `Title`, and `Credits` are extracted.

### 3.3 AudioPreviewFadeTime

**What JDU provides:** Float value controlling how quickly the song preview fades when leaving
the song selection screen. Currently not extracted; engine uses default fade.

---

## Priority Implementation Table

| # | Item | Effort | Quality Improvement | Status |
|---|------|--------|--------------------|--------------------|
| 1 | ~~Pass through Tags from CKD~~ | ~~Trivial~~ | ~~Song filter/categorization~~ | **DONE** |
| 2 | ~~Use CKD PhoneImages paths~~ | ~~Trivial~~ | ~~Path reliability~~ | **DONE** |
| 3 | ~~Use real stape SlotClip data~~ | ~~Medium~~ | ~~Beat sync (tempo changes)~~ | **DONE** |
| 4 | ~~Investigate PC MotionPlatformSpecifics~~ | ~~Investigation~~ | ~~Score accuracy~~ | **N/A** (mobile scoring) |
| 5 | MenuArt shader/mask switch | Medium | Rounded album art corners | Open (matches reference) |
| 6 | ~~Autodance FX parameters~~ | ~~Complex~~ | ~~Autodance visual effects~~ | **DONE** (already handled) |
| 7 | SubArtist/SubTitle metadata | Trivial | Richer song info | Open (not in CKD) |

Items marked **DONE** have been implemented. Items marked **N/A** were investigated and
determined to not require changes. Remaining open items are candidates for future work.

---

*Based on analysis of GetGetDown (reference map, 407 files) and BadRomance/Albatraoz JDU
payloads (874 files across 8 platforms). February 2026.*
