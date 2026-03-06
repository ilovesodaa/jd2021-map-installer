import json
import sys
import os
from log_config import get_logger
from helpers import load_ckd_json

logger = get_logger("json_to_lua")

def convert_value(val, indent_level):
    indent = "    " * indent_level
    if isinstance(val, dict):
        if "__class" in val:
            class_name = val["__class"]
            out = f"{{\n{indent}    NAME = \"{class_name}\",\n"
            out += f"{indent}    {class_name} = \n"
            out += f"{indent}    {{\n"
            for k, v in val.items():
                if k == "__class": continue
                out += f"{indent}        {k} = {convert_value(v, indent_level + 2)},\n"
            out += f"{indent}    }},\n{indent}}}"
            return out
        else:
            # It's a map/dictionary without __class
            # Translate to array of KEY/VAL pairs
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
        escaped = val.replace('"', '\\"')
        return f"\"{escaped}\""
    elif isinstance(val, bool):
        return "1" if val else "0"
    elif val is None:
        return "nil"
    elif isinstance(val, float) or isinstance(val, int):
        return str(val)
    else:
        return str(val)

def convert_file(in_path, out_path):
    """Convert a CKD JSON file to UbiArt Lua format.

    Args:
        in_path: Path to the input JSON/CKD file.
        out_path: Path to write the output Lua file.
    """
    if not os.path.isfile(in_path):
        logger.error("Input file not found: %s", in_path)
        return

    try:
        data = load_ckd_json(in_path)
    except Exception as e:
        logger.error("Error parsing CKD %s: %s", in_path, e)
        return

    lua_str = "params =\n" + convert_value(data, 0)

    # Validate output directory exists
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        logger.error("Output directory does not exist: %s", out_dir)
        return

    try:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(lua_str)
        logger.info("Successfully converted %s -> %s", in_path, out_path)
    except OSError as e:
        logger.error("Failed to write output file %s: %s", out_path, e)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python json_to_lua.py <input.json> <output.lua>")
        sys.exit(1)
    convert_file(sys.argv[1], sys.argv[2])
