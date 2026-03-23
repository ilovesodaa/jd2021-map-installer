"""Normalizer pipeline: raw extracted files → NormalizedMapData.

Orchestrates CKD loading (JSON or binary), media asset discovery,
and validation to produce a single ``NormalizedMapData`` instance
regardless of whether the source is a web download or an IPK archive.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from jd2021_installer.core.exceptions import (
    NormalizationError,
    ParseError,
    ValidationError,
)
from jd2021_installer.core.models import (
    CinematicTape,
    DanceTape,
    DefaultColors,
    KaraokeTape,
    MapMedia,
    MusicTrackStructure,
    NormalizedMapData,
    SongDescription,
)
from jd2021_installer.parsers.binary_ckd import parse_binary_ckd

logger = logging.getLogger("jd2021.parsers.normalizer")


# ---------------------------------------------------------------------------
# CKD file loading (JSON-first, binary fallback)
# ---------------------------------------------------------------------------

def load_ckd(file_path: str | Path) -> dict | object:
    """Read a CKD file, trying JSON first and falling back to binary.

    Returns either a parsed JSON dict or a typed dataclass from
    :func:`parse_binary_ckd`.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"CKD file not found: {path}")

    raw = path.read_bytes()

    # Try JSON first (strip null padding)
    cleaned = raw.replace(b"\x00", b"").strip()
    try:
        return json.loads(cleaned.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Fall back to binary parser
    return parse_binary_ckd(raw, path.name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prefer_non_legacy(paths: List[str]) -> List[str]:
    """Sort CKD paths so non-legacy (JSON) files come before binary."""
    non_legacy = [p for p in paths if "main_legacy" not in os.path.basename(p).lower()]
    legacy = [p for p in paths if "main_legacy" in os.path.basename(p).lower()]
    return non_legacy + legacy


def _filter_by_codename(
    paths: List[str], codename: Optional[str], base_dir: Optional[str] = None
) -> List[str]:
    """Filter paths to those containing codename as a directory component or in filename."""
    if not codename:
        return paths
    cn_lower = codename.lower()
    filtered = []
    for p in paths:
        rel = (os.path.relpath(p, base_dir) if base_dir else p).replace("\\", "/").lower()
        parts = rel.split("/")
        # Match if codename is a path component OR appears in the filename
        if cn_lower in parts or cn_lower in os.path.basename(p).lower():
            filtered.append(p)
    return filtered


def _find_ckd_files(
    directory: str,
    pattern: str,
    codename: Optional[str] = None,
) -> List[str]:
    """Find CKD files matching a glob pattern, preferring non-legacy.

    If no results are found with codename filtering, falls back to
    searching without the codename filter (handles deeply nested ZIPs).
    """
    from pathlib import Path
    base_path = Path(directory)
    # Using Path.rglob is often more robust than glob.glob with ** on some systems
    paths = [str(p) for p in base_path.rglob(pattern)]
    
    if not paths and "musictrack" in pattern:
        # Extra fallback for musictrack variations
        alt_patterns = ["*TM_MusicTrack*.ckd", "*musictrack*.ckd", "*MusicTrack*.ckd"]
        for alt in alt_patterns:
            paths = [str(p) for p in base_path.rglob(alt)]
            if paths: break

    filtered = _filter_by_codename(paths, codename, directory)
    result = _prefer_non_legacy(filtered)

    # Fallback: if codename filtering removed all candidates, try without it
    if not result and paths:
        logger.debug(
            "CKD search with codename '%s' found 0 results; "
            "falling back to unfiltered (%d candidates)",
            codename, len(paths),
        )
        result = _prefer_non_legacy(paths)

    return result


# ---------------------------------------------------------------------------
# Individual CKD extractors
# ---------------------------------------------------------------------------

def _extract_music_track(
    directory: str, codename: Optional[str] = None
) -> MusicTrackStructure:
    """Find and parse a musictrack CKD → MusicTrackStructure."""
    ckd_paths = _find_ckd_files(directory, "*musictrack*.tpl.ckd", codename)
    if not ckd_paths:
        raise NormalizationError("musictrack.tpl.ckd not found")

    data = load_ckd(ckd_paths[0])

    # Already a typed MusicTrackStructure from binary parser
    if isinstance(data, MusicTrackStructure):
        return data

    # JSON dict → build MusicTrackStructure
    try:
        from jd2021_installer.core.models import MusicSection, MusicSignature
        s = data["COMPONENTS"][0]["trackData"]["structure"]
        res = MusicTrackStructure(
            markers=s["markers"],
            signatures=[
                MusicSignature(beats=sig["beats"], marker=sig["marker"])
                for sig in s.get("signatures", [])
            ],
            sections=[
                MusicSection(section_type=sec["sectionType"], marker=sec["marker"])
                for sec in s.get("sections", [])
            ],
            start_beat=s["startBeat"],
            end_beat=s["endBeat"],
            video_start_time=s["videoStartTime"],
            preview_entry=float(s.get("previewEntry", 0)),
            preview_loop_start=float(s.get("previewLoopStart", 0)),
            preview_loop_end=float(s.get("previewLoopEnd", 0)),
            volume=float(s.get("volume", 0)),
            fade_in_duration=float(s.get("fadeInDuration", 0)),
            fade_in_type=int(s.get("fadeInType", 0)),
            fade_out_duration=float(s.get("fadeOutDuration", 0)),
            fade_out_type=int(s.get("fadeOutType", 0)),
        )

        # V1/V2 unit parity & safety: if videoStartTime is 0 but startBeat is negative, 
        # it's likely a binary CKD that needs synthesis from markers.
        if res.video_start_time == 0.0 and res.start_beat < 0:
            idx = abs(res.start_beat)
            if 0 <= idx < len(res.markers):
                vst = -(res.markers[idx] / 48.0 / 1000.0)
                logger.info("Synthesized video_start_time from markers: %.3f s", vst)
                res.video_start_time = vst
        return res
    except (KeyError, IndexError, TypeError) as exc:
        raise NormalizationError(f"Invalid musictrack JSON: {exc}") from exc


def _extract_song_desc(
    directory: str, codename: Optional[str] = None
) -> SongDescription:
    """Find and parse a songdesc CKD → SongDescription."""
    ckd_paths = _find_ckd_files(directory, "*songdesc*.tpl.ckd", codename)

    if not ckd_paths:
        # Return defaults if songdesc not found
        logger.warning("songdesc.tpl.ckd not found; using defaults")
        return SongDescription(
            map_name=codename or "Unknown",
            title=codename or "Unknown",
            artist="Unknown Artist",
        )

    data = load_ckd(ckd_paths[0])

    if isinstance(data, SongDescription):
        return data

    # JSON dict
    try:
        sd = data["COMPONENTS"][0]
        dc_raw = sd.get("DefaultColors", {})
        dc = DefaultColors()
        if isinstance(dc_raw, dict):
            dc.theme = dc_raw.get("theme", dc.theme)
            dc.lyrics = dc_raw.get("lyrics", dc.lyrics)
            for k, v in dc_raw.items():
                if k.lower() not in ("theme", "lyrics"):
                    dc.extra[k] = v

        return SongDescription(
            map_name=sd.get("MapName", codename or "Unknown"),
            title=sd.get("Title", codename or "Unknown"),
            artist=sd.get("Artist", "Unknown Artist"),
            dancer_name=sd.get("DancerName", "Unknown Dancer"),
            credits=sd.get("Credits", ""),
            num_coach=int(sd.get("NumCoach", 1)),
            main_coach=int(sd.get("MainCoach", -1)),
            difficulty=int(sd.get("Difficulty", 2)),
            sweat_difficulty=int(sd.get("SweatDifficulty", 1)),
            background_type=int(sd.get("backgroundType", sd.get("BackgroundType", 0))),
            lyrics_type=int(sd.get("LyricsType", 0)),
            energy=int(sd.get("Energy", 1)),
            tags=sd.get("Tags", ["Main"]) or ["Main"],
            status=int(sd.get("Status", 3)),
            locale_id=int(sd.get("LocaleID", 4294967295)),
            mojo_value=int(sd.get("MojoValue", 0)),
            jd_version=int(sd.get("JDVersion", 2021)),
            original_jd_version=int(sd.get("OriginalJDVersion", 2021)),
            default_colors=dc,
            phone_images=sd.get("PhoneImages", {}),
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise NormalizationError(f"Invalid songdesc JSON: {exc}") from exc


def _extract_dance_tape(
    directory: str, codename: Optional[str] = None
) -> Optional[DanceTape]:
    """Find and parse a dtape CKD → DanceTape (or None)."""
    ckd_paths = _find_ckd_files(directory, "*dtape*ckd", codename)
    if not ckd_paths:
        return None
    data = load_ckd(ckd_paths[0])
    if isinstance(data, DanceTape):
        return data
    # For JSON dtapes we'd construct from dict; minimal stub
    return None


def _extract_karaoke_tape(
    directory: str, codename: Optional[str] = None
) -> Optional[KaraokeTape]:
    """Find and parse a ktape CKD → KaraokeTape (or None)."""
    ckd_paths = _find_ckd_files(directory, "*ktape*ckd", codename)
    if not ckd_paths:
        return None
    data = load_ckd(ckd_paths[0])
    if isinstance(data, KaraokeTape):
        return data
    return None


def _discover_media(directory: str, codename: Optional[str] = None) -> MapMedia:
    """Scan directory for media assets and populate MapMedia."""
    media = MapMedia()
    dir_path = Path(directory)

    # Video files
    webm_files = list(dir_path.rglob("*.webm"))
    if webm_files:
        # Prefer the highest-quality non-preview video
        main_videos = [f for f in webm_files if "MapPreview" not in f.name
                       and "VideoPreview" not in f.name]
        if main_videos:
            media.video_path = main_videos[0]
        preview_videos = [f for f in webm_files if "MapPreview" in f.name]
        if preview_videos:
            media.map_preview_video = preview_videos[0]

    # Audio files
    ogg_files = [f for f in dir_path.rglob("*.ogg") if "AudioPreview" not in f.name]
    if ogg_files:
        media.audio_path = ogg_files[0]
    else:
        # Fallback: look for Xbox 360 .wav.ckd (XMA2) and auto-decode
        wav_ckd_files = [
            f for f in dir_path.rglob("*.wav.ckd")
            if "audiopreview" not in f.name.lower()
        ]
        if wav_ckd_files:
            from jd2021_installer.installers.media_processor import (
                decode_xma2_audio,
                is_xma2_audio,
            )
            ckd_src = wav_ckd_files[0]
            decoded_wav = ckd_src.parent / (ckd_src.stem.replace(".wav", "") + "_decoded.wav")
            if decoded_wav.exists():
                logger.info("Using previously decoded audio: %s", decoded_wav.name)
                media.audio_path = decoded_wav
            elif is_xma2_audio(ckd_src):
                try:
                    media.audio_path = decode_xma2_audio(ckd_src, decoded_wav)
                except Exception as e:
                    logger.warning(
                        "Failed to decode X360 audio %s: %s", ckd_src.name, e
                    )

    # Cover images
    for ext in ("*.jpg", "*.png", "*.tga"):
        covers = [f for f in dir_path.rglob(ext) if "cover" in f.name.lower()]
        if covers:
            media.cover_path = covers[0]
            break

    # Coach images
    for ext in ("*.png", "*.tga"):
        coaches = sorted(
            f for f in dir_path.rglob(ext) if "coach_" in f.name.lower()
        )
        if coaches:
            media.coach_images = coaches
            break

    # Pictogram directory
    picto_dirs = list(dir_path.rglob("pictos"))
    if picto_dirs:
        media.pictogram_dir = picto_dirs[0]

    # Moves directory
    move_dirs = [d for d in dir_path.rglob("moves") if d.is_dir()]
    if move_dirs:
        media.moves_dir = move_dirs[0]

    return media


# ---------------------------------------------------------------------------
# Main normalizer entry point
# ---------------------------------------------------------------------------

def normalize(
    directory: str | Path,
    codename: Optional[str] = None,
) -> NormalizedMapData:
    """Normalize an extracted directory into a canonical NormalizedMapData.

    This is the single public entry-point for the normalizer pipeline.
    Works identically whether the directory was populated by the web
    extractor or the IPK extractor.

    Args:
        directory: Path to the directory containing extracted files.
        codename:  Optional map codename for filtering in bundle IPKs.

    Returns:
        A fully-populated ``NormalizedMapData`` instance.

    Raises:
        NormalizationError: If critical data (musictrack) is missing.
        ValidationError:    If the normalized data fails validation.
    """
    directory = str(directory)

    music_track = _extract_music_track(directory, codename)
    song_desc = _extract_song_desc(directory, codename)
    dance_tape = _extract_dance_tape(directory, codename)
    karaoke_tape = _extract_karaoke_tape(directory, codename)
    media = _discover_media(directory, codename)

    # Infer codename from song_desc if not provided
    effective_codename = codename or song_desc.map_name

    result = NormalizedMapData(
        codename=effective_codename,
        song_desc=song_desc,
        music_track=music_track,
        dance_tape=dance_tape,
        karaoke_tape=karaoke_tape,
        media=media,
        source_dir=Path(directory),
    )

    # Validation
    if not result.music_track.markers:
        raise ValidationError(
            f"MusicTrack for '{effective_codename}' has no beat markers"
        )

    logger.info(
        "Normalized '%s': %d markers, %d dance clips, %d karaoke clips",
        effective_codename,
        len(result.music_track.markers),
        len(result.dance_tape.clips) if result.dance_tape else 0,
        len(result.karaoke_tape.clips) if result.karaoke_tape else 0,
    )

    return result
