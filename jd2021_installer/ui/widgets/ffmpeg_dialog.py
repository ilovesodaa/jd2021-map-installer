"""FFmpeg Auto-Installer Dialog.

Handles downloading and extracting FFmpeg/FFplay binaries if missing.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Optional

import requests
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QMessageBox,
)

logger = logging.getLogger("jd2021.ui.widgets.ffmpeg_dialog")


# Standard FFmpeg build for Windows (gyan.dev)
FFMPEG_URL_WIN = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
# Placeholder for other platforms if needed
FFMPEG_URL_LINUX = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

class DownloadWorker(QObject):
    """Background worker for downloading and extracting FFmpeg."""
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, target_dir: Path) -> None:
        super().__init__()
        self._target_dir = target_dir

    def run(self) -> None:
        try:
            if sys.platform == "win32":
                self._run_windows()
            elif sys.platform.startswith("linux"):
                self._run_linux()
            else:
                self.error.emit(
                    "Auto-install is only supported on Windows and Linux. "
                    "Please install FFmpeg via your package manager."
                )
                self.finished.emit(False)
        except Exception as e:
            logger.error("FFmpeg install failed: %s", e)
            self.error.emit(str(e))
            self.finished.emit(False)

    def _run_windows(self) -> None:
        self.status.emit("Downloading FFmpeg Essentials...")
        temp_zip = self._target_dir / "ffmpeg.zip"

        response = requests.get(FFMPEG_URL_WIN, stream=True, timeout=30)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))

        downloaded = 0
        with open(temp_zip, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        self.progress.emit(int((downloaded / total_size) * 80))

        self.status.emit("Extracting binaries...")
        self.progress.emit(85)

        extract_temp = self._target_dir / "_extract"
        extract_temp.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(extract_temp)

        required_bins = {"ffmpeg.exe", "ffplay.exe", "ffprobe.exe"}
        binaries_found = set()
        for p in extract_temp.rglob("*.exe"):
            lower_name = p.name.lower()
            if lower_name in required_bins:
                shutil.move(str(p), str(self._target_dir / p.name))
                binaries_found.add(lower_name)

        shutil.rmtree(extract_temp, ignore_errors=True)
        if temp_zip.exists():
            temp_zip.unlink()

        missing_bins = sorted(required_bins - binaries_found)
        if not missing_bins:
            self.status.emit("Installation complete!")
            self.progress.emit(100)
            self.finished.emit(True)
        else:
            self.error.emit(
                "Downloaded archive is missing required binaries: "
                + ", ".join(missing_bins)
            )
            self.finished.emit(False)

    def _run_linux(self) -> None:
        self.status.emit("Downloading FFmpeg static build for Linux...")
        temp_archive = self._target_dir / "ffmpeg-linux.tar.xz"

        response = requests.get(FFMPEG_URL_LINUX, stream=True, timeout=30)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))

        downloaded = 0
        with open(temp_archive, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        self.progress.emit(int((downloaded / total_size) * 80))

        self.status.emit("Extracting binaries...")
        self.progress.emit(85)

        # The static build contains ffmpeg and ffprobe; ffplay is not included.
        required_bins = {"ffmpeg", "ffprobe"}
        binaries_found = set()

        with tarfile.open(temp_archive, "r:xz") as tf:
            for member in tf.getmembers():
                name = os.path.basename(member.name)
                if name in required_bins and member.isfile():
                    member.name = name  # strip directory prefix
                    tf.extract(member, path=self._target_dir)
                    dest = self._target_dir / name
                    dest.chmod(dest.stat().st_mode | 0o111)
                    binaries_found.add(name)

        if temp_archive.exists():
            temp_archive.unlink()

        missing_bins = sorted(required_bins - binaries_found)
        if not missing_bins:
            self.status.emit("Installation complete!")
            self.progress.emit(100)
            self.finished.emit(True)
        else:
            self.error.emit(
                "Downloaded archive is missing required binaries: "
                + ", ".join(missing_bins)
            )
            self.finished.emit(False)

class FFmpegInstallDialog(QDialog):
    """Dialog showing progress of FFmpeg installation."""

    def __init__(self, target_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self._target_dir = target_dir
        self.setWindowTitle("Installing FFmpeg")
        self.setMinimumSize(420, 180)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        
        self.lbl_status = QLabel("Preparing to download...")
        layout.addWidget(self.lbl_status)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        layout.addWidget(self.btn_cancel)

    @classmethod
    def install(cls, target_dir: Path, parent=None) -> bool:
        """Static entry point to show the dialog and run the install."""
        dlg = cls(target_dir, parent)
        
        worker = DownloadWorker(target_dir)
        thread = QThread()
        worker.moveToThread(thread)
        
        success = [False]
        
        def on_finished(ok):
            success[0] = ok
            if ok:
                dlg.accept()
            else:
                dlg.reject()

        def on_error(msg):
            QMessageBox.critical(dlg, "Installation Error", f"FFmpeg installation failed:\n{msg}")

        thread.started.connect(worker.run)
        worker.status.connect(dlg.lbl_status.setText)
        worker.progress.connect(dlg.progress.setValue)
        worker.error.connect(on_error)
        worker.finished.connect(on_finished)
        
        # Cleanup chain
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        thread.start()
        
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return success[0]
        
        # If cancelled, try to kill thread
        if thread.isRunning():
            thread.terminate()
            thread.wait(1000)
        return False
