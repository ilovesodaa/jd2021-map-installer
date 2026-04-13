#!/usr/bin/env bash
# Linux setup script — mirrors the steps performed by setup.bat.
set -e

cd "$(dirname "$0")"

echo "[1/7] Installing Python dependencies..."
python3 -m pip install -r requirements.txt

echo ""
echo "[2/7] Installing Chromium for Playwright..."
python -m playwright install chromium

echo ""
echo "[3/7] Cloning AssetStudio..."
mkdir -p tools

ensure_git_clone() {
    local repo_url="$1"
    local dest_dir="$2"
    local branch="$3"

    if [ -d "$dest_dir/.git" ]; then
        echo "[OK] $dest_dir already present"
        return 0
    fi

    if [ -e "$dest_dir" ]; then
        echo "[WARNING] $dest_dir exists but is not a git checkout. Skipping clone."
        return 0
    fi

    echo "[INFO] Cloning $repo_url into $dest_dir"
    git clone --depth 1 --branch "$branch" "$repo_url" "$dest_dir"
}

ensure_git_clone https://github.com/Perfare/AssetStudio.git tools/AssetStudio master

echo ""
echo "[4/7] Cloning UnityPy..."
ensure_git_clone https://github.com/K0lb3/UnityPy.git tools/UnityPy master

echo ""
echo "[5/7] Cloning Unity2UbiArt..."
ensure_git_clone https://github.com/Itaybl14/Unity2UbiArt.git tools/Unity2UbiArt main

echo ""
echo "[6/7] Staging AssetStudioModCLI runtime..."

CLI_DIR="tools/Unity2UbiArt/bin/AssetStudioModCLI"
CLI_EXE="$CLI_DIR/AssetStudioModCLI.exe"

if [ -f "$CLI_EXE" ]; then
    echo "[OK] AssetStudioModCLI already present at $CLI_EXE"
else
    mkdir -p "tools/Unity2UbiArt/bin"

    echo "[INFO] Fetching latest AssetStudioModCLI release..."
    RELEASE_JSON=$(curl -fsSL -H "User-Agent: jd2021-map-installer-setup" \
        https://api.github.com/repos/aelurum/AssetStudio/releases/latest)

    # Find a Windows CLI asset (zip preferred)
    ASSET_URL=$(python3 - <<'PYEOF'
import json, sys, re

data = json.load(sys.stdin)
assets = data.get("assets", [])
# Prefer a zip matching CLI/cmd/console + win
for a in assets:
    name = a["name"]
    if re.search(r'AssetStudio.*(CLI|cmd|console).*win.*\.(zip|7z)$', name, re.IGNORECASE):
        print(a["browser_download_url"])
        sys.exit(0)
# Fallback: any CLI zip
for a in assets:
    name = a["name"]
    if re.search(r'AssetStudio.*CLI.*\.(zip|7z)$', name, re.IGNORECASE):
        print(a["browser_download_url"])
        sys.exit(0)
print("")
PYEOF
<<< "$RELEASE_JSON")

    if [ -z "$ASSET_URL" ]; then
        echo "[WARNING] Could not find a Windows AssetStudio CLI release asset."
        echo "          JDNext mapPackage extraction may fail until AssetStudioModCLI"
        echo "          is staged manually in $CLI_DIR."
    else
        TMP_DIR="tools/Unity2UbiArt/bin/_assetstudio_tmp"
        rm -rf "$TMP_DIR"
        mkdir -p "$TMP_DIR"

        ARCHIVE_NAME=$(basename "$ASSET_URL")
        curl -fsSL -H "User-Agent: jd2021-map-installer-setup" \
            -o "$TMP_DIR/$ARCHIVE_NAME" "$ASSET_URL"

        case "$ARCHIVE_NAME" in
            *.zip)
                unzip -q "$TMP_DIR/$ARCHIVE_NAME" -d "$TMP_DIR"
                ;;
            *.7z)
                if ! command -v 7z &>/dev/null; then
                    echo "[ERROR] Archive is .7z but 7z is not installed. Install p7zip (e.g. sudo apt install p7zip-full on Debian/Ubuntu)."
                    rm -rf "$TMP_DIR"
                    exit 1
                fi
                7z x "$TMP_DIR/$ARCHIVE_NAME" -o"$TMP_DIR" -y >/dev/null
                ;;
            *)
                echo "[ERROR] Unsupported archive format: $ARCHIVE_NAME"
                rm -rf "$TMP_DIR"
                exit 1
                ;;
        esac

        # Locate the directory containing AssetStudioModCLI.exe
        CLI_FOUND=$(find "$TMP_DIR" -name "AssetStudioModCLI.exe" -type f | head -n1)
        if [ -z "$CLI_FOUND" ]; then
            echo "[WARNING] AssetStudioModCLI.exe not found in downloaded archive."
        else
            CLI_FOUND_DIR=$(dirname "$CLI_FOUND")
            rm -rf "$CLI_DIR"
            mkdir -p "$CLI_DIR"
            cp -r "$CLI_FOUND_DIR"/. "$CLI_DIR/"
            echo "[OK] AssetStudioModCLI staged at $CLI_EXE"
        fi

        rm -rf "$TMP_DIR"
    fi
fi

echo ""
echo "[7/7] Installing vgmstream toolchain..."
mkdir -p tools/vgmstream

VGMSTREAM_JSON=$(curl -fsSL -H "User-Agent: jd2021-map-installer-setup" \
    https://api.github.com/repos/vgmstream/vgmstream/releases/latest)

VGMSTREAM_URL=$(python3 - <<'PYEOF'
import json, sys

data = json.load(sys.stdin)
assets = data.get("assets", [])
for a in assets:
    name = a["name"].lower()
    if "linux" in name and name.endswith(".zip"):
        print(a["browser_download_url"])
        sys.exit(0)
print("")
PYEOF
<<< "$VGMSTREAM_JSON")

if [ -z "$VGMSTREAM_URL" ]; then
    echo "[WARNING] Could not find a Linux vgmstream release asset."
    echo "          IPK X360 audio decode may fail. Install vgmstream-cli manually."
else
    TMP_VGM="tools/vgmstream/_extract"
    rm -rf "$TMP_VGM"
    mkdir -p "$TMP_VGM"

    VGM_ARCHIVE="tools/vgmstream/vgmstream-linux.zip"
    curl -fsSL -H "User-Agent: jd2021-map-installer-setup" \
        -o "$VGM_ARCHIVE" "$VGMSTREAM_URL"

    unzip -q "$VGM_ARCHIVE" -d "$TMP_VGM"

    # Find vgmstream-cli binary (no extension)
    VGM_BIN=$(find "$TMP_VGM" -name "vgmstream-cli" -type f | head -n1)
    if [ -z "$VGM_BIN" ]; then
        echo "[WARNING] vgmstream-cli binary not found in archive."
    else
        VGM_BIN_DIR=$(dirname "$VGM_BIN")
        cp -r "$VGM_BIN_DIR"/. tools/vgmstream/
        chmod +x tools/vgmstream/vgmstream-cli
        echo "[OK] vgmstream installed in tools/vgmstream"
    fi

    rm -rf "$TMP_VGM"
    rm -f "$VGM_ARCHIVE"
fi

echo ""
echo "Setup complete!"
