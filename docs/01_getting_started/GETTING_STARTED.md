# Getting Started

> **Last Updated:** April 2026 | **Applies to:** JD2021 Map Installer v2

This guide shows the fastest way to run JD2021 Map Installer v2 on Windows, plus a full manual setup path.

---

## Current Limitations (Read First)

1. **Intro AMB is temporarily disabled in v2.**
   The installer currently forces silent intro placeholder behavior for stability. Reliable intro AMB playback is not expected right now.

2. **IPK-derived `videoStartTime` is approximate by design.**
   For many IPK maps, binary metadata does not reliably encode lead-in timing. Manual video offset tuning is expected.

3. **External media tools are required for full results.**
   FFmpeg/FFprobe and vgmstream are required for complete media processing paths.

---

## Quick Start (Recommended)

Use this path first. It is the intended Windows setup flow.

1. Open PowerShell or Command Prompt in the project root.
2. Run:

```bat
setup.bat
```

3. Launch the installer with:

```bat
RUN.bat
```

What `setup.bat` handles:

1. Python package install from `requirements.txt`
2. Playwright Chromium install (Fetch mode runtime)
3. Clone/update of JDNext third-party source trees under `tools/`:
   - `tools/AssetStudio`
   - `tools/UnityPy`
   - `tools/Unity2UbiArt`
4. Runtime tooling bootstrap used by this project (including vgmstream pathing)

Important JDNext note:

- `AssetStudioModCLI` runtime binaries are not distributed in this repository.
- For JDNext mapPackage workflows, stage the extracted CLI bundle under `tools/Unity2UbiArt/bin/AssetStudioModCLI/`.

If `setup.bat` fails or you want full control, follow **Manual Setup**.

---

## Manual Setup (Alternative)

### Step 1 — Install Python

Install **Python 3.10+** from <https://www.python.org/downloads/> and enable **Add Python to PATH**.

Verify:

```bash
python --version
```

---

### Step 2 — Install Python Dependencies

From the project root:

```bash
pip install -r requirements.txt
```

Core packages include PyQt6, Playwright, Pydantic, Pillow, and test tooling.

---

### Step 3 — Install Playwright Browser Runtime

Required for Fetch/codename workflows:

```bash
python -m playwright install chromium
```

If you only use IPK, batch folder, or manual source workflows, this may be optional.

---

### Step 4 — Install FFmpeg and FFprobe

Install FFmpeg from <https://ffmpeg.org/download.html> so both `ffmpeg` and `ffprobe` are available on PATH.

Verify:

```bash
ffmpeg -version
ffprobe -version
```

---

### Step 5 — Install vgmstream

`vgmstream` is required for X360/XMA2 decode paths.

Recommended options:

1. Run `setup.bat` once and let the project place vgmstream in the expected runtime location.
2. Or install manually and ensure the CLI binary is available to the installer.

Verify (if available in PATH):

```bash
vgmstream-cli -h
```

PowerShell path check:

```powershell
Get-Command vgmstream-cli
```

---

### Step 6 — Run the Installer

Windows entrypoint:

```bat
RUN.bat
```

Manual Python entrypoint:

```bash
python -m jd2021_installer.main
```

---

## First Run Workflow

In the app:

1. Pick your source mode: Fetch, HTML, IPK, Batch, or Manual.
2. Provide required files/paths.
3. Start install and monitor progress/log output.
4. Use preview/readjust if timing changes are needed.

Timing notes:

1. **IPK maps:** manual video offset tuning is commonly required.
2. **AMB intro:** silent intro placeholder behavior is currently expected.

---

## Troubleshooting Setup

1. `ffmpeg` / `ffprobe` not found:
   Reinstall FFmpeg and add its `bin` directory to PATH.
2. `vgmstream-cli` not found:
   Re-run `setup.bat` or add the vgmstream binary directory to PATH.
3. Fetch mode fails early:
   Re-run `python -m playwright install chromium`.
4. Media output is missing or degraded:
   Confirm all three tools resolve: ffmpeg, ffprobe, vgmstream-cli.
5. JDNext extract fails with `AssetStudioModCLI.exe not found under tools`:
   Ensure the CLI bundle is present at `tools/Unity2UbiArt/bin/AssetStudioModCLI/`.

---

## Further Reading

- **[README.md](../../README.md)** — Project overview, features, and limitations
- **[Architecture](../02_core/ARCHITECTURE.md)** — Components and data flow
- **[Pipeline Reference](../02_core/PIPELINE_REFERENCE.md)** — Extract → Normalize → Install phases
- **[GUI Reference](GUI_REFERENCE.md)** — Main window and controls
- **[Audio Timing](../03_media/AUDIO_TIMING.md)** — `videoStartTime`, offset tuning, and AMB intro caveats
- **[Troubleshooting](TROUBLESHOOTING.md)** — Operational troubleshooting
- **[Third-Party Tools](../04_reference/THIRD_PARTY_TOOLS.md)** — External dependency details
