# Getting Started

This guide walks you through setting up the JD2021 Map Installer v2 from scratch.

---

## Step 1 — Install Python

Download **Python 3.10+** from <https://www.python.org/downloads/>

During installation, check **"Add Python to PATH"**.

Verify after installing:

```
python --version
```

---

## Step 2 — Install Dependencies

From the project root, install all Python packages:

```bash
pip install -r requirements.txt
```

This installs:

| Package | Purpose |
|---------|---------|
| **PyQt6** | GUI framework |
| **playwright** | Headless browser for JDU web scraping |
| **Pydantic** | Configuration and data validation |
| **Pillow** | Image format conversion (DDS/TGA/PNG) |
| **pytest / pytest-qt** | Testing (development only) |

---

## Step 3 — Install the Headless Browser

Playwright requires a one-time browser download:

```bash
python -m playwright install chromium
```

This fetches a headless Chromium binary used by the web extractor to scrape JDU asset pages.

---

## Step 4 — Obtain Just Dance 2021 PC

You need a **Just Dance 2021 PC development build**. This is not publicly available — you need to obtain it through the Just Dance modding community.

---

## Step 5 — Verify Your Folder Structure

After completing the previous steps, your project should look like this:

```
projectRoot/
├── jd2021_installer/
│   ├── __init__.py
│   ├── main.py              ← Application entry point
│   ├── core/
│   │   ├── config.py        ← Pydantic AppConfig
│   │   ├── exceptions.py    ← Typed exception hierarchy
│   │   └── models.py        ← NormalizedMapData and sub-models
│   ├── extractors/
│   │   ├── base.py           ← BaseExtractor ABC
│   │   ├── web_playwright.py ← Web/HTML extractor
│   │   └── archive_ipk.py   ← IPK archive extractor
│   ├── parsers/
│   │   ├── normalizer.py    ← Raw files → NormalizedMapData
│   │   └── binary_ckd.py    ← Binary CKD parser
│   ├── installers/
│   │   ├── game_writer.py   ← UbiArt config file generator
│   │   └── media_processor.py ← FFmpeg/Pillow wrappers
│   └── ui/
│       ├── main_window.py   ← PyQt6 MainWindow
│       ├── widgets/
│       └── workers/
│           └── pipeline_workers.py ← QThread workers
├── tests/
├── docs/
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## Step 6 — Get Map Data from JDHelper

Each map install requires **two HTML files** exported from the **JDHelper** Discord bot (one for JDU assets, one for the NOHUD video). Asset links expire quickly, so do this right before running the installer.

1. Add JDHelper to a Discord server (or find a server that already has it).
2. Use the bot to query the song you want — one command for **JDU assets**, one for **NOHUD video**.
3. Open Discord in a **browser** (Chrome or Edge recommended).
4. Open DevTools with `F12` or `Ctrl+Shift+I`.
5. Click the **element selector** icon (top-left of DevTools).
6. Hover over the bot's response message in Discord.
7. In the DOM tree, find the `div` with an ID starting with `message-accessories-...`
8. Right-click → **Copy** → **Copy element**.
9. Paste into a text file and save as:
   - `assets.html` — for the JDU assets query
   - `nohud.html` — for the NOHUD video query

> **Note:** Asset links expire approximately 30 minutes after the bot responds. Run the installer immediately after saving the files.

---

## Step 7 — Run the Installer

```bash
python -m jd2021_installer.main
```

1. Click **Load HTML / URLs** and select your asset and NOHUD HTML files.
2. Or click **Load IPK Archive** for Xbox 360 `.ipk` files.
3. Click **Install Map** to run the full extraction → normalization → installation pipeline.
4. Monitor progress in the log panel and progress bar.

---

## Further Reading

- **[README.md](../README.md)** — Project overview, features, and limitations
- **[Architecture](ARCHITECTURE.md)** — Component map, concurrency model, and data flow
- **[Pipeline Reference](PIPELINE_REFERENCE.md)** — Extract → Normalize → Install pipeline phases
- **[GUI Reference](GUI_REFERENCE.md)** — PyQt6 main window and controls
- **[Audio Timing](AUDIO_TIMING.md)** — How `videoStartTime` causes pre-roll silence and how the AMB intro fix works
- **[Troubleshooting](TROUBLESHOOTING.md)** — Common errors and their solutions
- **[Third-Party Tools](THIRD_PARTY_TOOLS.md)** — External dependencies
