# Getting Started

This guide walks you through setting up the project from scratch. Some required components are **not included in this repository** and must be downloaded separately.

---

## Step 1 — Install System Dependencies

These must be installed before running any scripts:

### Python 3.6+
Download from https://www.python.org/downloads/

During installation, check **"Add Python to PATH"**.

Verify after installing:
```
python --version
```

### FFmpeg
Download from https://ffmpeg.org/download.html

Extract it and add the `bin/` folder to your system `PATH`.

Verify after installing:
```
ffmpeg -version
```

### Pillow (Python image library)
```
pip install Pillow
```

---

## Step 2 — Download Third-Party Tools (Not Included in Repo)

These tools must be downloaded separately and placed inside the project root folder.

### ubiart-archive-tools *(required)*
Used to unpack `.ipk` archive files.

Download: https://github.com/PartyService/ubiart-archive-tools

Clone or download the ZIP and place the folder in the project root as `ubiart-archive-tools/`.

### XTX-Extractor *(required for Switch textures)*
Used to extract textures from Nintendo Switch XTX containers.

Download: https://github.com/aboood40091/XTX-Extractor

Clone or download the ZIP and place the folder in the project root as `XTX-Extractor/`.

---

## Step 3 — Obtain Just Dance 2021 PC

You need a **Just Dance 2021 PC development build**. This is not publicly available for download — you need to obtain it through the Just Dance modding community.

Once you have it, place it inside the project root in a folder named `jd21/`:

```
projectRoot/
└── jd21/
    └── data/
        └── World/
            └── ...
└── map_installer.py
└── ...
```

The script auto-detects the `jd21` folder if it is in the project root. If yours is elsewhere, you can pass `--jd-dir "C:\path\to\jd21"` when running the installer.

---

## Step 4 — Verify Your Folder Structure

After completing steps 1–3, your project root should look like this:

```
projectRoot/
├── map_installer.py
├── map_builder.py
├── map_downloader.py
├── ckd_decode.py
├── json_to_lua.py
├── ubiart_lua.py
├── batch_install_maps.py
├── README.md
├── docs/
│   ├── GETTING_STARTED.md
│   ├── AUDIO_TIMING.md
│   ├── MANUAL_PORTING_GUIDE.md
│   ├── JDU_DATA_MAPPING.md
│   └── JDU_UNUSED_DATA_OPPORTUNITIES.md
├── ubiart-archive-tools/    <- downloaded in Step 2
├── XTX-Extractor/           <- downloaded in Step 2
└── jd21/                    <- your JD2021 PC install from Step 3
```

---

## Step 5 — Get Map Data from JDHelper

Each map install requires **two HTML files** exported from the **JDHelper** Discord bot (one for the JDU assets, one for the NOHUD video). Asset links expire quickly, so do this right before running the installer.

1. Add JDHelper to a Discord server (or find a server that already has it)
2. Use the bot to query the song you want — one command for **JDU assets**, one for **NOHUD video**
3. Open Discord in a **browser** (Chrome or Edge recommended)
4. Open DevTools with `F12` or `Ctrl+Shift+I`
5. Click the **element selector** icon (top-left of the DevTools panel)

   ![Selector Tool](img/selector_tool.png)

6. Hover over the bot's response message in Discord, just above the main embed

   ![Hover Message](img/hover_message.png)

7. In the DOM tree, find the `div` with an ID starting with `message-accessories-...`
8. Right-click it → **Copy** → **Copy element**
9. Paste into a text file and save as:
   - `assets.html` — for the JDU assets query
   - `nohud.html` — for the NOHUD video query

> **Note:** Asset links expire shortly after the bot responds. Run the installer immediately after saving the files.

---

## Step 6 — Run the Installer

Open a terminal in the project root and run:

```bash
python map_installer.py --map-name YourMapName --asset-html assets.html --nohud-html nohud.html
```

If the auto-detection can't find your JD installation:

```bash
python map_installer.py --map-name YourMapName --asset-html assets.html --nohud-html nohud.html --jd-dir "C:\path\to\jd21"
```

### Batch Installation (Multiple Maps)

If you have several maps to install, organize folders like this:

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

Each map opens in its own terminal window for independent review.

---

## What the Installer Does

| Step | Description |
|------|-------------|
| **[1]** | Clean up previous build output |
| **[2]** | Download assets (IPKs, ZIPs, WebMs, textures) from JDU servers |
| **[3]** | Extract scene archives |
| **[4]** | Unpack IPK archives |
| **[5]** | Decode menu art textures (CKD → PNG/TGA) |
| **[6]** | Generate UbiArt config files (scenes, templates, tracks, manifests) |
| **[7]** | Convert choreography and karaoke tapes to Lua |
| **[8]** | Convert cinematic tapes to Lua |
| **[9]** | Process ambient sound templates from IPK |
| **[10]** | Decode pictograms |
| **[11]** | Extract move files and autodance data |
| **[12]** | Convert audio to 48kHz WAV and generate intro AMB for pre-roll coverage |
| **[13]** | Copy gameplay video |
| **[14]** | Register the map in SkuScene |
| **Interactive** | Audio/video sync fine-tuning with live FFplay preview (intro AMB regenerates on each adjustment) |

---

## Further Reading

- **[README.md](../README.md)** — Project overview, feature list, and limitations
- **[AUDIO_TIMING.md](AUDIO_TIMING.md)** — How `videoStartTime` causes pre-roll silence and how the AMB intro fix works
- **[MANUAL_PORTING_GUIDE.md](MANUAL_PORTING_GUIDE.md)** — How to manually port a map without scripts; map directory structure reference
- **[JDU_DATA_MAPPING.md](JDU_DATA_MAPPING.md)** — Technical property mapping between JDU and JD2021 PC
