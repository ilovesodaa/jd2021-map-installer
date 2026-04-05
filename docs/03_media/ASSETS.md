# Asset HTML Files

> **Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

Each map install requires **two HTML files** exported from the JDHelper Discord bot. These are the only external inputs the installer needs before it can download and install a map.

This page documents the **HTML input workflow** used by JD2021 Map Installer v2. V2 also supports Fetch by codename, IPK archive mode, batch directory mode, and manual source folder installs; those modes are documented separately.

> **Critical V2 Behavior and Limits (Read First)**
>
> 1. **Intro AMB is temporarily disabled globally** as a stability mitigation in v2. Expect silent intro placeholders rather than reliable intro ambient playback.
> 2. **Video timing may still require manual adjustment** after install in the Sync/Readjust flow. This is especially common in IPK-derived maps, and can still appear map-by-map in other sources.
> 3. **FFmpeg/FFprobe and vgmstream must be available** for full media processing/decoding behavior. Missing tools can cause degraded behavior, fallback paths, or install-time warnings.

| File | Conventional name | Source bot command | Contains |
|---|---|---|---|
| Asset HTML | `assets.html` | JDU assets query | Game data files (textures, main scene ZIP, preview media) |
| NOHUD HTML | `nohud.html` | NOHUD video query | Private CDN links for the full-length coach videos and audio |

> **Link expiry:** NOHUD links are time-limited (signed with `exp=` and `hmac=` parameters). Asset links also expire, though typically after longer. Run the installer immediately after saving the files.

---

## assets.html

### Origin

Saved from the JDHelper bot's "JDU assets" embed response for a specific map. The HTML is a raw Discord embed page — CSS class names like `embedField__623de` are from Discord's stylesheet and are not semantically meaningful; the parser ignores them and only reads `href` attributes.

### What it contains

The embed groups assets under several named sections:

| Section | Assets |
|---|---|
| **Coach portraits** | Coach 1–4 (`.tga.ckd`), Phone Coach 1–4 (`.png`) |
| **Cover images** | `coverImageUrl`, `cover_1024ImageUrl`, `cover_smallImageUrl`, `expandBkgImageUrl`, `expandCoachImageUrl`, `phoneCoverImageUrl`, `map_bkgImageUrl`, `banner_bkgImageUrl` |
| **Video Preview** | `AudioPreview.ogg`, multi-quality preview WebMs (`HIGH.vp8`, `HIGH.vp9`, `MID.vp8`, `MID.vp9`, `LOW.vp8`, `LOW.vp9`, `ULTRA.vp8`, `ULTRA.vp9`) |
| **Main Scene** | Per-platform ZIPs: `PC`, `Nintendo Switch` (`NX`), `Xbox One` (`DURANGO`), `Xbox SX` (`SCARLETT`), `PlayStation 4` (`ORBIS`), `PlayStation 5` (`PROSPERO`), `Google Stadia` (`GGP`), `Nintendo WiiU` |

### CDN URL structure (public assets)

```
https://jd-s3.cdn.ubi.com/public/map/{MapName}/{platform}/{Filename}/{hash}.{ext}
```

- `{MapName}` — the map codename (e.g. `Starships`). The installer extracts this automatically from discovered URLs.
- `{platform}` — subdirectory indicating the target platform (`pc/`, `nx/`, `ps4/`, `x1/`, `ggp/`, `wiiu/`). Absent for platform-agnostic files (cover images, phone textures, audio preview).
- `{hash}` — MD5 content hash used by the CDN for cache-busting. Ignored by the installer.

### What the pipeline downloads from assets.html

| Asset type | Action |
|---|---|
| Main Scene ZIP | Selected by platform preference: **DURANGO** → NX → SCARLETT → any available. Extracted and installed into the game directory. |
| Coach textures (`.ckd`) | Downloaded to the map's download directory and installed. |
| Cover/background images (`.ckd`, `.jpg`, `.png`) | Downloaded and installed. |
| Video/audio preview files | Partially used. Preview WebM may be copied as optional media when discovered in source files, but current generated runtime preview config still targets main NOHUD media. `AudioPreview.ogg` is not used as install audio. |

