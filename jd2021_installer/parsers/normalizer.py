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
import re
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
    SoundSetClip,
    TapeReferenceClip,
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

    # Try JSON first (strip null padding) using strict UTF-8 decoding.
    try:
        content = raw.replace(b"\x00", b"").strip().decode("utf-8")
        return json.loads(content)
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
    """Filter paths to codename-scoped matches (exact path component or safe filename prefix)."""
    if not codename:
        return paths
    cn_lower = codename.lower()

    def _path_has_codename_component(path_str: str) -> bool:
        rel = (os.path.relpath(path_str, base_dir) if base_dir else path_str).replace("\\", "/").lower()
        parts = [p for p in rel.split("/") if p]
        return cn_lower in parts

    def _filename_matches_codename(path_str: str) -> bool:
        name = os.path.basename(path_str).lower()
        # Prevent collisions like "apt" matching "aptalt".
        return bool(re.match(rf"^{re.escape(cn_lower)}(?:[^a-z0-9]|$)", name))

    filtered = []
    for p in paths:
        if _path_has_codename_component(p) or _filename_matches_codename(p):
            filtered.append(p)
    return filtered


def _resolve_map_source_dir(directory: Path, codename: Optional[str]) -> Path:
    """Resolve the most likely map-local directory for a codename within extracted sources."""
    if not codename:
        return directory

    cn_lower = codename.lower()
    parts = [p.lower() for p in directory.parts]
    if cn_lower in parts:
        return directory

    candidates: List[Path] = []

    for p in directory.rglob("*"):
        if not p.is_dir():
            continue
        p_parts = [x.lower() for x in p.parts]
        if cn_lower not in p_parts:
            continue

        try:
            idx = p_parts.index("world")
            if idx + 2 < len(p_parts) and p_parts[idx + 1] == "maps" and p_parts[idx + 2] == cn_lower:
                candidates.append(p)
                continue
            if idx + 2 < len(p_parts) and p_parts[idx + 1].startswith("jd") and p_parts[idx + 2] == cn_lower:
                candidates.append(p)
                continue
        except ValueError:
            pass

        if p.name.lower() == cn_lower:
            candidates.append(p)

    if not candidates:
        return directory

    # Prefer shallowest candidate relative to extraction root.
    candidates.sort(key=lambda c: len(c.relative_to(directory).parts))
    resolved = candidates[0]
    logger.debug("Resolved map source dir for '%s': %s", codename, resolved)
    return resolved


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

    # V1 Parity: STRICT SCOPING for bundles.
    # If a codename was specified but scoped search returned 0 while candidates exist, 
    # we only fall back if there's a single candidate (meaning codename inference was just slightly off).
    # If multiple candidates exist but none match, it's safer to return 0 than to pick a random map.
    if not result and paths:
        if not codename or len(paths) == 1:
            logger.debug(
                "CKD search for '%s' returned 0 results; falling back to unfiltered (candidate count: %d)",
                codename or "None",
                len(paths),
            )
            result = _prefer_non_legacy(paths)
        else:
            logger.warning(
                "CKD search for '%s' returned 0 results in bundle (%d other candidates found). Skipping to avoid mis-assignment.",
                codename,
                len(paths),
            )

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

    if isinstance(data, MusicTrackStructure):
        res = data
    elif isinstance(data, dict):
        # JSON dict → build MusicTrackStructure
        try:
            from jd2021_installer.core.models import MusicSection, MusicSignature
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
        except (KeyError, IndexError, TypeError) as exc:
            raise NormalizationError(f"Invalid musictrack JSON: {exc}") from exc
    else:
        return MusicTrackStructure()

    # V1/V2 unit parity & safety: if videoStartTime is 0 but startBeat is negative, 
    # it's likely a binary CKD that needs synthesis from markers.
    if res.video_start_time == 0.0 and res.start_beat < 0:
        idx = abs(res.start_beat)
        if 0 <= idx < len(res.markers):
            # V1 Parity: NO marker offset for videoStartTime synthesis
            vst = -(res.markers[idx] / 48.0 / 1000.0)
            logger.info("Synthesized video_start_time from markers: %.3f s", vst)
            res.video_start_time = vst
    return res


