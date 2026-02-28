"""
UbiArt Lua Converter for Just Dance

Converts UbiArt CKD/JSON game data to engine-compatible Lua format with proper
handling of tapes, cinematics, motion clips, curves, and ambient sounds.

Ported and improved from jduncooker.py / uaf2lua.py (JDTools by BLDS).
"""

import json
import os


# ---------------------------------------------------------------------------
# vector2d type -- emits vector2dNew(x, y) in Lua output
# ---------------------------------------------------------------------------

class vector2d:
    """Represents a UbiArt 2D vector that serializes to vector2dNew(x,y) in Lua."""

    def __init__(self, array):
        if not isinstance(array, list) or len(array) != 2:
            raise ValueError(f"vector2d expects a list of 2 numbers, got {array!r}")
        self.x = array[0]
        self.y = array[1]

    def __str__(self):
        return f"vector2dNew({self.x},{self.y})"


# ---------------------------------------------------------------------------
# Lua serializer
# ---------------------------------------------------------------------------

def dict_to_lua(data, indent=0, from_list=False):
    """
    Recursively convert a Python data structure to a UbiArt Lua string.

    Improvements over the generic json_to_lua.py converter:
    - vector2d support for cinematic curve keys
    - Consistent 6-decimal float formatting
    - Full string escaping (quotes, newlines, carriage returns)
    - Tab-based indentation matching engine convention
    """
    indent += 1
    lua = ''
    nl = '\n' + '\t' * indent  # newline + indent
    space = '' if from_list else ' '

    if isinstance(data, dict):
        lua += ('\n' + '\t' * (indent - 1)) + '{'
        for key, value in data.items():
            lua += nl + f'{key} ={dict_to_lua(value, indent)},'
        lua += '\n' + '\t' * (indent - 1) + '}'
        return lua

    elif isinstance(data, list):
        if len(data) == 0:
            return ' {}'
        lua += ('\n' + '\t' * (indent - 1)) + '{'
        for item in data:
            if isinstance(item, (dict, list)):
                lua += f'{dict_to_lua(item, indent)},'
            else:
                lua += f'{nl}{dict_to_lua(item, indent, from_list=True)},'
        lua += '\n' + '\t' * (indent - 1) + '}'
        return lua

    elif isinstance(data, bool):
        return f'{space}true' if data else f'{space}false'

    elif isinstance(data, str):
        escaped = data.replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
        return f'{space}"{escaped}"'

    elif isinstance(data, vector2d):
        return f'{space}{data}'

    elif isinstance(data, float):
        return f'{space}{data:.6f}'

    elif isinstance(data, int):
        return f'{space}{data}'

    else:
        return f'{space}nil'


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def load_ckd_json(file_path):
    """Read a .ckd file, strip trailing null bytes, parse as JSON."""
    with open(file_path, 'rb') as f:
        return json.loads(f.read().rstrip(b'\x00'))


def argb_hex(color_list, default="0xffffffff"):
    """
    Convert a [a, r, g, b] float array (each 0.0-1.0) to '0xRRGGBBAA' hex string.

    The UbiArt engine reads DefaultColors and MotionClip Colors in RRGGBBAA order.
    JDU stores them as [alpha, red, green, blue] normalized floats.
    """
    if (isinstance(color_list, list)
            and len(color_list) == 4
            and all(isinstance(c, (float, int)) and c <= 1.1 for c in color_list)):
        a, r, g, b = [int(c * 255) for c in color_list]
        hex_value = (r << 24) | (g << 16) | (b << 8) | a
        return f"0x{hex_value:08x}"
    return default


