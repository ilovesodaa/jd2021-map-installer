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


def _generate_synthetic_amb(
    wav_ckd_path: Path,
    output_dir: Path,
    codename: str
) -> bool:
    """Generate synthetic ILU/TPL for a .wav.ckd without a template."""
    base = wav_ckd_path.name.replace(".wav.ckd", "")
    map_lower = codename.lower()
    wav_rel = f"world/maps/{map_lower}/audio/amb/{base}.wav"

    # Synthetic ILU
    ilu_content = (
        f'DESCRIPTOR =\n{{\n'
        f'\t{{\n\t\tNAME = "SoundDescriptor_Template",\n'
        f'\t\tSoundDescriptor_Template =\n\t\t{{\n'
        f'\t\t\tname = "{base}",\n\t\t\tvolume = 0,\n'
        f'\t\t\tcategory = "amb",\n\t\t\tlimitCategory = "",\n'
        f'\t\t\tlimitMode = 0,\n\t\t\tmaxInstances = 4294967295,\n'
        f'\t\t\tfiles =\n\t\t\t{{\n\t\t\t\t{{\n'
        f'\t\t\t\t\tVAL = "{wav_rel}",\n'
        f'\t\t\t\t}},\n\t\t\t}},\n'
        f'\t\t\tserialPlayingMode = 0,\n\t\t\tserialStoppingMode = 0,\n'
        f'\t\t}},\n\t}},\n}}\n'
    )

    # Synthetic TPL
    tpl_content = (
        f'params =\n{{\n\tNAME = "Actor_Template",\n'
        f'\tActor_Template =\n\t{{\n\t\tCOMPONENTS =\n\t\t{{\n'
        f'\t\t\t{{\n\t\t\t\tNAME = "SoundComponent_Template",\n'
        f'\t\t\t\tSoundComponent_Template =\n\t\t\t\t{{\n'
        f'\t\t\t\t\tsoundList = {{}},\n'
        f'\t\t\t\t\tSoundwichEvent = "",\n'
        f'\t\t\t\t}},\n\t\t\t}},\n\t\t}},\n\t}},\n}}\n'
        'includeReference("EngineData/Misc/Components/SoundComponent.ilu")\n'
        f'includeReference("world/maps/{codename}/audio/amb/{base}.ilu")'
    )

    try:
        (output_dir / f"{base}.ilu").write_text(ilu_content, encoding="utf-8")
        (output_dir / f"{base}.tpl").write_text(tpl_content, encoding="utf-8")
        
        # Decode the CKD audio
        from jd2021_installer.installers.media_processor import extract_ckd_audio_v1
        decoded = extract_ckd_audio_v1(wav_ckd_path, output_dir)
        if decoded:
            decoded_path = Path(decoded)
            target_wav = output_dir / f"{base}.wav"
            if decoded_path.exists() and decoded_path != target_wav:
                if target_wav.exists():
                    target_wav.unlink()
                decoded_path.rename(target_wav)
        return True
    except Exception as e:
        logger.error("Failed to generate synthetic AMB for %s: %s", base, e)
        return False


def inject_ambient_actors(target_dir: Path, codename: str) -> bool:
    """Inject AMB actors into the map's audio.isc file."""
    audio_isc = target_dir / "Audio" / f"{codename}_audio.isc"
    if not audio_isc.is_file():
        # Case insensitive fallback
        isc_files = list((target_dir / "Audio").glob("*_audio.isc"))
        if isc_files:
            audio_isc = isc_files[0]
        else:
            return False

    amb_tpls = list((target_dir / "Audio" / "AMB").glob("*.tpl"))
    if not amb_tpls:
        return False

    try:
        content = audio_isc.read_text(encoding="utf-8", errors="replace")
        
        # Build actor blocks
        amb_actors = ""
        for i, tpl in enumerate(sorted(amb_tpls)):
            amb_name = tpl.stem
            z = f"0.{i + 2:06d}"
            amb_actors += (
                f'\t\t<ACTORS NAME="Actor">\n'
                f'\t\t\t<Actor RELATIVEZ="{z}" SCALE="1.000000 1.000000" '
                f'xFLIPPED="0" USERFRIENDLY="{amb_name}" '
                f'POS2D="0.000000 0.000000" ANGLE="0.000000" '
                f'INSTANCEDATAFILE="" LUA="world/maps/{codename}/audio/amb/{amb_name}.tpl">\n'
                f'\t\t\t\t<COMPONENTS NAME="SoundComponent">\n'
                f'\t\t\t\t\t<SoundComponent />\n'
                f'\t\t\t\t</COMPONENTS>\n'
                f'\t\t\t</Actor>\n'
                f'\t\t</ACTORS>\n'
            )

        # Inject before <sceneConfigs>
        import re
        pattern = re.compile(r'([ \t]*<sceneConfigs>)', re.IGNORECASE)
        match = pattern.search(content)
        if match:
            new_content = content[:match.start()] + amb_actors + content[match.start():]
            audio_isc.write_text(new_content, encoding="utf-8")
            logger.info("Injected %d AMB actor(s) into %s", len(amb_tpls), audio_isc.name)
            return True
    except Exception as e:
        logger.error("Failed to inject AMB actors into %s: %s", audio_isc.name, e)
    
    return False


def process_ambient_directory(source_dir: Path, target_dir: Path, codename: str) -> int:
    """Process all ambient assets (templates and loose CKDs) in a directory."""
    amb_out_dir = target_dir / "Audio" / "AMB"
    amb_out_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    # 1. Process existing .tpl.ckd templates
    tpl_bases = set()
    for ckd in source_dir.rglob("amb_*.tpl.ckd"):
        try:
            data = _load_ckd_json(ckd)
            ilu_c, tpl_c, audio_files = process_ambient_tpl(data, codename, ckd.name)

            if ilu_c and tpl_c:
                base_name = ckd.name.replace(".tpl.ckd", "")
                tpl_bases.add(base_name.lower())
                
                ilu_path = amb_out_dir / f"{base_name}.ilu"
                tpl_path = amb_out_dir / f"{base_name}.tpl"

                ilu_path.write_text(ilu_c, encoding="utf-8")
                tpl_path.write_text(tpl_c, encoding="utf-8")
                
                logger.debug("Processed AMB template: %s", ckd.name)
                count += 1
        except Exception as e:
            logger.error("Failed to process ambient file %s: %s", ckd.name, e)

    # 2. Process "orphan" .wav.ckd files (no corresponding .tpl.ckd)
    for wav_ckd in source_dir.rglob("*.wav.ckd"):
        if "/amb/" not in str(wav_ckd).lower().replace("\\", "/"):
            continue
            
        base = wav_ckd.name.replace(".wav.ckd", "")
        if base.lower() not in tpl_bases:
            if _generate_synthetic_amb(wav_ckd, amb_out_dir, codename):
                count += 1
                logger.info("Generated synthetic AMB for orphan audio: %s", wav_ckd.name)

    # 3. Inject actors into audio.isc
    inject_ambient_actors(target_dir, codename)

    return count
