# JDNext Map Installation Handover Report: MrBlueSky

## Overview

The goal was to experiment with installing a "JDNext" map (`MrBlueSky`) into JD2021 PC using `Unity2UbiArt` to convert the raw Unity assets, and then manually integrating those outputs into the game engine to understand the pipeline for future automation.

## What Was Accomplished

1. **Unity2UbiArt Execution**:
   - Configured `config.json` (disabled audio cutting to avoid Tkinter dialog hangs).
   - Acquired and placed `AssetStudioModCLI` in `bin/AssetStudioModCLI`.
   - Placed the `MrBlueSky` map bundle in the `input` folder and ran `main.py`.
   - Successfully generated output files in `output/MrBlueSky`: `Audio/`, `Cinematics/`, `Timeline/`, and `songdesc.tpl.ckd`.

2. **Asset Conversion (Audio & Video)**:
   - Used FFmpeg to convert `1b466108d85083ff698b82ed345b9438.opus` into both `.wav` and `.ogg` formats under `data/World/MAPS/MrBlueSky/Audio/`.
   - Copied the `a974de036b4cfdd37722a2277f74675c.webm` to `data/World/MAPS/MrBlueSky/VideosCoach/mrbluesky.webm`.

3. **Asset Extraction (UI Graphics)**:
   - Used `AssetStudioModCLI` directly on the `MrBlueSky` map package directory to extract `Texture2D` PNGs.
   - Converted the extracted PNGs (Covers, Coach graphics) into `.tga` format using Python's Pillow library and placed them in `data/World/MAPS/MrBlueSky/menuart/textures/`.

4. **Map Data Stub Generation**:
   - Used the project's existing `map_builder.py` functions to generate the boilerplate XML `.isc`, `.tpl`, and `.act` files for Audio, Timeline, Cinematics, MenuArt, VideosCoach, and Autodance in the `data/` directory.

5. **JSON CKD Parsing and Lua Generation**:
   - **Crucial Discovery**: `Unity2UbiArt` produces files with a `.ckd` extension, but they are actually **plaintext JSON**, not compiled UbiArt binary data.
   - The game engine crashes when it tries to read these JSON files directly from the `cache/itf_cooked/...` directories.
   - **Fix**: We wrote a temporary script (`tmp_convert.py`) that uses `ubiart_lua` and `map_builder` to ingest these JSON `.ckd` files and output properly formatted Lua files (`.trk`, `.ktape`, `.dtape`, `.tape`) directly into the `data/World/MAPS/MrBlueSky/` directories.
   - Deleted the pseudo-`.ckd` files from the `cache/` directory so the engine relies solely on our generated Lua files.

6. **Raw Asset Placement**:
   - Copied raw `.msm` (Moves) and `.png` (Pictograms) from the `Unity2UbiArt` Timeline output directly into `data/World/MAPS/MrBlueSky/Timeline/`.

7. **Registration**:
   - Successfully ran `register_map.py` to add `MrBlueSky` to all `SkuScene` registries.

## Current Status & Known Issues

- **The map is registered and the data files are in place, but the game is still throwing errors upon attempting to load or play it.**
- The exact error logs were not accessible in this session due to time/routing constraints, but they are occurring *after* the initial Lua parsing fixes were applied.

## Next Steps for the Next AI

1. **Diagnose the Crash**: Ask the user for the specific crash logs or assert messages that appeared during the last playtest.
2. **Investigate JSON-to-Lua Accuracy**: Verify that the Lua files we generated (especially `MrBlueSky.trk` and the tapes) perfectly match the format the engine expects. There might be missing fields, incorrect data types, or structural issues in how `ubiart_lua.py` handles the *specific* JSON output from `Unity2UbiArt` (which might differ slightly from officially un-cooked JD2021 maps).
3. **Verify SongDesc**: Ensure `SongDesc.tpl` is correctly linked and formatted. We generated a dummy one using `map_builder._write_songdesc` fed by data from `songdesc.tpl.ckd`.
4. **Check Raw Assets**: Ensure the engine is successfully compiling the raw `.msm` and `.png` pictograms on the fly. If not, they might need to be pre-cooked into real `.ckd` binaries using a different tool before loading.
5. **Pathing Audit**: Double-check all internal paths within the `.isc` and `.tpl` files against the physical file locations on disk (paying close attention to capitalization, as the PC cache paths are strictly lowercase).
6. **Automation Planning**: Once the manual installation is stable and crash-free, begin designing the automated script (`install_jdnext.py` or an integration into `map_installer.py`) as noted in the user's `todo.txt` (`integrate with JDH_Downloader so you only need to provide a code name and it will be automated to being installed`).
