# Map Config Format

This document describes the per-map configuration JSON files stored in `map_configs/`.

---

## Overview

When a map installation is finalized (via "Apply & Finish" in the GUI or the CLI sync refinement loop), the pipeline saves a configuration JSON file to `map_configs/{map_name}.json`. On subsequent installations of the same map, this config is automatically loaded to restore previous sync settings.

---

## File Location

```
project_root/
└── map_configs/
    ├── Starships.json
    ├── BadRomance.json
    └── Albatraoz.json
```

The `map_configs/` directory is created automatically by `_config_dir()` (`map_installer.py:175`).

---

## Schema

```json
{
  "map_name": "Starships",
  "v_override": -2.145,
  "a_offset": -2.060,
  "quality": "ULTRA_HD",
  "codename": "Starships",
  "marker_preroll_ms": 2060.0,
  "installed_at": "2024-01-15T14:30:00.123456"
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `map_name` | string | Sanitized map name used for file paths |
| `v_override` | float | Video start time override in seconds (typically negative) |
| `a_offset` | float | Audio offset in seconds (negative = trim, positive = pad) |
| `quality` | string | Video quality tier used (e.g., `"ULTRA_HD"`, `"HIGH"`) |
| `codename` | string | Internal JDU codename (may differ from map_name for sanitized names) |
| `marker_preroll_ms` | float or null | Marker-based pre-roll duration in milliseconds, or null if unavailable |
| `installed_at` | string | ISO 8601 timestamp of when the config was saved |

---

## Loading Behavior

`load_map_config(map_name)` (`map_installer.py:182`) is called during pipeline state creation:

1. Checks for `map_configs/{map_name}.json`
2. If found, loads and returns the JSON dict
3. Prints the loaded sync values: `v_override`, `a_offset`, `quality`
4. If the file is missing, corrupt, or unreadable, returns `None`

In the batch installer (`batch_install_maps.py`), saved configs are loaded during `create_state()` to automatically apply previous sync settings.

---

## Saving Behavior

`save_map_config()` (`map_installer.py:197`) is called:
- In the GUI: when "Apply & Finish" is clicked
- In the CLI: not called automatically (the CLI sync loop exits on option 0 without saving)

The function writes the JSON with `indent=2` formatting.

---

## Interaction with CLI Arguments

CLI arguments take precedence over saved config values:

```bash
# Uses saved config if available
python map_installer.py --asset-html assets.html --nohud-html nohud.html

# Overrides saved v_override
python map_installer.py --asset-html assets.html --nohud-html nohud.html --video-override -3.0

# Loads from explicit config file (overrides auto-detected config)
python map_installer.py --asset-html assets.html --nohud-html nohud.html --sync-config my_config.json
```

When `--sync-config` is provided, `v_override`, `a_offset`, and `marker_preroll_ms` are loaded from the specified JSON file. Explicit CLI arguments (`--video-override`, `--audio-offset`) still take priority if both are provided.
