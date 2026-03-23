"""CKD JSON → UbiArt Lua tape converter.

Converts normalized CKD JSON structures (dance tapes, karaoke tapes,
and cinematic/mainsequence tapes) into the UbiArt Lua format expected
by the JD2021 game engine.

Ported from V1's ``json_to_lua.py`` with typed interfaces.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("jd2021.installers.tape_converter")


# ---------------------------------------------------------------------------
# Core JSON → Lua converter  (recursive, ported from V1 json_to_lua.py)
# ---------------------------------------------------------------------------

def _convert_value(val: Any, indent_level: int = 0) -> str:
    """Recursively convert a Python value to UbiArt Lua literal syntax."""
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
                out += f"{indent}        {k} = {_convert_value(v, indent_level + 2)},\n"
            out += f"{indent}    }},\n{indent}}}"
            return out
        else:
            # Dictionary without __class → KEY/VAL pairs
            out = "{\n"
            for k, v in val.items():
                out += f"{indent}    {{\n"
                out += f"{indent}        KEY = \"{k}\",\n"
                out += f"{indent}        VAL = {_convert_value(v, indent_level + 2)},\n"
                out += f"{indent}    }},\n"
            out += f"{indent}}}"
            return out

    elif isinstance(val, list):
        out = "{\n"
        for item in val:
            if isinstance(item, (int, float, str, bool)) or item is None:
                out += f"{indent}    {{\n"
                out += f"{indent}        VAL = {_convert_value(item, indent_level + 2)}\n"
                out += f"{indent}    }},\n"
            else:
                out += f"{indent}    {_convert_value(item, indent_level + 1)},\n"
        out += f"{indent}}}"
        return out

    elif isinstance(val, str):
        escaped = val.replace('"', '\\"')
        return f'"{escaped}"'

    elif isinstance(val, bool):
        return "1" if val else "0"

    elif val is None:
        return "nil"

    elif isinstance(val, (float, int)):
        return str(val)

    return str(val)


def json_to_lua(data: Dict[str, Any]) -> str:
    """Convert a full CKD JSON structure to UbiArt Lua format.

    Args:
        data: Parsed CKD JSON dictionary (typically with COMPONENTS array).

    Returns:
        Complete Lua string starting with ``params = ...``.
    """
    return "params =\n" + _convert_value(data, 0)


# ---------------------------------------------------------------------------
# File-level converters
# ---------------------------------------------------------------------------

def _load_ckd_json(ckd_path: Path) -> Dict[str, Any]:
    """Load a CKD file as JSON. Handles the common UbiArt CKD JSON format.
    
    Uses raw_decode to handle files with trailing garbage and 
    binary headers before the JSON start.
    """
    try:
        content_bytes = ckd_path.read_bytes()
        if not content_bytes:
            return {}
            
        # Try to find JSON start '{' to handle leading binary junk (e.g. from some IPK tools)
        start_idx = content_bytes.find(b'{')
        if start_idx == -1:
            logger.warning("No JSON object found in CKD %s (it might be binary)", ckd_path.name)
            return {}
            
        content = content_bytes[start_idx:].decode("utf-8-sig", errors="replace").strip()
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(content)
        return obj
    except Exception as e:
        logger.debug("Non-critical tape parsing error for %s: %s", ckd_path.name, e)
        return {}


from jd2021_installer.parsers.binary_ckd import parse_binary_ckd


def convert_tape_file(ckd_path: Path, output_path: Path) -> bool:
    """Convert a CKD (JSON or Binary) tape file to UbiArt Lua format.

    Works for dance tapes (.dtape.ckd), karaoke tapes (.ktape.ckd),
    and mainsequence tapes (_mainsequence.tape.ckd).

    Args:
        ckd_path:    Path to the source CKD file.
        output_path: Path to write the Lua output.

    Returns:
        True if conversion succeeded, False otherwise.
    """
    if not ckd_path.is_file():
        logger.error("Tape CKD not found: %s", ckd_path)
        return False

    try:
        # 1. Try JSON parsing first
        data = _load_ckd_json(ckd_path)
        
        # 2. If JSON is empty/invalid, try Binary parsing
        if not data:
            logger.debug("Tape %s is not JSON, attempting binary parse", ckd_path.name)
            parsed = parse_binary_ckd(ckd_path.read_bytes(), ckd_path.name)
            if hasattr(parsed, "as_ubiart_dict"):
                data = parsed.as_ubiart_dict()
            elif isinstance(parsed, dict) and "clips" in parsed: # For legacy dicts if any
                data = parsed
            else:
                logger.error("Binary parse of %s returned non-convertible result", ckd_path.name)
                return False

        lua_str = json_to_lua(data)

        # 1. Ensure 'pictos' is lowercase
        # 2. Ensure '.png' is used instead of '.ckd' or '.tga' for pictos
        import re
        lua_str = re.sub(r'([Pp]ictos)/([^"]+)\.(ckd|tga)', r'pictos/\2.png', lua_str)
        # 3. Align all system paths with V1 lowercase conventions
        lua_str = lua_str.replace('"World/MAPS/', '"world/maps/')
        lua_str = lua_str.replace('"MenuArt/', '"menuart/')
        lua_str = lua_str.replace('"Autodance/', '"autodance/')
        lua_str = lua_str.replace('"Timeline/pictos/', '"timeline/pictos/')
        lua_str = lua_str.replace('"Timeline/', '"timeline/')

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(lua_str, encoding="utf-8")
        logger.info("Converted tape: %s → %s", ckd_path.name, output_path.name)
        return True

    except Exception as e:
        logger.error("Failed to convert tape CKD %s: %s", ckd_path.name, e)
        return False


def convert_dance_tape(ckd_path: Path, target_dir: Path, codename: str) -> bool:
    """Convert a dance tape CKD to the game's timeline directory.

    Input:  ``*_TML_Dance.dtape.ckd``
    Output: ``Timeline/{codename}_TML_Dance.dtape``
    """
    output = target_dir / "timeline" / f"{codename}_TML_Dance.dtape"
    return convert_tape_file(ckd_path, output)


def convert_karaoke_tape(ckd_path: Path, target_dir: Path, codename: str) -> bool:
    """Convert a karaoke tape CKD to the game's timeline directory.

    Input:  ``*_TML_Karaoke.ktape.ckd``
    Output: ``Timeline/{codename}_TML_Karaoke.ktape``
    """
    output = target_dir / "timeline" / f"{codename}_TML_Karaoke.ktape"
    return convert_tape_file(ckd_path, output)


def convert_cinematic_tape(ckd_path: Path, target_dir: Path, codename: str) -> bool:
    """Convert a mainsequence tape CKD to the Cinematics directory.

    Input:  ``*_mainsequence.tape.ckd`` or ``*_MainSequence.tape.ckd``
    Output: ``Cinematics/{codename}_MainSequence.tape``
    """
    output = target_dir / "cinematics" / f"{codename}_MainSequence.tape"
    return convert_tape_file(ckd_path, output)


def auto_convert_tapes(source_dir: Path, target_dir: Path, codename: str) -> int:
    """Auto-detect and convert all tape CKD files in a directory.

    Searches ``source_dir`` recursively for dtape, ktape, and
    mainsequence tape CKDs and converts them to UbiArt Lua format.

    Returns:
        Number of tapes successfully converted.
    """
    converted = 0
    cn_lower = codename.lower()

    for ckd in source_dir.rglob("*.ckd"):
        name_lower = ckd.name.lower()

        # Relaxed matching: match dtape, ktape, or mainsequence anywhere in name
        # If multiple files exist, we take the first one or prioritize codename if present
        if "dtape" in name_lower:
            if convert_dance_tape(ckd, target_dir, codename):
                converted += 1

        elif "ktape" in name_lower:
            if convert_karaoke_tape(ckd, target_dir, codename):
                converted += 1

        elif "mainsequence" in name_lower and "tape" in name_lower:
            if convert_cinematic_tape(ckd, target_dir, codename):
                converted += 1

    logger.info("Auto-converted %d tape(s) for '%s'", converted, codename)
    return converted
