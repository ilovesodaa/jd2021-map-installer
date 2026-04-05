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
import re
import shutil
import struct
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.exceptions import ExtractionError, IPKExtractionError
from jd2021_installer.core.logging_config import log_exception_for_profile
from jd2021_installer.core.models import NormalizedMapData
from jd2021_installer.extractors.base import BaseExtractor
from jd2021_installer.extractors.archive_ipk import ArchiveIPKExtractor
from jd2021_installer.installers.game_writer import write_game_files
from jd2021_installer.parsers.normalizer import normalize

logger = logging.getLogger("jd2021.ui.workers")

_READY_STATUS_VALUE = 3

_V1_RECOVERABLE_IPK_ERRORS = (IPKExtractionError, AssertionError, OSError, struct.error)


def _is_user_cancelled_browser_close(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "target page, context or browser has been closed" in text
        or "browser has been closed" in text
        or "target closed" in text
        or "fetch cancelled" in text
    )


def _path_has_codename_component(path: Path, codename: str) -> bool:
    codename_low = codename.lower()
    parts = [p.lower() for p in path.parts]
    if codename_low in parts:
        return True
    name_low = path.name.lower()
    return name_low.startswith(codename_low)


def _pick_ipk_audio(search_dirs: list[Path], codename: Optional[str]) -> Optional[Path]:
    for pattern in ("*.ogg", "*.wav", "*.wav.ckd"):
        candidates: list[Path] = []
        for root in search_dirs:
            if not root or not root.is_dir():
                continue
            for p in root.rglob(pattern):
                low_path = str(p).lower().replace("\\", "/")
                low_name = p.name.lower()
                if "audiopreview" in low_name:
                    continue
                if "/amb/" in low_path or "/autodance/" in low_path:
                    continue
                if low_name.startswith("amb_"):
                    continue
                candidates.append(p)

        if not candidates:
            continue

        if codename:
            scoped = [p for p in candidates if _path_has_codename_component(p, codename)]
            if scoped:
                return scoped[0]
            # V1 behavior: do not pick random media from another map when codename is known.
            continue
        return candidates[0]

    return None


def _pick_ipk_video(search_dirs: list[Path], codename: Optional[str]) -> Optional[Path]:
    candidates: list[Path] = []
    for root in search_dirs:
        if not root or not root.is_dir():
            continue
        for p in root.rglob("*.webm"):
            low_name = p.name.lower()
            if "mappreview" in low_name or "videopreview" in low_name:
                continue
            candidates.append(p)

    if not candidates:
        return None

    if codename:
        scoped = [p for p in candidates if _path_has_codename_component(p, codename)]
        if scoped:
            candidates = scoped
        else:
            # V1 behavior: avoid selecting cross-map videos when codename is known.
            return None

    for quality in ("ULTRA_HD", "ULTRA", "HIGH_HD", "HIGH", "MID_HD", "MID", "LOW_HD", "LOW"):
        suffix = f"_{quality}.webm"
        for p in candidates:
            if p.name.upper().endswith(suffix):
                return p
    return candidates[0]


def _collect_menuart_texture_sources(source_dir: Path, codename: str) -> list[Path]:
    """Collect candidate MenuArt texture directories for decode fallback.

    Some IPK layouts only place MenuArt textures under cache/itf_cooked/<platform>
    and not under world/maps/<codename>/MenuArt. This helper discovers both.
    """
    seen: set[str] = set()
    sources: list[Path] = []

    def _add(path: Path) -> None:
        key = str(path).lower()
        if key in seen:
            return
        if path.is_dir():
            seen.add(key)
            sources.append(path)

    _add(source_dir / "MenuArt")
    _add(source_dir / "menuart")
    _add(source_dir / "MenuArt" / "textures")
    _add(source_dir / "menuart" / "textures")

    extraction_root: Optional[Path] = None
    for candidate in [source_dir, *source_dir.parents]:
        if (candidate / "cache" / "itf_cooked").exists():
            extraction_root = candidate
            break
        if candidate.name.lower() in {"_extraction", "temp_extraction"}:
            extraction_root = candidate
            break

    if extraction_root is None:
        return sources

    itf_cooked = extraction_root / "cache" / "itf_cooked"
    if not itf_cooked.is_dir():
        return sources

    codename_low = codename.lower()
    for platform_dir in itf_cooked.iterdir():
        if not platform_dir.is_dir():
            continue
        _add(platform_dir / "world" / "maps" / codename / "menuart")
        _add(platform_dir / "world" / "maps" / codename_low / "menuart")
        _add(platform_dir / "world" / "maps" / codename / "menuart" / "textures")
        _add(platform_dir / "world" / "maps" / codename_low / "menuart" / "textures")

    return sources


def _collect_pictogram_sources(source_dir: Path, codename: str, preferred: Optional[Path] = None) -> list[Path]:
    """Collect candidate pictogram directories, including IPK cache fallbacks."""
    seen: set[str] = set()
    sources: list[Path] = []

    def _add(path: Optional[Path]) -> None:
        if path is None:
            return
        key = str(path).lower()
        if key in seen:
            return
        if path.is_dir():
            seen.add(key)
            sources.append(path)

    _add(preferred)
    _add(source_dir / "pictos")
    _add(source_dir / "timeline" / "pictos")

    extraction_root: Optional[Path] = None
    for candidate in [source_dir, *source_dir.parents]:
        if (candidate / "cache" / "itf_cooked").exists():
            extraction_root = candidate
            break
        if candidate.name.lower() in {"_extraction", "temp_extraction"}:
            extraction_root = candidate
            break

    if extraction_root is None:
        return sources

    itf_cooked = extraction_root / "cache" / "itf_cooked"
    if not itf_cooked.is_dir():
        return sources

    codename_low = codename.lower()
    for platform_dir in itf_cooked.iterdir():
        if not platform_dir.is_dir():
            continue
        _add(platform_dir / "world" / "maps" / codename / "timeline" / "pictos")
        _add(platform_dir / "world" / "maps" / codename_low / "timeline" / "pictos")

    return sources


