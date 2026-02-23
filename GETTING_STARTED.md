# Getting Started

## Prerequisites

Install these before running anything:

1. **Python 3.6+** — https://www.python.org/downloads/
2. **FFmpeg** — must be in your system `PATH`
   - Download: https://ffmpeg.org/download.html
   - Test: `ffmpeg -version` in terminal
3. **Pillow** (required for texture conversion):
   ```
   pip install Pillow
   ```
4. **Just Dance 2021 PC** development build — place it in a `jd21/` folder inside the project root, or pass the path manually via `--jd-dir`.

---

## Setup

Unzip everything into a single folder. Your structure should look like:

```
jd2021pc/
├── map_installer.py
├── map_builder.py
├── map_downloader.py
├── ckd_decode.py
├── json_to_lua.py
├── ubiart_lua.py
├── batch_install_maps.py
├── README.md
├── GETTING_STARTED.md
├── docs/
├── ubiart-archive-tools/
├── XTX-Extractor/
└── jd21/              <- your JD2021 PC install goes here
```

---

## Preparing Your Map Data

You need two HTML files per map, obtained from the **JDHelper** Discord bot:

1. Open Discord in a **browser** (Chrome or Edge recommended)
2. Query the bot for the song — one query for **JDU assets**, one for **NOHUD video**
3. Open DevTools (`F12` or `Ctrl+Shift+I`)
4. Click the **element selector** icon (top-left of DevTools panel)
5. Hover over the bot's response message in Discord
6. In the DOM tree, find the `div` with an ID starting with `message-accessories-...`
7. Right-click it → **Copy** → **Copy element**
8. Paste into a text file and save as:
   - `assets.html` — for the JDU assets query
   - `nohud.html` — for the NOHUD video query

> **Note:** Asset links expire shortly after the bot responds. Run the script immediately after saving the HTML files.

See `docs/img/` for screenshots of the element selector and hover target.

---

## Running

### Single Map

```bash
python map_installer.py --map-name YourMapName --asset-html assets.html --nohud-html nohud.html
```

If the script cannot auto-detect your `jd21` directory:

```bash
python map_installer.py --map-name YourMapName --asset-html assets.html --nohud-html nohud.html --jd-dir "C:\path\to\jd21"
```

### Batch (Multiple Maps)

Organize your maps like this:

```
maps/
  SongA/
    assets.html
    nohud.html
  SongB/
    assets.html
    nohud.html
```

Then run:

```bash
python batch_install_maps.py "C:\path\to\maps"
```

With an explicit JD root override:

```bash
python batch_install_maps.py "C:\path\to\maps" --jd21-path "C:\path\to\jd21"
```

Each map opens in its own terminal window for independent review.

---

## What the Installer Does

The script fully automates the following steps:

| Step | Description |
|------|-------------|
| **[0]** | Cleans up any previous build output |
| **[1]** | Downloads IPKs, ZIPs, WebMs, and textures from JDU servers |
| **[2]** | Extracts `MAIN_SCENE` ZIP archives |
| **[3]** | Unpacks IPK archives |
| **[4]** | Decodes CKD textures to PNG/TGA |
| **[5]** | Generates UbiArt config files (`.isc`, `.tpl`, `.act`, `.trk`, `.mpd`) with enriched SongDesc metadata and full DefaultColors |
| **[6]** | Converts choreography tapes via `ubiart_lua` (MotionClip color hex, MotionPlatformSpecifics KEY/VAL, Tracks array) |
| **[6.5]** | Converts cinematic tapes (curve data with `vector2dNew`, ActorIndices to ActorPaths resolution) |
| **[6.6]** | Processes ambient sound templates into `.ilu` + `.tpl` pairs |
| **[7]** | Decodes pictograms and extracts platform move files |
| **[7.5]** | Extracts Autodance files and converts templates |
| **[8]** | Converts audio OGG to WAV (48kHz) with offset handling |
| **[9]** | Copies video WebM files |
| **[10]** | Registers the map in `SkuScene_Maps_PC_All.isc` |
| **[Interactive]** | Audio/video sync fine-tuning with live FFplay preview |

---

## Further Reading

- **[README.md](README.md)** — Project overview and feature list
- **[docs/MANUAL_PORTING_GUIDE.md](docs/MANUAL_PORTING_GUIDE.md)** — How to manually port a map without scripts
- **[docs/JDU_DATA_MAPPING.md](docs/JDU_DATA_MAPPING.md)** — Technical property mapping between JDU and JD2021 PC
