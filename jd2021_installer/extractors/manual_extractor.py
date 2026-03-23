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

    def __init__(
        self,
        codename: str,
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
        self._root_dir = Path(root_dir) if root_dir else None
        self._files = files or {}
        self._dirs = dirs or {}

    def get_codename(self) -> Optional[str]:
        return self._codename or "UnknownMap"

    def extract(self, output_dir: Path) -> Path:
        """Copy manual files to the extraction output_dir.

        If a root folder was provided and no granular files were given,
        we can simply return the root folder as the extracted data.
        Otherwise, we assemble a clean directory.
        """
        # If there are NO explicit files/dirs configured but there IS a root,
        # just yield the root directly as the extraction source for the normalizer.
        if self._root_dir and self._root_dir.is_dir() and not any(self._files.values()) and not any(self._dirs.values()):
            logger.info("Manual extraction using root dir directly: %s", self._root_dir)
            return self._root_dir

        if not self._codename:
            raise DownloadError("Codename is required for manual mode.")

        map_output_dir = output_dir / self._codename
        map_output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Assembling manual files into %s", map_output_dir)

        # Base case: copy everything from root if provided, then overwrite with specific files
        if self._root_dir and self._root_dir.is_dir():
            logger.info("Copying contents of root dir %s", self._root_dir)
            shutil.copytree(self._root_dir, map_output_dir, dirs_exist_ok=True)

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
