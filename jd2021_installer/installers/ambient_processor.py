"""Ambient sound processor.

Processes ambient sound templates (`amb_*.tpl.ckd`) into the
corresponding engine-ready `.ilu` and `.tpl` Lua pairs.

Ported from V1's ``ubiart_lua.py`` (`process_ambient_sound`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from jd2021_installer.installers.tape_converter import _convert_value, _load_ckd_json

logger = logging.getLogger("jd2021.installers.ambient_processor")


def process_ambient_tpl(
    json_data: Dict[str, Any],
    map_name: str,
    amb_filename: str
) -> Tuple[str, str, List[str]]:
    """Process an ambient sound .tpl.ckd dictionary.

    Args:
        json_data:    Parsed JSON dict from the ambient .tpl.ckd
        map_name:     The map codename (e.g. "RainOnMe")
        amb_filename: Original filename (e.g. "amb_rainonme.tpl.ckd")

    Returns:
        (ilu_content, tpl_content, audio_file_paths)
    """
    try:
        components = json_data.get("COMPONENTS", [])
        if not components:
            logger.warning("No COMPONENTS block in %s", amb_filename)
            return "", "", []

        sound_component = components[0]
        if "soundList" not in sound_component:
            logger.warning("No soundList in first component of %s", amb_filename)
            return "", "", []

        sound_list = sound_component["soundList"]
        audio_file_paths: List[str] = []

        # Find referenced audio files
        for entry in sound_list:
            files = entry.get("files", [])
            for f in files:
                # the V1 format has raw strings in the files list initially
                if isinstance(f, str):
                    audio_file_paths.append(f)
                elif isinstance(f, dict) and "VAL" in f:
                    audio_file_paths.append(f["VAL"])

        # Convert to VAL wrapper format expected by UbiArt Lua if needed
        # V2's `_convert_value` handles lists natively, but if the engine strictly requires
        # the {"VAL": "..."} struct format, we structure it explicitly here for safety.
        for entry in sound_list:
            if "files" in entry:
                new_files = []
                for f in entry["files"]:
                    if isinstance(f, str):
                        new_files.append({"VAL": f})
                    else:
                        new_files.append(f)
                entry["files"] = new_files
                
                # Also strip __class wrappers if they exist in the entry (V1 remove_class logic)
                if "__class" in entry:
                    class_name = entry.pop("__class")
                    entry["NAME"] = class_name
                    # Wrap the inner properties inside the class name key
                    inner_props = dict(entry)
                    inner_props.pop("NAME")
                    entry.clear()
                    entry["NAME"] = class_name
                    entry[class_name] = inner_props

        # Use our tape converter's _convert_value for the Lua serialization
        lua_str = _convert_value(sound_list, indent_level=0)

        ilu_name = amb_filename.replace('.tpl.ckd', '.ilu')

        ilu_content = (
            f"DESCRIPTOR = {lua_str}\n"
            f"appendTable(component.SoundComponent_Template.soundList,DESCRIPTOR)"
        )

        tpl_content = (
            'params=\n{\n\tNAME="Actor_Template",\n\tActor_Template=\n\t{\n'
            '\t\tCOMPONENTS=\n\t\t{\n\t\t}\n\t}\n}\n'
            'includeReference("EngineData/Misc/Components/SoundComponent.ilu")\n'
            f'includeReference("world/maps/{map_name}/audio/amb/{ilu_name}")'
        )

        return ilu_content, tpl_content, audio_file_paths

    except Exception as e:
        logger.error("Error processing AMB template %s: %s", amb_filename, e)
        return "", "", []


def process_ambient_directory(source_dir: Path, target_dir: Path, codename: str) -> int:
    """Process all ambient .tpl.ckd files in a directory.

    Reads files mapping `amb_*.tpl.ckd` and writes the resulting `.ilu`
    and `.tpl` files to `target_dir/Audio/AMB/` (or directly to target_dir if Audio/AMB isn't specified).

    Args:
        source_dir: Directory to scan for .tpl.ckd files.
        target_dir: The map's root installation directory (e.g. cache/World/MAPS/Codename).
        codename:   The map codename.

    Returns:
        Number of templates processed successfully.
    """
    amb_out_dir = target_dir / "Audio" / "AMB"
    amb_out_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for ckd in source_dir.rglob("amb_*.tpl.ckd"):
        try:
            data = _load_ckd_json(ckd)
            ilu_c, tpl_c, audio_files = process_ambient_tpl(data, codename, ckd.name)

            if ilu_c and tpl_c:
                base_name = ckd.name.replace(".tpl.ckd", "")
                ilu_path = amb_out_dir / f"{base_name}.ilu"
                tpl_path = amb_out_dir / f"{base_name}.tpl"

                ilu_path.write_text(ilu_c, encoding="utf-8")
                tpl_path.write_text(tpl_c, encoding="utf-8")
                
                logger.info("Processed AMB template: %s", ckd.name)
                count += 1
        except json.JSONDecodeError:
            logger.warning("Skipping non-JSON ambient file: %s", ckd.name)
        except Exception as e:
            logger.error("Failed to process ambient file %s: %s", ckd.name, e)

    return count
