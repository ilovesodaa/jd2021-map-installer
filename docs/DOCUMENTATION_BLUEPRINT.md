# Documentation Update Blueprint: V1 → V2

This document provides a comprehensive mapping of how the "jd2021-map-installer" documentation must evolve from Version 1 (Tkinter + CLI + Node.js) to Version 2 (PyQt6 + Strict GUI + playwright-python).

## 1. The Doc Audit

### ❌ What Gets Deleted Entirely
The following documents represent deprecated workflows or architectures and must be permanently removed:
- **`CLI_REFERENCE.md`**: V2 is a strict GUI-only application. All CLI operations, arguments, and batch scripts are removed.
- **Node.js References**: Any mentions of Node.js, `npm install`, or external JS scripts must be purged from all documents.

### ⚠️ What Needs Heavy Revision
These documents form the core of the system and require massive structural rewrites to match the new V2 codebase:
- **`README.md`**: Update the technology stack (PyQt6, playwright-python, QThread). Remove CLI mentions.
- **`ARCHITECTURE.md`**: Rewrite the Component Map. Replace Tkinter and CLI with PyQt6 `MainWindow` and `QThread`. Document the new MVC-like `core/`, `extractors/`, `parsers/`, and `ui/` module separation.
- **`PIPELINE_REFERENCE.md`**: Disconnect the legacy 16-step synchronous monolithic pipeline. Detail how `pipeline_workers.py` manages execution via PyQt signals and slots, and how `web_playwright.py` handles extraction asynchronously.
- **`GUI_REFERENCE.md`**: Complete rewrite. Document the new `MainWindow` layout, Qt widgets, Qt styling, and how the QThread interacts with the UI to stay responsive during heavy operations.
- **`GETTING_STARTED.md`**: Remove the Node.js installation requirement. Update dependency installation to simply `pip install -r requirements.txt`. Update the run command to `python main.py` or `python -m jd2021_installer.main`.
- **`THIRD_PARTY_TOOLS.md`**: Remove Node.js. Add PyQt6 (GUI Framework), Playwright for Python (Web Scraping / Extractor), Pydantic (Data Validation), and pytest-qt (Testing).

### ✅ What Stays (Minor Tweaks Only)
These documents cover binary formats, logic, and data that haven't fundamentally changed, though minor references to V1 scripts should be sanitized:
- `AUDIO_TIMING.md`
- `DATA_FORMATS.md`
- `MAP_CONFIG_FORMAT.md`
- `ASSETS.md`
- `VIDEO.md`
- `GAME_CONFIG_REFERENCE.md`
- `JDU_DATA_MAPPING.md`
- `JDU_UNUSED_DATA_OPPORTUNITIES.md`
- `MANUAL_PORTING_GUIDE.md`
- `KNOWN_GAPS.md`
- `TROUBLESHOOTING.md`

---

## 2. New Documentation Tree

When V2 is complete, the `/docs` folder should look like this:

```text
docs/
├── GETTING_STARTED.md           # Updated for pip / PyQt6 / Playwright
├── ARCHITECTURE.md              # New Modular Core/UI/Extractor architecture
├── PIPELINE_REFERENCE.md        # Updated QThread based pipeline
├── GUI_REFERENCE.md             # New PyQt6 Main Window reference
├── AUDIO_TIMING.md              # Unchanged
├── TROUBLESHOOTING.md           # Unchanged
├── DATA_FORMATS.md              # Unchanged
├── MAP_CONFIG_FORMAT.md         # Unchanged
├── ASSETS.md                    # Unchanged
├── VIDEO.md                     # Unchanged
├── GAME_CONFIG_REFERENCE.md     # Unchanged
├── THIRD_PARTY_TOOLS.md         # Updated for Pydantic, PyQt6, Playwright
├── KNOWN_GAPS.md                # Unchanged
├── MANUAL_PORTING_GUIDE.md      # Unchanged
├── JDU_DATA_MAPPING.md          # Unchanged
└── JDU_UNUSED_DATA_OPPORTUNITIES.md # Unchanged
```

