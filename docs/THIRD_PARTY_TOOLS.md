# Third-Party Tools

This document lists all external tools and libraries used by the JD2021 Map Installer, where they are used, and what they do.

---

## Required Dependencies

### Python 3.6+

The entire pipeline is written in Python. Required for all scripts.

### Pillow (PIL)

**Install:** `pip install Pillow`

| Where Used | Purpose |
|------------|---------|
| `ckd_decode.py` (`dds_to_image()`) | Converts DDS data to TGA/PNG images |
| `gui_installer.py` (`_read_video_frames()`) | Converts raw RGB24 ffmpeg output to Tkinter-displayable images |
| `map_installer.py` (`step_05b_validate_menuart()`) | Re-saves TGA covers as uncompressed 32-bit RGBA |

### FFmpeg

**Install:** Auto-installed by the pipeline if missing, or install manually and add to PATH.

Auto-install location: `tools/ffmpeg/` within the project directory. Downloaded from `https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip`.

| Where Used | Purpose |
|------------|---------|
| `map_installer.py` (`convert_audio()`) | OGG to 48kHz WAV conversion with optional trim/pad |
| `map_installer.py` (`generate_intro_amb()`) | Generates intro AMB WAV with fade-out |
| `map_installer.py` (`extract_amb_audio()`) | Extracts real audio from OGG for AMB placeholders |
| `map_installer.py` (`show_ffplay_preview()`) | ffmpeg pipe for sync preview (video + audio muxing) |
| `gui_installer.py` (`_launch_preview()`) | ffmpeg RGB24 pipe for embedded video preview |

### FFplay

**Install:** Bundled with FFmpeg. Optional but recommended.

| Where Used | Purpose |
|------------|---------|
| `map_installer.py` (`show_ffplay_preview()`) | CLI sync preview window (receives ffmpeg pipe) |
| `gui_installer.py` (`_launch_preview()`) | Audio-only playback for GUI embedded preview |

Without FFplay, sync preview is unavailable but map installation works normally.

### FFprobe

**Install:** Bundled with FFmpeg. Optional.

| Where Used | Purpose |
|------------|---------|
| `map_installer.py` (CLI sync option 2) | Detects video and audio duration for padding calculation |
| `gui_installer.py` | Detects audio duration for seekbar range |

Without FFprobe, the "pad audio to match video length" sync option and the GUI seek bar duration display are unavailable.

---

## Bundled Dependencies

These are included in the repository and do not need separate installation.

### XTX-Extractor

**Location:** `xtx_extractor/` in project root

**Source:** [github.com/aboood40091/XTX-Extractor](https://github.com/aboood40091/XTX-Extractor)

**Purpose:** Deswizzles Nintendo Switch XTX texture data to DDS format. Called by `ckd_decode.py` when processing NX-platform CKD textures.

**How it works:** Reads the NvFD header structure from XTX data, deswizzles tiled texture data based on format-specific block sizes, and produces a standard DDS header + payload.

### ubiart-archive-tools (IPK format)

**Integrated into:** `ipk_unpack.py`

**Source:** [github.com/PartyService/ubiart-archive-tools](https://github.com/PartyService/ubiart-archive-tools)

**Purpose:** Unpacks UbiArt `.ipk` archive files. The extraction logic is integrated directly into `ipk_unpack.py`.

---

## Referenced Tools (Not Bundled)

These tools were used as references during development. Their logic has been ported into the pipeline.

### JDTools by BLDS

Tape processing logic was analyzed and ported into `ubiart_lua.py`. Contributions include:
- Cinematic curve handling (`vector2dNew()` serialization)
- MotionClip color conversion (`[a,r,g,b]` floats to `0xRRGGBBAA` hex)
- Ambient sound template processing
- Lua serialization approach

### UBIART-AMB-CUTTER by RN-JK

The AMB extraction algorithm was used as a reference for implementing automated AMB audio generation in `map_installer.py`. Specifically:
- Marker tick-to-millisecond formula (`markers[idx] / 48.0`)
- SoundSetClip splitting logic
- The 85ms calibration constant for OGG codec decode latency

### JustDanceTools

**Source:** [github.com/WodsonKun/JustDanceTools](https://github.com/WodsonKun/JustDanceTools)

Used for various UbiArt and Just Dance specific file format understanding.

---

## External Services

### JDHelper Discord Bot

**Author:** [rama0dev](https://github.com/rama0dev)

Not a code dependency, but the primary source of JDU asset data. The bot provides two HTML exports per map:
- **Asset HTML:** Contains URLs for CKD textures, IPK archives, OGG audio, and scene ZIPs
- **NOHUD HTML:** Contains the URL for the gameplay WebM video

Links expire approximately 30 minutes after the bot responds.

### Ubisoft CDN

The actual asset files are hosted on Ubisoft's CDN (`jd-s3.cdn.ubi.com`). SSL certificate verification is disabled in `map_downloader.py` for compatibility with some systems that fail to verify the CDN's certificates.
