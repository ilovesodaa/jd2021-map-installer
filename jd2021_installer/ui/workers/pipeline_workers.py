"""QObject-based workers for background processing via QThread.

Each worker encapsulates a heavy operation (extraction, normalization,
installation, media preview) and communicates with the GUI through
Qt signals exclusively — never touching widgets directly.

Usage (in controller):
    worker = InstallMapWorker(map_data, target_dir)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.models import NormalizedMapData
from jd2021_installer.extractors.base import BaseExtractor
from jd2021_installer.installers.game_writer import write_game_files
from jd2021_installer.parsers.normalizer import normalize

logger = logging.getLogger("jd2021.ui.workers")


class ExtractAndNormalizeWorker(QObject):
    """Extract map data and normalize it in a background thread."""

    progress = pyqtSignal(int)          # 0-100
    status = pyqtSignal(str)            # human-readable status message
    error = pyqtSignal(str)             # error message
    finished = pyqtSignal(object)       # NormalizedMapData or None

    def __init__(
        self,
        extractor: BaseExtractor,
        output_dir: Path,
        codename: Optional[str] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._extractor = extractor
        self._output_dir = output_dir
        self._codename = codename

    def run(self) -> None:
        try:
            self.status.emit("Extracting map data...")
            self.progress.emit(10)
            extracted_dir = self._extractor.extract(self._output_dir)

            codename = self._codename or self._extractor.get_codename()

            self.status.emit("Normalizing map data...")
            self.progress.emit(50)
            map_data = normalize(extracted_dir, codename)

            self.progress.emit(100)
            self.status.emit("Normalization complete.")
            self.finished.emit(map_data)

        except Exception as e:
            logger.error("ExtractAndNormalize failed: %s\n%s", e, traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(None)


class InstallMapWorker(QObject):
    """Install a normalized map into the game directory."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(bool)         # success / failure

    def __init__(
        self,
        map_data: NormalizedMapData,
        target_dir: Path,
        config: Optional[AppConfig] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._map_data = map_data
        self._target_dir = target_dir
        self._config = config

    def run(self) -> None:
        try:
            self.status.emit(f"Installing {self._map_data.codename}...")
            self.progress.emit(20)

            write_game_files(self._map_data, self._target_dir, self._config)

            self.progress.emit(100)
            self.status.emit("Installation complete!")
            self.finished.emit(True)

        except Exception as e:
            logger.error("InstallMap failed: %s\n%s", e, traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(False)