*Note: `CLI_REFERENCE.md` does not appear in the V2 tree.*

---

## 3. Claude Execution Blueprint (Instruction List)

Provide these exact instructions to Claude to generate the new V2 Markdown files.

### 🎯 Objective 1: Update `README.md`
- **Action:** Overwrite existing `README.md`.
- **Details to Include:**
  - Change descriptive text to emphasize this is a "Pure Python GUI Application built on PyQt6".
  - Remove all mentions of "CLI support" and "Node.js".
  - List Main Features: PyQt6 dark-themed UI, headless playwright integration for JDU assets, QThread concurrent processing.
  - Setup: Point to the updated `GETTING_STARTED.md`.

### 🎯 Objective 2: Update `GETTING_STARTED.md` & `THIRD_PARTY_TOOLS.md`
- **Action:** Overwrite both files.
- **Details for GETTING_STARTED:**
  - Step 1: Install Python 3.10+.
  - Step 2: `pip install -r requirements.txt`. (Mention that this installs PyQt6 and Playwright).
  - Step 3: Run `playwright install chromium` to fetch the headless browser.
  - Step 4: Run the app via `python -m jd2021_installer.main`.
  - Delete old "Install System Dependencies -> Node.js" steps.
- **Details for THIRD_PARTY_TOOLS:**
  - Remove: Node.js, Tkinter.
  - Add: **PyQt6** (GUI framework), **playwright-python** (Replaces Node scraper, runs via `asyncio`), **Pydantic** (Models & Validation), **pytest/pytest-qt** (Testing).

### 🎯 Objective 3: Rewrite `ARCHITECTURE.md`
- **Action:** Full rewrite.
- **Details to Include:**
  - **Component Map:** Draw a new text-diagram showing `main.py` -> `ui/` -> `workers/` -> `core/` & `extractors/` & `parsers/`.
  - **Core Modules Table:** Define `core/` (Models and Config), `ui/` (Main Window and Qt Widgets), `workers/` (QThread payload management), `extractors/` (Base and WebPlaywright async data gatherers). 
  - **Concurrency Model:** Explain how UI blocking is prevented using `QThread` and customized Qt signals for logging (`sys.stdout` redirection via PySide/PyQt signals).
  - **Scraping Model:** Detail `WebPlaywrightExtractor`, noting it runs in an `asyncio` loop wrapped in a thread to safely await headless chromium without locking the GUI.

### 🎯 Objective 4: Rewrite `PIPELINE_REFERENCE.md`
- **Action:** Full rewrite.
- **Details to Include:**
  - Remove the legacy `Step 00 to Step 14` monolith description.
  - Describe the new pipeline orchestration found in `pipeline_workers.py`.
  - Outline the phases: Extraction (`web_playwright.py`), Normalization/Parsing (`parsers/`), and Installation (`installers/`).
  - Explain how errors (like WebExtractionError or DownloadError) bubble up via Qt Signals to the main window for user notification.

### 🎯 Objective 5: Rewrite `GUI_REFERENCE.md`
- **Action:** Full rewrite.
- **Details to Include:**
  - **Toolkit:** Change "Tkinter" to "PyQt6".
  - Describe the new MainWindow layout built with Qt layout managers (`QVBoxLayout`, `QHBoxLayout`).
  - Document the unified mode selection, removing batch and CLI tabs.
  - Document how standard output (`sys.stdout`) is tapped into a custom Qt signal to populate the dark-themed `QTextEdit` log widget.
  - Document the thread lifecycle: user clicks "Install" -> Start QThread worker -> Disable inputs -> QThread finishes -> Emit finished signal -> Enable inputs.

### 🎯 Objective 6: Delete `CLI_REFERENCE.md`
- **Action:** Delete the file physically from the /docs folder. V2 does not support CLI.
