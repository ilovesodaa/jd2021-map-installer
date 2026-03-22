"""Abstract base class for all extractors.

Each extractor is responsible for fetching raw map data from a specific
source (web, IPK archive, etc.) and placing it into a temporary directory
for the normalizer to process.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jd2021.extractors.base")


class BaseExtractor(ABC):
    """Abstract interface for map data extractors.

    Subclasses implement :meth:`extract` which populates a directory
    with raw CKD files and media assets.  The normalizer then processes
    this directory into a ``NormalizedMapData``.
    """

    @abstractmethod
    def extract(self, output_dir: Path) -> Path:
        """Extract map data into ``output_dir``.

        Args:
            output_dir: Directory to write extracted files into.

        Returns:
            Path to the directory containing extracted files
            (may be ``output_dir`` itself or a subdirectory).

        Raises:
            ExtractionError: If extraction fails.
        """
        ...

    @abstractmethod
    def get_codename(self) -> Optional[str]:
        """Return the map codename if known, else None."""
        ...
