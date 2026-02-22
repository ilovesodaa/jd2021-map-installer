# JD2021 Map Builder & Installer

An automated pipeline for extracting, building, and installing custom JDU (Just Dance Unlimited) maps into Just Dance 2021 PC. 

This project goes beyond simple video parsing; it fully integrates original map logic, including controller tracking gestures and Autodance camera features, bridging the gap between basic video backdrops and fully playable, natively-scored levels.

## Features

- **Full Playable Extraction**: Downloads and parses `MAIN_SCENE_*.zip` assets dynamically based on provided HTML configuration files.
- **Multiformat Texture Support**: Automatically strips `.ckd` headers and converts internal texture formats (including compressed DDS layouts) into standard formats (PNG/TGA/JPG) for UI usage.
- **Gesture Tracking Support (Moves)**: Automatically identifies, extracts, and injects platform-specific controller scoring logic (`.msm` and `.msq`), converting them to `.gesture` formats compatible with NX (JoyCon), Durango/Scarlett (Kinect), and Wii/Orbis controllers. 
- **Autodance Generation**: Builds native Autodance camera logic (`.act` / `.isc` / `.tpl`) natively from cooked JSON templates so matches can output their video recaps correctly. Let's record those dances!
- **Audio Sync Tools**: Provides a built-in syncing loop with interactive FFplay preview to ensure custom audio correctly pads or matches your gameplay video offset.

## Core Scripts

* `map_downloader.py`: Scrapes and downloads all necessary IPKs, Zips, WebMs, and CKD assets from raw repository `mapping.html` dumps. It guarantees required `.zip` platforms (like Orbis or PC) are prioritized so that the map isn't missing required game data.
* `json_to_lua.py`: Securely converts `.ckd` mapped JSON configurations back into engine-readable `.lua` tables and `.tpl` template files.
* `map_builder.py`: Autogenerates the massive XML/JSON-style `.isc` configurations for the map, stitching the video, audio sequences, timelines, pictograms, menus, and sub-scenes together.
* `map_installer.py`: The main entrypoint. Handles unzipping, UbiArt IPK unpacking, file routing, audio format conversions (OGG to WAV), asset conversion, and finally calls the builder to integrate the finished files into the game structure.

## Usage

```bash
python map_installer.py --map-name [YourMapName] --asset-html [path/to/assets_mapping.html] --nohud-html [path/to/nohud_mapping.html]
```

### Pre-requisites 
- A valid Just Dance 2021 PC extraction / development build.
- Python 3.x with dependencies (e.g. `requests`, `beautifulsoup4`)
- FFmpeg installed in your system PATH for audio/video manipulation and conversion.
- `ubiart-archive-tools` located in the root directory for unpacking `.ipk` archives.

## Note on Gestures
To ensure scoring accuracy across differently ported controller mechanics, the script hunts for the appropriate tracking mapping stored inside the downloaded IPKs (e.g. `Timeline/Moves/DURANGO`). By retaining these custom `.gesture` logic blocks, imported maps mimic the responsiveness of their native console releases.
