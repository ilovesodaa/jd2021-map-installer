"""
Generic JSON to UbiArt Lua converter for non-tape CKD files.

This script converts cooked JSON (such as autodance templates, configmusic files,
or other standard UbiArt classes) into formatted Lua configurations compatible
with the Just Dance 2021 PC engine.

Usage:
    python tools/convert_json_to_lua.py input.ckd output.lua
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


def convert_value(val, indent_level):
    """Recursively serialize Python structures to UbiArt Lua strings."""
    indent = "    " * indent_level
    if isinstance(val, dict):
        if "__class" in val:
            class_name = val["__class"]
            out = f"{{\n{indent}    NAME = \"{class_name}\",\n"
            out += f"{indent}    {class_name} = \n"
            out += f"{indent}    {{\n"
            for k, v in val.items():
                if k == "__class":
                    continue
                out += f"{indent}        {k} = {convert_value(v, indent_level + 2)},\n"
            out += f"{indent}    }},\n{indent}}}"
            return out
        else:
            # Dictionary without __class -> array of KEY/VAL pairs
            out = "{\n"
            for k, v in val.items():
                out += f"{indent}    {{\n"
                out += f"{indent}        KEY = \"{k}\",\n"
                out += f"{indent}        VAL = {convert_value(v, indent_level + 2)},\n"
                out += f"{indent}    }},\n"
            out += f"{indent}}}"
            return out

    elif isinstance(val, list):
        out = "{\n"
        for item in val:
            if isinstance(item, (int, float, str, bool)) or item is None:
                out += f"{indent}    {{\n"
                out += f"{indent}        VAL = {convert_value(item, indent_level + 2)}\n"
                out += f"{indent}    }},\n"
            else:
                out += f"{indent}    {convert_value(item, indent_level + 1)},\n"
        out += f"{indent}}}"
        return out

    elif isinstance(val, str):
        escaped = val.replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        return f"\"{escaped}\""

    elif isinstance(val, bool):
        return "1" if val else "0"

    elif val is None:
        return "nil"

    elif isinstance(val, float) or isinstance(val, int):
        return str(val)

    else:
        return str(val)


def convert_json_to_lua(in_path, out_path):
    """Convert a CKD JSON file to UbiArt Lua format."""
    if not os.path.isfile(in_path):
        print(f"[ERROR] Input file not found: {in_path}")
        return False

    try:
        data = load_ckd_json(in_path)
    except Exception as e:
        print(f"[ERROR] failed to parse JSON in {in_path}: {e}")
        return False

    lua_str = "params =\n" + convert_value(data, 0)

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    try:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(lua_str)
        print(f"[OK] {os.path.basename(in_path)} -> {os.path.basename(out_path)}")
        return True
    except Exception as e:
        print(f"[ERROR] failed to write output file {out_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert a generic CKD JSON file to a UbiArt Lua format.")
    parser.add_argument("input", help="Path to input CKD JSOn file (e.g. file.ckd)")
    parser.add_argument("output", help="Path to output Lua file (e.g. file.lua)")

    args = parser.parse_args()
    if convert_json_to_lua(args.input, args.output):
        print("\nDone.")


if __name__ == "__main__":
    main()
