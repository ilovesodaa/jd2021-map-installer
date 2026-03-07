"""Shared helper utilities for the JD2021 Map Installer project.

Centralizes duplicated patterns (CKD JSON loading, constants) used across
multiple modules.
"""

import json
import os
from log_config import get_logger

logger = get_logger("helpers")


# ---------------------------------------------------------------------------
# Constants (previously magic numbers scattered across modules)
# ---------------------------------------------------------------------------

TICKS_PER_MS = 48           # UbiArt tick rate: markers[i] / 48 = milliseconds
DISK_SPACE_MIN_MB = 500     # Minimum free space warning threshold
DOWNLOAD_TIMEOUT_S = 60     # Network request timeout in seconds
TOOLTIP_DELAY_MS = 500      # Hover delay before showing tooltips
PREVIEW_FPS = 24            # Frames per second for embedded video preview
PREVIEW_POLL_FRAMES = 6     # Update seek UI every N frames (~250ms at 24fps)
AUDIO_PREVIEW_FADE_S = 2.0  # Default audio preview fade-out duration in seconds
MAX_JD_VERSION = 2021       # Maximum JDVersion the engine supports
MIN_JD_VERSION = 2014       # Minimum JDVersion that JD2021 GameManagerConfig supports


# ---------------------------------------------------------------------------
# Shared file loading
# ---------------------------------------------------------------------------

def load_ckd_json(file_path):
    """Read a CKD file, strip null bytes and whitespace, parse as JSON.

    CKD files from the UbiArt engine often have trailing null bytes and
    whitespace padding.  This function handles both binary and text CKD
    formats consistently.

    Args:
        file_path: Path to the .ckd file.

    Returns:
        Parsed JSON data (dict or list).

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the content is not valid JSON.
        ValueError: If it's an unsupported binary format.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"CKD file not found: {file_path}")

    with open(file_path, 'rb') as f:
        raw = f.read()

    # Strip null bytes (UbiArt CKD padding), then whitespace
    cleaned = raw.replace(b'\x00', b'').strip()

    try:
        return json.loads(cleaned.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.debug("Failed to parse as text JSON, attempting binary parse: %s", e)
        import binary_ckd_parser
        import importlib
        importlib.reload(binary_ckd_parser)
        try:
            return binary_ckd_parser.parse_binary_ckd(file_path)
        except Exception as bin_err:
            logger.error("Failed to parse CKD JSON (both text and binary) from %s: %s | %s", file_path, e, bin_err)
            raise