def _validate_ipk_media_presence(
    map_output_dir: Path,
    codename: Optional[str],
    search_root: Optional[Path],
) -> list[str]:
    search_dirs = [map_output_dir]
    if search_root and search_root not in search_dirs:
        search_dirs.append(search_root)

    warnings: list[str] = []

    audio = _pick_ipk_audio(search_dirs, codename)
    if not audio:
        warnings.append(
            "No audio file found after IPK extraction. "
            "Ensure the IPK contains .ogg, .wav, or .wav.ckd audio."
        )

    video = _pick_ipk_video(search_dirs, codename)
    if not video:
        warnings.append(
            "No gameplay video (.webm) found after IPK extraction. "
            "Ensure a .webm file is in the source directory."
        )

    return warnings


class ExtractAndNormalizeWorker(QObject):
    """Extract map data and normalize it in a background thread."""

    progress = pyqtSignal(int)          # 0-100
    status = pyqtSignal(str)            # human-readable status message
    error = pyqtSignal(str, str)        # stage name, error message
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
        failed_stage = "Extract map data"
        try:
            # Clear output_dir (temp extraction dir) before starting
            import shutil
            if self._output_dir.exists():
                logger.debug("Cleaning temp extraction dir: %s", self._output_dir)
                shutil.rmtree(self._output_dir)
            self._output_dir.mkdir(parents=True, exist_ok=True)

            self.status.emit("Extract map data")
            self.progress.emit(10)
            try:
                map_output_dir = self._extractor.extract(self._output_dir)
            except Exception as exc:
                if isinstance(self._extractor, ArchiveIPKExtractor) and isinstance(exc, _V1_RECOVERABLE_IPK_ERRORS):
                    logger.warning("IPK extraction issue (continuing for parity): %s", exc)
                    self.status.emit(f"Warning: IPK extraction issue: {exc}")
                    # V1 parity: continue with any partial extraction state.
                    map_output_dir = self._output_dir
                else:
                    raise

            for warning in self._extractor.get_warnings():
                self.status.emit(f"Warning: {warning}")

            codename = self._codename or self._extractor.get_codename()
            search_root: Optional[Path] = None
            normalize_search_root: Optional[Path] = None
            media_errors: list[str] = []

            if isinstance(self._extractor, ArchiveIPKExtractor):
                # V1 parity: IPK mode also probes media alongside the selected .ipk file.
                search_root = self._extractor.get_source_dir()
                media_errors.extend(_validate_ipk_media_presence(map_output_dir, codename, search_root))
                # For normalization, scan the extracted tree so map-local optional assets
                # (e.g., albumcoach/map_bkg) are discovered before ACT generation.
                normalize_search_root = map_output_dir
            elif hasattr(self._extractor, "is_ipk_source"):
                if bool(self._extractor.is_ipk_source()):  # type: ignore[attr-defined]
                    media_errors.extend(_validate_ipk_media_presence(map_output_dir, codename, None))
                    normalize_search_root = map_output_dir

            if media_errors:
                for error in media_errors:
                    logger.error("IPK media validation failed: %s", error)
                raise RuntimeError(" ".join(media_errors))

            failed_stage = "Parse CKDs & Metadata"
            self.status.emit("Parse CKDs & Metadata")
            self.progress.emit(40)
            
            failed_stage = "Normalize assets"
            self.status.emit("Normalize assets")
            self.progress.emit(50)

            map_data = normalize(
                map_output_dir,
                codename,
                search_root=normalize_search_root,
            )

            self.progress.emit(100)
            self.status.emit("Normalization complete.")
            self.finished.emit(map_data)

        except Exception as e:
            if isinstance(e, ExtractionError) or _is_user_cancelled_browser_close(e):
                user_msg = str(e)
                if _is_user_cancelled_browser_close(e):
                    user_msg = "Browser was closed by user. Fetch cancelled."
                logger.warning("ExtractAndNormalize failed: %s", user_msg)
                self.error.emit(failed_stage, user_msg)
                self.finished.emit(None)
                return

            log_exception_for_profile(logger, "ExtractAndNormalize failed", e)
            self.error.emit(failed_stage, str(e))
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
        source_mode: str = "",
        config: Optional[AppConfig] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._map_data = map_data
        self._target_dir = target_dir
        self._source_mode = source_mode
        self._config = config

    def run(self) -> None:
        try:
            install_map_to_game(
                self._map_data, 
                self._target_dir, 
                self._config,
                source_mode=self._source_mode,
                status_callback=self.status.emit,
                progress_callback=self.progress.emit
            )
            self.finished.emit(True)

        except Exception as e:
            log_exception_for_profile(logger, "InstallMap failed", e)
            self.error.emit(str(e))
            self.finished.emit(False)


