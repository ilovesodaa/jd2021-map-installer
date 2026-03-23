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
            install_map_to_game(
                self._map_data, 
                self._target_dir, 
                self._config,
                status_callback=self.status.emit,
                progress_callback=self.progress.emit
            )
            self.finished.emit(True)

        except Exception as e:
            logger.error("InstallMap failed: %s\n%s", e, traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(False)


def reprocess_audio(
    map_data: NormalizedMapData, 
    target_dir: Path, 
    a_offset: float = 0.0,
    config: Optional[AppConfig] = None
) -> None:
    """Rebuild game configuration files and reprocess physical audio files."""
    # 1. Update UbiArt config (musictrack.trk, etc)
    write_game_files(map_data, target_dir, config)
    
    # 2. Ported V1 FFmpeg logic: pad/trim main audio and generate intro AMB
    from jd2021_installer.installers.media_processor import convert_audio, generate_intro_amb
    
    codename = map_data.codename
    media = map_data.media
    
    if media.audio_path and media.audio_path.exists():
        # Generates Audio/<codename>.wav and .ogg
        convert_audio(media.audio_path, codename, target_dir, a_offset, config)
        
        # Generates Audio/AMB/<intro>.wav/tpl/ilu and injects into audio ISC
        ogg_path = target_dir / "Audio" / f"{codename}.ogg"
        v_override = map_data.video_start_time_override
        
        # Use beat marker data if available for precise pre-roll
        preroll = None
        if map_data.music_track and map_data.music_track.markers:
            from jd2021_installer.parsers.binary_ckd import calculate_marker_preroll
            preroll = calculate_marker_preroll(
                map_data.music_track.markers, 
                map_data.music_track.start_beat
            )
            
        generate_intro_amb(ogg_path, codename, target_dir, a_offset, v_override, preroll, config)


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
        a_offset: float = 0.0,
        config: Optional[AppConfig] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._map_data = map_data
        self._target_dir = target_dir
        self._cache_dir = cache_dir
        self._a_offset = a_offset
        self._config = config

    def run(self) -> None:
        try:
            self.status.emit("Reprocessing audio offsets...")
            self.progress.emit(30)
            
            # 1. Update configs and audio via reprocess_audio
            reprocess_audio(self._map_data, self._target_dir, self._a_offset, self._config)
            
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
    finished_with_data = pyqtSignal(list) # list[NormalizedMapData]

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
            installed_maps: list[NormalizedMapData] = []
            
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
                        installed_maps.append(map_data)
                        logger.info("Batch installed map: %s", map_data.codename)
                    
                except Exception as e:
                    logger.warning("Failed to install map from %s: %s", candidate.name, e)
                    self.status.emit(f"Warning: Failed {candidate.name} ({str(e)[:30]})")

            import shutil
            shutil.rmtree(batch_cache, ignore_errors=True)

            self.progress.emit(100)
            self.status.emit(f"Batch install complete. {success_count}/{total} maps installed.")
            self.finished_with_data.emit(installed_maps)
            self.finished.emit(True)

        except Exception as e:
            logger.error("BatchInstallWorker failed: %s\n%s", e, traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(False)
            
    def _install_map_synchronously(self, map_data: NormalizedMapData) -> None:
        """Execute the same steps as InstallMapWorker.run() synchronously."""
        install_map_to_game(map_data, self._target_dir, self._config)


def install_map_to_game(
    map_data: NormalizedMapData, 
    game_dir: Path, 
    config: AppConfig,
    status_callback: Optional[callable] = None,
    progress_callback: Optional[callable] = None
) -> None:
    """Core installation logic: files → game directory."""
    codename = map_data.codename
    if status_callback: status_callback(f"Installing {codename}...")
    if progress_callback: progress_callback(10)

    # Resolve target directory: game_dir / World / MAPS / <codename>
    map_target = game_dir / "World" / "MAPS" / codename
    map_target.mkdir(parents=True, exist_ok=True)

    # 1. Write all UbiArt config files
    if status_callback: status_callback("Writing game configuration files...")
    if progress_callback: progress_callback(20)
    write_game_files(map_data, map_target, config)

    # 2. Copy media files (video + audio)
    media = map_data.media
    if media.video_path and media.video_path.exists():
        if status_callback: status_callback("Copying video file...")
        if progress_callback: progress_callback(40)
        from jd2021_installer.installers.media_processor import copy_video
        video_dst = map_target / "VideosCoach" / f"{codename}.webm"
        copy_video(media.video_path, video_dst)
        if media.map_preview_video and media.map_preview_video.exists():
            preview_dst = map_target / "VideosCoach" / f"{codename}_MapPreview.webm"
            copy_video(media.map_preview_video, preview_dst)

    if media.audio_path and media.audio_path.exists():
        if status_callback: status_callback("Copying/Transcoding audio file...")
        if progress_callback: progress_callback(60)
        from jd2021_installer.installers.media_processor import copy_audio
        audio_dst = map_target / "Audio" / f"{codename}.wav"
        copy_audio(media.audio_path, audio_dst)

    # 3. Copy cover/coach images
    textures_dir = map_target / "MenuArt" / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    if media.cover_path and media.cover_path.exists():
        shutil.copy2(media.cover_path, textures_dir / media.cover_path.name)
    for coach_img in media.coach_images:
        if coach_img.exists():
            shutil.copy2(coach_img, textures_dir / coach_img.name)

    # 4. Physical Converters (Tape, Texture, Ambient)
    if map_data.source_dir and map_data.source_dir.exists():
        if status_callback: status_callback("Converting timeline tapes...")
        from jd2021_installer.installers.tape_converter import auto_convert_tapes
        auto_convert_tapes(map_data.source_dir, map_target, codename)
        
        if status_callback: status_callback("Processing ambient sound...")
        from jd2021_installer.installers.ambient_processor import process_ambient_directory
        process_ambient_directory(map_data.source_dir, map_target, codename)
        
        if status_callback: status_callback("Decoding textures...")
        from jd2021_installer.installers.texture_decoder import decode_menuart_textures, decode_pictograms
        menuart_src = map_data.source_dir / "MenuArt" / "textures"
        if menuart_src.exists():
            decode_menuart_textures(menuart_src, textures_dir)
        picto_src = map_data.source_dir / "pictos"
        if picto_src.exists():
            decode_pictograms(picto_src, map_target / "pictos")

    # 5. Moves
    if media.moves_dir and media.moves_dir.exists():
        if status_callback: status_callback("Integrating cross-platform move data...")
        from jd2021_installer.installers.media_processor import copy_moves
        copy_moves(media.moves_dir, map_target)

    # 6. Register map in SkuScene ISC
    if status_callback: status_callback("Registering map in song list...")
    if progress_callback: progress_callback(90)
    try:
        from jd2021_installer.installers.sku_scene import register_map
        register_map(game_dir, codename)
    except Exception as e:
        logger.warning("SkuScene registration failed (non-fatal): %s", e)

    if progress_callback: progress_callback(100)
    if status_callback: status_callback("Installation complete!")
