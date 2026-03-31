# Manual IPK Porting Guide (Just Dance 2021 PC)

> **Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This guide is a practical, IPK-specific manual workflow for porting maps into JD2021 PC (UbiArt), based on current V2 code behavior. It is intended for debugging, recovery, parity checks, and advanced manual installs when automation is not enough.

## Current V2 Behavior Notice (Read First)

1. **Intro AMB is under temporary mitigation in automated V2 installs.**
   - Intro AMB attempt logic is intentionally disabled in current V2 behavior.
   - Silent intro placeholders can appear and are currently expected.
2. **IPK video timing is often approximate.**
   - Many IPK musictracks provide incomplete lead-in metadata.
   - Manual post-install video offset tuning is often required.
3. **Dependencies are required for full-fidelity output.**
   - FFmpeg and FFprobe for conversion/probing.
   - vgmstream for some console audio decode paths.

---

## Table of Contents

1. [What Makes IPK Porting Different](#1-what-makes-ipk-porting-different)
2. [Prerequisites](#2-prerequisites)
3. [Step 1: Extract the IPK Safely](#3-step-1-extract-the-ipk-safely)
4. [Step 2: Identify Codename and Core Assets](#4-step-2-identify-codename-and-core-assets)
5. [Step 3: Parse MusicTrack and Build Timing](#5-step-3-parse-musictrack-and-build-timing)
6. [Step 4: Convert Audio and Video Assets](#6-step-4-convert-audio-and-video-assets)
7. [Step 5: Convert Textures, Pictos, and Tapes](#7-step-5-convert-textures-pictos-and-tapes)
8. [Step 6: Generate JD2021 Game Files](#8-step-6-generate-jd2021-game-files)
9. [Step 7: Register in SkuScene](#9-step-7-register-in-skuscene)
10. [Step 8: Validate and Readjust](#10-step-8-validate-and-readjust)
11. [Troubleshooting](#11-troubleshooting)
12. [Manual Checklist](#12-manual-checklist)

---

## 1. What Makes IPK Porting Different

Compared with Fetch or HTML workflows, IPK installs are more likely to require recovery logic:

- Binary CKD parsing is common (musictrack, songdesc, tapes).
- `videoStartTime` may be missing or zero in legacy console data.
- Textures/pictos can be split between normal map folders and cooked cache paths.
- Audio may arrive as `.wav.ckd` and need decode fallback.

Result: an IPK map may install successfully but still need manual sync refinement.

---

## 2. Prerequisites

Required tools:

- FFmpeg
- FFprobe
- vgmstream (recommended for broader audio compatibility)

Required output target:

- JD2021 game directory with write access (typically `jd21/data/World/MAPS/`).

Recommended workspace prep:

1. Keep one working folder per map (`temp/<codename>/`).
2. Keep original extracted IPK files unchanged.
3. Record every offset you test during sync tuning.

---

## 3. Step 1: Extract the IPK Safely

Manual extraction should follow the same safety expectations as V2:

1. Validate IPK magic/header before processing.
2. Decompress entries (zlib first, then lzma fallback where needed).
3. Reject unsafe paths:
   - absolute paths,
   - parent traversal (`..`),
   - any output that escapes the chosen extraction root.
4. Preserve folder structure from the archive.

Expected result: a local extracted tree containing map data, audio/video assets, and CKD files.

---

## 4. Step 2: Identify Codename and Core Assets

Find codename first, then scope every search to that codename.

Primary map content usually appears under a `world/maps/<codename>/` path inside extracted data.

Collect these inputs:

- musictrack CKD/TPL
- songdesc CKD/TPL
- dance/karaoke tape sources (`dtape`, `ktape`, or tape CKD variants)
- main video (`.webm`)
- primary audio (`.ogg`, `.wav`, or `.wav.ckd`)
- menuart covers/coaches and timeline pictos
- moves assets for platform folders

If multiple maps are bundled, do not mix assets across codenames.

---

## 5. Step 3: Parse MusicTrack and Build Timing

This is the most important IPK step.

Extract or derive:

- `markers` (sample positions at 48kHz)
- `startBeat` and `endBeat`
- `videoStartTime`
- preview fields (`previewEntry`, `previewLoopStart`, `previewLoopEnd`)

Timing rules for IPK manual work:

1. If `videoStartTime` is valid and non-zero, use it.
2. If it is zero/missing and `startBeat` is negative, derive pre-roll from markers as an approximation.
3. Keep a note that derived IPK video offsets are often close, not final.

Important: do not invent synthetic timing that ignores source marker structure.

---

## 6. Step 4: Convert Audio and Video Assets

### Audio

1. Prefer source OGG when available.
2. If only `.wav.ckd` exists, decode it first.
3. Produce map WAV at 48kHz PCM.
4. Preserve the original OGG for selection/preview usage when possible.

Example conversion:

```bash
ffmpeg -i input.ogg -ar 48000 output.wav
```

If you need trim-based alignment, use the offset derived from your timing step and keep logs of exact values tested.

### Video

1. Keep source `.webm` as primary gameplay video.
2. Ensure MPD/manifest references remain valid if present.
3. Expect to tune video sync after first in-game validation on many IPK maps.

---

## 7. Step 5: Convert Textures, Pictos, and Tapes

### Textures and pictos

1. Strip CKD wrappers where needed.
2. Decode DDS/XTX payloads to usable texture outputs (usually TGA/PNG).
3. Check both standard map paths and cooked cache-like layouts if direct paths are empty.
4. Place final outputs under expected map folders (`MenuArt/textures`, `Timeline/pictos`).

### Tapes

1. Convert JSON-style data to Lua tables for JD2021 consumption.
2. For binary tape formats, parse clips and rebuild valid Lua structures.
3. Validate clip timing/ticks and track references before install.

---

## 8. Step 6: Generate JD2021 Game Files

Create the standard map structure under `World/MAPS/<MapName>/` and generate:

- main scene ISC
- `SongDesc.tpl` and `SongDesc.act`
- Audio chain (`.trk`, musictrack tpl, sequence tpl, `.stape`, audio ISC, config sfi)
- Timeline dance/karaoke assets
- Cinematics chain
- VideosCoach files
- MenuArt actors/textures
- Autodance assets

Critical IPK notes:

1. Ensure `.trk` markers stay sample-accurate with 48kHz assumptions.
2. Keep `videoStartTime` in `.trk` aligned with your best known offset.
3. If AMB assets are missing, do not treat that as immediate install failure under current V2 mitigation state.

---

## 9. Step 7: Register in SkuScene

Register the map in `SkuScene_Maps_PC_All.isc`:

1. Add actor entry with the map codename and songdesc template path.
2. Ensure registration is idempotent (avoid duplicate entries).
3. Confirm map title and covers resolve in song select.

---

## 10. Step 8: Validate and Readjust

After first launch:

1. Confirm map loads and appears in song list.
2. Check coach select, timeline cues, and video playback.
3. Test audio/video start alignment on first beats.
4. Apply sync refinement iteratively until visually correct.

Recommended readjust loop:

1. Change only one offset axis at a time.
2. Retest from map start each pass.
3. Persist final values in your tracking/index workflow.

---

## 11. Troubleshooting

| Issue | Likely Cause | Manual Fix |
|------|------|------|
| Start silence on automated V2 install | Intro AMB mitigation currently active | Expected in current builds; continue sync tuning and watch AMB redesign updates |
| Video still off after install | IPK lead-in metadata incomplete/approximate | Manually tune video offset in readjust workflow |
| Progressive desync | Wrong WAV sample rate | Rebuild WAV at exactly 48kHz |
| Audio decode failure from CKD | Missing/unsupported decode path | Verify vgmstream availability and fallback source assets |
| Missing pictos/menuart | Assets only present in cooked/cache-style paths | Scan fallback cooked paths and re-place outputs manually |
| Coach select crash | Incomplete cinematics/timeline chain | Rebuild required ISC/TPL/ACT/TAPE references |
| Missing map title | SkuScene or SongDesc reference mismatch | Recheck codename and songdesc paths in SkuScene |

---

## 12. Manual Checklist

Use this before finalizing an IPK port:

1. IPK extracted with safe paths and no traversal issues.
2. Codename-scoped assets collected (no cross-map contamination).
3. MusicTrack markers/startBeat/endBeat/videoStartTime validated.
4. WAV exported at 48kHz PCM.
5. Video asset and manifest verified.
6. Tapes converted to valid Lua output.
7. MenuArt/pictos resolved, including fallback scans when needed.
8. Full map folder generated under `World/MAPS/<MapName>/`.
9. SkuScene registration added once (no duplicates).
10. In-game validation and manual readjust completed.

If all ten checks pass, the IPK map is in a stable manual-port state for V2.