The parser collects all `href` URLs from the file, filters out Discord CDN proxy URLs (`discordapp.net`), then categorizes them by extension and filename pattern.

### Preview Integration Status (Current v2)

Dedicated preview assets in `assets.html` are **not required** for functional installs.

- Main gameplay still uses NOHUD video + NOHUD audio.
- In-game preview timing is primarily driven by `.trk` preview fields (`previewEntry`, `previewLoopStart`, `previewLoopEnd`) over main media.
- `AudioPreview.ogg` is not selected as gameplay audio.

#### Installed-output difference today

| Scenario | Installed files/config effect |
|---|---|
| No dedicated preview assets | Install is still valid. Preview uses main media + `.trk` markers. |
| Dedicated preview video exists | `<codename>_MapPreview.webm` may be copied into `VideosCoach/` as optional payload. |
| Dedicated preview audio exists | No install-path change in current v2; it is not wired into generated game config. |

#### Important implementation note

Current generated preview actor config (`video_player_map_preview.act`) still references main video/MPD paths by default. This means dedicated preview payloads are optional in practice unless future runtime wiring is added.

---

## nohud.html

### Origin

Saved from the JDHelper bot's NOHUD video embed response. Unlike `assets.html`, this embed is compact — it contains only video and audio download links with no section headers.

### What it contains

| Field label | File |
|---|---|
| `Ultra:` | `{Codename}_ULTRA.webm` |
| `Ultra HD:` | `{Codename}_ULTRA.hd.webm` |
| `High:` | `{Codename}_HIGH.webm` |
| `High HD:` | `{Codename}_HIGH.hd.webm` |
| `Mid:` | `{Codename}_MID.webm` |
| `Mid HD:` | `{Codename}_MID.hd.webm` |
| `Low:` | `{Codename}_LOW.webm` |
| `Low HD:` | `{Codename}_LOW.hd.webm` |
| `Audio:` | `{Codename}.ogg` |

### CDN URL structure (private, signed)

```
https://jdcn-switch.cdn.ubisoft.cn/private/map/{MapName}/{Filename}/{hash}.{ext}
    ?auth=exp={unix_timestamp}~acl=/private/map/{MapName}/*~hmac={signature}
```

- `exp=` — Unix timestamp after which the link is invalid.
- `acl=` — Access control scope (wildcard covers all files for this map).
- `hmac=` — HMAC signature. Altering any part of the URL invalidates the signature and results in a 403.

All 8 video tiers and the audio track share the same `auth` token in a single bot response.

### What the pipeline downloads from nohud.html

| Asset | Action |
|---|---|
| One NOHUD WebM (selected quality) | Downloaded and installed as the map's coach video. See [VIDEO.md](VIDEO.md) for quality selection and fallback logic. |
| `{Codename}.ogg` | Downloaded as the map's game audio track. |

The preferred video quality is set by the `--quality` flag (CLI) or the Video Quality dropdown (GUI). If the requested tier is not present in the HTML, the pipeline falls back through lower tiers automatically.

> **Timing note:** Even with correctly downloaded NOHUD assets, final in-game sync can vary by map/source. Use the installer's Sync/Readjust workflow for per-map correction when needed.

---

## How the parser works

Both files are processed identically by `extract_urls()`:

1. Opens the HTML as UTF-8 text.
2. Extracts all `href="..."` values via regex.
3. Strips Discord proxy URLs (`discordapp.net`) and decodes HTML entities (`&amp;` → `&`).
4. Returns a flat list of CDN URLs.

The distinction between asset and NOHUD content is made downstream in `download_files()` by filename pattern matching: `.ogg` without `AudioPreview` = audio track, `_ULTRA.webm` / `_HIGH.hd.webm` etc. = video, `MAIN_SCENE_*.zip` = main scene, `.ckd` / `.jpg` / `.png` = textures.

---

## File naming and placement

For single-map installs the filenames are arbitrary - pass them via `--asset-html` and `--nohud-html`. For **batch installs**, the installer expects this exact layout:

```
MapDownloads/
  {MapName}/
    assets.html    ← asset HTML for this map
    nohud.html     ← NOHUD HTML for this map
```

The map name is derived from the folder name if URL-based detection fails.
