"""
Convert cooked UbiArt CKD map data into engine-ready Lua files.

Handles SongDesc, MusicTrack/TRK, dance/karaoke tapes, cinematic tapes
(with curve processing), and AMB sound descriptors.

Usage:
    python tools/convert_map_data.py --input path/to/extracted --output path/to/out --map-name MapName
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lua_serializer import (
    Vector2D,
    color_to_hex,
    get_case_insensitive,
    load_ckd_json,
    strip_empty,
    to_key_val,
    to_lua,
    to_val_list,
    transform_classes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_file(directory, filename):
    """Case-insensitive file lookup in *directory*."""
    if not os.path.isdir(directory):
        return None
    for entry in os.listdir(directory):
        if entry.lower() == filename.lower():
            return os.path.join(directory, entry)
    return None


def _build_tracks(track_ids):
    """Build the Tracks array expected by UbiArt Lua tapes."""
    return [{"TapeTrack": {"id": tid}} for tid in track_ids]


# ---------------------------------------------------------------------------
# SongDesc conversion
# ---------------------------------------------------------------------------

def convert_songdesc(ckd_path, map_name):
    """Convert ``songdesc.tpl.ckd`` → SongDesc Lua string."""
    data = load_ckd_json(ckd_path)
    component = data["COMPONENTS"][0]

    desc = {}
    desc["MapName"]            = get_case_insensitive(component, "MapName", "")
    desc["RelatedAlbums"]      = get_case_insensitive(component, "RelatedAlbums", [])
    desc["JDVersion"]          = get_case_insensitive(component, "JDVersion", 2016)
    desc["OriginalJDVersion"]  = get_case_insensitive(component, "OriginalJDVersion", 2016)
    desc["Artist"]             = get_case_insensitive(component, "Artist", "")
    desc["DancerName"]         = get_case_insensitive(component, "DancerName", "Unknown Dancer")
    desc["Title"]              = get_case_insensitive(component, "Title", "")
    desc["Credits"]            = get_case_insensitive(component, "Credits",
        "All rights of the producer and other rightholders to the recorded work reserved. "
        "Unless otherwise authorized, the duplication, rental, loan, exchange or use of "
        "this video game for public performance, broadcasting and online distribution to "
        "the public are prohibited.")
    desc["PhoneImages"]        = to_key_val(get_case_insensitive(component, "PhoneImages", {}))
    desc["NumCoach"]           = get_case_insensitive(component, "NumCoach", -1)
    desc["MainCoach"]          = get_case_insensitive(component, "MainCoach", -1)
    desc["Difficulty"]         = get_case_insensitive(component, "Difficulty", 1)
    desc["SweatDifficulty"]    = get_case_insensitive(component, "SweatDifficulty", 1)
    desc["BackgroundType"]     = get_case_insensitive(component, "BackgroundType", 0)
    desc["LyricsType"]         = get_case_insensitive(component, "LyricsType", -1)
    desc["Energy"]             = get_case_insensitive(component, "Energy", 1)
    desc["Tags"]               = to_val_list(get_case_insensitive(component, "Tags", ["Main"]))
    desc["Status"]             = get_case_insensitive(component, "Status", 3)
    desc["LocaleID"]           = get_case_insensitive(component, "LocaleID", 4294967295)
    desc["MojoValue"]          = get_case_insensitive(component, "MojoValue", 0)
    desc["CountInProgression"] = get_case_insensitive(component, "CountInProgression", 1)

    # DefaultColors → hex KEY/VAL
    raw_colors = get_case_insensitive(component, "DefaultColors", {})
    if raw_colors:
        desc["DefaultColors"] = to_key_val(
            {k: color_to_hex(v) for k, v in raw_colors.items()})
    else:
        desc["DefaultColors"] = []

    desc["Mode"] = 6
    desc["AudioPreviewFadeTime"] = 0.0

    desc = strip_empty(desc, keep=("AudioPreviewFadeTime", "MojoValue"))

    lua = {
        "NAME": "Actor_Template",
        "Actor_Template": {
            "TAGS": to_val_list(["songdescmain"]),
            "WIP": 0,
            "LOWUPDATE": 0,
            "UPDATE_LAYER": 0,
            "ENUM_UPDATE_LAYER": "WorldUpdateLayer_Gameplay",
            "PROCEDURAL": 0,
            "STARTPAUSED": 0,
            "FORCEISENVIRONMENT": 0,
            "COMPONENTS": [desc],
        },
    }

    return "params =" + to_lua(lua)


# ---------------------------------------------------------------------------
# MusicTrack conversion
# ---------------------------------------------------------------------------

def convert_musictrack(ckd_path, map_name):
    """Convert ``*_musictrack.tpl.ckd`` → (tpl_lua, trk_lua) tuple."""
    data = load_ckd_json(ckd_path)

    # -- TPL: full template with class transform --
    # Strip top-level engine boilerplate keys
    for key in ("WIP", "LOWUPDATE", "UPDATE_LAYER",
                "PROCEDURAL", "STARTPAUSED", "FORCEISENVIRONMENT"):
        data.pop(key, None)

    track_data = get_case_insensitive(data["COMPONENTS"][0], "trackData", {})
    structure = get_case_insensitive(track_data, "structure", {})
    markers = get_case_insensitive(structure, "markers", [])
    if markers:
        structure["markers"] = to_val_list(markers)

    tpl_lua = "params =" + to_lua(transform_classes(data))

    # -- TRK: music track structure --
    trk = {
        "MusicTrackStructure": {
            "markers": to_val_list(get_case_insensitive(structure, "markers", [])) if not markers else structure["markers"],
            "signatures": [],
            "sections": [],
            "comments": [],
        }
    }

    sigs = get_case_insensitive(structure, "signatures", None)
    if sigs:
        for sig in sigs:
            trk["MusicTrackStructure"]["signatures"].append({
                "MusicSignature": {
                    "beats": sig.get("beats", 4),
                    "marker": float(sig.get("marker", 0)),
                    "comment": "",
                }
            })
    else:
        trk["MusicTrackStructure"]["signatures"] = [{
            "MusicSignature": {"beats": 4, "marker": 0.0, "comment": ""}
        }]

    sections = get_case_insensitive(structure, "sections", None)
    if sections:
        for sec in sections:
            trk["MusicTrackStructure"]["sections"].append({
                "MusicSection": {
                    "sectionType": sec.get("sectionType", 0),
                    "marker": float(sec.get("marker", 0)),
                    "comment": sec.get("comment", ""),
                }
            })

    # Copy scalar timing fields
    ts = trk["MusicTrackStructure"]
    for field in ("startBeat", "endBeat", "videoStartTime", "previewEntry",
                  "previewLoopStart", "previewLoopEnd"):
        ts[field] = get_case_insensitive(structure, field, 0)
    ts["volume"] = float(get_case_insensitive(structure, "volume", 0))
    ts["entryPoints"] = {}

    trk_lua = "structure =" + to_lua(trk)

    return tpl_lua, trk_lua


# ---------------------------------------------------------------------------
# Tape conversion (dance, karaoke, cinematic)
# ---------------------------------------------------------------------------

# Clip classes that contain curve data and their curve field names
_CURVE_FIELDS = {
    "AlphaClip":                        ["Curve"],
    "RotationClip":                     ["CurveX", "CurveY", "CurveZ"],
    "TranslationClip":                  ["CurveX", "CurveY", "CurveZ"],
    "SizeClip":                         ["CurveX", "CurveY"],
    "ScaleClip":                        ["CurveX", "CurveY"],
    "ColorClip":                        ["ColorRed", "ColorGreen", "ColorBlue"],
    "MaterialGraphicDiffuseAlphaClip":  ["CurveA"],
    "MaterialGraphicDiffuseColorClip":  ["ColorR", "ColorG", "ColorB"],
    "MaterialGraphicUVTranslationClip": ["CurveU", "CurveV"],
    "ProportionClip":                   ["CurveX", "CurveY"],
}


def _process_curve(curve_data):
    """Extract keys from a curve dict and convert coordinate arrays to
    Vector2D objects."""
    keys = curve_data.get("Curve", {}).get("Keys", [])
    for key in keys:
        for k, v in list(key.items()):
            if isinstance(v, list) and len(v) == 2:
                key[k] = Vector2D(v[0], v[1])
    result = {kk: vv for kk, vv in curve_data.items() if kk != "Curve"}
    result["Keys"] = keys
    return result


def convert_tape(ckd_path, tape_type="dance"):
    """Convert a tape CKD (dance / karaoke / cinematic) → Lua string.

    *tape_type* should be ``"dance"``, ``"karaoke"``, or ``"cinematics"``.
    """
    data = load_ckd_json(ckd_path)
    data["Tracks"] = []
    track_ids = []

    clips = get_case_insensitive(data, "Clips", [])

    for clip in clips:
        tid = get_case_insensitive(clip, "TrackId", 0)
        if tid not in track_ids:
            track_ids.append(tid)

        clip_class = get_case_insensitive(clip, "__class", "")

        # MotionClip: colour conversion
        if clip_class == "MotionClip":
            if "Color" in clip:
                clip["Color"] = color_to_hex(clip["Color"])
            else:
                clip["Color"] = "0xFFFFFFFF"

            # MotionPlatformSpecifics → KEY/VAL
            if "MotionPlatformSpecifics" in clip:
                mps = []
                for platform, pdata in clip["MotionPlatformSpecifics"].items():
                    mps.append({"KEY": platform, "VAL": transform_classes(pdata)})
                clip["MotionPlatformSpecifics"] = mps

    # Degenerate TrackIds: if each clip has a unique ID, regroup by class
    if len(track_ids) == len(clips) and len(clips) > 1:
        track_ids = []
        class_ids = {}
        for clip in clips:
            cc = get_case_insensitive(clip, "__class", "")
            if cc not in class_ids:
                class_ids[cc] = random.randint(0, 0xFFFFFFFF)
            clip["TrackId"] = class_ids[cc]
            if class_ids[cc] not in track_ids:
                track_ids.append(class_ids[cc])

    # Cinematic-specific processing
    if tape_type == "cinematics":
        for clip in clips:
            # Resolve ActorIndices → ActorPaths
            if "ActorIndices" in clip and "ActorPaths" in data:
                resolved = [data["ActorPaths"][i] for i in clip["ActorIndices"]]
                clip["ActorPaths"] = to_val_list(resolved)
                del clip["ActorIndices"]

            # Process curve data
            cc = get_case_insensitive(clip, "__class", "")
            if cc in _CURVE_FIELDS:
                for field in _CURVE_FIELDS[cc]:
                    if field in clip:
                        clip[field] = _process_curve(clip[field])

    data["Tracks"] = _build_tracks(track_ids)
    data.pop("ActorPaths", None)

    transformed = strip_empty(transform_classes(data))
    return "params =" + to_lua(transformed)


# ---------------------------------------------------------------------------
# AMB sound descriptor conversion
# ---------------------------------------------------------------------------

def convert_amb(ckd_path, map_name):
    """Convert an AMB ``*.tpl.ckd`` → (ilu_lua, tpl_lua) tuple."""
    data = load_ckd_json(ckd_path)
    sound_list = data["COMPONENTS"][0]["soundList"]

    # Convert files arrays to VAL lists
    for entry in sound_list:
        if "files" in entry:
            entry["files"] = to_val_list(entry["files"])

    ilu_lua = ("DESCRIPTOR =" + to_lua(transform_classes(sound_list)) +
               "\nappendTable(component.SoundComponent_Template.soundList,DESCRIPTOR)")

    basename = os.path.basename(ckd_path).replace(".tpl.ckd", "")
    tpl_lua = f"""params=
{{
\tNAME="Actor_Template",
\tActor_Template=
\t{{
\t\tCOMPONENTS=
\t\t{{
\t\t}}
\t}}
}}
includeReference("EngineData/Misc/Components/SoundComponent.ilu")
includeReference("world/maps/{map_name}/audio/amb/{basename}.ilu")"""

    return ilu_lua, tpl_lua


# ---------------------------------------------------------------------------
# CLI orchestrator
# ---------------------------------------------------------------------------

def run(input_dir, output_dir, map_name):
    """Process all available CKD files for a map."""
    os.makedirs(output_dir, exist_ok=True)
    converted = 0

    # 1. SongDesc
    sd_path = _find_file(input_dir, "songdesc.tpl.ckd")
    if sd_path:
        lua = convert_songdesc(sd_path, map_name)
        with open(os.path.join(output_dir, "SongDesc.tpl"), "w") as f:
            f.write(lua)
        converted += 1
        print(f"[OK] SongDesc.tpl")

    # 2. MusicTrack + TRK
    audio_dir = os.path.join(input_dir, "audio")
    mt_path = _find_file(audio_dir, f"{map_name.lower()}_musictrack.tpl.ckd")
    if mt_path:
        tpl_lua, trk_lua = convert_musictrack(mt_path, map_name)
        out_audio = os.path.join(output_dir, "Audio")
        os.makedirs(out_audio, exist_ok=True)
        with open(os.path.join(out_audio, f"{map_name}_MusicTrack.tpl"), "w") as f:
            f.write(tpl_lua)
        with open(os.path.join(out_audio, f"{map_name}.trk"), "w") as f:
            f.write(trk_lua)
        converted += 2
        print(f"[OK] {map_name}_MusicTrack.tpl + {map_name}.trk")

    # 3. Dance tape
    tl_dir = os.path.join(input_dir, "timeline")
    dance_path = _find_file(tl_dir, f"{map_name.lower()}_tml_dance.dtape.ckd")
    if dance_path:
        lua = convert_tape(dance_path, "dance")
        out_tl = os.path.join(output_dir, "Timeline")
        os.makedirs(out_tl, exist_ok=True)
        with open(os.path.join(out_tl, f"{map_name}_TML_Dance.dtape"), "w") as f:
            f.write(lua)
        converted += 1
        print(f"[OK] {map_name}_TML_Dance.dtape")

    # 4. Karaoke tape
    kara_path = _find_file(tl_dir, f"{map_name.lower()}_tml_karaoke.ktape.ckd")
    if kara_path:
        lua = convert_tape(kara_path, "karaoke")
        out_tl = os.path.join(output_dir, "Timeline")
        os.makedirs(out_tl, exist_ok=True)
        with open(os.path.join(out_tl, f"{map_name}_TML_Karaoke.ktape"), "w") as f:
            f.write(lua)
        converted += 1
        print(f"[OK] {map_name}_TML_Karaoke.ktape")

    # 5. Cinematic tapes (all *.tape.ckd in cinematics/)
    cin_dir = os.path.join(input_dir, "cinematics")
    if os.path.isdir(cin_dir):
        out_cin = os.path.join(output_dir, "Cinematics")
        os.makedirs(out_cin, exist_ok=True)
        for entry in os.listdir(cin_dir):
            if entry.lower().endswith("tape.ckd"):
                full = os.path.join(cin_dir, entry)
                lua = convert_tape(full, "cinematics")
                out_name = entry.replace(".ckd", "")
                with open(os.path.join(out_cin, out_name), "w") as f:
                    f.write(lua)
                converted += 1
                print(f"[OK] Cinematics/{out_name}")

    # 6. AMB descriptors
    amb_dir = os.path.join(input_dir, "audio", "amb")
    if os.path.isdir(amb_dir):
        out_amb = os.path.join(output_dir, "Audio", "AMB")
        os.makedirs(out_amb, exist_ok=True)
        for entry in os.listdir(amb_dir):
            if entry.lower().endswith(".tpl.ckd"):
                full = os.path.join(amb_dir, entry)
                ilu_lua, tpl_lua = convert_amb(full, map_name)
                base = entry.replace(".tpl.ckd", "")
                with open(os.path.join(out_amb, f"{base}.ilu"), "w") as f:
                    f.write(ilu_lua)
                with open(os.path.join(out_amb, f"{base}.tpl"), "w") as f:
                    f.write(tpl_lua)
                converted += 2
                print(f"[OK] AMB/{base}.ilu + .tpl")

    print(f"\nDone — {converted} file(s) generated.")


def main():
    parser = argparse.ArgumentParser(
        description="Convert cooked UbiArt CKD map data to engine-ready Lua files.")
    parser.add_argument("--input", required=True,
                        help="Directory containing extracted CKD files (e.g. ipk_extracted/MapName)")
    parser.add_argument("--output", required=True,
                        help="Output directory for generated Lua files")
    parser.add_argument("--map-name", required=True,
                        help="Map codename (e.g. Starships)")
    args = parser.parse_args()
    run(args.input, args.output, args.map_name)


if __name__ == "__main__":
    main()
