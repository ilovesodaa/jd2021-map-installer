# JDNext Maps Installation - Session Report (Mar 5, 2026)

## Work Completed

During this session, we continued fixing the JD2021 Map Installer's support for JDNext maps, resolving several issues with the pipeline after Unity2UbiArt extraction:

1. **Missing Pictos and Moves**: Modified `step_04b` in `map_installer.py` to recursively copy Pictos from `Timeline/Pictos/` and Moves from `Timeline/Moves/WIIU/`. Added picto downscaling to safely resize JDNext's 512x512 PNGs to JD2021's expected 256x256 using Pillow's `Image.LANCZOS` resampling.
2. **Missing Audio and Cinematics**: Modified `step_04b` to also copy the `Audio/` and `Cinematics/` subdirectories from the Unity2UbiArt output.
3. **Missing Song Metadata (Title/Artist)**: Added `extract_jdnext_artist` to `map_downloader.py` to extract the artist string from the JDNext HTML embed. In `map_installer.py`'s `step_06`, we now use both `extract_jdnext_map_name` (Title) and `extract_jdnext_artist` (Artist) to populate `metadata_overrides`. This successfully replaces the default "Unknown Title" and "Unknown Artist" from U2UA's `songdesc.tpl.ckd`.
4. **CopyFile Permission Error**: Fixed an issue where `songdesc.tpl.ckd` was attempting to overwrite itself when the source and destination paths were the same (which happens for JDNext maps since both refer to `unity2ubiart_output/`).
5. **MenuArt Textures (Missing Covers/Background/Coach)**: Added a JDNext-specific texture mapping function (`_jdnext_menuart_mapping`) in `step_05b` to rename and convert the U2UA output PNGs into the `.tga` files that JD2021 expects:
   - `{Map}_Cover_*.png` -> mapped to `cover_generic`, `cover_online`, `cover_albumbkg`, `cover_albumcoach`.
   - `{Map}_map_bkg.png` -> mapped to `map_bkg` and `banner_bkg`.
   - `{Map}_Coach_{N}.png` -> mapped to `coach_{N}` (up to 4 coaches).

## Pending Issues / Next Steps

The following issues were discovered but have not yet been fully resolved, as the session was suspended:

1. **Squished Cover Art**: The JDNext generic cover art appears squished in-game. JDNext likely uses a 16:9 aspect ratio cover, whereas JDU/JD2021 expects a square aspect ratio (e.g., 512x512 or 1024x1024). We will need to implement cropping mechanics (e.g., cropping from the center) inside the `_jdnext_menuart_mapping` function when converting the cover PNGs to TGAs.
2. **Garbled Gesture Paths in Dance Tape**: The game crashed complaining about a gesture resource not found: `world/maps/judas/timeline/moves/pc/mapsjudasimelinemovesjudas_moto_1.gesture.gesture`.
   Investigation of the `Judas_TML_Dance.dtape` revealed that the `ClassifierPath` is garbled (e.g., `"world/maps/judas/timeline/moves/maps\judas\timeline\moves\judas_moto_1.gesture.gesture"`). This points to an issue with how the converter concatenates the Windows-style relative path from the CKD. This needs to be patched in the `map_builder.py` or the tape conversion process.
   *NOTE: Work on this was suspended as the current test map didn't have gesture files, but it will need fixing prior to completion.*

## Stashed Changes

The modifications made to `map_installer.py` and `map_downloader.py` during this session have been stored via `git stash`. You can review or re-apply them later using `git stash pop`.