def remove_class(data):
    """
    Recursively transform __class-tagged dicts to UbiArt NAME/class structure.

    Input:  {"__class": "Foo", "x": 1}
    Output: {"NAME": "Foo", "Foo": {"x": 1}}
    """
    if isinstance(data, dict):
        if "__class" in data:
            class_name = data["__class"]
            new_dict = {k: remove_class(v) for k, v in data.items() if k != "__class"}
            return {"NAME": class_name, class_name: new_dict}
        return {k: remove_class(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [remove_class(item) for item in data]
    return data


def remove_falsy(data, excluded_keys=None):
    """
    Strip keys with falsy default values from dicts.

    Removes keys whose values are "", 0, 0.0, False, {}, [], or None.
    Keys listed in excluded_keys are preserved even if falsy.
    """
    if excluded_keys is None:
        excluded_keys = []
    falsy_values = ("", 0, 0.0, False, {}, [], None)

    if isinstance(data, dict):
        return {k: v for k, v in data.items()
                if v not in falsy_values or k in excluded_keys}
    elif isinstance(data, list):
        return [remove_falsy(item, excluded_keys) for item in data]
    return data


def val_array(array):
    """Wrap list items as [{VAL: item}, ...]."""
    return [{"VAL": i} for i in array]


def val_dict(dictionary):
    """Convert dict to [{KEY: k, VAL: v}, ...]."""
    return [{"KEY": k, "VAL": v} for k, v in dictionary.items()]


# ---------------------------------------------------------------------------
# Tape processing
# ---------------------------------------------------------------------------

# Cinematic clip types that contain curve data, and which keys hold curves.
CINEMATIC_CURVE_MAP = {
    "AlphaClip": ["Curve"],
    "RotationClip": ["CurveX", "CurveY", "CurveZ"],
    "TranslationClip": ["CurveX", "CurveY", "CurveZ"],
    "SizeClip": ["CurveX", "CurveY"],
    "ScaleClip": ["CurveX", "CurveY"],
    "ColorClip": ["ColorRed", "ColorGreen", "ColorBlue"],
    "MaterialGraphicDiffuseAlphaClip": ["CurveA"],
    "MaterialGraphicDiffuseColorClip": ["ColorR", "ColorG", "ColorB"],
    "MaterialGraphicUVTranslationClip": ["CurveU", "CurveV"],
    "ProportionClip": ["CurveX", "CurveY"],
}


def _get(d, key, default=None):
    """Case-insensitive dict get."""
    lookup = {k.lower(): v for k, v in d.items()}
    return lookup.get(key.lower(), default)


def _process_curve(curve_data):
    """
    Convert a curve dict's Keys values from [x, y] lists to vector2d objects.

    Input curve_data: {"Curve": {"Keys": [{"Value": [0.5, 1.0], ...}, ...]}, ...}
    Output: {"Keys": [{"Value": vector2d([0.5, 1.0]), ...}, ...]}
    """
    keys = curve_data.get("Curve", {}).get("Keys", [])
    for key_entry in keys:
        for k, v in key_entry.items():
            if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
                key_entry[k] = vector2d(v)
    # Flatten: remove the Curve wrapper, keep Keys at top level
    result = {k: v for k, v in curve_data.items() if k != "Curve"}
    result["Keys"] = keys
    return result


def process_tape(json_data, tape_type="dance"):
    """
    Full UbiArt tape processing pipeline.

    Args:
        json_data: Parsed JSON dict from a .tape.ckd / .dtape.ckd / .ktape.ckd file
        tape_type: One of "dance", "karaoke", "cinematics"

    Returns:
        str: Complete Lua string including 'params =' prefix
    """
    tape = json_data
    tape["Tracks"] = []
    track_ids = []

    clips = _get(tape, "Clips", [])

    # --- Pass 1: Collect TrackIds, process MotionClips ---
    for clip in clips:
        track_id = _get(clip, "TrackId", 0)
        if track_id not in track_ids:
            track_ids.append(track_id)

        clip_class = _get(clip, "__class", "")

        # MotionClip Color -> ARGB hex
        if clip_class == "MotionClip":
            if "Color" in clip:
                clip["Color"] = argb_hex(clip["Color"])
            else:
                clip["Color"] = "0xffffffff"

            # Keep MotionPlatformSpecifics as dict-key format (engine expects this for proper Kinect/Camera tracking)
            if "MotionPlatformSpecifics" in clip:
                mps = {}
                for platform, pdata in clip["MotionPlatformSpecifics"].items():
                    mps[platform] = remove_class(pdata)
                clip["MotionPlatformSpecifics"] = mps

    # --- Degenerate TrackId normalization ---
    # When every clip has a unique TrackId, group by __class instead
    if len(track_ids) == len(clips) and len(clips) > 1:
        track_ids = []
        class_ids = {}
        for clip in clips:
            clip_class = _get(clip, "__class", "")
            key = clip_class if clip_class else ""
            if key not in class_ids:
                # Deterministic ID from class name (instead of random)
                class_ids[key] = hash(key) & 0xFFFFFFFF
            clip["TrackId"] = class_ids[key]
            if class_ids[key] not in track_ids:
                track_ids.append(class_ids[key])

    # --- Cinematics-specific processing ---
    if tape_type == "cinematics":
        for clip in clips:
            # Resolve ActorIndices -> ActorPaths
            if "ActorIndices" in clip and "ActorPaths" in tape:
                resolved = []
                for idx in clip["ActorIndices"]:
                    if idx < len(tape["ActorPaths"]):
                        resolved.append(tape["ActorPaths"][idx])
                clip["ActorPaths"] = val_array(resolved)
                del clip["ActorIndices"]

            # Process curves
            clip_class = _get(clip, "__class", "")
            if clip_class in CINEMATIC_CURVE_MAP:
                for curve_key in CINEMATIC_CURVE_MAP[clip_class]:
                    if curve_key in clip:
                        clip[curve_key] = _process_curve(clip[curve_key])

        # Remove top-level ActorPaths (already resolved into clips)
        tape.pop("ActorPaths", None)

    # --- Build Tracks array ---
    tracks = []
    for tid in track_ids:
        tracks.append({"TapeTrack": {"id": tid}})
    tape["Tracks"] = tracks

    # --- Serialize ---
    # PRESERVE_KEYS defends against regression if remove_falsy is ever made recursive
    PRESERVE_KEYS = [
        "Id", "TrackId", "IsActive", "StartTime", "Duration",
        "GoldMove", "CoachId", "MoveType", "Color",
        "TapeClock", "TapeBarCount", "FreeResourcesAfterPlay",
        "ScoringMode", "ScoreSmoothing", "ScoreScale",
        "LowThreshold", "HighThreshold", "SoundwichEvent"
    ]
    processed = remove_falsy(remove_class(tape), excluded_keys=PRESERVE_KEYS)
    return "params =" + dict_to_lua(processed)


# ---------------------------------------------------------------------------
# Ambient sound processing
# ---------------------------------------------------------------------------

def process_ambient_sound(json_data, map_name, amb_filename):
    """
    Process an ambient sound .tpl.ckd file.

    Args:
        json_data: Parsed JSON dict from the ambient .tpl.ckd
        map_name: The map codename (e.g. "Starships")
        amb_filename: Original filename (e.g. "amb_something.tpl.ckd")

    Returns:
        tuple: (ilu_content, tpl_content, audio_file_paths)
    """
    sound_list = json_data['COMPONENTS'][0]['soundList']
    # Collect referenced audio file paths before wrapping in VAL dicts
    audio_file_paths = []
    for entry in sound_list:
        for f in entry.get('files', []):
            audio_file_paths.append(f)
    files = []
    for f in sound_list[0].get('files', []):
        files.append({"VAL": f})
    sound_list[0]['files'] = files
    processed = remove_class(sound_list)
    lua_str = dict_to_lua(processed)

    ilu_name = amb_filename.replace('.tpl.ckd', '.ilu')

    ilu_content = (
        'DESCRIPTOR =' + lua_str +
        '\nappendTable(component.SoundComponent_Template.soundList,DESCRIPTOR)'
    )

    tpl_content = (
        f'params=\n{{\n\tNAME="Actor_Template",\n\tActor_Template=\n\t{{\n'
        f'\t\tCOMPONENTS=\n\t\t{{\n\t\t}}\n\t}}\n}}\n'
        f'includeReference("EngineData/Misc/Components/SoundComponent.ilu")\n'
        f'includeReference("world/maps/{map_name}/audio/amb/{ilu_name}")'
    )

    return ilu_content, tpl_content, audio_file_paths
