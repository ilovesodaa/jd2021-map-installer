"""
Shared utilities for converting UbiArt JSON data to Lua format.

Provides JSON-to-Lua serialization, CKD file loading, color conversion,
class/property transforms, and a Vector2D type for cinematic curves.
"""

import json
import os


class Vector2D:
    """Represents a 2D coordinate that serializes as vector2dNew(x,y) in Lua."""
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)

    def __repr__(self):
        return f"vector2dNew({self.x},{self.y})"


# ---------------------------------------------------------------------------
# CKD loading
# ---------------------------------------------------------------------------

def load_ckd_json(path):
    """Read a .ckd file (binary JSON with trailing null bytes) and return
    the parsed Python object."""
    with open(path, "rb") as fh:
        raw = fh.read().rstrip(b"\0")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# UbiArt transforms
# ---------------------------------------------------------------------------

def color_to_hex(argb):
    """Convert an [a, r, g, b] float list (0.0–1.0 each) to a hex string
    like ``0xRRGGBBAA``."""
    if (
        isinstance(argb, list)
        and len(argb) == 4
        and all(isinstance(c, (int, float)) for c in argb)
    ):
        a = int(argb[0] * 255)
        r = int(argb[1] * 255)
        g = int(argb[2] * 255)
        b = int(argb[3] * 255)
        return f"0x{r:02X}{g:02X}{b:02X}{a:02X}"
    return "0xFFFFFFFF"


def transform_classes(data):
    """Recursively rewrite ``{"__class": "Foo", key: val, ...}`` into
    ``{"NAME": "Foo", "Foo": {key: val, ...}}``."""
    if isinstance(data, dict):
        if "__class" in data:
            cls = data["__class"]
            inner = {k: transform_classes(v)
                     for k, v in data.items() if k != "__class"}
            return {"NAME": cls, cls: inner}
        return {k: transform_classes(v) for k, v in data.items()}
    if isinstance(data, list):
        return [transform_classes(item) for item in data]
    return data


def strip_empty(data, keep=()):
    """Remove dict keys whose values are falsy (0, 0.0, False, '', [], {},
    None) unless the key appears in *keep*.  Recurses into lists."""
    _falsy = {"", 0, 0.0, False, None}

    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in keep or (v not in _falsy and v != {} and v != []):
                out[k] = v
        return out
    if isinstance(data, list):
        return [strip_empty(item, keep) for item in data]
    return data


def to_val_list(items):
    """``[a, b]`` → ``[{"VAL": a}, {"VAL": b}]``"""
    return [{"VAL": v} for v in items]


def to_key_val(mapping):
    """``{"k": "v", ...}`` → ``[{"KEY": "k", "VAL": "v"}, ...]``"""
    return [{"KEY": k, "VAL": v} for k, v in mapping.items()]


def get_case_insensitive(d, key, default=None):
    """Look up *key* in *d* case-insensitively."""
    lower_map = {k.lower(): v for k, v in d.items()}
    return lower_map.get(key.lower(), default)


# ---------------------------------------------------------------------------
# JSON → Lua serializer
# ---------------------------------------------------------------------------

def to_lua(data, indent=0):
    """Serialize a Python object into a UbiArt-compatible Lua string."""
    indent += 1
    nl = "\n" + "\t" * indent   # newline + indentation for children
    up = "\n" + "\t" * (indent - 1)  # newline + indentation for closing brace

    if isinstance(data, dict):
        if not data:
            return " {}"
        parts = []
        items = list(data.items())
        prev_key = None
        for key, value in items:
            # ENUM_ keys emit a Lua comment after the previous line
            if prev_key is not None and key == f"ENUM_{prev_key}":
                parts.append(f" -- {value}")
            else:
                parts.append(f"{nl}{key} ={to_lua(value, indent)},")
            prev_key = key
        return up + "{" + "".join(parts) + up + "}"

    if isinstance(data, list):
        if not data:
            return " {}"
        parts = []
        for item in data:
            if isinstance(item, (dict, list)):
                parts.append(f"{to_lua(item, indent)},")
            else:
                parts.append(f"{nl}{_scalar(item)},")
        return up + "{" + "".join(parts) + up + "}"

    return " " + _scalar(data)


def _scalar(value):
    """Format a single scalar value for Lua output."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        return f'"{escaped}"'
    if isinstance(value, Vector2D):
        return repr(value)
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, int):
        return str(value)
    return "nil"
