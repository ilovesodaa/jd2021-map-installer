# Usage Guide

> Last Updated: April 2026 | Applies to: JD2021 Map Installer v2

This guide is a single beginner-friendly walkthrough that combines:

1. Getting started setup
2. Every main on-screen GUI option
3. Complete mode selection help
4. Settings dialog explanations

Use this as your primary reference if you are new to the tool.

---

## 1. Getting Started

### 1.1 First-time setup (Windows)

1. Open a terminal in the project root.
2. Run:

```bat
setup.bat
```

3. Start the app:

```bat
RUN.bat
```

If needed, manual launch also works:

```bash
python -m jd2021_installer.main
```

### 1.2 Required external tools

For full media support you should have:

1. `ffmpeg`
2. `ffprobe`
3. `vgmstream-cli` (important for some decode paths)

Fetch mode also needs Playwright Chromium:

```bash
python -m playwright install chromium
```

JDNext mapPackage workflows also expect local tool staging under `tools/`:

1. `tools/AssetStudio` (source clone)
2. `tools/UnityPy` (source clone)
3. `tools/Unity2UbiArt/bin/AssetStudioModCLI/` (runtime CLI bundle)

### 1.3 First launch checklist

Before your first install:

1. Set Game Directory in the Configuration panel.
2. Choose the source Mode.
3. Fill mode-specific inputs.
4. Click Pre-flight Check.
5. Click Install Map.

---

## 2. Main Screen Guide (All On-Screen Options)

The main window is split into two columns:

1. Left side: Mode + Configuration + Actions + Progress
2. Right side: Preview + Sync Refinement + Log Console

### 2.1 Mode Selector (top-left)

Mode dropdown options:

1. Fetch (Codename)
2. HTML Files
3. IPK Archive
4. Batch (Directory)
5. Manual (Directory)

Each mode shows different inputs (see Section 4).

### 2.2 Configuration panel

Visible controls:

1. Game Directory field (read-only display)
2. Auto-Detect button
3. Browse button
4. Video Quality dropdown

Video Quality values:

1. ULTRA_HD
2. ULTRA
3. HIGH_HD
4. HIGH
5. MID_HD
6. MID
7. LOW_HD
8. LOW

### 2.3 Actions panel

Buttons and what they do:

1. Install Map: runs full extract -> normalize -> install pipeline
2. Pre-flight Check: validates paths, mode inputs, and dependencies
3. Re-adjust Offset: opens map selection for post-install sync work
4. Settings: opens Installer Settings dialog
5. Reset State: clears current mode input/state

### 2.4 Progress panel

Shows:

1. Checklist of pipeline steps with status icons
2. Progress bar from 0 to 100

Typical checklist entries include extract, parse, normalize, decode/convert, tape conversion, registration, and finalizing offsets.

### 2.5 Preview panel

Controls:

1. Video canvas
2. Seek slider with current/total time
3. -5s button
4. Play/Stop button
5. +5s button

Use this panel to inspect sync visually.

### 2.6 Sync Refinement panel

Controls:

1. Audio Offset (ms) input
2. Video Offset (ms) checkbox
3. Video Offset (ms) input
4. Audio adjust buttons: -1000, -100, -10, -1, +1, +10, +100, +1000
5. Video adjust buttons: -1000, -100, -10, -1, +1, +10, +100, +1000
6. Preview button
7. Pad Audio
8. Sync Beatgrid
9. Apply Offset
10. Prev Map / Next Map navigation (shown in multi-map flows)

### 2.7 Log Console panel

Read-only live log output. Use it for:

1. Progress details
2. Warnings/errors
3. Dependency or input failure clues

### 2.8 Status bar

Bottom status message area. Default state is `Ready`.

---

## 3. Install Workflow (Recommended)

For most users, this order gives the best results:

1. Select Game Directory.
2. Select Mode.
3. Fill all required inputs for that mode.
4. Run Pre-flight Check and fix any red flags.
5. Click Install Map.
6. Watch Progress and Log Console.
7. If timing is off, use Re-adjust Offset.

