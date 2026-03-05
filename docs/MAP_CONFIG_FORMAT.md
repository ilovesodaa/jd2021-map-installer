# Installer Settings Format

This document describes the persistent user settings stored in `installer_settings.json`.

---

## Overview

The installer supports a shared settings file that controls behavior across all entry points (GUI, CLI, batch installer). Settings are loaded at startup and can be edited via the GUI Settings dialog or by editing the JSON file directly.

---

## File Location

```
project_root/
└── installer_settings.json
```

Created automatically when settings are saved for the first time via the GUI Settings dialog or programmatically via `save_settings()`.

---

## Schema

```json
{
  "skip_preflight": false,
  "suppress_offset_notification": false,
  "auto_cleanup_downloads": false,
  "default_quality": "ultra_hd"
}
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `skip_preflight` | bool | `false` | Skip pre-flight checks (ffmpeg, game paths, etc.). When enabled, the GUI Install button is available immediately without running Pre-flight Check first. CLI and batch also skip the preflight step. |
| `suppress_offset_notification` | bool | `false` | Don't show the "offset refinement is needed" popup in the GUI after the installation pipeline completes. |
| `auto_cleanup_downloads` | bool | `false` | Automatically delete intermediate download files (scene ZIPs, extracted scenes, decoded CKDs) after Apply & Finish, without prompting. Audio (.ogg), video (.webm), and IPK data are always kept. |
| `default_quality` | string | `"ultra_hd"` | Default video quality tier. Used as the initial value for the GUI quality dropdown and as the CLI/batch default when `--quality` is not specified. Valid values: `ultra_hd`, `ultra`, `high_hd`, `high`, `mid_hd`, `mid`, `low_hd`, `low`. |

---

## Where Settings Are Applied

### GUI (`gui_installer.py`)
- **Startup**: Loads settings, applies `default_quality` to dropdown, enables Install button if `skip_preflight` is set
- **Pre-flight Check button**: Skips checks if `skip_preflight` is enabled
- **Pipeline complete**: Suppresses notification popup if `suppress_offset_notification` is set
- **Post-apply cleanup**: Auto-cleans without dialog if `auto_cleanup_downloads` is set
- **Settings dialog**: Opens a Toplevel window to edit all settings with Save/Cancel

### CLI (`map_installer.py`)
- **Quality default**: `--quality` flag defaults to `default_quality` setting
- **Pre-flight**: Skipped if `skip_preflight` is enabled

### Batch (`batch_install_maps.py`)
- **Quality default**: `--quality` flag defaults to `default_quality` setting
- **Pre-flight**: Skipped if `skip_preflight` is enabled

---

## API Functions (`map_installer.py`)

| Function | Description |
|----------|-------------|
| `load_settings()` | Returns a dict of all settings (defaults merged with saved values) |
| `save_settings(settings_dict)` | Writes settings dict to `installer_settings.json` |
| `get_setting(key)` | Convenience accessor for a single setting value |

---

## Offset Readjustment

The installer also supports re-adjusting offset on an already-installed map without re-running the full pipeline, provided the original download files (`.ogg`, `.webm`) still exist.

### GUI
Click "Re-adjust Offset" and select the map's download folder. The sync refinement panel activates with the map's current values.

### CLI
```bash
python map_installer.py --readjust path/to/MapDownloads/SomeMap
```

The `reconstruct_state_for_readjust()` function builds a minimal pipeline state from:
- `.ogg` audio file in the download directory
- `.webm` video file (excluding previews)
- `ipk_extracted/` musictrack metadata (if available)
- Installed `.trk` file `videoStartTime` (fallback)
