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
    
    Uses raw_decode to handle files with trailing garbage data (Extra data errors).
    """
    content = ckd_path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(content.strip())
        return obj
    except json.JSONDecodeError:
        return json.loads(content)


def convert_tape_file(ckd_path: Path, output_path: Path) -> bool:
    """Convert a CKD JSON tape file to UbiArt Lua format.

    Works for dance tapes (.dtape.ckd), karaoke tapes (.ktape.ckd),
    and mainsequence tapes (_mainsequence.tape.ckd).

    Args:
        ckd_path:    Path to the source CKD JSON file.
        output_path: Path to write the Lua output.

    Returns:
        True if conversion succeeded, False otherwise.
    """
    if not ckd_path.is_file():
        logger.error("Tape CKD not found: %s", ckd_path)
        return False

    try:
        data = _load_ckd_json(ckd_path)
        lua_str = json_to_lua(data)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(lua_str, encoding="utf-8")
        logger.info("Converted tape: %s → %s", ckd_path.name, output_path.name)
        return True

    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Failed to parse tape CKD %s: %s", ckd_path.name, e)
        return False
    except OSError as e:
        logger.error("Failed to write tape %s: %s", output_path.name, e)
        return False


def convert_dance_tape(ckd_path: Path, target_dir: Path, codename: str) -> bool:
    """Convert a dance tape CKD to the game's timeline directory.

    Input:  ``*_TML_Dance.dtape.ckd``
    Output: ``Timeline/{codename}_TML_Dance.dtape``
    """
    output = target_dir / "Timeline" / f"{codename}_TML_Dance.dtape"
    return convert_tape_file(ckd_path, output)


def convert_karaoke_tape(ckd_path: Path, target_dir: Path, codename: str) -> bool:
    """Convert a karaoke tape CKD to the game's timeline directory.

    Input:  ``*_TML_Karaoke.ktape.ckd``
    Output: ``Timeline/{codename}_TML_Karaoke.ktape``
    """
    output = target_dir / "Timeline" / f"{codename}_TML_Karaoke.ktape"
    return convert_tape_file(ckd_path, output)


def convert_cinematic_tape(ckd_path: Path, target_dir: Path, codename: str) -> bool:
    """Convert a mainsequence tape CKD to the Cinematics directory.

    Input:  ``*_mainsequence.tape.ckd`` or ``*_MainSequence.tape.ckd``
    Output: ``Cinematics/{codename}_MainSequence.tape``
    """
    output = target_dir / "Cinematics" / f"{codename}_MainSequence.tape"
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
