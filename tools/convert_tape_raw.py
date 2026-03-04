"""
Convert cooked UbiArt CKD tape files to raw JSON dtape/ktape files.

Usage:
    python tools/convert_tape_raw.py files...
    python tools/convert_tape_raw.py files... --output path/to/output
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

try:
    from lua_serializer import load_ckd_json
except ImportError:
    def load_ckd_json(path):
        with open(path, "rb") as fh:
            raw = fh.read().rstrip(b"\0")
        return json.loads(raw)

def convert_tape_raw(ckd_path, output_dir):
    """Load a cooked JSON tape file and save it as formatted raw JSON."""
    try:
        data = load_ckd_json(ckd_path)
    except Exception as e:
        print(f"[ERROR] Failed to load {os.path.basename(ckd_path)}: {e}")
        return False

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.basename(ckd_path)
    if base.lower().endswith(".ckd"):
        base = base[:-4]

    out_path = os.path.join(output_dir, base)

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        print(f"[OK] {os.path.basename(ckd_path)} -> {os.path.basename(out_path)}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save {os.path.basename(out_path)}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Convert cooked UbiArt CKD tape files to raw JSON dtape/ktape files.")
    parser.add_argument("files", nargs="+", help="CKD tape files to convert (e.g. *.dtape.ckd)")
    parser.add_argument("--output", default=".", help="Output directory (default: current directory)")

    args = parser.parse_args()

    success_count = 0
    for f in args.files:
        if convert_tape_raw(f, args.output):
            success_count += 1

    print(f"\nDone — {success_count}/{len(args.files)} file(s) converted.")

if __name__ == "__main__":
    main()
