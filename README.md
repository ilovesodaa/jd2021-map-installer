# JD2021 Map Installer

An automated pipeline for extracting, building, and installing JDU (Just Dance Unlimited) maps into Just Dance 2021 PC.

## Features

- **Full Playable Extraction**: Downloads and parses `MAIN_SCENE_*.zip` assets dynamically based on provided HTML configuration files.
- **Multiformat Texture Support**: Automatically strips `.ckd` headers and converts internal texture formats (including compressed DDS and Nintendo Switch XTX) into standard formats (PNG/TGA/JPG) for UI usage.
- **UbiArt-Aware Tape Conversion**: Converts choreography, karaoke, and cinematic tapes from JDU JSON to engine-compatible Lua with proper MotionClip color hex encoding, platform-specific motion data (KEY/VAL), `Tracks` array generation, and cinematic curve processing (`vector2dNew`) with actor path resolution.
- **Cinematic & Ambient Sound Support**: Processes cinematic tapes with curve data and ambient sound templates into engine-ready `.ilu`/`.tpl` pairs.
- **Full DefaultColors Extraction**: Extracts all song theme colors (lyrics, theme, songColor_1A/1B/2A/2B, and any extras) from JDU metadata with case-insensitive key matching and hex conversion.
- **Gesture Tracking Support (Moves)**: Automatically identifies, extracts, and injects platform-specific controller scoring logic (`.msm` and `.msq`) for NX (JoyCon), Durango/Scarlett (Kinect), Orbis/Prospero, and Wii controllers.
- **Autodance Generation**: Builds native Autodance camera logic (`.act` / `.isc` / `.tpl`) from cooked JSON templates so matches can output their video recaps correctly.
- **Audio Sync Tools**: Provides a built-in syncing loop with interactive FFplay preview to ensure custom audio correctly pads or matches your gameplay video offset.

## Repository Structure

The repository has been reorganized for clarity. Core automation scripts are in the root, while archives and advanced documentation are located in subdirectories:

- **Root**: Active automation pipeline scripts.
- **[docs/](docs/)**: Comprehensive technical specifications and guides.
- **[docs/archive/](docs/archive/)**: Outdated project discovery and handoff notes.
- **[scripts/archive/](scripts/archive/)**: Legacy map-specific build and test scripts.

## Core Scripts

* `map_installer.py`: The main orchestrator. Handles downloading, unzipping, IPK unpacking, tape conversion, audio/video synchronization, asset conversion, and engine integration.
* `map_builder.py`: Autogenerates the UbiArt `.isc`, `.tpl`, `.act`, `.trk`, and `.mpd` configurations for the map, including enriched SongDesc metadata and full DefaultColors extraction from CKD data.
* `map_downloader.py`: Scrapes and downloads all necessary IPKs, ZIPs, WebMs, and CKD assets from JDU server mapping HTML files.
* `ubiart_lua.py`: UbiArt-aware Lua converter for tapes and game data. Handles MotionClip color encoding, MotionPlatformSpecifics KEY/VAL conversion, cinematic curve processing with `vector2dNew()`, ActorIndices-to-ActorPaths resolution, `Tracks` array generation, and ambient sound template processing.
* `json_to_lua.py`: Generic JSON-to-Lua converter used for non-tape files (autodance templates). For tape conversion, see `ubiart_lua.py`.
* `ckd_decode.py`: Decodes compressed CKD textures (strips 44-byte UbiArt header, handles DDS and XTX/Nintendo Switch formats).
* `batch_install_maps.py`: Batch installer that launches a separate terminal for each map folder in a given directory.

## Documentation

For advanced technical details, refer to the following guides:
- **[Manual Porting Guide](docs/MANUAL_PORTING_GUIDE.md)**: How to manually port a map without using the scripts.
- **[JDU Data Mapping Specification](docs/JDU_DATA_MAPPING.md)**: Technical breakdown of property mapping between JDU and JD2021 PC.

## Detailed Usage Guide

To use the automated installer, you need to provide two HTML files containing the JDU asset links and the NOHUD (No-HUD) video links. These are obtained using the **JDHelper** bot on Discord.

### Step 1: Query the Bot
1. Join a server that has the **JDHelper** bot (or add it to your own).
2. Use the bot's commands to query the **JDU assets** and **NOHUD assets** for the song you want to import. The links expire, so you need to do this right before running the script.

### Step 2: Extract the Data from Discord
1. Open Discord in your web browser (Chrome/Edge recommended).
2. Open **Developer Tools** (F12 or Ctrl+Shift+I).
3. Click the **Element Selector** icon in the top-left corner of the DevTools panel.
   
   ![Selector Tool](docs/img/selector_tool.png)
4. Hover over the JDHelper's response message in Discord. Aim for the area just above the main embed.
5. In the DOM tree, look for a `div` with an ID starting with `message-accessories-...`.

   ![Hover Message](docs/img/hover_message.png)
6. Once you see that its the correct element, click once.
7. On the elements panel, **Right-click** that `div` -> **Copy** -> **Copy element**.

### Step 3: Save and Run
1. Paste the copied code into a new text file. 
2. Save it as `assets.html` (for the JDU query) and `nohud.html` (for the NOHUD query).
3. Run the following command in your terminal:

```bash
python map_installer.py --map-name [MapName] --asset-html assets.html --nohud-html nohud.html
```

> [!TIP]
> **New in v1.1:** You no longer need to specify `--jd-dir` if you are running the script from the project root! The script also now automatically cleans up accidental spaces or quotes in your paths (great for dragging and dropping files into the terminal).

## Pre-requisites
- A valid Just Dance 2021 PC development build.
- Python 3.6+ with Pillow (`pip install Pillow`).
- FFmpeg installed in your system PATH.
- `ubiart-archive-tools` located in the root directory.

## Batch Installation (new)

If you have a directory of map folders (each containing the two HTML files exported from JDHelper), use the batch installer to launch installers for every map in separate terminals for manual review:

Structure:

```
givenPath/
   MapA/
      assets.html
      nohud.html
   MapB/
      assets.html
      nohud.html
```

Usage:

```bash
python batch_install_maps.py "C:\path\to\givenPath"
```

Optional JD root override:

```bash
python batch_install_maps.py "C:\path\to\givenPath" --jd21-path "D:\jd2021pc\jd21"
```

The script will try common defaults to locate your JD installation and will prompt you if it cannot find it.

## Credits

This project utilizes several essential third-party tools from the Just Dance modding community:

- **[JustDanceTools](https://github.com/the-m-v-p/JustDanceTools)**: For various UbiArt and Just Dance specific file manipulations.
- **[XTX-Extractor](https://github.com/Tofat/XTX-Extractor)**: For extracting textures from Switch-specific XTX containers.
- **[ubiart-archive-tools](https://github.com/the-m-v-p/ubiart-archive-tools)**: For unpacking and packing UbiArt `.ipk` archives.
- **JDTools by BLDS**: Tape processing logic was analyzed and ported, bringing cinematic curve handling, MotionClip color conversion, ambient sound processing, and improved Lua serialization to this pipeline.
- **Just Dance Helper**: For providing a way to get JDU assets and NOHUD videos from Discord. Built by [rama0dev](https://github.com/rama0dev).

Special thanks to the authors and contributors of these tools for making Just Dance modding possible.