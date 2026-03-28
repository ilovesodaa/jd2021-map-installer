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


def validate_ipk_magic(target_file: str | Path) -> None:
    """Validate IPK magic bytes before expensive extraction work.

    Raises:
        IPKExtractionError: If the file is missing or does not start with IPK magic.
    """
    target_path = Path(target_file)
    if not target_path.exists():
        raise IPKExtractionError(f"IPK file not found: {target_path}")

    with open(target_path, "rb") as f:
        magic = f.read(4)
    if magic != _IPK_MAGIC:
        raise IPKExtractionError("Not a valid IPK file (bad magic bytes)")


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


def extract_ipk(target_file: str | Path, output_dir: str | Path | None = None) -> Path:
    """Extract an IPK archive to the given output directory.

    Args:
        target_file: Path to the .ipk file.
        output_dir:  Directory to extract into. If omitted, defaults to
                 ``target_file.stem`` (V1-compatible behavior).

    Returns:
        Path to the output directory.

    Raises:
        IPKExtractionError: If extraction fails.
    """
    target_file = Path(target_file)
    output_path = Path(output_dir) if output_dir is not None else Path(target_file.stem)

    validate_ipk_magic(target_file)

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
            codenames_found = set()
            extracted_files = 0

            for k, chunk in enumerate(file_chunks):
                path_ori = chunk["path_name"]["value"].decode().lower().replace('\\', '/')
                if "world/maps/" in path_ori:
                    after_maps = path_ori.split("world/maps/")[1]
                    parts = after_maps.split("/")
                    if parts and parts[0]:
                        codenames_found.add(parts[0])

                if k % 100 == 0:
                    status = f"file {k + 1}/{num_files}"
                    if codenames_found:
                        status += f" (maps: {', '.join(sorted(codenames_found))})"
                    logger.info("IPK: Extracting %s...", status)

                offset = _unpack(chunk["offset"]["value"])
                data_size = _unpack(chunk["size"]["value"])

                path_ori_raw = chunk["path_name"]["value"].decode()
                if os.path.basename(path_ori_raw) == path_ori_raw:
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
                extracted_files += 1

        logger.info("IPK: Extracted %d/%d files to %s", extracted_files, num_files, output_path)
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
            
            # V1 Parity: Support both standard (world/maps/) and legacy (world/jd20XX/) structures
            for _ in range(num_files):
                fheader = _get_file_header()
                for v in fheader:
                    size = fheader[v]["size"]
                    if v == "path_name":
                        size = _unpack(fheader["path_size"]["value"])
                    if v == "file_name":
                        size = _unpack(fheader["name_size"]["value"])
                    fheader[v]["value"] = f.read(size)
                
                raw_path = fheader["path_name"]["value"].decode(errors="ignore").replace('\\', '/')
                raw_file = fheader["file_name"]["value"].decode(errors="ignore").replace('\\', '/')

                candidates = []
                if "/" in raw_path:
                    candidates.append(raw_path)
                if "/" in raw_file:
                    candidates.append(raw_file)
                if not candidates:
                    candidates = [raw_path, raw_file]

                for candidate in candidates:
                    path_ori = candidate.lower()
                    if "world/maps/" in path_ori:
                        after_maps = path_ori.split("world/maps/")[1]
                        parts = [p for p in after_maps.split("/") if p]
                        if parts:
                            root_dirs.add(parts[0])
                        continue

                    if "world/jd" in path_ori:
                        parts = [p for p in path_ori.split("/") if p]
                        try:
                            idx = parts.index("world")
                            if idx + 2 < len(parts) and parts[idx + 1].startswith("jd"):
                                root_dirs.add(parts[idx + 2])
                        except (ValueError, IndexError):
                            pass

            # V1 Parity: Filter out engine-specific internal folders that are not maps
            ignore_list = {"cache", "common", "etc", "enginedata", "audio", "videoscoach", "localization"}
            return sorted({d for d in root_dirs if d and not d.startswith(".") and d.lower() not in ignore_list})

    except Exception as exc:
        logger.warning("Fast inspect failed for IPK %s: %s", target_file, exc)
        return []




def _detect_maps_in_dir(directory: Path) -> list[str]:
    """Scan a directory for map codenames using the UbiArt structure.
    
    Supports both standard (world/maps/) and legacy (world/jd20XX/) layouts.
    """
    import re
    codenames = set()
    
    # 1. Standard layout: world/maps/<codename>/
    maps_dirs = list(directory.rglob("world/maps"))
    for maps_dir in maps_dirs:
        if maps_dir.is_dir():
            for entry in maps_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith('.'):
                    codenames.add(entry.name)
                    
    # 2. Legacy layout: world/jd20XX/<codename>/
    for world_dir in directory.rglob("world"):
        if world_dir.is_dir():
            for jd_dir in world_dir.iterdir():
                if jd_dir.is_dir() and re.match(r"jd\d+", jd_dir.name, re.I):
                    for entry in jd_dir.iterdir():
                        if entry.is_dir() and not entry.name.startswith('.'):
                            codenames.add(entry.name)
                                
    ignore_list = {"cache", "common", "etc", "enginedata", "audio", "videoscoach", "localization"}
    return sorted({c for c in codenames if c and c.lower() not in ignore_list})


class ArchiveIPKExtractor(BaseExtractor):
    """Extractor for IPK archive files."""

    def __init__(self, ipk_path: str | Path) -> None:
        self._ipk_path = Path(ipk_path)
        self._codename: Optional[str] = None
        self.bundle_maps: list[str] = []

    def extract(self, output_dir: Path) -> Path:
        import re
        result = extract_ipk(self._ipk_path, output_dir)
        
        # V1 Parity: Detect maps from filesystem structure after extraction
        actual_maps = _detect_maps_in_dir(result)
        
        # Fast inspect as a secondary source of truth
        headers_maps = inspect_ipk(self._ipk_path)
        
        # Combine and prioritize
        discovered = sorted(set(actual_maps) | set(headers_maps))
        self.bundle_maps = discovered
        
        if len(discovered) == 1:
            self._codename = discovered[0]
            logger.info("Inferred codename: %s", self._codename)
        elif len(discovered) > 1:
            logger.info("Multiple maps discovered in IPK: %s", ", ".join(discovered))
            # Try to match the codename from the IPK filename
            base = self._ipk_path.stem
            stem = re.sub(r"_(x360|durango|scarlett|nx|orbis|prospero|pc)$", "", base, flags=re.IGNORECASE)
            
            matches = [m for m in discovered if m.lower() == stem.lower()]
            if matches:
                self._codename = matches[0]
                logger.info("Matched bundle codename from filename: %s", self._codename)
            else:
                self._codename = discovered[0]
                logger.info("Auto-selected first candidate for bundle: %s", self._codename)
        else:
            # Fallback to filename inference if no maps found in structure
            base = self._ipk_path.stem
            stem = re.sub(r"_(x360|durango|scarlett|nx|orbis|prospero|pc)$", "", base, flags=re.IGNORECASE)
            self._codename = stem
            logger.info("No maps found in structure, using fallback from filename: %s", self._codename)
            
        return result

    def get_codename(self) -> Optional[str]:
        return self._codename

    def get_source_dir(self) -> Path:
        """Return the folder that contains the selected .ipk file."""
        return self._ipk_path.parent
