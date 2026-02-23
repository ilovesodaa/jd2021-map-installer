# Conversion Project Todo List

## Current Tasks

- [x] Investigate audio preview logic — **DONE: preview audio uses main audio via `.trk` seek values; `AudioPreview` files are orphaned and can be removed.**
- [ ] Fix missing UI elements
    - Outline separating song select confirmation from background song list is missing (global issue, not limited to Starships).
    - On coach select, the "dance" label and controller button are not visible. This is a global, non-game-breaking visual bug affecting song select UI. Investigate possible conflicts or missing assets/config.
- [ ] Generalize script for all JDU songs
    - See `GENERALIZATION_HANDOFF.md` for full analysis and plan.


## New Issue: Audio/Video Sync (Full Length)

- [x] Investigate and manually adjust sync between full-length audio and video.
    - **FIXED:** Added `--video-start-time-override SECONDS` CLI arg to `build_starships_fix.py`. Defaults to the original JDU value; pass a negative float to shift video sync empirically.
    - **AudioPreview orphan also fixed:** Removed `Starships_AudioPreview.ogg/wav` copy/conversion from `restore_starships_media.py`. Engine uses main audio + `.trk` seek values only.

## Investigation Notes

### Audio Preview Logic — RESOLVED
- **Finding:** The engine uses `previewEntry`/`previewLoopStart`/`previewLoopEnd` in the `.trk` file to seek into the **main audio** for preview. No separate audio preview actor or explicit path is used anywhere — confirmed by comparing against GetGetDown (reference map), which also has no separate preview audio file.
- **`Starships_AudioPreview.ogg/wav` are orphaned assets.** Copied by `restore_starships_media.py` but never referenced by any actor, ISC, TPL, or scene file. The engine is never told to use them. Safe to remove from the copy/convert pipeline.
- Confirmed values in `Starships.trk`: `previewEntry = 84.0`, `previewLoopStart = 84.0`, `previewLoopEnd = 244.0` (beats). These serve as both audio and video preview seek points simultaneously.
- **Action:** Remove `Starships_AudioPreview.ogg/wav` copy/conversion from `restore_starships_media.py`. The main audio handles everything.

### UI Elements
- Missing outline and "dance" label may be due to config or asset issues.
- Next steps: Compare with a working reference map (e.g., GetGetDown) to identify differences in config or assets that affect UI rendering.

### Script Generalization
- Current scripts are tailored for "Starships"; need to parameterize for other songs.
- Next steps: Identify all hardcoded values, design a flexible input system (CLI/GUI), and document required adjustments for new songs.