def reprocess_audio(
    map_data: NormalizedMapData, 
    target_dir: Path, 
    a_offset: float = 0.0,
    config: Optional[AppConfig] = None
) -> None:
    """Rebuild game configuration files and reprocess physical audio files."""
    codename = map_data.codename
    mainsequence_path = target_dir / "Cinematics" / f"{codename}_MainSequence.tape"
    mainsequence_backup: Optional[str] = None
    if mainsequence_path.exists():
        try:
            mainsequence_backup = mainsequence_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            mainsequence_backup = None

    # 1. Update UbiArt config (musictrack.trk, etc)
    write_game_files(map_data, target_dir, config)

    # Keep converted cinematic tape content across offset reprocess runs.
    if mainsequence_backup:
        try:
            mainsequence_path.parent.mkdir(parents=True, exist_ok=True)
            mainsequence_path.write_text(mainsequence_backup, encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not restore existing MainSequence tape for '%s': %s", codename, exc)
    
    # 2. Ported V1 FFmpeg logic: pad/trim main audio and generate intro AMB
    from jd2021_installer.installers.media_processor import (
        convert_audio, 
        generate_intro_amb,
        extract_amb_clips,
    )
    
    media = map_data.media

    if (not media.audio_path or not media.audio_path.exists()) and map_data.source_dir:
        fallback_audio = _pick_ipk_audio([map_data.source_dir], codename)
        if fallback_audio and fallback_audio.exists():
            media.audio_path = fallback_audio
            logger.info("Recovered missing audio source from extraction tree: %s", fallback_audio)
    
    if not media.audio_path or not media.audio_path.exists():
        raise RuntimeError(
            f"Audio source missing for '{codename}'. "
            "Bundle/IPK map cannot be finalized without decoded audio."
        )

    # Generates audio/<codename>.wav and .ogg
    convert_audio(media.audio_path, codename, target_dir, a_offset, config)
    
    # Generates audio/amb/<intro>.wav/tpl/ilu and injects into audio ISC
    ogg_path = target_dir / "audio" / f"{codename}.ogg"
    v_override = map_data.effective_video_start_time
    
    # Use beat marker data if available for precise pre-roll
    preroll = None
    if map_data.music_track and map_data.music_track.markers:
        from jd2021_installer.parsers.binary_ckd import calculate_marker_preroll
        preroll = calculate_marker_preroll(
            map_data.music_track.markers, 
            map_data.music_track.start_beat
        )
        
    generate_intro_amb(ogg_path, codename, target_dir, a_offset, v_override, preroll, config)

    # Ensure intro AMB is triggerable even when source cinematic clip data is sparse.
    try:
        from jd2021_installer.installers.ambient_processor import _inject_intro_amb_soundset_clip

        _inject_intro_amb_soundset_clip(target_dir, codename)
    except Exception as exc:
        logger.debug("AMB SoundSetClip injection skipped for '%s': %s", codename, exc)

    # Ported V1: Extract cinematic AMB clips from the main audio
    if map_data.cinematic_tape:
        extract_amb_clips(map_data.cinematic_tape, media.audio_path, target_dir, codename, config)


def _update_trk_video_start_time(trk_path: Path, value_seconds: float) -> None:
    """Patch videoStartTime in an existing .trk file."""
    if not trk_path.exists():
        raise RuntimeError(f"Missing .trk file for readjust apply: {trk_path}")

    content = trk_path.read_text(encoding="utf-8")
    pattern = r"videoStartTime\s*=\s*([-+]?\d*\.?\d+)"
    replacement = f"videoStartTime = {value_seconds:.6f}"
    updated, count = re.subn(pattern, replacement, content, count=1)
    if count == 0:
        raise RuntimeError(f"Could not find videoStartTime in {trk_path}")
    trk_path.write_text(updated, encoding="utf-8")


def reprocess_audio_readjust(
    map_data: NormalizedMapData,
    target_dir: Path,
    *,
    a_offset: float,
    v_override: float,
    update_video: bool,
    update_audio: bool,
    config: Optional[AppConfig] = None,
) -> None:
    """Apply readjust offsets without rewriting full map config files.

    This mode is used for readjust sessions restored from index entries where
    source CKD payloads may no longer be complete.
    """
    from jd2021_installer.installers.media_processor import (
        convert_audio,
        generate_intro_amb,
        extract_amb_clips,
    )

    codename = map_data.codename
    media = map_data.media

    if (not media.audio_path or not media.audio_path.exists()) and map_data.source_dir:
        fallback_audio = _pick_ipk_audio([map_data.source_dir], codename)
        if fallback_audio and fallback_audio.exists():
            media.audio_path = fallback_audio
            logger.info("Recovered missing audio source from extraction tree: %s", fallback_audio)

    if update_video:
        trk_path = target_dir / "Audio" / f"{codename}.trk"
        _update_trk_video_start_time(trk_path, v_override)

    if not update_audio:
        return

    if not media.audio_path or not media.audio_path.exists():
        raise RuntimeError(
            f"Audio source missing for '{codename}'. Cannot apply readjust audio offset."
        )

    convert_audio(media.audio_path, codename, target_dir, a_offset, config)

    ogg_path = target_dir / "audio" / f"{codename}.ogg"
    preroll = None
    if map_data.music_track and map_data.music_track.markers:
        from jd2021_installer.parsers.binary_ckd import calculate_marker_preroll

        preroll = calculate_marker_preroll(
            map_data.music_track.markers,
            map_data.music_track.start_beat,
        )

    generate_intro_amb(ogg_path, codename, target_dir, a_offset, v_override, preroll, config)

    try:
        from jd2021_installer.installers.ambient_processor import _inject_intro_amb_soundset_clip

        _inject_intro_amb_soundset_clip(target_dir, codename)
    except Exception as exc:
        logger.debug("AMB SoundSetClip injection skipped for '%s' (readjust): %s", codename, exc)

    if map_data.cinematic_tape:
        extract_amb_clips(map_data.cinematic_tape, media.audio_path, target_dir, codename, config)


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
            self.status.emit("Finalizing Offsets")
            self.progress.emit(30)
            
            # 1. Update configs and audio via reprocess_audio
            reprocess_audio(self._map_data, self._target_dir, self._a_offset, self._config)
            
            self.progress.emit(100)
            self.status.emit("Sync offsets applied successfully.")
            self.finished.emit(True)
        except Exception as e:
            log_exception_for_profile(logger, "ApplyAndFinish failed", e)
            self.error.emit(str(e))
            self.finished.emit(False)


class ApplyOffsetsBatchWorker(QObject):
    """Apply offset finalization across multiple maps in one background task."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(
        self,
        entries: list[tuple[NormalizedMapData, Path, float]],
        config: Optional[AppConfig] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._entries = entries
        self._config = config

    def run(self) -> None:
        try:
            total = len(self._entries)
            if total == 0:
                self.finished.emit(True)
                return

            for idx, (map_data, target_dir, a_offset) in enumerate(self._entries, start=1):
                codename = map_data.codename
                self.status.emit(f"[{codename}] Finalizing Offsets")
                progress = int(((idx - 1) / total) * 100)
                self.progress.emit(progress)
                reprocess_audio(map_data, target_dir, a_offset, self._config)

            self.progress.emit(100)
            self.status.emit("Sync offsets applied successfully.")
            self.finished.emit(True)
        except Exception as e:
            log_exception_for_profile(logger, "ApplyOffsetsBatch failed", e)
            self.error.emit(str(e))
            self.finished.emit(False)


class ApplyReadjustOffsetsBatchWorker(QObject):
    """Apply readjust offsets across one or more maps."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(
        self,
        entries: list[tuple[NormalizedMapData, Path, float, float, bool, bool]],
        config: Optional[AppConfig] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._entries = entries
        self._config = config

    def run(self) -> None:
        try:
            total = len(self._entries)
            if total == 0:
                self.finished.emit(True)
                return

            for idx, (map_data, target_dir, a_offset, v_override, update_video, update_audio) in enumerate(self._entries, start=1):
                codename = map_data.codename
                self.status.emit(f"[{codename}] Finalizing Offsets")
                progress = int(((idx - 1) / total) * 100)
                self.progress.emit(progress)
                reprocess_audio_readjust(
                    map_data,
                    target_dir,
                    a_offset=a_offset,
                    v_override=v_override,
                    update_video=update_video,
                    update_audio=update_audio,
                    config=self._config,
                )

            self.progress.emit(100)
            self.status.emit("Sync offsets applied successfully.")
            self.finished.emit(True)
        except Exception as e:
            log_exception_for_profile(logger, "ApplyReadjustOffsetsBatch failed", e)
            self.error.emit(str(e))
            self.finished.emit(False)


class BatchInstallWorker(QObject):
    """Iterate through a directory and install all discovered maps (folders/IPKs)."""

    progress = pyqtSignal(int)          # overall progress 0-100
    status = pyqtSignal(str)            # status text
    error = pyqtSignal(str)             # error message
    finished = pyqtSignal(bool)         # success flag
    finished_with_data = pyqtSignal(list) # list[NormalizedMapData]
    discovered_maps = pyqtSignal(list)  # list[str] (codenames)

    def __init__(
        self,
        batch_source_dir: Path,
        target_game_dir: Path,
        config: AppConfig,
        selected_maps: Optional[set[str]] = None,
        fetch_codenames: Optional[list[str]] = None,
        fetch_source: str = "jdu",
        force_unlock_locked_status: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._source_dir = batch_source_dir
        self._target_dir = target_game_dir
        self._config = config
        self._selected_maps = selected_maps
        self._fetch_codenames = [c.strip() for c in (fetch_codenames or []) if c and c.strip()]
        self._fetch_source = (fetch_source or "jdu").strip().lower() or "jdu"
        self._force_unlock_locked_status = force_unlock_locked_status

    def run(self) -> None:
        try:
            import shutil

            self.status.emit("Scanning for maps in batch directory...")
            progress_value = 0

            def find_html_pair(folder: Path) -> tuple[Optional[Path], Optional[Path]]:
                asset: Optional[Path] = None
                nohud: Optional[Path] = None
                html_files = sorted(
                    [
                        p
                        for p in folder.iterdir()
                        if p.is_file() and p.suffix.lower() in {".html", ".htm"}
                    ],
                    key=lambda p: p.name.lower(),
                )

                for html in html_files:
                    lower = html.name.lower()
                    if "nohud" in lower and nohud is None:
                        nohud = html
                    elif "asset" in lower and asset is None:
                        asset = html

                if len(html_files) >= 2:
                    if asset is None:
                        asset = next((h for h in html_files if h != nohud), html_files[0])
                    if nohud is None:
                        nohud = next((h for h in html_files if h != asset), html_files[-1])

                return asset, nohud

            def looks_like_prepared_map_dir(folder: Path) -> bool:
                if not folder.is_dir():
                    return False

                has_ckd = any(folder.rglob("*.ckd"))
                if has_ckd:
                    return True

                has_audio = False
                for pattern in ("*.ogg", "*.wav", "*.wav.ckd"):
                    for p in folder.rglob(pattern):
                        low_name = p.name.lower()
                        low_path = str(p).lower().replace("\\", "/")
                        if "audiopreview" in low_name:
                            continue
                        if "/amb/" in low_path or "/autodance/" in low_path:
                            continue
                        if low_name.startswith("amb_"):
                            continue
                        has_audio = True
                        break
                    if has_audio:
                        break

                has_video = any(
                    p.is_file()
                    and "mappreview" not in p.name.lower()
                    and "videopreview" not in p.name.lower()
                    for p in folder.rglob("*.webm")
                )

                has_musictrack = any(folder.rglob("*musictrack*.tpl.ckd"))

                return has_audio and has_video and has_musictrack

            def emit_progress(value: int) -> None:
                nonlocal progress_value
                clamped = max(0, min(100, value))
                if clamped > progress_value:
                    progress_value = clamped
                    self.progress.emit(clamped)
            
            candidates: list[dict[str, object]] = []
            if self._fetch_codenames:
                for codename in self._fetch_codenames:
                    candidates.append({"kind": "fetch", "name": codename, "path": self._source_dir})

            # When explicit fetch codenames are provided, treat this as a pure fetch batch.
            if self._source_dir and not self._fetch_codenames:
                if self._source_dir.is_file() and self._source_dir.suffix.lower() == ".ipk":
                    candidates.append({"kind": "ipk", "path": self._source_dir})
                elif self._source_dir.is_dir():
                    root_asset, root_nohud = find_html_pair(self._source_dir)
                    if root_asset and root_nohud:
                        candidates.append(
                            {
                                "kind": "html",
                                "path": self._source_dir,
                                "name": self._source_dir.name,
                                "asset": root_asset,
                                "nohud": root_nohud,
                            }
                        )

                    for path in sorted(self._source_dir.iterdir(), key=lambda p: p.name.lower()):
                        if path.is_file() and path.suffix.lower() == ".ipk":
                            candidates.append({"kind": "ipk", "path": path})
                        elif path.is_dir():
                            if looks_like_prepared_map_dir(path):
                                candidates.append({"kind": "dir", "path": path})
                                continue

                            asset_html, nohud_html = find_html_pair(path)
                            if asset_html and nohud_html:
                                candidates.append(
                                    {
                                        "kind": "html",
                                        "path": path,
                                        "name": path.name,
                                        "asset": asset_html,
                                        "nohud": nohud_html,
                                    }
                                )
            
            total = len(candidates)
            if total == 0:
                self.error.emit(
                    "No valid IPK files, prepared map folders, or HTML map folders found in the selected batch directory."
                )
                self.finished.emit(False)
                return

            emit_progress(1)
            self.status.emit(f"Found {total} source item(s) to process.")
            
            # Emit discovered map names to the UI so it can populate the checklist
            map_names = []
            for candidate in candidates:
                kind = str(candidate["kind"])
                cpath = Path(candidate["path"])
                if kind == "fetch":
                    map_names.append(str(candidate.get("name") or cpath.name))
                elif kind == "ipk":
                    from jd2021_installer.extractors.archive_ipk import inspect_ipk
                    maps_in_ipk = inspect_ipk(cpath)
                    map_names.extend(maps_in_ipk or [cpath.stem])
                elif kind == "html":
                    map_names.append(str(candidate.get("name") or cpath.name))
                else:
                    map_names.append(cpath.name)

            # Merge all discovered map names into one stable list (case-insensitive dedupe).
            merged_map_names: list[str] = []
            seen_discovered: set[str] = set()
            for name in map_names:
                key = name.lower()
                if key in seen_discovered:
                    continue
                seen_discovered.add(key)
                merged_map_names.append(name)

            selected_lookup = {m.lower() for m in self._selected_maps} if self._selected_maps else None
            display_map_names = merged_map_names
            if selected_lookup is not None:
                display_map_names = [name for name in merged_map_names if name.lower() in selected_lookup]
            self.discovered_maps.emit(display_map_names)
            emit_progress(3)

            planned_maps = len(display_map_names) if display_map_names else len(merged_map_names)
            total_units = max(planned_maps * 3, 1)
            completed_units = 0

            def emit_map_stage(stage_offset: int) -> None:
                units = min(total_units, completed_units + stage_offset)
                emit_progress(min(99, 5 + int((units / total_units) * 90)))

            success_count = 0
            attempted_maps = 0
            installed_maps: list[NormalizedMapData] = []
            html_prepared: list[tuple[str, Path]] = []
            installed_codenames: set[str] = set()
            
            # Temporary cache for extracted IPKs
            batch_cache = self._config.cache_directory / "_batch_temp"
            batch_cache.mkdir(parents=True, exist_ok=True)

            # V1-style parity: prepare all HTML-sourced maps first while links are fresh.
            html_candidates = [c for c in candidates if str(c["kind"]) == "html"]
            if html_candidates:
                self.status.emit("Phase 1/2: Preparing HTML-sourced batch maps...")
                for idx, candidate in enumerate(html_candidates, start=1):
                    map_name = str(candidate.get("name") or Path(candidate["path"]).name)
                    if selected_lookup and map_name.lower() not in selected_lookup:
                        continue
                    asset_html = Path(candidate["asset"])
                    nohud_html = Path(candidate["nohud"])

                    self.status.emit(
                        f"[{idx}/{len(html_candidates)}] Downloading/Preparing HTML map {map_name}..."
                    )
                    try:
                        from jd2021_installer.extractors.web_playwright import WebPlaywrightExtractor

                        extractor = WebPlaywrightExtractor(
                            asset_html=str(asset_html),
                            nohud_html=str(nohud_html),
                            quality=self._config.video_quality,
                            config=self._config,
                        )
                        prepared_dir = extractor.extract(batch_cache)
                        html_prepared.append((map_name, prepared_dir))
                    except Exception as e:
                        logger.warning("Failed HTML prepare for %s: %s", map_name, e)
                        self.status.emit(f"Warning: Failed HTML prepare for {map_name} ({str(e)[:40]})")

            process_candidates = [c for c in candidates if str(c["kind"]) != "html"]

            self.status.emit("Phase 2/2: Installing prepared maps...")

            for i, candidate in enumerate(process_candidates):
                try:
                    cpath = Path(candidate["path"])
                    display_name = str(candidate.get("name") or cpath.name)
                    self.status.emit(f"[{i+1}/{len(process_candidates)}] Processing {display_name}...")
                    
                    map_dir = cpath
                    map_names_for_candidate: list[str] = []
                    is_candidate_ipk = str(candidate["kind"]) == "ipk"
                    is_candidate_fetch = str(candidate["kind"]) == "fetch"
                    if is_candidate_fetch:
                        from jd2021_installer.extractors.web_playwright import WebPlaywrightExtractor

                        map_name = str(candidate.get("name") or "").strip()
                        if selected_lookup and map_name.lower() not in selected_lookup:
                            continue

                        self.status.emit(f"[{map_name}] Fetch map data")
                        extractor = WebPlaywrightExtractor(
                            codenames=[map_name],
                            source_game=self._fetch_source,
                            quality=self._config.video_quality,
                            config=self._config,
                        )
                        map_dir = extractor.extract(batch_cache)
                        resolved_name = (extractor.get_codename() or map_name).strip()
                        map_names_for_candidate = [resolved_name or map_name]
                    elif is_candidate_ipk:
                        # Extract IPK to temp dir
                        from jd2021_installer.extractors.archive_ipk import ArchiveIPKExtractor
                        # Try to get codename from IPK name for early status
                        from jd2021_installer.extractors.archive_ipk import inspect_ipk
                        maps_in_ipk = inspect_ipk(cpath)
                        ipk_name_hint = maps_in_ipk[0] if maps_in_ipk else cpath.name
                        
                        self.status.emit(f"[{ipk_name_hint}] Extract map data")
                        desired_codename = None
                        if selected_lookup and maps_in_ipk:
                            for discovered_name in maps_in_ipk:
                                if discovered_name.lower() in selected_lookup:
                                    desired_codename = discovered_name
                                    break

                        extractor = ArchiveIPKExtractor(cpath, desired_codename=desired_codename)
                        import shutil
                        shutil.rmtree(batch_cache, ignore_errors=True)
                        map_dir = extractor.extract(batch_cache)
                        extracted_maps = sorted(set(maps_in_ipk) | set(getattr(extractor, "bundle_maps", []) or []))
                        map_names_for_candidate = extracted_maps
                    
                    if not map_names_for_candidate:
                        songdescs = list(map_dir.rglob("*songdesc*.tpl.ckd"))
                        if songdescs:
                            map_names_for_candidate = sorted({p.parent.name for p in songdescs})
                        else:
                            map_names_for_candidate = [map_dir.name]

                    logger.info("Discovered %d map(s) in %s", len(map_names_for_candidate), cpath.name)

                    for map_name in map_names_for_candidate:
                        if selected_lookup and map_name.lower() not in selected_lookup:
                            continue
                        if map_name.lower() in installed_codenames:
                            self.status.emit(f"Warning: Duplicate map '{map_name}' detected; skipping duplicate source.")
                            continue
                        attempted_maps += 1
                        emit_map_stage(0)
                            
                        self.status.emit(f"[{map_name}] Parse CKDs & Metadata")
                        from jd2021_installer.parsers.normalizer import normalize
                        map_data = normalize(map_dir, codename=map_name, search_root=map_dir)
                        setattr(map_data, "_is_ipk_source", is_candidate_ipk)

                        canonical_name = (map_data.codename or map_name).strip()
                        canonical_key = canonical_name.lower()
                        if canonical_key in installed_codenames:
                            self.status.emit(
                                f"Warning: Duplicate map '{canonical_name}' resolved from multiple sources; skipping duplicate install."
                            )
                            continue

                        status_value = int(getattr(map_data.song_desc, "status", _READY_STATUS_VALUE))
                        if status_value != _READY_STATUS_VALUE:
                            if self._force_unlock_locked_status:
                                map_data.song_desc.status = _READY_STATUS_VALUE
                                self.status.emit(
                                    f"[{map_data.codename}] Non-default status {status_value} detected; forcing Status={_READY_STATUS_VALUE}"
                                )
                            else:
                                self.status.emit(
                                    f"[{map_data.codename}] Non-default status {status_value} detected; preserving original status"
                                )
                        
                        emit_map_stage(1)
                        self.status.emit(f"[{map_data.codename}] Normalize assets")
                        
                        # V1 Parity: Persist preview assets in map cache so they remain available after batch extraction is cleared
                        map_cache = self._config.cache_directory / map_data.codename
                        map_cache.mkdir(parents=True, exist_ok=True)
                        if map_data.media.video_path and map_data.media.video_path.exists():
                            persisted_video = map_cache / map_data.media.video_path.name
                            if not persisted_video.exists():
                                shutil.copy2(map_data.media.video_path, persisted_video)
                            map_data.media.video_path = persisted_video
                        
                        if map_data.media.map_preview_video and map_data.media.map_preview_video.exists():
                            persisted_preview = map_cache / map_data.media.map_preview_video.name
                            if not persisted_preview.exists():
                                shutil.copy2(map_data.media.map_preview_video, persisted_preview)
                            map_data.media.map_preview_video = persisted_preview
                        if map_data.media.audio_path and map_data.media.audio_path.exists():
                            persisted_audio = map_cache / map_data.media.audio_path.name
                            if not persisted_audio.exists():
                                shutil.copy2(map_data.media.audio_path, persisted_audio)
                            map_data.media.audio_path = persisted_audio
                        
                        self.status.emit(f"[{map_data.codename}] Installing map...")
                        self._install_map_synchronously(map_data)
                        emit_map_stage(2)
                        completed_units += 3
                        success_count += 1
                        installed_codenames.add(canonical_key)
                        installed_maps.append(map_data)
                        logger.info("Batch installed map: %s", map_data.codename)
                    
                except Exception as e:
                    cpath = Path(candidate["path"])
                    logger.warning("Failed to install map from %s: %s", cpath.name, e)
                    self.status.emit(f"Warning: Failed {cpath.name} ({str(e)[:30]})")

            # Process maps prepared from HTML folders in phase 1.
            for map_name, map_dir in html_prepared:
                try:
                    if selected_lookup and map_name.lower() not in selected_lookup:
                        continue
                    if map_name.lower() in installed_codenames:
                        self.status.emit(f"Warning: Duplicate map '{map_name}' detected; skipping duplicate source.")
                        continue
                    attempted_maps += 1
                    emit_map_stage(0)

                    self.status.emit(f"[{map_name}] Parse CKDs & Metadata")
                    from jd2021_installer.parsers.normalizer import normalize
                    map_data = normalize(map_dir, codename=map_name, search_root=map_dir)
                    setattr(map_data, "_is_ipk_source", False)

                    canonical_name = (map_data.codename or map_name).strip()
                    canonical_key = canonical_name.lower()
                    if canonical_key in installed_codenames:
                        self.status.emit(
                            f"Warning: Duplicate map '{canonical_name}' resolved from multiple sources; skipping duplicate install."
                        )
                        continue

                    status_value = int(getattr(map_data.song_desc, "status", _READY_STATUS_VALUE))
                    if status_value != _READY_STATUS_VALUE:
                        if self._force_unlock_locked_status:
                            map_data.song_desc.status = _READY_STATUS_VALUE
                            self.status.emit(
                                f"[{map_data.codename}] Non-default status {status_value} detected; forcing Status={_READY_STATUS_VALUE}"
                            )
                        else:
                            self.status.emit(
                                f"[{map_data.codename}] Non-default status {status_value} detected; preserving original status"
                            )

                    emit_map_stage(1)
                    self.status.emit(f"[{map_data.codename}] Normalize assets")

                    map_cache = self._config.cache_directory / map_data.codename
                    map_cache.mkdir(parents=True, exist_ok=True)
                    if map_data.media.video_path and map_data.media.video_path.exists():
                        persisted_video = map_cache / map_data.media.video_path.name
                        if not persisted_video.exists():
                            shutil.copy2(map_data.media.video_path, persisted_video)
                        map_data.media.video_path = persisted_video

                    if map_data.media.map_preview_video and map_data.media.map_preview_video.exists():
                        persisted_preview = map_cache / map_data.media.map_preview_video.name
                        if not persisted_preview.exists():
                            shutil.copy2(map_data.media.map_preview_video, persisted_preview)
                        map_data.media.map_preview_video = persisted_preview
                    if map_data.media.audio_path and map_data.media.audio_path.exists():
                        persisted_audio = map_cache / map_data.media.audio_path.name
                        if not persisted_audio.exists():
                            shutil.copy2(map_data.media.audio_path, persisted_audio)
                        map_data.media.audio_path = persisted_audio

                    self.status.emit(f"[{map_data.codename}] Installing map...")
                    self._install_map_synchronously(map_data)
                    emit_map_stage(2)
                    completed_units += 3
                    success_count += 1
                    installed_codenames.add(canonical_key)
                    installed_maps.append(map_data)
                    logger.info("Batch installed HTML map: %s", map_data.codename)
                except Exception as e:
                    logger.warning("Failed to install HTML map %s: %s", map_name, e)
                    self.status.emit(f"Warning: Failed {map_name} ({str(e)[:30]})")

            import shutil
            shutil.rmtree(batch_cache, ignore_errors=True)

            emit_progress(100)
            total_maps = attempted_maps if attempted_maps > 0 else total
            self.status.emit(f"Batch install complete. {success_count}/{total_maps} maps installed.")
            self.finished_with_data.emit(installed_maps)
            self.finished.emit(True)

        except Exception as e:
            log_exception_for_profile(logger, "BatchInstallWorker failed", e)
            self.error.emit(str(e))
            self.finished.emit(False)
            
    def _install_map_synchronously(self, map_data: NormalizedMapData) -> None:
        """Execute the same steps as InstallMapWorker.run() synchronously."""
        def callback(msg: str):
            prefix = f"[{map_data.codename}] "
            self.status.emit(prefix + msg)
            
        install_map_to_game(map_data, self._target_dir, self._config, status_callback=callback)



def pre_install_cleanup(
    game_dir: Path, 
    codename: str, 
    status_callback: Optional[Callable[[str], None]] = None
) -> None:
    """Clean up any previous installation of this map, including cooked cache."""
    import shutil
    
    # Normalize game_dir
    while game_dir.name.lower() in ("world", "data"):
        game_dir = game_dir.parent

    if status_callback:
        status_callback(f"Cleaning up previous installation of {codename}...")

    # 1. Delete main map directory
    map_dir = game_dir / "data" / "world" / "maps" / codename
    if map_dir.exists():
        logger.info("Deleting previous map directory: %s", codename)
        shutil.rmtree(map_dir, ignore_errors=True)

    # 2. Delete cooked cache directories
    # V1 Parity: engine cache paths are strictly lowercase
    name_lower = codename.lower()
    cache_base = game_dir / "data" / "cache" / "itf_cooked" / "pc" / "world" / "maps" / name_lower
    
    cache_paths = [
        cache_base,
        cache_base.with_name(cache_base.name + "_autodance"),
        cache_base.with_name(cache_base.name + "_cine"),
        cache_base / "audio"
    ]

    for cp in cache_paths:
        if cp.exists():
            logger.info("Deleting cache: %s", cp.name)
            shutil.rmtree(cp, ignore_errors=True)

    # 3. Unregister from SkuScene
    from jd2021_installer.installers.sku_scene import unregister_map
    unregister_map(game_dir, codename)


def install_map_to_game(
    map_data: NormalizedMapData, 
    game_dir: Path, 
    config: Optional[AppConfig],
    source_mode: str = "",
    status_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int], None]] = None
) -> None:
    """Core installation logic: files → game directory."""
    codename = map_data.codename
    
    # 0. Pre-install cleanup
    pre_install_cleanup(game_dir, codename, status_callback)
    if progress_callback: progress_callback(5)

    # Normalize the game directory root in case the user selected a subfolder
    while game_dir.name.lower() in ("world", "data"):
        game_dir = game_dir.parent

    # Resolve target directory: game_dir / data / world / maps / <codename>
    map_target = game_dir / "data" / "world" / "maps" / codename
    map_target.mkdir(parents=True, exist_ok=True)

    # 1. & 2. Write UbiArt config files and process audio WITH initial offsets
    # Calculate offset in seconds based on what was normalized
    initial_a_offset = map_data.sync.audio_ms / 1000.0
    
    # Note: reprocess_audio handles convert_audio, generate_intro_amb, and write_game_files
    # We'll need to manually emit status for its sub-steps if we want true granularity
    # but for now we'll wrap it.
    
    if status_callback: status_callback("Decode XMA2 Audio")
    if progress_callback: progress_callback(20)
    
    if status_callback: status_callback("Convert Audio (Pad/Trim)")
    if progress_callback: progress_callback(30)
    
    if status_callback: status_callback("Generate Intro AMB")
    if progress_callback: progress_callback(40)
    
    reprocess_audio(map_data, map_target, initial_a_offset, config)

    # Fetch/HTML parity ticket: boost installed gameplay audio by +8 dB.
    mode_low = (source_mode or "").lower()
    if "fetch" in mode_low or "html" in mode_low:
        if status_callback: status_callback("Apply +8dB JDU audio boost")
        if progress_callback: progress_callback(45)
        from jd2021_installer.installers.media_processor import apply_audio_gain

        audio_wav = map_target / "audio" / f"{codename}.wav"
        if audio_wav.exists():
            apply_audio_gain(audio_wav, gain_db=8.0, config=config)
        else:
            logger.warning("Expected gameplay WAV missing for gain boost: %s", audio_wav)

    # 2b. Copy Video
    media = map_data.media
    if media.video_path and media.video_path.exists():
        if status_callback: status_callback("Copy Video files")
        if progress_callback: progress_callback(50)
        from jd2021_installer.installers.media_processor import copy_video
        video_dst = map_target / "videoscoach" / f"{codename}.webm"
        copy_video(
            media.video_path,
            video_dst,
            config=config,
        )
        if media.map_preview_video and media.map_preview_video.exists():
            preview_dst = map_target / "videoscoach" / f"{codename}_MapPreview.webm"
            copy_video(media.map_preview_video, preview_dst, config=config)

    # 3. Copy/Rename MenuArt assets (Cover, Banner, Coach, etc.)
    textures_dir = map_target / "menuart" / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)
    
    # Map of MapMedia fields to V1 canonical art suffixes
    art_map = {
        "cover_generic_path": "cover_generic",
        "cover_online_path": "cover_online",
        "banner_bkg_path": "banner_bkg",
        "map_bkg_path": "map_bkg",
        "cover_albumbkg_path": "cover_albumbkg",
        "cover_albumcoach_path": "cover_albumcoach",
    }
    
    for field_name, art_suffix in art_map.items():
        src_path = getattr(media, field_name, None)
        if src_path and src_path.exists():
            # Canonical name: {codename}_{suffix}{ext}
            # We preserve .ckd suffix if present so texture_decoder can pick it up
            suffix = src_path.suffix.lower()
            if src_path.name.lower().endswith(".tga.ckd"):
                ext = ".tga.ckd"
            elif src_path.name.lower().endswith(".png.ckd"):
                ext = ".png.ckd"
            else:
                ext = suffix
                
            dst_name = f"{codename}_{art_suffix}{ext}"
            shutil.copy2(src_path, textures_dir / dst_name)
    
    def _extract_coach_index(path: Path) -> int:
        match = re.search(r"coach[_-]?(\d+)", path.name.lower())
        return int(match.group(1)) if match else 0

    # Coaches are now separated into main and phone lists in normalize_sync.
    # We use the index from the filename to ensure correct mapping even if some are missing.
    fallback_idx = 1
    used_indices: set[int] = set()
    for coach_img in media.coach_images:
        if coach_img.exists():
            idx = _extract_coach_index(coach_img)
            if idx == 0:
                while fallback_idx in used_indices:
                    fallback_idx += 1
                idx = fallback_idx
            used_indices.add(idx)
            
            suffix = coach_img.suffix.lower()
            if coach_img.name.lower().endswith(".tga.ckd"):
                ext = ".tga.ckd"
            else:
                ext = suffix
            dst_name = f"{codename}_coach_{idx}{ext}"
            shutil.copy2(coach_img, textures_dir / dst_name)
            
    for phone_img in media.coach_phone_images:
        if phone_img.exists():
            idx = _extract_coach_index(phone_img)
            if idx == 0:
                continue
            
            ext = ".png" # Phone assets are usually PNG
            if phone_img.name.lower().endswith(".tga.ckd"):
                ext = ".tga.ckd"
            elif phone_img.suffix.lower() == ".png" or phone_img.suffix.lower() == ".jpg":
                ext = phone_img.suffix.lower()

            dst_name = f"{codename}_coach_{idx}_phone{ext}"
            shutil.copy2(phone_img, textures_dir / dst_name)


    # 4. Physical Converters (Tape, Texture, Ambient)
    if map_data.source_dir and map_data.source_dir.exists():
        picto_src = map_data.media.pictogram_dir
        if not picto_src or not picto_src.exists():
            picto_src = map_data.source_dir / "pictos"

        if picto_src and picto_src.exists():
            menuart_tokens = ("cover_", "banner", "map_bkg", "coach_")
            for asset in picto_src.rglob("*"):
                if not asset.is_file():
                    continue
                name_low = asset.name.lower()
                if not any(token in name_low for token in menuart_tokens):
                    continue
                ext = asset.suffix.lower()
                if ext not in (".ckd", ".tga", ".png", ".jpg", ".jpeg"):
                    continue
                target_name = asset.name
                if not target_name.lower().startswith(f"{codename.lower()}_"):
                    target_name = f"{codename}_{target_name}"
                shutil.copy2(asset, textures_dir / target_name)

        if status_callback: status_callback("Convert Dance Tapes")
        if progress_callback: progress_callback(60)
        from jd2021_installer.installers.tape_converter import auto_convert_tapes
        auto_convert_tapes(map_data.source_dir, map_target, codename)
        
        # We don't have separate steps for Karaoke/Cinematic yet in logic, but status can reflect them
        if status_callback: status_callback("Convert Karaoke Tapes")
        if status_callback: status_callback("Convert Cinematic Tapes")
        
        if status_callback: status_callback("Process Ambient Sounds")
        if progress_callback: progress_callback(70)
        from jd2021_installer.installers.ambient_processor import process_ambient_directory
        process_ambient_directory(map_data.source_dir, map_target, codename)
        
        if status_callback: status_callback("Decode MenuArt textures")
        if progress_callback: progress_callback(80)
        from jd2021_installer.installers.texture_decoder import decode_menuart_textures, decode_pictograms
        
        # V1 Parity: Decode textures directly in the target directory 
        # to handle loose assets copied from Fetch/HTML mode.
        decoded_menuart = decode_menuart_textures(textures_dir, textures_dir)

        if map_data.source_dir and map_data.source_dir.exists():
            for menuart_src in _collect_menuart_texture_sources(map_data.source_dir, codename):
                decoded_menuart += decode_menuart_textures(menuart_src, textures_dir)

        if decoded_menuart == 0:
            logger.warning(
                "No MenuArt textures decoded for '%s'. "
                "Source may not include texture payloads.",
                codename,
            )

            
        # V1 Parity: Validate and heal MenuArt (case-fix + RGBA re-save)
        from jd2021_installer.installers.media_processor import process_menu_art
        process_menu_art(map_target, codename)
            
        if status_callback: status_callback("Decode Pictograms")
        decoded_pictos = 0
        if map_data.source_dir and map_data.source_dir.exists():
            for picto_dir in _collect_pictogram_sources(map_data.source_dir, codename, preferred=picto_src):
                decoded_pictos += decode_pictograms(picto_dir, map_target / "timeline" / "pictos")
        elif picto_src and picto_src.exists():
            decoded_pictos += decode_pictograms(picto_src, map_target / "timeline" / "pictos")

        if decoded_pictos == 0:
            logger.warning(
                "No pictograms decoded for '%s'. Source may not include pictogram textures.",
                codename,
            )

    # 5. Moves
    if media.moves_dir and media.moves_dir.exists():
        if status_callback: status_callback("Integrate Move data")
        if progress_callback: progress_callback(85)
        from jd2021_installer.installers.media_processor import copy_moves
        copy_moves(media.moves_dir, map_target)

    # 5b. Autodance + stape payloads (V1 step_11 parity)
    if map_data.has_autodance and map_data.source_dir and map_data.source_dir.exists():
        if status_callback: status_callback("Extract moves & autodance")
        from jd2021_installer.installers.autodance_processor import (
            process_autodance_directory,
            process_stape_file,
        )
        process_autodance_directory(map_data.source_dir, map_target, codename)
        process_stape_file(map_data.source_dir, map_target, codename)
    elif map_data.source_dir and map_data.source_dir.exists():
        # Some maps ship stape without autodance blocks.
        from jd2021_installer.installers.autodance_processor import process_stape_file
        process_stape_file(map_data.source_dir, map_target, codename)

    # 6. Register map in SkuScene ISC
    if status_callback: status_callback("Register in SkuScene")
    if progress_callback: progress_callback(95)
    try:
        from jd2021_installer.installers.sku_scene import register_map
        register_map(game_dir, codename)
    except Exception as e:
        logger.warning("SkuScene registration failed (non-fatal): %s", e)

    if status_callback: status_callback("Finalizing Offsets")
    if progress_callback: progress_callback(100)
