# Troubleshooting Guide - JD2021 Map Installer

This guide covers common errors and their solutions, derived from the error handling and logging throughout the codebase.

---

## Download Errors

- **HTTP 403/404 during download**: CDN links expired. Solution: get fresh HTML files from JDHelper. Links expire ~30 minutes after bot response.
- **HTTP 429 (Too Many Requests)**: CDN rate limiting. Pipeline has built-in retry with Retry-After header. If persistent, wait a few minutes.
- **"Full Audio missing"**: OGG not found after download. Usually means NOHUD HTML links expired. Get fresh links.
- **"Full Video missing"**: WebM not found. Same cause as above.
- **Network timeouts**: DOWNLOAD_TIMEOUT_S = 60 seconds. If on slow connection, downloads may fail. Retry.
- **SSL errors**: SSL verification is disabled globally (`ssl._create_unverified_context`) for CDN compatibility. If still seeing SSL errors, check network/proxy.
- **Existing video of different quality**: In CLI, prompted to Reuse/Download/Stop. In GUI/batch, existing video reused silently.

## Preflight Check Failures

- **"ffmpeg not found in PATH"**: Install ffmpeg or let the installer auto-install to `tools/ffmpeg/`.
- **"JD2021 game data not found"**: Game path resolution failed. Checked: `search_root/jd21/`, `search_root` itself, `SCRIPT_DIR/jd21/`, recursive scan. Solutions: use shorter path without spaces/accents, avoid Program Files, point directly at `jd21/` folder.
- **"SkuScene_Maps_PC_All.isc not found"**: Game data incomplete or wrong directory.
- **"Cannot write to game directory"**: Permission error. Try running as admin or moving game to non-protected path.
- **"ipk_unpack.py not found"**: Project scripts not in correct directory.
- **"Pillow not installed"**: Run `pip install Pillow`.
- **"xtx_extractor/ package not found"**: Missing bundled dependency - re-clone the repository.
- **ffplay not found (warning)**: Sync preview unavailable but installation works.
- **ffprobe not found (warning)**: Duration calculations unavailable.

## Game Path Discovery Issues

- **Clear Path Cache button / `clear_paths_cache()`**: Deletes `installer_paths.json`, forces re-scan on next run.
- **Path with spaces**: May cause issues with some tools. Use short path like `D:\jd2021`.
- **Non-ASCII characters in path**: May cause encoding errors. Use ASCII-only paths.
- **Path in Program Files**: May need admin privileges for write access.

## Texture Decoding Issues

- **"Not a CKD file: missing magic bytes"**: File is not a valid CKD texture.
- **"Not a texture CKD: missing TEX marker"**: CKD is not a texture file (it's JSON data).
- **"Unknown texture format after CKD header"**: Neither XTX nor DDS payload.
- **"Failed to deswizzle XTX texture data"**: xtx_extractor couldn't process the texture. Raw XTX saved as fallback.
- **"Pillow can't decode this DDS format"**: Uncommon DDS format. Raw DDS saved for manual conversion with ImageMagick.
- **Missing cover TGA files**: Step 05b logs `[MISS]` for each. Map loads but with blank cover art. If `cover_generic` exists but `cover_online` doesn't (or vice versa), Step 05b auto-copies.

## Audio/Sync Issues

- **Silence at map start**: Normal if no intro AMB exists. Pipeline generates intro AMB automatically. If still silent, check `Audio/AMB/` directory for intro WAV/TPL/ILU files.
- **Progressive audio desync**: Wrong sample rate. WAV MUST be 48kHz (matches markers). Re-run with correct settings.
- **Audio too early or too late**: `a_offset` value incorrect. Use sync refinement to adjust. Marker-based default is usually correct.
- **Pictos/karaoke appear too early**: `videoStartTime` incorrectly set to 0 on a pre-roll map. Restore original negative value.
- **Double audio**: AMB intro and main WAV should overlap inaudibly (same source). If you hear doubling, check if multiple AMB actors are injected.

## Config Generation Issues

- **"Could not fetch video start time"**: `musictrack.tpl.ckd` not found or has no `videoStartTime` field. Critical error.
- **Non-ASCII metadata**: Pipeline auto-strips in non-interactive mode, prompts in CLI, shows dialog in GUI.

## IPK Issues

- **"IPK extraction issue"**: Logged as warning, continues. Some IPK entries may use unsupported compression.
- **Path traversal detected**: IPK contains malicious path with `..`. Entry skipped for security.

## SkuScene Registration Issues

- **"Could not find sceneConfigs insertion point"**: SkuScene ISC is malformed or modified by another tool.
- **Map already registered**: Skipped (safe to re-run installer).
- **Map not appearing in game menu**: Check both Actor and CoverflowSong blocks in SkuScene ISC. Both are needed.

## GUI-Specific Issues

- **Log/output not updating**: TextWidgetHandler polls queue every 50ms. Check that pipeline thread is running.
- **Preview not working**: Requires ffplay. Check that ffplay is installed and in PATH.
- **"No Preview" shown**: Video path not set or video file missing.
- **Preview frozen**: May occur if ffmpeg process crashes. Stop and relaunch preview.
- **GUI hangs**: Pipeline runs in background thread. If thread crashes, GUI remains responsive but pipeline stops.

## Batch Installation Issues

- **"No valid map folders found"**: Each map folder must contain both `assets.html` and `nohud.html`.
- **Link expiration with many maps**: The two-phase batch mode downloads all maps first (Phase 1) before processing (Phase 2). If you still get 403s, reduce number of maps per batch.
- **Map skipped as "already installed"**: Use without `--skip-existing` flag, or delete the `MAPS/{map_name}/` directory first.

## General Tips

- Always get fresh HTML links immediately before running the installer.
- Use video quality tier that matches what's already downloaded to avoid re-downloading.
- Global installer settings are saved to `installer_settings.json` and auto-loaded on reinstall.
- Log files are written to `logs/install_{map_name}_{timestamp}.log`.
- Ctrl+C gracefully stops after the current pipeline step completes.