def _find_source_trk_path(source_dir: Path, codename: str) -> Optional[Path]:
    """Locate the source .trk file for a map codename (case-insensitive)."""
    direct = source_dir / "Audio" / f"{codename}.trk"
    if direct.exists():
        return direct

    codename_lower = codename.lower()
    audio_dir = source_dir / "Audio"
    if audio_dir.exists():
        for candidate in audio_dir.glob("*.trk"):
            if candidate.stem.lower() == codename_lower:
                return candidate

    for candidate in source_dir.rglob("*.trk"):
        if candidate.stem.lower() == codename_lower:
            return candidate

    return None


def _read_musictrack_fields_from_trk(trk_path: Path) -> Dict[str, float]:
    """Read key timing fields from a UbiArt .trk text file."""
    if not trk_path.exists():
        return {}

    try:
        content = trk_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    fields: Dict[str, float] = {}
    number_pattern = r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
    for key in ("videoStartTime", "previewEntry", "previewLoopStart", "previewLoopEnd"):
        match = re.search(rf"{key}\s*=\s*{number_pattern}", content)
        if match:
            try:
                fields[key] = float(match.group(1))
            except ValueError:
                continue

    return fields


def _merge_preview_fields_from_trk(music_track: Optional[MusicTrackStructure], trk_path: Optional[Path]) -> None:
    """Override preview timing values from .trk when present.

    Some source CKDs (notably legacy console variants) omit or zero preview
    loop fields even when the source .trk contains valid values.
    """
    if music_track is None or trk_path is None:
        return

    trk_fields = _read_musictrack_fields_from_trk(trk_path)
    if not trk_fields:
        return

    if "previewEntry" in trk_fields:
        music_track.preview_entry = trk_fields["previewEntry"]
    if "previewLoopStart" in trk_fields:
        music_track.preview_loop_start = trk_fields["previewLoopStart"]
    if "previewLoopEnd" in trk_fields:
        music_track.preview_loop_end = trk_fields["previewLoopEnd"]

    logger.info(
        "Merged preview timing from source .trk (%s): entry=%.3f start=%.3f end=%.3f",
        trk_path,
        music_track.preview_entry,
        music_track.preview_loop_start,
        music_track.preview_loop_end,
    )


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


def _extract_cinematic_tape(
    directory: str, codename: Optional[str] = None
) -> Optional[CinematicTape]:
    """Find and parse a mainsequence/cinematic tape CKD -> CinematicTape (or None)."""
    ckd_paths = _find_ckd_files(directory, "*mainsequence*tape.ckd", codename)
    if not ckd_paths:
        ckd_paths = _find_ckd_files(directory, "*mainsequence*.tape.ckd", codename)
    if not ckd_paths:
        ckd_paths = _find_ckd_files(directory, "*mainsequence*.ckd", codename)
    if not ckd_paths:
        return None

    data = load_ckd(ckd_paths[0])
    if isinstance(data, CinematicTape):
        return data

    if not isinstance(data, dict):
        return None

    clips = []
    tape_dict = data
    if "Clips" not in tape_dict and "COMPONENTS" in tape_dict:
        # Some JSON CKD payloads store tape data under component wrappers.
        for comp in tape_dict.get("COMPONENTS", []):
            if "JD_TapeComponent_Template" in comp:
                tape_dict = comp["JD_TapeComponent_Template"].get("tape", tape_dict)
                break

    for raw_clip in tape_dict.get("Clips", []):
        if not isinstance(raw_clip, dict):
            continue

        clip_class = str(raw_clip.get("__class", "")).lower()
        if clip_class == "soundsetclip":
            clips.append(
                SoundSetClip(
                    id=int(raw_clip.get("Id", 0)),
                    track_id=int(raw_clip.get("TrackId", 0)),
                    is_active=int(raw_clip.get("IsActive", 1)),
                    start_time=int(raw_clip.get("StartTime", 0)),
                    duration=int(raw_clip.get("Duration", 0)),
                    sound_set_path=str(raw_clip.get("SoundSetPath", "")),
                    sound_channel=int(raw_clip.get("SoundChannel", 0)),
                    start_offset=int(raw_clip.get("StartOffset", 0)),
                    stops_on_end=int(raw_clip.get("StopsOnEnd", 0)),
                    accounted_for_duration=int(raw_clip.get("AccountedForDuration", 0)),
                )
            )
        elif clip_class == "tapereferenceclip":
            clips.append(
                TapeReferenceClip(
                    id=int(raw_clip.get("Id", 0)),
                    track_id=int(raw_clip.get("TrackId", 0)),
                    is_active=int(raw_clip.get("IsActive", 1)),
                    start_time=int(raw_clip.get("StartTime", 0)),
                    duration=int(raw_clip.get("Duration", 0)),
                    path=str(raw_clip.get("Path", "")),
                    loop=int(raw_clip.get("Loop", 0)),
                )
            )

    return CinematicTape(
        clips=clips,
        map_name=str(tape_dict.get("MapName", codename or "Unknown")),
        soundwich_event=str(tape_dict.get("SoundwichEvent", "")),
    )