---

## 4. Modes Guide (Which mode to use)

### 4.1 Fetch (Codename)

Use when you know song codename(s) and want automation.

Required input:

1. Codename(s), comma-separated (example: `RainOnMe,Koi`)

Also required:

1. Internet access
2. Playwright Chromium runtime
3. Valid Discord channel URL in Settings

### 4.2 HTML Files

Use when you already have `assets.html` and `nohud.html`.

Required inputs:

1. Asset HTML file
2. NOHUD HTML file

Notes:

1. Both files should be from the same map/version.
2. This mode is useful as a fallback when Fetch fails.

### 4.3 IPK Archive

Use when your source is an Xbox 360 `.ipk` archive.

Required input:

1. IPK file path

Behavior:

1. Single-map IPKs install directly.
2. Bundle IPKs open a map selection dialog.

### 4.4 Batch (Directory)

Use when processing many candidates at once.

Required input:

1. Root folder containing candidates

Accepted candidates:

1. `.ipk` files
2. Folders containing `assets.html` and `nohud.html`
3. Other supported map source layouts detected by scanner

### 4.5 Manual (Directory)

Use for advanced/manual control of source files.

Top controls:

1. Source Type: JDU / IPK / Mixed
2. Root Folder
3. Scan button
4. Codename field

Required Files group:

1. Audio File
2. Video File
3. Musictrack

Tapes and Config group:

1. Songdesc
2. Dance Tape
3. Karaoke Tape
4. Mainseq Tape

Asset Folders group:

1. Moves Folder
2. Pictos Folder
3. MenuArt Folder
4. AMB Folder

JDU MenuArt fields (shown when relevant):

1. Cover Generic
2. Cover Online
3. Banner
4. Banner Bkg
5. Map Bkg
6. Cover AlbumCoach
7. Cover AlbumBkg
8. Coach 1 Art
9. Coach 2 Art
10. Coach 3 Art
11. Coach 4 Art

---

## 5. Settings Guide (Every Settings dialog option)

Open using the Settings button in the Actions panel.

### 5.1 Behavior toggles

1. Skip pre-flight checks
2. Suppress offset refinement notification
3. Show "Pre-flight passed" popup
4. Show installation summary popup
5. Show quick-start hint on launch

### 5.2 Post-install behavior

1. After Apply and Finish:
   - ask
   - delete
   - keep
2. Non-3 song status handling:
   - ask
   - force3
   - keep

### 5.3 UI and diagnostics

1. Log detail level: quiet / user / detailed / developer
2. Theme: light / dark
3. Enforce minimum window size
4. Minimum window width/height
5. Show floating current window size while resizing
6. Enable Style Debug Mode (outline sections)

### 5.4 Media/fetch defaults

1. Default video quality
2. Discord Channel URL (required for Fetch mode)

### 5.5 Localization helper

Button: Update In-Game Localization...

This updates game localization from a selected JSON and creates a backup before writing.

---

## 6. Quick Troubleshooting

1. Install button stays disabled:
   Run Pre-flight Check and review missing requirements in logs.
2. Fetch mode fails:
   Confirm Discord Channel URL and Playwright Chromium install.
3. Audio/video out of sync:
   Use Re-adjust Offset with Preview and Apply Offset.
4. Missing media output:
   Verify ffmpeg/ffprobe/vgmstream-cli availability.
5. Batch failures:
   Re-run failed maps one-by-one in their best-fit mode.

---

## 7. Suggested First Session for New Users

1. Start with one known-good map.
2. Use Fetch or HTML mode first.
3. Run Pre-flight before every install.
4. Finish one successful install end-to-end.
5. Then move to Batch or Manual workflows.

---

## 8. Related Docs

1. [Getting Started](GETTING_STARTED.md)
2. [Modes Guide](MODES_GUIDE.md)
3. [GUI Reference](GUI_REFERENCE.md)
4. [Troubleshooting](TROUBLESHOOTING.md)
