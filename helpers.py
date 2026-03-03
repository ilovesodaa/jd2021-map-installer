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
        UnicodeDecodeError: If the content cannot be decoded as UTF-8.
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
        logger.error("Failed to parse CKD JSON from %s: %s", file_path, e)
        raise
