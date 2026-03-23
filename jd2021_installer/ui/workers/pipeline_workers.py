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
            map_output_dir = self._extractor.extract(self._output_dir)

            codename = self._codename or self._extractor.get_codename()

            self.status.emit("Normalizing map data...")
            self.progress.emit(50)
            map_data = normalize(map_output_dir, codename)

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
            codename = self._map_data.codename
            self.status.emit(f"Installing {codename}...")
            self.progress.emit(10)

            # Resolve target directory: game_dir / World / MAPS / <codename>
            map_target = self._target_dir / "World" / "MAPS" / codename
            map_target.mkdir(parents=True, exist_ok=True)

            # 1. Write all UbiArt config files
            self.status.emit("Writing game configuration files...")
            self.progress.emit(20)
            write_game_files(self._map_data, map_target, self._config)

            # 2. Copy media files (video + audio) into game directory
            media = self._map_data.media
            if media.video_path and media.video_path.exists():
                self.status.emit("Copying video file...")
                self.progress.emit(40)
                from jd2021_installer.installers.media_processor import copy_video
                video_dst = map_target / "VideosCoach" / f"{codename}.webm"
                copy_video(media.video_path, video_dst)

                # Also copy map preview video if available
                if media.map_preview_video and media.map_preview_video.exists():
                    preview_dst = map_target / "VideosCoach" / f"{codename}_MapPreview.webm"
                    copy_video(media.map_preview_video, preview_dst)

            if media.audio_path and media.audio_path.exists():
                self.status.emit("Copying/Transcoding audio file...")
                self.progress.emit(60)
                from jd2021_installer.installers.media_processor import copy_audio
                # Force .wav for legacy PC engine support
                audio_dst = map_target / "Audio" / f"{codename}.wav"
                copy_audio(media.audio_path, audio_dst)

            # 3. Copy cover/coach images to MenuArt/textures
            if media.cover_path and media.cover_path.exists():
                self.status.emit("Copying MenuArt textures...")
                self.progress.emit(70)
                import shutil
                textures_dir = map_target / "MenuArt" / "textures"
                textures_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(media.cover_path, textures_dir / media.cover_path.name)

            for coach_img in media.coach_images:
                if coach_img.exists():
                    import shutil
                    textures_dir = map_target / "MenuArt" / "textures"
                    shutil.copy2(coach_img, textures_dir / coach_img.name)

            # Moves
            if media.moves_dir and media.moves_dir.exists():
                self.status.emit("Integrating cross-platform move data...")
                from jd2021_installer.installers.media_processor import copy_moves
                moves_copied = copy_moves(media.moves_dir, map_target)
                logger.info("Integrated %d move skeleton(s) for %s", moves_copied, codename)
            else:
                logger.info("No 'moves' folder found for %s; autodance may fail.", codename)

            # 4. Register map in SkuScene ISC
            self.status.emit("Registering map in song list...")
            self.progress.emit(85)
            try:
                from jd2021_installer.installers.sku_scene import register_map
                register_map(self._target_dir, codename)
            except Exception as e:
                # Non-fatal: map files are installed, just won't appear in list
                logger.warning("SkuScene registration failed (non-fatal): %s", e)
                self.status.emit(f"Warning: SkuScene registration failed: {e}")

            self.progress.emit(100)
            self.status.emit("Installation complete!")
            self.finished.emit(True)

        except Exception as e:
            logger.error("InstallMap failed: %s\n%s", e, traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(False)


def reprocess_audio(map_data: NormalizedMapData, target_dir: Path, config: Optional[AppConfig] = None) -> None:
    """Rebuild game configuration files to apply updated audio/video offsets.
    
    In V1, this recomputed FFmpeg operations on the physical .ogg file. 
    In V2, offsets are tracked purely in `video_start_time_override`, 
    so we just re-execute write_game_files to rewrite the `.trk` file.
    """
    write_game_files(map_data, target_dir, config)


class ApplyAndFinishWorker(QObject):
    """Safely executes reprocess_audio(), clearing cache and finalizing offsets."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(
        self,
        map_data: NormalizedMapData,
        target_dir: Path,
        cache_dir: Path,
        config: Optional[AppConfig] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._map_data = map_data
        self._target_dir = target_dir
        self._cache_dir = cache_dir
        self._config = config

    def run(self) -> None:
        try:
            self.status.emit("Reprocessing audio offsets...")
            self.progress.emit(30)
            
            # 1. Update configs natively via reprocess_audio
            reprocess_audio(self._map_data, self._target_dir, self._config)
            
            # 2. Clear cache replicating V1's clean logic
            self.status.emit("Clearing downloaded cache...")
            if self._cache_dir.exists():
                import shutil
                shutil.rmtree(self._cache_dir, ignore_errors=True)
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                
            self.progress.emit(100)
            self.status.emit("Sync offsets applied successfully.")
            self.finished.emit(True)
        except Exception as e:
            logger.error("ApplyAndFinish failed: %s\n%s", e, traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(False)


class BatchInstallWorker(QObject):
    """Iterate through a directory and install all discovered maps (folders/IPKs)."""

    progress = pyqtSignal(int)          # overall progress 0-100
    status = pyqtSignal(str)            # status text
    error = pyqtSignal(str)             # error message
    finished = pyqtSignal(bool)         # success flag

    def __init__(
        self,
        batch_source_dir: Path,
        target_game_dir: Path,
        config: AppConfig,
        selected_maps: Optional[set[str]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._source_dir = batch_source_dir
        self._target_dir = target_game_dir
        self._config = config
        self._selected_maps = selected_maps

    def run(self) -> None:
        try:
            self.status.emit("Scanning for maps in batch directory...")
            
            candidates: list[Path] = []
            if self._source_dir and self._source_dir.is_dir():
                for path in self._source_dir.iterdir():
                    if path.is_file() and path.suffix.lower() == ".ipk":
                        candidates.append(path)
                    elif path.is_dir():
                        has_ckd = any(path.rglob("*.ckd"))
                        if has_ckd:
                            candidates.append(path)
            
            total = len(candidates)
            if total == 0:
                self.error.emit("No valid IPK files or map folders found in the selected batch directory.")
                self.finished.emit(False)
                return

            self.status.emit(f"Found {total} map(s) to process.")
            success_count = 0
            
            # Temporary cache for extracted IPKs
            batch_cache = self._config.cache_directory / "_batch_temp"
            batch_cache.mkdir(parents=True, exist_ok=True)

            for i, candidate in enumerate(candidates):
                progress_pct = int((i / total) * 100)
                self.progress.emit(progress_pct)
                
                try:
                    self.status.emit(f"[{i+1}/{total}] Processing {candidate.name}...")
                    
                    map_dir = candidate
                    if candidate.is_file() and candidate.suffix.lower() == ".ipk":
                        # Extract IPK to temp dir
                        from jd2021_installer.extractors.archive_ipk import ArchiveIPKExtractor
                        self.status.emit(f"[{i+1}/{total}] Unpacking IPK: {candidate.name}")
                        extractor = ArchiveIPKExtractor(candidate)
                        import shutil
                        shutil.rmtree(batch_cache, ignore_errors=True)
                        map_dir = extractor.extract(batch_cache)
                    
                    # If the source is a bundle IPK, map_dir will have multiple subfolders without ckd files at root
                    from jd2021_installer.parsers.normalizer import _find_ckd_files
                    if candidate.is_file() and candidate.suffix.lower() == ".ipk" and not _find_ckd_files(str(map_dir), "*songdesc*.tpl.ckd"):
                        sub_maps = [d for d in map_dir.iterdir() if d.is_dir()]
                    else:
                        sub_maps = [map_dir]

                    for sub_map in sub_maps:
                        if self._selected_maps and sub_map.name not in self._selected_maps:
                            # If it's a map folder and not in selected_maps, skip it.
                            # (If it's just batch processing standalone maps, it'll still work if selected_maps is None)
                            continue
                            
                        self.status.emit(f"[{i+1}/{total}] Normalizing {sub_map.name}...")
                        from jd2021_installer.parsers.normalizer import normalize
                        map_data = normalize(sub_map)
                        
                        self.status.emit(f"[{i+1}/{total}] Installing {map_data.codename}...")
                        self._install_map_synchronously(map_data)
                        success_count += 1
                        logger.info("Batch installed map: %s", map_data.codename)
                    
                except Exception as e:
                    logger.warning("Failed to install map from %s: %s", candidate.name, e)
                    self.status.emit(f"Warning: Failed {candidate.name} ({str(e)[:30]})")

            import shutil
            shutil.rmtree(batch_cache, ignore_errors=True)

            self.progress.emit(100)
            self.status.emit(f"Batch install complete. {success_count}/{total} maps installed.")
            self.finished.emit(True)

        except Exception as e:
            logger.error("BatchInstallWorker failed: %s\n%s", e, traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(False)
            
    def _install_map_synchronously(self, map_data: NormalizedMapData) -> None:
        """Execute the same steps as InstallMapWorker.run() synchronously."""
        codename = map_data.codename
        map_target = self._target_dir / "World" / "MAPS" / codename
        map_target.mkdir(parents=True, exist_ok=True)

        write_game_files(map_data, map_target, self._config)

        media = map_data.media
        from jd2021_installer.installers.media_processor import copy_video, copy_audio
        if media.video_path and media.video_path.exists():
            video_dst = map_target / "VideosCoach" / f"{codename}.webm"
            copy_video(media.video_path, video_dst)
            if media.map_preview_video and media.map_preview_video.exists():
                preview_dst = map_target / "VideosCoach" / f"{codename}_MapPreview.webm"
                copy_video(media.map_preview_video, preview_dst)

        if media.audio_path and media.audio_path.exists():
            audio_dst = map_target / "Audio" / f"{codename}.wav"
            copy_audio(media.audio_path, audio_dst)

        if media.cover_path and media.cover_path.exists():
            import shutil
            textures_dir = map_target / "MenuArt" / "textures"
            textures_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(media.cover_path, textures_dir / media.cover_path.name)

        for coach_img in media.coach_images:
            if coach_img.exists():
                import shutil
                textures_dir = map_target / "MenuArt" / "textures"
                shutil.copy2(coach_img, textures_dir / coach_img.name)

        if media.moves_dir and media.moves_dir.exists():
            from jd2021_installer.installers.media_processor import copy_moves
            copy_moves(media.moves_dir, map_target)

        from jd2021_installer.installers.sku_scene import register_map
        register_map(self._target_dir, codename)