def _discover_media(directory: str, codename: Optional[str] = None, search_root: Optional[str] = None) -> MapMedia:
    """Scan directory (and optional search_root) for media assets and populate MapMedia.
    
    Ported from V1 source_analysis.py recursive picking logic.
    """
    media = MapMedia()
    dir_path = Path(directory)
    # If search_root is provided (e.g. root of a bundle IPK), use it for recursive scans
    bg_search_dir = Path(search_root) if search_root else dir_path
    codename_low = codename.lower() if codename else None

    def _path_has_codename_component(path: Path) -> bool:
        if not codename_low:
            return True
        parts = [p.lower() for p in path.as_posix().split("/") if p]
        return codename_low in parts

    def _filename_matches_codename(path: Path) -> bool:
        if not codename_low:
            return True
        return bool(re.match(rf"^{re.escape(codename_low)}(?:[^a-z0-9]|$)", path.name.lower()))

    # 1. Video files (.webm)
    # V1 Parity: prioritize quality suffixes and codename match. Scan both local and search_root.
    SUPPORTED_QUALITIES = ["ULTRA_HD", "ULTRA", "HIGH_HD", "HIGH", "MID_HD", "MID", "LOW_HD", "LOW"]
    webms = list(dir_path.rglob("*.webm"))
    if search_root and bg_search_dir != dir_path:
        webms.extend(list(bg_search_dir.rglob("*.webm")))
    
    if webms:
        main_videos = []
        for w in webms:
            w_name = w.name.lower()
            if any(k in w_name for k in ("mappreview", "videopreview", "preview")):
                if "preview" in w_name and not media.map_preview_video:
                    media.map_preview_video = w
                continue
            main_videos.append(w)
        
        if main_videos:
            # Filter by codename first if in bundle
            if codename_low:
                matches = [v for v in main_videos if _filename_matches_codename(v)]
                if not matches:
                    # V1 Parity: Path-based scoping for bundle IPKs (e.g. world/maps/MapName/videos/MapName.webm)
                    matches = [v for v in main_videos if _path_has_codename_component(v)]
                
                if matches:
                    main_videos = matches
                elif len(main_videos) > 1:
                    # If we have multiple videos but none match the codename, we are likely in a bundle
                    # and picking a random video is dangerous.
                    logger.warning("No video match for codename %s in multi-map bundle; skipping video discovery", codename)
                    main_videos = []
            
            if main_videos:
                # Priority: 1. Requested quality suffix, 2. any quality suffix, 3. first available
                best_video = main_videos[0]
                found_quality = False
                for q in SUPPORTED_QUALITIES:
                    suffix = f"_{q}.webm"
                    for v in main_videos:
                        if v.name.upper().endswith(suffix):
                            best_video = v
                            found_quality = True
                            break
                    if found_quality: break
                
                media.video_path = best_video

    # 2. Audio files (.ogg, .wav, .wav.ckd)
    # V1 Priority: .ogg > .wav > .wav.ckd
    audio_found = False

    def _audio_base_name(path: Path) -> str:
        name = path.name.lower()
        for suffix in (".wav.ckd", ".ogg.ckd", ".wav", ".ogg", ".ckd"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return path.stem.lower()

    for ext_pattern in ("*.ogg", "*.wav", "*.wav.ckd"):
        if audio_found: break
        
        candidates = list(dir_path.rglob(ext_pattern))
        if search_root and bg_search_dir != dir_path:
            candidates.extend(list(bg_search_dir.rglob(ext_pattern)))
        if candidates:
            # Keep first-seen order while de-duplicating between both scans.
            candidates = list(dict.fromkeys(candidates))
        if not candidates: continue
        
        # Prune exclusions: amb, autodance, preview
        filtered = []
        for c in candidates:
            c_path = str(c).lower().replace("\\", "/")
            c_name = c.name.lower()
            # Strict V1 exclusions
            if any(k in c_path for k in ("/amb/", "/autodance/", "audiopreview", "mappreview")):
                continue
            if c_name.startswith("amb_") or c_name.startswith("ad_"):
                continue
            filtered.append(c)
        
        if not filtered: continue
        
        # Codename scoping
        if codename_low:
            exact_name_matches = [a for a in filtered if _audio_base_name(a) == codename_low]
            if exact_name_matches:
                matches = exact_name_matches
            else:
                matches = [a for a in filtered if _filename_matches_codename(a)]
            if not matches:
                # Path-based scoping for deeply nested IPK structures
                matches = [a for a in filtered if _path_has_codename_component(a)]
            if matches:
                filtered = matches
            else:
                # If we're in a bundle and this extension didn't match codename, skip it
                continue
        
        best_audio = filtered[0]
        # Handle CKD extraction
        if best_audio.name.lower().endswith(".ckd"):
            from jd2021_installer.installers.media_processor import extract_ckd_audio_v1

            decoded = extract_ckd_audio_v1(best_audio, best_audio.parent)
            if decoded:
                media.audio_path = Path(decoded)
                audio_found = True
            else:
                # Keep the cooked source as a fallback so install-time conversion can
                # retry extraction/decoding instead of failing as "audio missing".
                media.audio_path = best_audio
                audio_found = True
                logger.warning(
                    "Audio CKD decode deferred for '%s'; keeping source file: %s",
                    codename or "unknown",
                    best_audio.name,
                )
        else:
            media.audio_path = best_audio
            audio_found = True

    # 3. & 4. Images (Cover/Coach/Banner/Background)
    # Collect only texture-like files. Do NOT include generic *.ckd,
    # otherwise actor files like "*_cover_generic.act.ckd" can be selected.
    all_media_files: List[Path] = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.tga", "*.jpg.ckd", "*.jpeg.ckd", "*.png.ckd", "*.tga.ckd"):
        all_media_files.extend(list(dir_path.rglob(ext)))
        if search_root and bg_search_dir != dir_path:
            all_media_files.extend(list(bg_search_dir.rglob(ext)))
    if all_media_files:
        # Preserve scan order while removing duplicates from merged roots.
        all_media_files = list(dict.fromkeys(all_media_files))

    def _get_best_asset(keyword: str, files: List[Path]) -> Optional[Path]:
        candidates = [f for f in files if keyword in f.name.lower()]
        if not candidates:
            return None
        
        # Priority 1: Exact codename match in filename
        if codename_low:
            exact_matches = [c for c in candidates if _filename_matches_codename(c)]
            if exact_matches:
                return exact_matches[0]
            
            # Priority 2: Codename in parent directory path
            path_matches = [c for c in candidates if _path_has_codename_component(c)]
            if path_matches:
                return path_matches[0]
        
        # Priority 3: First available (fallback)
        # V1 Parity: Only fall back to first candidate if NO codename scoping was requested.
        # In bundles, if we found nothing matching the codename, it's safer to return None
        # than to pick a random map's asset.
        if codename_low:
            return None
        return candidates[0]

    media.cover_generic_path = _get_best_asset("cover_generic", all_media_files)
    media.cover_online_path = _get_best_asset("cover_online", all_media_files)
    
    # Fallback if specific covers missing
    if not media.cover_generic_path or not media.cover_online_path:
        general_cover = _get_best_asset("cover", all_media_files)
        if general_cover:
            if not media.cover_generic_path: media.cover_generic_path = general_cover
            if not media.cover_online_path: media.cover_online_path = general_cover

    media.banner_path = _get_best_asset("banner", all_media_files)
    media.banner_bkg_path = _get_best_asset("banner_bkg", all_media_files)
    media.map_bkg_path = _get_best_asset("map_bkg", all_media_files)

    media.cover_albumbkg_path = _get_best_asset("albumbkg", all_media_files)
    media.cover_albumcoach_path = _get_best_asset("albumcoach", all_media_files)
    
    # Coaches are a list
    all_coaches = [f for f in all_media_files if "coach_" in f.name.lower()]
    if codename_low:
        codename_coaches = [c for c in all_coaches if _filename_matches_codename(c)]
        if not codename_coaches:
            codename_coaches = [c for c in all_coaches if _path_has_codename_component(c)]
        if codename_coaches:
            all_coaches = codename_coaches

    # Sort and separate phone images
    main_coaches = [f for f in all_coaches if "_phone" not in f.name.lower()]
    phone_coaches = [f for f in all_coaches if "_phone" in f.name.lower()]
    
    media.coach_images = sorted(list(set(main_coaches)))
    media.coach_phone_images = sorted(list(set(phone_coaches)))



    # 5. Pictogram directory
    # V1 Parity: strictly scope to codename if possible
    media.pictogram_dir = None
    picto_candidates = [d for d in dir_path.rglob("*") if d.is_dir() and "picto" in d.name.lower()]
    if search_root and bg_search_dir != dir_path:
        picto_candidates.extend(
            [d for d in bg_search_dir.rglob("*") if d.is_dir() and "picto" in d.name.lower()]
        )
    if picto_candidates:
        picto_candidates = list(dict.fromkeys(picto_candidates))
    if codename_low:
        picto_candidates = [d for d in picto_candidates if _path_has_codename_component(d)]
    
    if picto_candidates:
        media.pictogram_dir = picto_candidates[0]
    else:
        # Fallback: finding parent of any picto CKD
        picto_files = list(dir_path.rglob("*picto*.ckd"))
        if search_root and bg_search_dir != dir_path:
            picto_files.extend(list(bg_search_dir.rglob("*picto*.ckd")))
        if picto_files:
            picto_files = list(dict.fromkeys(picto_files))
        if codename_low:
            picto_files = [f for f in picto_files if _path_has_codename_component(f)]
        if picto_files:
            media.pictogram_dir = picto_files[0].parent

    # 6. Moves directory
    media.moves_dir = None
    move_candidates = [d for d in dir_path.rglob("*") if d.is_dir() and "moves" in d.name.lower()]
    if search_root and bg_search_dir != dir_path:
        move_candidates.extend(
            [d for d in bg_search_dir.rglob("*") if d.is_dir() and "moves" in d.name.lower()]
        )
    if move_candidates:
        move_candidates = list(dict.fromkeys(move_candidates))
    if codename_low:
        move_candidates = [d for d in move_candidates if _path_has_codename_component(d)]
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
        if is_html_source:
            # Fetch/HTML mode (OGG)
            # V1 parity: marker-based sync for HTML mode.
            # Audio uses calibration (OGG delay), video does not.
            prms_video = calculate_marker_preroll(
                music_track.markers,
                music_track.start_beat,
                include_calibration=False,
            )
            prms_audio = calculate_marker_preroll(
                music_track.markers,
                music_track.start_beat,
                include_calibration=True,
            )

            metadata_ms = music_track.video_start_time * 1000.0
            if prms_audio is not None:
                audio_ms = -prms_audio
            else:
                audio_ms = metadata_ms

            # V1 parity: preserve metadata videoStartTime when present.
            # Only synthesize from markers when metadata is effectively zero.
            if abs(metadata_ms) > 0.0001:
                video_ms = metadata_ms
                logger.info(
                    "Fetch/HTML sync (metadata-preserved): audio_offset=%.3f ms (marker+cal), video_offset=%.3f ms (metadata)",
                    audio_ms,
                    video_ms,
                )
            elif prms_video is not None:
                video_ms = -prms_video
                logger.info(
                    "Fetch/HTML sync (synthesized video): audio_offset=%.3f ms (marker+cal), video_offset=%.3f ms (marker)",
                    audio_ms,
                    video_ms,
                )
            else:
                video_ms = metadata_ms
                logger.info("Fetch/HTML sync (fallback): using metadata offsets = %.3f ms", video_ms)

        else:
            # Binary Mode (IPK / WAV)
            # V1 Parity: No 85ms calibration for video or WAV audio.
            if abs(music_track.video_start_time) > 0.0001:
                # Use existing VST if present
                video_ms = music_track.video_start_time * 1000.0
                audio_ms = 0.0 # WAV from IPK already contains pre-roll
            else:
                # Fallback for missing VST in binary CKDs (Xbox 360)
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
    search_root: Optional[str | Path] = None
) -> NormalizedMapData:
    """Normalize an extracted directory into a canonical NormalizedMapData.

    This is the single public entry-point for the normalizer pipeline.
    Works identically whether the directory was populated by the web
    extractor or the IPK extractor.

    Args:
        directory:   Path to the directory containing extracted files.
        codename:    Optional map codename for filtering in bundle IPKs.
        search_root: Optional root directory to scan for media (videos/audio).

    Returns:
        A fully-populated ``NormalizedMapData`` instance.

    Raises:
        NormalizationError: If critical data (musictrack) is missing.
        ValidationError:    If the normalized data fails validation.
    """
    directory = str(directory)
    source_root = Path(directory)
    source_root_str = str(source_root)

    # V1 parity: in extracted bundle roots, resolve to this map's subtree to avoid cross-map bleed.
    map_source_dir = _resolve_map_source_dir(source_root, codename)
    source_dir = map_source_dir
    source_dir_str = str(source_dir)

    # 1. & 2. Extract basic metadata
    try:
        music_track = _extract_music_track(source_root_str, codename)
    except NormalizationError:
        music_track = None

    song_desc = _extract_song_desc(source_root_str, codename)
    dance_tape = _extract_dance_tape(source_root_str, codename)
    karaoke_tape = _extract_karaoke_tape(source_root_str, codename)
    cinematic_tape = _extract_cinematic_tape(source_root_str, codename)

    # Media discovery uses the resolved map subtree first, with full extraction root
    # as search_root fallback for assets that live outside world/maps/<codename>.
    if search_root:
        search_root_str = str(search_root)
    elif source_dir != source_root:
        search_root_str = source_root_str
    else:
        search_root_str = None
    media = _discover_media(source_dir_str, codename, search_root=search_root_str)

    # Infer codename from song_desc if not provided
    effective_codename = codename or song_desc.map_name

    # Determine default sync values like V1
    # Ported from V1 map_installer.py Step 06
    is_html_source = any(source_dir.glob("*.html")) or any(source_dir.glob("**/assets.html"))

    source_trk_path = _find_source_trk_path(source_dir, effective_codename)
    _merge_preview_fields_from_trk(music_track, source_trk_path)

    # 5. Calculate effective video start time (with V1-style fallbacks)
    sync_data = normalize_sync(
        music_track, 
        is_html_source=is_html_source,
        existing_trk_path=source_trk_path
    )

    # V1 Parity: Detect whether the source contains real autodance data.
    # Many sources ship minimal stub CKDs that should be ignored.
    has_autodance = False
    ad_tpls = _find_ckd_files(source_root_str, "*autodance*.tpl.ckd", codename)
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
        for ext in ("adtape", "advideo", "adrecording"):
            candidates = _find_ckd_files(source_root_str, f"*.{ext}.ckd", codename)
            valid_candidates = []
            for candidate in candidates:
                try:
                    if Path(candidate).stat().st_size > 256:
                        valid_candidates.append(candidate)
                except OSError:
                    continue
            if valid_candidates:
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
        cinematic_tape=cinematic_tape,
        media=media,
        sync=sync_data,
        video_start_time_override=sync_data.video_ms / 1000.0,
        source_dir=source_root,
        has_autodance=has_autodance,
    )

    # Validation
    if not result.music_track:
        raise NormalizationError(f"Critical data (musictrack) for '{effective_codename}' is missing")
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
