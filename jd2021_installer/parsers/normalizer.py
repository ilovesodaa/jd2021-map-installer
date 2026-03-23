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

    # Try JSON first (strip null padding/garbage)
    try:
        content = raw.decode("utf-8", errors="ignore").strip().replace("\x00", "")
        # Handle cases where there is extra data after the JSON object
        return json.JSONDecoder().raw_decode(content)[0]
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
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
        # Normalize relative path for easier matching
        rel = (os.path.relpath(p, base_dir) if base_dir else p).replace("\\", "/").lower()
        parts = rel.split("/")
        # Match if codename is ANY component of the path OR appears in the filename
        if any(cn_lower in part for part in parts) or cn_lower in os.path.basename(p).lower():
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
    if isinstance(data, dict):
        # Best-effort clip count for JSON dtapes (Fetch/HTML mode maps)
        clips = []
        for comp in data.get("COMPONENTS", []):
            if "JD_TapeComponent_Template" in comp:
                tape_data = comp["JD_TapeComponent_Template"].get("tape", {})
                for clip in tape_data.get("clips", []):
                    # Minimal stub to allow counting in logs/UI
                    clips.append(MotionClip(id=0, track_id=0, is_active=1, start_time=0, duration=0, classifier_path=""))
        return DanceTape(clips=clips, map_name=codename or "Unknown")
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
    if isinstance(data, dict):
        # Best-effort clip count for JSON ktapes
        clips = []
        for comp in data.get("COMPONENTS", []):
            if "JD_TapeComponent_Template" in comp:
                tape_data = comp["JD_TapeComponent_Template"].get("tape", {})
                for clip in tape_data.get("clips", []):
                    clips.append(KaraokeClip(id=0, track_id=0, is_active=1, start_time=0, duration=0, lyrics="", pitch=0))
        return KaraokeTape(clips=clips, map_name=codename or "Unknown")
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

    # 1. Try exact codename match at top level (.ogg then .wav)
    audio_found = False
    if codename:
        for ext in (".ogg", ".wav"):
            candidate = dir_path / f"{codename}{ext}"
            if candidate.is_file():
                media.audio_path = candidate
                logger.debug("Selected audio (exact match): %s", candidate.name)
                audio_found = True
                break

    # 2. Glob for any .ogg at top level (excluding previews)
    if not audio_found:
        oggs = [f for f in dir_path.glob("*.ogg") if "audiopreview" not in f.name.lower()]
        if oggs:
            if codename:
                lower = codename.lower()
                matches = [p for p in oggs if p.name.lower().startswith(lower)]
                if matches:
                    media.audio_path = matches[0]
                    logger.debug("Selected audio (top-level ogg match): %s", media.audio_path.name)
                    audio_found = True
            if not audio_found:
                media.audio_path = oggs[0]
                logger.debug("Selected audio (top-level ogg): %s", media.audio_path.name)
                audio_found = True

    # 3. Glob for any .wav at top level (excluding previews)
    if not audio_found:
        wavs = [f for f in dir_path.glob("*.wav") if "audiopreview" not in f.name.lower()]
        if wavs:
            if codename:
                lower = codename.lower()
                matches = [p for p in wavs if p.name.lower().startswith(lower)]
                if matches:
                    media.audio_path = matches[0]
                    logger.debug("Selected audio (top-level wav match): %s", media.audio_path.name)
                    audio_found = True
            if not audio_found:
                media.audio_path = wavs[0]
                logger.debug("Selected audio (top-level wav): %s", media.audio_path.name)
                audio_found = True

    # 4. Recursive search (for extracted IPK structures with nested dirs)
    if not audio_found:
        patterns = [("*.ogg", False), ("*.wav", False), ("*.wav.ckd", True)]
        for pattern, is_ckd in patterns:
            hits = list(dir_path.rglob(pattern))
            if not hits: continue
            
            filtered_hits = []
            for h in hits:
                h_low = str(h).lower().replace("\\", "/")
                h_name_low = h.name.lower()
                if "audiopreview" in h_name_low or "/amb/" in h_low or "/autodance/" in h_low:
                    continue
                if is_ckd and h_name_low.startswith("amb_"):
                    continue
                filtered_hits.append(h)
            
            if not filtered_hits: continue
                
            final_hits = []
            if codename:
                lower = codename.lower()
                final_hits = [p for p in filtered_hits if p.name.lower().startswith(lower)]
                if not final_hits:
                    final_hits = [p for p in filtered_hits if f"/{lower}/" in str(p).lower().replace("\\", "/")]
            
            if not final_hits:
                final_hits = filtered_hits

            selected = final_hits[0]
            if is_ckd:
                from jd2021_installer.installers.media_processor import extract_ckd_audio_v1
                decoded = extract_ckd_audio_v1(selected, selected.parent)
                if decoded:
                    media.audio_path = Path(decoded)
                    logger.debug("Selected and extracted audio: %s", media.audio_path.name)
                    audio_found = True
                    break
            else:
                media.audio_path = selected
                logger.debug("Selected audio (recursive): %s", media.audio_path.name)
                audio_found = True
                break

    # 5. Cover images
    for ext in ("*.jpg", "*.png", "*.tga", "*.tga.ckd", "*.jpg.ckd", "*.png.ckd"):
        covers = [f for f in dir_path.rglob(ext) if "cover" in f.name.lower()]
        if covers:
            media.cover_path = covers[0]
            break

    # 6. Coach images
    for ext in ("*.png", "*.tga", "*.png.ckd", "*.tga.ckd"):
        coaches = sorted(f for f in dir_path.rglob(ext) if "coach_" in f.name.lower())
        if coaches:
            media.coach_images = coaches
            break

    # 7. Pictogram directory
    # V1 parity: search for 'pictos' or 'timeline/pictos'
    picto_candidates = []
    for pattern in ("pictos", "Pictos", "PICTOS"):
        picto_candidates.extend([d for d in dir_path.rglob(pattern) if d.is_dir()])
    
    if picto_candidates:
        # Prefer the one closest to the codename if possible
        if codename:
            lower = codename.lower()
            filtered = [d for d in picto_candidates if lower in str(d).lower().replace("\\", "/")]
            media.pictogram_dir = filtered[0] if filtered else picto_candidates[0]
        else:
            media.pictogram_dir = picto_candidates[0]

    # 8. Moves directory
    move_dirs = [d for d in dir_path.rglob("moves") if d.is_dir()]
    if not move_dirs:
        move_dirs = [d for d in dir_path.rglob("Moves") if d.is_dir()]
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

    from jd2021_installer.core.models import MapSync
    from jd2021_installer.parsers.binary_ckd import calculate_marker_preroll

    # Determine default sync values like V1
    video_ms = music_track.video_start_time * 1000.0
    audio_ms = 0.0
    
    # If the map source is IPK, the audio and video are pre-synced.
    # We detect it by checking the directory structure or audio format.
    # Check for HTML files in the immediate root or mapDownloads subfolder
    dir_path = Path(directory)
    is_html_source = any(dir_path.glob("*.html")) or any(dir_path.glob("**/assets.html"))
    
    is_ipk = not is_html_source and (
        (dir_path / "world").exists() or 
        (dir_path / "World").exists() or 
        any(dir_path.rglob("*.wav.ckd")) or
        bool(media.audio_path and media.audio_path.suffix.lower() == ".wav")
    )
    
    if is_ipk:
        audio_ms = 0.0
        logger.info("IPK map detected: forcing audio_offset to 0.0 ms")
        
        # V1 Parity: If videoStartTime is 0.0, it might be a missing value.
        # Use markers to calculate a reasonable video offset if available.
        # IPK synthesis MUST be negative and NO calibration (vst = -preroll).
        if video_ms == 0.0:
            preroll = calculate_marker_preroll(music_track.markers, music_track.start_beat, include_calibration=False)
            if preroll is not None:
                video_ms = -preroll
                logger.info("IPK map (missing videoStartTime): marker-based video_offset=%.3f ms", video_ms)
    else:
        # Fetch/HTML map
        preroll_audio = calculate_marker_preroll(music_track.markers, music_track.start_beat, include_calibration=True)
        preroll_video = calculate_marker_preroll(music_track.markers, music_track.start_beat, include_calibration=False)
        
        if preroll_audio is not None:
            audio_ms = -preroll_audio
            logger.info("Fetch/HTML map detected: marker-based audio_offset=%.3f ms", audio_ms)
            if video_ms == 0.0:
                video_ms = -preroll_video
                logger.info("Fetch/HTML map (missing videoStartTime): marker-based video_offset=%.3f ms", video_ms)
        else:
            audio_ms = video_ms
            logger.info("Fetch/HTML map detected (no markers): audio_offset=%.3f ms", audio_ms)

    sync_data = MapSync(audio_ms=audio_ms, video_ms=video_ms)

    # V1 Parity: Detect whether the source contains real autodance data.
    # Many sources ship minimal stub CKDs that should be ignored.
    has_autodance = False
    ad_tpls = _find_ckd_files(directory, "*autodance*.tpl.ckd", codename)
    if ad_tpls:
        try:
            ad_data = load_ckd(ad_tpls[0])
            # Look for markers of real data (recording structure, video structure, or events)
            ad_str = str(ad_data).lower()
            if any(k in ad_str for k in ("recording_structure", "video_structure", "playback_events")):
                has_autodance = True
        except Exception:
            pass
    
    if not has_autodance:
        # Check for separate autodance data files as fallback
        for ext in ("adtape", "advideo", "adrecording"):
            if _find_ckd_files(directory, f"*.{ext}.ckd", codename):
                has_autodance = True
                break

    if has_autodance:
        logger.info("Real autodance data detected for '%s'", effective_codename)

    result = NormalizedMapData(
        codename=effective_codename,
        song_desc=song_desc,
        music_track=music_track,
        dance_tape=dance_tape,
        karaoke_tape=karaoke_tape,
        media=media,
        sync=sync_data,
        video_start_time_override=sync_data.video_ms / 1000.0,
        source_dir=Path(directory),
        has_autodance=has_autodance,
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
