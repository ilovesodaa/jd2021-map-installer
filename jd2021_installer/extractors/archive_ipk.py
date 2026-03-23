"""IPK archive extractor.

Extracts .ipk files (Ubisoft's proprietary archive format used on
console mods) into a temporary directory for normalizer processing.

Refactored from the original ``ipk_unpack.py`` with path-traversal
protection and proper error handling.
"""

from __future__ import annotations

import logging
import os
import struct
import zlib
import lzma
from pathlib import Path
from typing import Optional

from jd2021_installer.core.exceptions import IPKExtractionError
from jd2021_installer.extractors.base import BaseExtractor

logger = logging.getLogger("jd2021.extractors.archive_ipk")

# Big-endian for IPK format
_ENDIAN = ">"
_STRUCT_SIGNS = {1: "c", 2: "H", 4: "I", 8: "Q"}

_IPK_MAGIC = b"\x50\xEC\x12\xBA"


def _unpack(data: bytes) -> int:
    """Unpack a big-endian integer of 1/2/4/8 bytes."""
    return struct.unpack(_ENDIAN + _STRUCT_SIGNS[len(data)], data)[0]


def _read_header_fields(f, template: dict) -> dict:
    """Read header fields from file into dict with 'value' keys."""
    result = {k: dict(v) for k, v in template.items()}
    for v in result.values():
        v["value"] = f.read(v["size"])
    return result


_IPK_HEADER_TEMPLATE = {
    "magic": {"size": 4},
    "version": {"size": 4},
    "platformsupported": {"size": 4},
    "base_offset": {"size": 4},
    "num_files": {"size": 4},
    "compressed": {"size": 4},
    "binaryscene": {"size": 4},
    "binarylogic": {"size": 4},
    "datasignature": {"size": 4},
    "enginesignature": {"size": 4},
    "engineversion": {"size": 4},
    "num_files2": {"size": 4},
}


def _get_file_header() -> dict:
    return {
        "numOffset": {"size": 4},
        "size": {"size": 4},
        "compressed_size": {"size": 4},
        "time_stamp": {"size": 8},
        "offset": {"size": 8},
        "name_size": {"size": 4},
        "file_name": {"size": 0},
        "path_size": {"size": 4},
        "path_name": {"size": 4},
        "checksum": {"size": 4},
        "flag": {"size": 4},
    }


def extract_ipk(target_file: str | Path, output_dir: str | Path) -> Path:
    """Extract an IPK archive to the given output directory.

    Args:
        target_file: Path to the .ipk file.
        output_dir:  Directory to extract into.

    Returns:
        Path to the output directory.

    Raises:
        IPKExtractionError: If extraction fails.
    """
    target_file = Path(target_file)
    output_path = Path(output_dir)

    if not target_file.exists():
        raise IPKExtractionError(f"IPK file not found: {target_file}")

    try:
        output_path.mkdir(parents=True, exist_ok=True)

        with open(target_file, "rb") as f:
            ipk_header = _read_header_fields(f, _IPK_HEADER_TEMPLATE)

            if ipk_header["magic"]["value"] != _IPK_MAGIC:
                raise IPKExtractionError("Not a valid IPK file (bad magic bytes)")

            num_files = _unpack(ipk_header["num_files"]["value"])
            logger.info("IPK: Found %d files...", num_files)

            file_chunks = []
            for _ in range(num_files):
                fheader = _get_file_header()
                for v in fheader:
                    size = fheader[v]["size"]
                    if v == "path_name":
                        size = _unpack(fheader["path_size"]["value"])
                    if v == "file_name":
                        size = _unpack(fheader["name_size"]["value"])
                    fheader[v]["value"] = f.read(size)
                file_chunks.append(fheader)

            base_offset = _unpack(ipk_header["base_offset"]["value"])
            created_dirs = set()

            for k, chunk in enumerate(file_chunks):
                if k % 100 == 0:
                    logger.info("IPK: Extracting file %d/%d...", k + 1, num_files)

                offset = _unpack(chunk["offset"]["value"])
                data_size = _unpack(chunk["size"]["value"])

                path_ori = chunk["path_name"]["value"].decode()
                if os.path.basename(path_ori) == path_ori:
                    file_path = output_path / chunk["file_name"]["value"].decode()
                    file_name = chunk["path_name"]["value"].decode()
                else:
                    file_path = output_path / chunk["path_name"]["value"].decode()
                    file_name = chunk["file_name"]["value"].decode()

                # Path traversal protection
                resolved = os.path.normpath(os.path.join(str(file_path), file_name))
                if not resolved.startswith(str(output_path)):
                    logger.warning("Skipping path-traversal entry: %s", resolved)
                    continue

                f.seek(offset + base_offset)
                if file_path not in created_dirs:
                    file_path.mkdir(parents=True, exist_ok=True)
                    created_dirs.add(file_path)

                with open(file_path / file_name, "wb") as ff:
                    raw_data = f.read(data_size)
                    try:
                        decompressed = zlib.decompress(raw_data)
                    except zlib.error:
                        try:
                            decompressed = lzma.decompress(raw_data)
                        except lzma.LZMAError:
                            decompressed = raw_data
                    ff.write(decompressed)

        logger.info("IPK: Extracted %d files to %s", num_files, output_path)
        return output_path

    except IPKExtractionError:
        raise
    except Exception as exc:
        raise IPKExtractionError(f"Failed to extract IPK: {exc}") from exc


def inspect_ipk(target_file: str | Path) -> list[str]:
    """Fast scan of the IPK to discover top-level directories (maps).
    
    Reads only headers without decompressing data.
    """
    target_file = Path(target_file)
    if not target_file.exists():
        return []

    try:
        with open(target_file, "rb") as f:
            ipk_header = _read_header_fields(f, _IPK_HEADER_TEMPLATE)
            if ipk_header["magic"]["value"] != _IPK_MAGIC:
                return []

            num_files = _unpack(ipk_header["num_files"]["value"])
            root_dirs = set()
            
            for _ in range(num_files):
                fheader = _get_file_header()
                for v in fheader:
                    size = fheader[v]["size"]
                    if v == "path_name":
                        size = _unpack(fheader["path_size"]["value"])
                    if v == "file_name":
                        size = _unpack(fheader["name_size"]["value"])
                    fheader[v]["value"] = f.read(size)
                
                # Check path name to see if it belongs to a folder
                path_ori = fheader["path_name"]["value"].decode().lower().replace('\\', '/')
                # Look for world/maps/<codename>
                if "world/maps/" in path_ori:
                    # Extract the codename
                    after_maps = path_ori.split("world/maps/")[1]
                    parts = after_maps.split("/")
                    if parts and parts[0]:
                        root_dirs.add(parts[0])

            # Filter out random junk
            return sorted({d for d in root_dirs if d and not d.startswith(".")})

    except Exception as exc:
        logger.warning("Fast inspect failed for IPK %s: %s", target_file, exc)
        return []




class ArchiveIPKExtractor(BaseExtractor):
    """Extractor for IPK archive files."""

    def __init__(self, ipk_path: str | Path) -> None:
        self._ipk_path = Path(ipk_path)
        self._codename: Optional[str] = None

    def extract(self, output_dir: Path) -> Path:
        result = extract_ipk(self._ipk_path, output_dir)
        # Try to infer codename from directory contents, ignoring generic structure folders
        for item in output_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                name_low = item.name.lower()
                if name_low in ("world", "data", "cache", "temp", "_extraction"):
                    continue
                self._codename = item.name
                break
                break
        return result

    def get_codename(self) -> Optional[str]:
        return self._codename
