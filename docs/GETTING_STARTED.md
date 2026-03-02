# Getting Started

This guide walks you through setting up the project from scratch.

---

## Step 1 — Install System Dependencies

### Python 3.6+
Download from https://www.python.org/downloads/

During installation, check **"Add Python to PATH"**.

Verify after installing:
```
python --version
```

### Pillow (Python image library)
```
pip install Pillow
```

> **Note on FFmpeg:** The installer checks for FFmpeg during the Pre-flight Check. If it is not found on your system, the installer will offer to download and install it automatically into the project's `tools/ffmpeg/` folder — no manual setup required.

---

## Step 2 — Obtain Just Dance 2021 PC

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

## Step 3 — Verify Your Folder Structure

After completing steps 1–2, your project root should look like this:

```
projectRoot/
├── map_installer.py
├── map_builder.py
├── map_downloader.py
├── gui_installer.py
├── ckd_decode.py
├── ipk_unpack.py
├── json_to_lua.py
├── ubiart_lua.py
├── batch_install_maps.py
├── xtx_extractor/           <- bundled, no download needed
├── README.md
├── docs/
│   ├── GETTING_STARTED.md
│   ├── AUDIO_TIMING.md
│   ├── MANUAL_PORTING_GUIDE.md
│   ├── JDU_DATA_MAPPING.md
│   ├── JDU_UNUSED_DATA_OPPORTUNITIES.md
│   ├── JD21_Configuration_Map.md
│   └── MOBILE_SCORING_RESTORATION.md
└── jd21/                    <- your JD2021 PC install from Step 2
```

All required tools (`ipk_unpack.py`, `xtx_extractor/`) are already included in the repository — no separate downloads are needed.

---

## Step 4 — Get Map Data from JDHelper

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

## Step 5 — Run the Installer

### GUI (Recommended)

Double-click `gui_installer.py` or run:

```bash
python gui_installer.py
```

1. Browse to your **Asset HTML** and **NOHUD HTML** files — the map name is auto-detected from the asset URLs.
2. Select a **Video Quality** tier (default: Ultra HD).
3. Click **Pre-flight Check** to verify dependencies. If FFmpeg is missing, the GUI will offer to auto-install it.
4. Click **Install Map**.
5. After installation, use the **Sync Refinement** panel to fine-tune audio/video timing with live FFplay preview.
6. Click **Apply & Finish** to save your settings.

Sync settings are saved per map — on reinstall, they are reloaded automatically.

### CLI

```bash
python map_installer.py --asset-html assets.html --nohud-html nohud.html
```

The map name is auto-detected from the asset URLs. To override it manually:

```bash
python map_installer.py --map-name YourMapName --asset-html assets.html --nohud-html nohud.html
```

If the auto-detection can't find your JD installation:

```bash
python map_installer.py --asset-html assets.html --nohud-html nohud.html --jd-dir "C:\path\to\jd21"
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
| **[1]** | Pre-install cleanup (remove previous map installation from game directory) |
| **[2]** | Clean previous build output (target dir, cache, extracted dirs) |
| **[3]** | Download assets (IPKs, ZIPs, WebMs, textures) from JDU servers |
| **[4]** | Extract scene archives |
| **[5]** | Unpack IPK archives |
| **[6]** | Decode menu art textures (CKD → PNG/TGA) |
| **[7]** | Validate MenuArt covers (format check and case matching) |
| **[8]** | Generate UbiArt config files (scenes, templates, tracks, manifests) |
| **[9]** | Convert choreography and karaoke tapes to Lua |
| **[10]** | Convert cinematic tapes to Lua |
| **[11]** | Process ambient sound templates from IPK |
| **[12]** | Decode pictograms |
| **[13]** | Extract move files and autodance data |
| **[14]** | Convert audio to 48kHz WAV and generate intro AMB for pre-roll coverage |
| **[15]** | Copy gameplay video |
| **[16]** | Register the map in SkuScene |
| **Interactive** | Audio/video sync fine-tuning with live FFplay preview (intro AMB regenerates on each adjustment) |

---

## Further Reading

- **[README.md](../README.md)** — Project overview, feature list, and limitations
- **[AUDIO_TIMING.md](AUDIO_TIMING.md)** — How `videoStartTime` causes pre-roll silence and how the AMB intro fix works
- **[MANUAL_PORTING_GUIDE.md](MANUAL_PORTING_GUIDE.md)** — How to manually port a map without scripts; map directory structure reference
- **[JDU_DATA_MAPPING.md](JDU_DATA_MAPPING.md)** — Technical property mapping between JDU and JD2021 PC
