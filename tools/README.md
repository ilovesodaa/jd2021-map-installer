# JD2021 Modding Tools

This folder contains a collection of standalone Python scripts for working with Just Dance 2021 PC game files. These tools aid in extracting, converting, and registering map data.

## Available Tools

### 1. `convert_map_data.py` (Map Data & Tape Converter)

Converts "cooked" UbiArt JSON data (`.ckd` files) into Engine-ready Lua files. This script generates the metadata and choreography tracking needed by the game.

**What it converts:**

- **SongDesc:** `songdesc.tpl.ckd` → `SongDesc.tpl`
- **MusicTrack:** `*_musictrack.tpl.ckd` → `*_MusicTrack.tpl` and `*.trk`
- **Tapes (Dance/Karaoke):** `*_tml_dance.dtape.ckd` → `*_TML_Dance.dtape`
- **Cinematics:** `*_mainsequence.tape.ckd` → `*_MainSequence.tape` (includes curve processing for camera movements)
- **AMB Sounds:** `audio/amb/*.tpl.ckd` → `.ilu` and `.tpl` descriptor files

**Usage:**

```bash
python convert_map_data.py --input path/to/extracted/map --output path/to/output --map-name MapName
```

---

### 2. `register_map.py` (SkuScene Registration)

Registers one or more maps into the JD2021 SkuScene XML files (`.isc`). It automatically creates the necessary `Actor` nodes and `CoverflowSkuSongs` entries for all 16 platform SKU variants (PC, Switch, PS4, Xbox, etc).

**Usage:**

```bash
# Add maps via command line arguments
python register_map.py --maps Starships Temperature --output path/to/output

# Add maps from a JSON file
python register_map.py --json input.json --output path/to/output
```

> **Note:** The script has built-in duplicate detection. If a map is already registered in a SkuScene file, it will be safely skipped.

---

### 3. `convert_assets.py` (Asset Conversion Wrapper)

A batch utility for common file conversions, such as unpacking `.ipk` archives and stripping CKD headers from textures and audio files.

**Usage:**

```bash
# Extract IPK archives
python convert_assets.py ipk-extract my_archive.ipk --output path/to/output

# Decode CKD textures to standard formats (DDS/PNG/TGA)
python convert_assets.py ckd-decode texture1.ckd texture2.ckd

# Extract raw audio from CKD audio files (OGG/WAV)
python convert_assets.py ckd-audio audio1.ckd
```

---

### 4. `lua_serializer.py` (Shared Module)

This is a core utility module imported by the other tools. It is not meant to be run directly. It provides:

- JSON-to-UbiArt-Lua serialization (`to_lua()`)
- `load_ckd_json()` for stripping trailing null bytes from cooked JSON
- `color_to_hex()` for float array to `0xRRGGBBAA` conversion
- UbiArt class transformations and empty-field stripping
- A `Vector2D` class used specifically when processing cinematic curve coordinates

---

### 5. `convert_tape_raw.py` (Raw Tape Converter)

Converts "cooked" UbiArt tape data (`.dtape.ckd` or `.ktape.ckd`) into raw, readable JSON files by stripping trailing null bytes and formatting the JSON data.

**Usage:**

```bash
# Convert one or more tape CKD files to raw JSON in the current directory
python convert_tape_raw.py file1_tml_dance.dtape.ckd file2_tml_karaoke.ktape.ckd

# Convert files and save them to a specific output directory
python convert_tape_raw.py file1.dtape.ckd --output path/to/output
```

## Requirements

These tools are written in pure Python 3 and have no external library dependencies (no `lxml`, no `quickbms` required).
