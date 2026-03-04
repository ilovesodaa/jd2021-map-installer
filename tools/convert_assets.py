"""
Batch file conversion utilities for JD modding.

Provides CKD texture decoding, CKD audio extraction, and IPK archive
unpacking through a unified CLI.

Usage:
    python tools/convert_assets.py ckd-decode FILES...         # CKD texture -> PNG/TGA/DDS
    python tools/convert_assets.py ckd-audio  FILES...         # CKD audio -> raw OGG/WAV
    python tools/convert_assets.py ipk-extract ARCHIVES...     # IPK -> extracted files
    python tools/convert_assets.py ipk-extract ARCHIVES... --output DIR
"""

import argparse
import os
import struct
import sys

# Add project root to path so we can import existing modules
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# CKD texture decoding
# ---------------------------------------------------------------------------

CKD_HEADER_SIZE = 44  # Standard UbiArt CKD header length

def decode_ckd_texture(ckd_path, output_dir):
    """Strip the CKD header from a texture file and write the raw image data.

    Delegates to the project's ckd_decode module if available; otherwise
    performs a basic header strip (works for DDS/TGA payloads).
    """
    try:
        from ckd_decode import decode_ckd
        os.makedirs(output_dir, exist_ok=True)
        result = decode_ckd(ckd_path, output_dir)
        if result:
            print(f"[OK] {os.path.basename(ckd_path)} -> {result}")
            return result
    except ImportError:
        pass

    # Fallback: basic header strip
    with open(ckd_path, "rb") as f:
        data = f.read()

    if len(data) <= CKD_HEADER_SIZE:
        print(f"[SKIP] {os.path.basename(ckd_path)} — file too small")
        return None

    payload = data[CKD_HEADER_SIZE:]

    # Detect format from magic bytes
    if payload[:4] == b"DDS ":
        ext = ".dds"
    elif payload[:3] == b"\x00\x00\x02" or payload[:3] == b"\x00\x00\x0a":
        ext = ".tga"
    elif payload[:4] == b"\x89PNG":
        ext = ".png"
    else:
        ext = ".bin"

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(ckd_path))[0]
    # Remove .tga suffix if embedded (e.g. "Cover.tga.ckd" -> "Cover")
    if base.lower().endswith(".tga"):
        base = base[:-4]
    out_path = os.path.join(output_dir, base + ext)

    with open(out_path, "wb") as f:
        f.write(payload)

    print(f"[OK] {os.path.basename(ckd_path)} -> {os.path.basename(out_path)}")
    return out_path


# ---------------------------------------------------------------------------
# CKD audio extraction
# ---------------------------------------------------------------------------

def extract_ckd_audio(ckd_path, output_dir):
    """Strip the CKD header from an audio file and write the raw audio data."""
    with open(ckd_path, "rb") as f:
        data = f.read()

    if len(data) <= CKD_HEADER_SIZE:
        print(f"[SKIP] {os.path.basename(ckd_path)} — file too small")
        return None

    payload = data[CKD_HEADER_SIZE:]

    # Detect audio format
    if payload[:4] == b"OggS":
        ext = ".ogg"
    elif payload[:4] == b"RIFF":
        ext = ".wav"
    else:
        ext = ".raw"

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(ckd_path))[0]
    if base.lower().endswith(".wav"):
        base = base[:-4]
    out_path = os.path.join(output_dir, base + ext)

    with open(out_path, "wb") as f:
        f.write(payload)

    print(f"[OK] {os.path.basename(ckd_path)} -> {os.path.basename(out_path)}")
    return out_path


# ---------------------------------------------------------------------------
# IPK extraction
# ---------------------------------------------------------------------------

def extract_ipk(ipk_path, output_dir):
    """Extract an IPK archive using the project's ipk_unpack module."""
    try:
        from ipk_unpack import extract_ipk as _extract
    except ImportError:
        print("[ERROR] ipk_unpack module not found. Make sure ipk_unpack.py "
              "is in the project root.")
        return False

    os.makedirs(output_dir, exist_ok=True)
    try:
        _extract(ipk_path, output_dir)
        print(f"[OK] Extracted {os.path.basename(ipk_path)} -> {output_dir}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to extract {os.path.basename(ipk_path)}: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Batch file conversion utilities for JD modding.")
    sub = parser.add_subparsers(dest="command", required=True)

    # ckd-decode
    p_tex = sub.add_parser("ckd-decode",
        help="Decode CKD texture files to standard image formats")
    p_tex.add_argument("files", nargs="+", help="CKD texture files to decode")
    p_tex.add_argument("--output", default=".", help="Output directory (default: current)")

    # ckd-audio
    p_aud = sub.add_parser("ckd-audio",
        help="Extract raw audio from CKD audio files")
    p_aud.add_argument("files", nargs="+", help="CKD audio files to extract")
    p_aud.add_argument("--output", default=".", help="Output directory (default: current)")

    # ipk-extract
    p_ipk = sub.add_parser("ipk-extract",
        help="Extract IPK archives")
    p_ipk.add_argument("files", nargs="+", help="IPK archive files to extract")
    p_ipk.add_argument("--output", default=".", help="Output directory (default: current)")

    args = parser.parse_args()

    if args.command == "ckd-decode":
        for f in args.files:
            decode_ckd_texture(f, args.output)

    elif args.command == "ckd-audio":
        for f in args.files:
            extract_ckd_audio(f, args.output)

    elif args.command == "ipk-extract":
        for f in args.files:
            out = os.path.join(args.output, os.path.splitext(os.path.basename(f))[0])
            extract_ipk(f, out)


if __name__ == "__main__":
    main()
