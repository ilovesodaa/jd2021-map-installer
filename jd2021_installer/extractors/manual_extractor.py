"""Manual Extractor for JD2021 Map Installer.

Assembles an extraction directory from a collection of manually-specified
local file paths (audio, video, musictrack, tapes, assets) provided by
the user via the UI.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict, Optional

from jd2021_installer.core.exceptions import DownloadError
from jd2021_installer.extractors.base import BaseExtractor

logger = logging.getLogger("jd2021.extractors.manual")


class ManualExtractor(BaseExtractor):
    """Assembles a map directory from manually specified paths."""

    def _resolve_root_dir(self, root: Path) -> Path:
        """Apply source-type specific root resolution for manual mode."""
        return root

    def is_ipk_source(self) -> bool:
        """True when manual mode is operating on unpacked IPK content."""
        return self._source_type == "ipk"

    def _validate_ipk_root(self, root: Path) -> None:
        """Validate codename/root consistency for manual IPK roots."""
        if not self.is_ipk_source():
            return

        world_maps = root / "world" / "maps"
        if not world_maps.is_dir():
            return

        candidates = sorted(d.name for d in world_maps.iterdir() if d.is_dir())
        if not candidates:
            return

        self.bundle_maps = candidates

        if not self._codename:
            self._codename = candidates[0]
            if len(candidates) > 1:
                logger.warning(
                    "Manual IPK source contains multiple maps; auto-selected first candidate '%s'.",
                    self._codename,
                )
            else:
                logger.info("Inferred manual IPK codename from root: %s", self._codename)
            return

        lower_candidates = {c.lower() for c in candidates}
        if self._codename.lower() not in lower_candidates:
            fallback = candidates[0]
            logger.warning(
                "Manual IPK codename '%s' does not match discovered maps (%s); using '%s'.",
                self._codename,
                ", ".join(candidates),
                fallback,
            )
            self._codename = fallback

    def __init__(
        self,
        codename: str,
        source_type: str = "jdu",
        root_dir: Optional[str] = None,
        files: Optional[Dict[str, str]] = None,
        dirs: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialize the extractor.

        Args:
            codename: The name of the map.
            root_dir: Optional base directory if files are already bundled.
            files:    Dict of logical name → absolute file path (e.g. dict(audio="...", dtape="...")).
            dirs:     Dict of logical name → absolute directory path for assets (moves, pictos, etc).
        """
        self._codename = codename.strip() if codename else ""
        self._source_type = source_type.strip().lower() if source_type else "jdu"
        self._root_dir = Path(root_dir) if root_dir else None
        self._files = files or {}
        self._dirs = dirs or {}
        self.bundle_maps: list[str] = []

    def get_codename(self) -> Optional[str]:
        return self._codename or None

    def extract(self, output_dir: Path) -> Path:
        """Copy manual files to the extraction output_dir.

        If a root folder was provided and no granular files were given,
        we can simply return the root folder as the extracted data.
        Otherwise, we assemble a clean directory.
        """
        # If there are NO explicit files/dirs configured but there IS a root,
        # just yield the root directly as the extraction source for the normalizer.
        resolved_root = self._resolve_root_dir(self._root_dir) if self._root_dir and self._root_dir.is_dir() else None
        if resolved_root:
            self._validate_ipk_root(resolved_root)

        if resolved_root and not any(self._files.values()) and not any(self._dirs.values()):
            logger.info(
                "Manual extraction using root dir directly (%s): %s",
                self._source_type,
                resolved_root,
            )
            return resolved_root

        if not self._codename:
            raise DownloadError("Codename is required for manual mode.")

        map_output_dir = output_dir / self._codename
        map_output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Assembling manual files into %s (source_type=%s)", map_output_dir, self._source_type)

        # Base case: copy everything from root if provided, then overwrite with specific files
        if resolved_root:
            logger.info("Copying contents of root dir %s", resolved_root)
            shutil.copytree(resolved_root, map_output_dir, dirs_exist_ok=True)

        # Copy specific files
        for ftype, path_str in self._files.items():
            if not path_str:
                continue
            src = Path(path_str)
            if src.is_file():
                dest = map_output_dir / src.name
                shutil.copy2(src, dest)
                logger.info("Copied manual file: %s", src.name)

        # Copy specific asset directories
        for dtype, dpath_str in self._dirs.items():
            if not dpath_str:
                continue
            src_dir = Path(dpath_str)
            if src_dir.is_dir():
                dest_dir = map_output_dir / src_dir.name
                shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)
                logger.info("Copied manual dir: %s", src_dir.name)

        return map_output_dir
