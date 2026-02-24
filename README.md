# JD2021 Map Installer

An automated pipeline for extracting, building, and installing JDU (Just Dance Unlimited) maps into Just Dance 2021 PC.

## Features

- **Full Playable Extraction**: Downloads and parses `MAIN_SCENE_*.zip` assets dynamically based on provided HTML configuration files.
- **Multiformat Texture Support**: Automatically strips `.ckd` headers and converts internal texture formats (including compressed DDS and Nintendo Switch XTX) into standard formats (PNG/TGA/JPG) for UI usage.
- **UbiArt-Aware Tape Conversion**: Converts choreography, karaoke, and cinematic tapes from JDU JSON to engine-compatible Lua with proper MotionClip color hex encoding, platform-specific motion data (KEY/VAL), `Tracks` array generation, and cinematic curve processing (`vector2dNew`) with actor path resolution.
- **Cinematic & Ambient Sound Support**: Processes cinematic tapes with curve data and ambient sound templates into engine-ready `.ilu`/`.tpl` pairs.
- **Pre-Roll Audio Coverage**: Generates an intro AMB that covers the silence window caused by negative `videoStartTime` (the engine's WAV scheduling delay). Sources audio from the same OGG as the main track, making the overlap inaudible. Formula scales automatically to any map.
- **Full DefaultColors Extraction**: Extracts all song theme colors (`lyrics`, `theme`, `songColor_1A/1B/2A/2B`, and any extras) from JDU metadata with case-insensitive key matching and hex conversion.
- **Gesture Tracking Support (Moves)**: Automatically identifies, extracts, and injects platform-specific controller scoring logic (`.msm` and `.msq`) for NX (JoyCon), Durango/Scarlett (Kinect), Orbis/Prospero, and Wii controllers.
- **Autodance Generation**: Builds native Autodance camera logic (`.act` / `.isc` / `.tpl`) from cooked JSON templates so matches can output their video recaps correctly.
- **Audio Sync Tools**: Provides a built-in syncing loop with interactive FFplay preview to ensure custom audio correctly pads or matches your gameplay video offset. Intro AMB regenerates automatically on every sync adjustment.

## Core Scripts

* `map_installer.py`: The main orchestrator. Handles downloading, unzipping, IPK unpacking, tape conversion, audio/video synchronization, intro AMB generation, asset conversion, and engine integration.
* `map_builder.py`: Autogenerates the UbiArt `.isc`, `.tpl`, `.act`, `.trk`, and `.mpd` configurations for the map, including enriched SongDesc metadata and full DefaultColors extraction from CKD data.
* `map_downloader.py`: Scrapes and downloads all necessary IPKs, ZIPs, WebMs, and CKD assets from JDU server mapping HTML files.
* `ubiart_lua.py`: UbiArt-aware Lua converter for tapes and game data. Handles MotionClip color encoding, MotionPlatformSpecifics KEY/VAL conversion, cinematic curve processing with `vector2dNew()`, ActorIndices-to-ActorPaths resolution, `Tracks` array generation, and ambient sound template processing.
* `json_to_lua.py`: Generic JSON-to-Lua converter used for non-tape files (autodance templates, stape data). For tape conversion, see `ubiart_lua.py`.
* `ckd_decode.py`: Decodes compressed CKD textures (strips 44-byte UbiArt header, handles DDS and XTX/Nintendo Switch formats).
* `batch_install_maps.py`: Batch installer that launches a separate terminal for each map folder in a given directory.

## Documentation

- **[Getting Started](docs/GETTING_STARTED.md)** — Full setup walkthrough: dependencies, third-party tools, obtaining JD2021 PC, and running the installer.
- **[Audio Timing & Pre-Roll Silence](docs/AUDIO_TIMING.md)** — Technical deep-dive into the `videoStartTime` synchronization model and the AMB intro solution.
- **[JDU Data Mapping Specification](docs/JDU_DATA_MAPPING.md)** — Field-level mapping between JDU JSON payloads and JD2021 PC engine files.
- **[Manual Porting Guide](docs/MANUAL_PORTING_GUIDE.md)** — How to manually port a map without using the scripts; also covers the full map directory structure and file format reference.
- **[Unused Data Opportunities](docs/JDU_UNUSED_DATA_OPPORTUNITIES.md)** — Catalog of JDU data fields not currently used, with implementation status and priority rankings.

## Limitations

- **JD2021 PC only** — maps installed by this pipeline target the PC development build and are not compatible with console versions.
- **Background AMB sounds remain silent** — JDU ambient sounds other than the intro are kept as silent placeholders; their audio is hosted on JDU servers and cannot be downloaded through this pipeline.
- **JDHelper required** — asset HTML files must be exported from the JDHelper Discord bot. Links expire quickly after the bot responds.
- **WAV scheduling jitter** — the intro AMB tail (1.355s past the nominal handoff) was empirically derived. On systems with unusually high audio pipeline latency the gap may still be audible, though this has not been observed in practice.
- **No multi-audio-track support** — maps with more than one audio stream are not supported.

## Credits

This project utilizes several essential third-party tools from the Just Dance modding community:

- **[JustDanceTools](https://github.com/WodsonKun/JustDanceTools)**: For various UbiArt and Just Dance specific file manipulations.
- **[XTX-Extractor](https://github.com/aboood40091/XTX-Extractor)**: For extracting textures from Switch-specific XTX containers.
- **[ubiart-archive-tools](https://github.com/PartyService/ubiart-archive-tools)**: For unpacking and packing UbiArt `.ipk` archives.
- **JDTools by BLDS**: Tape processing logic was analyzed and ported, bringing cinematic curve handling, MotionClip color conversion, ambient sound processing, and improved Lua serialization to this pipeline.
- **Just Dance Helper**: For providing a way to get JDU assets and NOHUD videos from Discord. Built by [rama0dev](https://github.com/rama0dev).

Special thanks to the authors and contributors of these tools for making Just Dance modding possible.
