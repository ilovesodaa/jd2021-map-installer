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
    KaraokeClip,
    KaraokeTape,
    MapMedia,
    MapSync,
    MotionClip,
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
        # V1 Parity: In Readjust mode, we might not have the original CKD, 
        # but we can still work with the .trk in normalization.
        return None

    data = load_ckd(ckd_paths[0])

    # Already a typed MusicTrackStructure from binary parser
    if isinstance(data, MusicTrackStructure):
        return data

    # JSON dict → build MusicTrackStructure
    try:
        from jd2021_installer.core.models import MusicSection, MusicSignature
        if not isinstance(data, dict):
            return MusicTrackStructure()
        s = data.get("COMPONENTS", [{}])[0].get("trackData", {}).get("structure", {})

        vst = s.get("videoStartTime", 0.0)
        # V1 Parity: Auto-detect units (ticks vs seconds)
        if abs(vst) > 1000:
            vst /= 48000.0
            logger.debug("Detected videoStartTime in ticks; converted to %.6fs", vst)
            
        res = MusicTrackStructure(
            markers=s.get("markers", []),
            signatures=[
                MusicSignature(beats=sig["beats"], marker=sig["marker"])
                for sig in s.get("signatures", [])
            ],
            sections=[
                MusicSection(section_type=sec["sectionType"], marker=sec["marker"])
                for sec in s.get("sections", [])
            ],
            start_beat=s.get("startBeat", 0),
            end_beat=s.get("endBeat", 0),
            video_start_time=vst,
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

    if not isinstance(data, dict):
        return SongDescription(map_name=codename or "unknown")

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
    """Scan directory for media assets and populate MapMedia.
    
    Ported from V1 source_analysis.py recursive picking logic.
    """
    media = MapMedia()
    dir_path = Path(directory)
    codename_low = codename.lower() if codename else None

    # 1. Video files (.webm)
    webms = list(dir_path.rglob("*.webm"))
    if webms:
        # Exclusion list for main video
        main_videos = []
        for w in webms:
            w_name = w.name.lower()
            if any(k in w_name for k in ("mappreview", "videopreview", "preview")):
                if "preview" in w_name and not media.map_preview_video:
                    media.map_preview_video = w
                continue
            main_videos.append(w)
        
        if main_videos:
            # Priority: 1. codename.webm, 2. codename in path, 3. first available
            best_video = main_videos[0]
            if codename_low:
                for v in main_videos:
                    if v.name.lower() == f"{codename_low}.webm":
                        best_video = v
                        break
                    if codename_low and codename_low in str(v).lower().replace("\\", "/"):
                        best_video = v
            media.video_path = best_video

    # 2. Audio files (.ogg, .wav, .wav.ckd)
    # V1 Priority: 1. codename.ext, 2. *.ext
    # Recursive search with strict exclusions
    audio_patterns = ["*.ogg", "*.wav", "*.wav.ckd"]
    audio_found = False
    
    for pattern in audio_patterns:
        if audio_found: break
        
        candidates = list(dir_path.rglob(pattern))
        if not candidates: continue
        
        # Prune exclusions: amb, autodance, preview
        filtered = []
        for c in candidates:
            c_path = str(c).lower().replace("\\", "/")
            c_name = c.name.lower()
            if any(k in c_path for k in ("/amb/", "/autodance/", "audiopreview")):
                continue
            if c_name.startswith("amb_") or c_name.startswith("ad_"):
                continue
            filtered.append(c)
        
        if not filtered: continue
        
        # Pick best candidate
        best_audio = filtered[0]
        if codename_low:
            # 1. Exact name match
            for a in filtered:
                if a.stem.lower() == codename_low or a.name.lower() == f"{codename_low}.wav.ckd":
                    best_audio = a
                    break
            else:
                # 2. Path match
                for a in filtered:
                    if f"/{codename_low}/" in str(a).lower().replace("\\", "/"):
                        best_audio = a
                        break
        
        # Handle CKD extraction
        if best_audio.name.lower().endswith(".ckd"):
            from jd2021_installer.installers.media_processor import extract_ckd_audio_v1
            decoded = extract_ckd_audio_v1(best_audio, best_audio.parent)
            if decoded:
                media.audio_path = Path(decoded)
                audio_found = True
        else:
            media.audio_path = best_audio
            audio_found = True

    # 3. Cover images
    for ext in ("*.jpg", "*.png", "*.tga", "*.ckd"):
        covers = [f for f in dir_path.rglob(ext) if "cover" in f.name.lower()]
        if covers:
            media.cover_path = covers[0]
            break

    # 4. Coach images
    for ext in ("*.png", "*.tga", "*.ckd"):
        coaches = sorted(f for f in dir_path.rglob(ext) if "coach_" in f.name.lower())
        if coaches:
            media.coach_images = coaches
            break

    # 5. Pictogram directory
    # V1 Parity: Look for 'pictos' folder OR any folder containing '*picto*.ckd'
    media.pictogram_dir = None
    picto_candidates = [d for d in dir_path.rglob("*") if d.is_dir() and "picto" in d.name.lower()]
    if picto_candidates:
        # Prefer 'pictos' or 'timeline/pictos'
        for d in picto_candidates:
            if d.name.lower() == "pictos":
                media.pictogram_dir = d
                break
        else:
            media.pictogram_dir = picto_candidates[0]
    
    if not media.pictogram_dir:
        # Check for folders containing picto CKDs if 'pictos' folder name doesn't exist
        for d in [p.parent for p in dir_path.rglob("*picto*.ckd")]:
            media.pictogram_dir = d
            break

    # 6. Moves directory
    media.moves_dir = None
    move_candidates = [d for d in dir_path.rglob("*") if d.is_dir() and "moves" in d.name.lower()]
    if move_candidates:
        media.moves_dir = move_candidates[0]

    return media


def normalize_sync(
    music_track: Optional[MusicTrackStructure], 
    is_html_source: bool = False,
    existing_trk_path: Optional[Path] = None,
) -> MapSync:
    """Determine the optimal audio/video sync offsets.
    
    Ported from V1 source_analysis.py logic.
    - HTML/Fetch maps get +85ms calibration.
    - IPK/Readjust maps inherit existing videoStartTime.
    """
    from jd2021_installer.parsers.binary_ckd import calculate_marker_preroll
    import re
    
    audio_ms = 0.0
    video_ms = 0.0

    # Readjust mode: if .trk exists in source (e.g. from previously installed map), use it.
    if existing_trk_path and existing_trk_path.exists():
        try:
            content = existing_trk_path.read_text(encoding="utf-8")
            match = re.search(r"videoStartTime\s*=\s*([-+]?\d*\.?\d+)", content)
            if match:
                vst = float(match.group(1))
                # Auto-fix if ticks were accidentally written to the trk previously
                if abs(vst) > 1000:
                    vst /= 48000.0
                video_ms = vst * 1000.0
                logger.info("Readjust mode: inherited videoStartTime %.6fs from existing .trk", vst)
                return MapSync(audio_ms=audio_ms, video_ms=video_ms)
        except Exception as e:
            logger.warning("Failed to read existing .trk for readjust: %s", e)

    # If no existing .trk or failed to read, proceed with standard logic
    if music_track:
        video_ms = music_track.video_start_time * 1000.0

        if is_html_source:
            # Fetch/HTML mode (OGG)
            prms = calculate_marker_preroll(music_track.markers, music_track.start_beat, include_calibration=False)
            if prms is not None:
                audio_ms = -(prms + 85.0)
                if video_ms == 0.0:
                    video_ms = -prms
                logger.info("Fetch/HTML sync: audio_offset=%.3f ms (incl. 85ms calib), video_offset=%.3f ms", audio_ms, video_ms)
            else:
                audio_ms = video_ms
                logger.info("Fetch/HTML sync (no markers): using video_start_time for both = %.3f ms", video_ms)
        else:
            # IPK mode (WAV/CKD)
            audio_ms = 0.0
            if video_ms == 0.0:
                # Fallback for missing VST in binary CKDs
                prms = calculate_marker_preroll(music_track.markers, music_track.start_beat, include_calibration=False)
                if prms is not None:
                    video_ms = -prms
                    logger.info("IPK sync (synthesized): audio_offset=0, video_offset=%.3f ms", video_ms)
            else:
                logger.info("IPK sync (pre-synced): audio_offset=0, video_offset=%.3f ms", video_ms)
    else:
        logger.warning("No music_track provided to normalize_sync, returning default 0 offsets.")

    return MapSync(audio_ms=audio_ms, video_ms=video_ms)


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
    source_dir = Path(directory)

    # 1. & 2. Extract basic metadata
    try:
        music_track = _extract_music_track(directory, codename)
    except NormalizationError:
        music_track = None

    song_desc = _extract_song_desc(directory, codename)
    dance_tape = _extract_dance_tape(directory, codename)
    karaoke_tape = _extract_karaoke_tape(directory, codename)
    media = _discover_media(directory, codename)

    # Infer codename from song_desc if not provided
    effective_codename = codename or song_desc.map_name

    # Determine default sync values like V1
    # Ported from V1 map_installer.py Step 06
    is_html_source = any(source_dir.glob("*.html")) or any(source_dir.glob("**/assets.html"))

    # 5. Calculate effective video start time (with V1-style fallbacks)
    sync_data = normalize_sync(
        music_track, 
        is_html_source=is_html_source,
        existing_trk_path=source_dir / "Audio" / f"{effective_codename}.trk"
    )

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
