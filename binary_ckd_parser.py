"""Binary (main_legacy) UbiArt CKD parser.

Handles the binary serialisation format used by older Just Dance titles
(legacy consoles such as Xbox 360, pre-JD2017).  These files carry a
``main_legacy`` infix in their name and cannot be decoded as JSON.

The binary format was reverse-engineered from the open-source ubiart_toolkit
Rust crate (src/cooked/tpl/binary.rs).

Exported API
------------
parse_binary_ckd(file_path) -> dict
    Read a binary CKD and return the same dict structure that
    ``helpers.load_ckd_json`` returns for JSON-format CKDs.
"""

import struct
import zlib
import os
from log_config import get_logger

logger = get_logger("binary_ckd_parser")


# ---------------------------------------------------------------------------
# Known InternedString CRC32 values (UbiArt engine class identifiers)
# ---------------------------------------------------------------------------

_MUSICTRACK_TEMPLATE_CRC = 0x02883A7E   # "MusicTrackComponent_Template"
_SONGDESC_TEMPLATE_CRC   = 0x8AC2B5C6   # "JD_SongDescTemplate"
_ACTOR_TEMPLATE_CRC      = 0x1B857BCE   # "Actor_Template"
_AUTODANCE_TEMPLATE_CRC  = 0x51EA2CD0   # "JD_AutodanceTemplate" (X360)
_SOUND_COMPONENT_TEMPLATE_CRC = 0xD94D6C53 # "SoundComponent_Template" (X360/JD4)


def _string_id(s: str) -> int:
    """CRC32 of the uppercase ASCII representation (UbiArt InternedString)."""
    return zlib.crc32(s.upper().encode("ascii")) & 0xFFFF_FFFF


# Pre-compute CRCs for the colour names stored in DefaultColors
_THEME_CRC  = _string_id("theme")
_LYRICS_CRC = _string_id("lyrics")


# ---------------------------------------------------------------------------
# Low-level big-endian sequential reader
# ---------------------------------------------------------------------------

class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos  = 0

    def u32(self) -> int:
        v = struct.unpack_from(">I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from(">i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from(">f", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u16(self) -> int:
        v = struct.unpack_from(">H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def skip(self, n: int):
        self.pos += n

    def len_string(self) -> str:
        n = self.u32()
        s = self.data[self.pos:self.pos + n].decode("utf-8", errors="replace")
        self.pos += n
        return s

    def interned_string(self) -> int:
        return self.u32()

    def split_path(self) -> str:
        """SplitPath: filename (len-str) + path (len-str) + path_id (u32) + padding (u32)."""
        filename = self.len_string()
        path     = self.len_string()
        _pid     = self.u32()
        _pad     = self.u32()
        return (path + filename).replace("\\", "/")


# ---------------------------------------------------------------------------
# Actor header
# ---------------------------------------------------------------------------

def _read_actor_header(r: _Reader) -> int:
    """Consume the fixed 48-byte Actor header; return template class CRC."""
    unk1 = r.u32()
    if unk1 != 1:
        raise ValueError(f"Actor header unk1={unk1} (expected 1)")
    _unk2       = r.u32()
    actor_crc   = r.interned_string()
    if actor_crc != _ACTOR_TEMPLATE_CRC:
        raise ValueError(
            f"Actor class 0x{actor_crc:08X} (expected 0x{_ACTOR_TEMPLATE_CRC:08X})"
        )
    _unk3 = r.u32()   # = 0x6C
    for _ in range(7):
        r.u32()       # zeros
    _comp_count = r.u32()
    return r.interned_string()


# ---------------------------------------------------------------------------
# MusicTrackComponent / MusicTrackStructure
# ---------------------------------------------------------------------------

def _parse_musictrack_from_reader(r: _Reader) -> dict:
    """Parse MusicTrackComponent_Template after the Actor header has been read.

    Supports both newer (MusicTrackStructure unk1=0x4C) and older
    (unk1=0x6C, eight extra u32 fields after volume) formats.
    """
    _mc_unk1 = r.u32()   # 0x80 newer / 0xA0 older
    _md_unk1 = r.u32()   # 0x70 newer / 0x90 older

    ms_unk1  = r.u32()   # 0x4C newer / 0x6C older
    is_older = (ms_unk1 == 0x6C)

    N = r.u32()
    markers = [r.u32() for _ in range(N)]

    S = r.u32()
    signatures = []
    for _ in range(S):
        _sig_unk1 = r.u32()   # = 0x8
        marker    = r.i32()
        beats     = r.u32()
        signatures.append({"beats": beats, "marker": marker})

    K = r.u32()
    sections = []
    for _ in range(K):
        _sect_unk1 = r.u32()   # = 0x14
        marker     = r.i32()
        sect_type  = r.u32()
        comment_len = r.u32()  # length-prefixed string (usually 0)
        if comment_len > 0:
            r.pos += comment_len  # skip the comment bytes
        sections.append({"sectionType": sect_type, "marker": marker})

    start_beat       = r.i32()
    end_beat         = r.u32()
    video_start_time = r.f32()
    volume           = r.f32()

    preview_entry      = 0
    preview_loop_start = 0
    preview_loop_end   = 0
    fade_in_duration   = 0
    fade_in_type       = 0
    fade_out_duration  = 0
    fade_out_type      = 0

    if is_older:
        # Preview fields are floats (beat indices); fade fields are mixed.
        # Read each with the correct type to avoid garbage values.
        preview_entry      = r.f32()
        preview_loop_start = r.f32()
        preview_loop_end   = r.f32()
        fade_in_duration   = r.f32()
        fade_in_type       = r.u32()
        fade_out_duration  = r.f32()
        fade_out_type      = r.u32()
        _unknown           = r.u32()  # discarded

        # Sanity-check preview fields: X360 binary CKDs sometimes store
        # unrelated data in these positions, producing garbage floats.
        # Valid beat indices are non-negative and well under 10000.
        for pval in (preview_entry, preview_loop_start, preview_loop_end):
            if pval < 0 or pval > 10000:
                preview_entry = 0
                preview_loop_start = 0
                preview_loop_end = 0
                break

    return {
        "COMPONENTS": [{
            "trackData": {
                "structure": {
                    "markers":          markers,
                    "signatures":       signatures,
                    "sections":         sections,
                    "startBeat":        start_beat,
                    "endBeat":          end_beat,
                    "videoStartTime":   video_start_time,
                    "previewEntry":     preview_entry,
                    "previewLoopStart": preview_loop_start,
                    "previewLoopEnd":   preview_loop_end,
                    "volume":           volume,
                    "fadeInDuration":   fade_in_duration,
                    "fadeInType":       fade_in_type,
                    "fadeOutDuration":  fade_out_duration,
                    "fadeOutType":      fade_out_type,
                }
            }
        }]
    }


def parse_musictrack(filepath):
    """Public helper: parse a musictrack CKD (legacy binary or JSON fallback)."""
    with open(filepath, "rb") as fh:
        data = fh.read()
    r = _Reader(data)
    _template_crc = _read_actor_header(r)
    return _parse_musictrack_from_reader(r)


# ---------------------------------------------------------------------------
# JD_SongDescTemplate
# ---------------------------------------------------------------------------

def _parse_songdesc_from_reader(r: _Reader) -> dict:
    """Parse JD_SongDescTemplate after the Actor header has been read."""
    _unk1 = r.u32()   # = 0xF4

    map_name            = r.len_string()
    jd_version          = r.u32()
    original_jd_version = r.u32()

    # Related albums
    for _ in range(r.u32()):
        r.len_string()

    # Unknown58 array – 13 × u32be per entry; discard
    for _ in range(r.u32()):
        for _ in range(13):
            r.u32()

    artist      = r.len_string()
    dancer_name = r.len_string()
    title       = r.len_string()

    num_coach       = r.u32()
    main_coach      = r.i32()
    difficulty      = r.u32()
    background_type = r.u32()
    lyrics_type     = r.i32()
    energy          = r.u32()
    _unk17          = r.f32()

    # Unknown10 (tags) – u32be=0x10, InternedString CRC, u32be, u32be per entry
    tags = []
    for _ in range(r.u32()):
        _tag_unk1  = r.u32()   # = 0x10
        _tag_crc   = r.u32()   # InternedString CRC of tag name (not decoded)
        _tag_unk21 = r.u32()
        _tag_unk22 = r.u32()
    if not tags:
        tags = ["Main"]

    # DefaultColors – u32be count, (u32be CRC, 4×f32be RGBA) pairs
    default_colors: dict = {}
    for _ in range(r.u32()):
        name_crc = r.u32()
        rgba     = [r.f32() for _ in range(4)]
        if name_crc == _THEME_CRC:
            default_colors["theme"] = rgba
        elif name_crc == _LYRICS_CRC:
            default_colors["lyrics"] = rgba
        else:
            default_colors[f"0x{name_crc:08X}"] = rgba

    # Paths – consume but don't return
    for _ in range(r.u32()):
        r.split_path()
    for _ in range(r.u32()):
        r.split_path()

    return {
        "COMPONENTS": [{
            "MapName":           map_name,
            "JDVersion":         jd_version,
            "OriginalJDVersion": original_jd_version,
            "Artist":            artist,
            "DancerName":        dancer_name,
            "Title":             title,
            "Credits":           "",
            "NumCoach":          num_coach,
            "MainCoach":         main_coach,
            "Difficulty":        difficulty,
            "SweatDifficulty":   1,
            "backgroundType":    background_type,
            "LyricsType":        lyrics_type,
            "Energy":            energy,
            "Tags":              tags,
            "Status":            3,
            "LocaleID":          4294967295,
            "MojoValue":         0,
            "DefaultColors":     default_colors,
        }]
    }


def parse_songdesc(filepath):
    """Public helper: parse a songdesc CKD (legacy binary)."""
    with open(filepath, "rb") as fh:
        data = fh.read()
    r = _Reader(data)
    _template_crc = _read_actor_header(r)
    return _parse_songdesc_from_reader(r)

def parse_dtape(filepath):
    map_name = os.path.basename(filepath).split('_')[0]
    clips = []
    with open(filepath, "rb") as f:
        f.read(12)
        timeline_ver = struct.unpack('>I', f.read(4))[0]
        entries = struct.unpack('>I', f.read(4))[0]
        
        for _ in range(entries):
            struct.unpack('>I', f.read(4))[0] # unknown
            entry_class = struct.unpack('>I', f.read(4))[0]
            entry_id = struct.unpack('>I', f.read(4))[0]
            entry_trackid = struct.unpack('>I', f.read(4))[0]
            entry_isactive = struct.unpack('>I', f.read(4))[0]
            entry_starttime = struct.unpack('>I', f.read(4))[0]
            entry_duration = struct.unpack('>I', f.read(4))[0]
            
            if entry_class in (108, 112, 56):
                namelen = struct.unpack('>I', f.read(4))[0]
                name = f.read(namelen).decode("utf-8", errors="ignore")
                pathlen = struct.unpack('>I', f.read(4))[0]
                path = f.read(pathlen).decode("utf-8", errors="ignore")
                struct.unpack('>I', f.read(4))[0] # atlindex
                struct.unpack('>I', f.read(4))[0] # unknown2
                
                if entry_class in (108, 112): # MotionClip
                    goldmove = struct.unpack('>I', f.read(4))[0]
                    coachid = struct.unpack('>I', f.read(4))[0]
                    movetype = struct.unpack('>I', f.read(4))[0]
                    f.read(16) # colors
                    f.read(64) # pointing/useless
                    
                    clips.append({
                        "__class": "MotionClip",
                        "Id": entry_id,
                        "TrackId": entry_trackid,
                        "IsActive": entry_isactive,
                        "StartTime": entry_starttime,
                        "Duration": entry_duration,
                        "ClassifierPath": path.replace("jd2015", "maps") + name,
                        "GoldMove": goldmove,
                        "CoachId": coachid,
                        "MoveType": movetype,
                        "Color": [1, 0.968, 0.164, 0.552]
                    })
                elif entry_class == 56: # PictogramClip
                    coachcount = struct.unpack('>I', f.read(4))[0]
                    clips.append({
                        "__class": "PictogramClip",
                        "Id": entry_id,
                        "TrackId": entry_trackid,
                        "IsActive": entry_isactive,
                        "StartTime": entry_starttime,
                        "Duration": entry_duration,
                        "PictoPath": path.replace("jd2015", "maps") + name,
                        "CoachCount": coachcount
                    })
            elif entry_class == 28: # GoldEffectClip
                effecttype = struct.unpack('>I', f.read(4))[0]
                clips.append({
                    "__class": "GoldEffectClip",
                    "Id": entry_id,
                    "TrackId": entry_trackid,
                    "IsActive": entry_isactive,
                    "StartTime": entry_starttime,
                    "Duration": entry_duration,
                    "EffectType": effecttype
                })
    return {
        "__class": "Tape",
        "Clips": clips,
        "TapeClock": 0,
        "TapeBarCount": 1,
        "FreeResourcesAfterPlay": 0,
        "MapName": map_name
    }

def parse_ktape(filepath):
    map_name = os.path.basename(filepath).split('_')[0]
    clips = []
    with open(filepath, "rb") as f:
        f.read(12)
        timeline_ver = struct.unpack('>I', f.read(4))[0]
        entries = struct.unpack('>I', f.read(4))[0]
        
        for _ in range(entries):
            struct.unpack('>I', f.read(4))[0] # unknown
            entry_class = struct.unpack('>I', f.read(4))[0]
            entry_id = struct.unpack('>I', f.read(4))[0]
            entry_trackid = struct.unpack('>I', f.read(4))[0]
            entry_isactive = struct.unpack('>I', f.read(4))[0]
            entry_starttime = struct.unpack('>I', f.read(4))[0]
            entry_duration = struct.unpack('>I', f.read(4))[0]
            
            if entry_class in (32, 80): # KaraokeClip (32=older, 80=X360/newer)
                pitch = struct.unpack('>f', f.read(4))[0]
                lyriclen = struct.unpack('>I', f.read(4))[0]
                lyric = f.read(lyriclen).decode("utf-8", errors="ignore")

                if entry_class == 80:
                    # Class 80 layout: IsEndOfLine, ContentType,
                    # StartTimeTolerance, EndTimeTolerance, SemitoneTolerance
                    isendofline = struct.unpack('>I', f.read(4))[0]
                    content_type = struct.unpack('>I', f.read(4))[0]
                    start_time_tol = struct.unpack('>I', f.read(4))[0]
                    end_time_tol = struct.unpack('>I', f.read(4))[0]
                    semitone_tol = struct.unpack('>f', f.read(4))[0]
                else:
                    # Class 32 layout: unknown, IsEndOfLine
                    struct.unpack('>I', f.read(4))[0]  # unknown
                    isendofline = struct.unpack('>I', f.read(4))[0]
                    content_type = 0
                    start_time_tol = 4
                    end_time_tol = 4
                    semitone_tol = 5

                clips.append({
                    "__class": "KaraokeClip",
                    "Id": entry_id,
                    "TrackId": entry_trackid,
                    "IsActive": entry_isactive,
                    "StartTime": entry_starttime,
                    "Duration": entry_duration,
                    "Pitch": pitch,
                    "Lyrics": lyric,
                    "IsEndOfLine": isendofline,
                    "ContentType": content_type,
                    "StartTimeTolerance": start_time_tol,
                    "EndTimeTolerance": end_time_tol,
                    "SemitoneTolerance": semitone_tol
                })
    return {
        "__class": "Tape",
        "Clips": clips,
        "TapeClock": 0,
        "TapeBarCount": 1,
        "FreeResourcesAfterPlay": 0,
        "MapName": map_name
    }

def parse_cinematic_tape(filepath):
    map_name = os.path.basename(filepath).split('_')[0]
    clips = []
    
    try:
        with open(filepath, "rb") as f:
            f.read(12)
            timeline_ver = struct.unpack('>I', f.read(4))[0]
            entries = struct.unpack('>I', f.read(4))[0]
            
            for _ in range(entries):
                struct.unpack('>I', f.read(4))[0] # unknown
                entry_class = struct.unpack('>I', f.read(4))[0]
                
                # Check known entry classes:
                # 136 == SoundSetClip, 160 == TapeReferenceClip
                if entry_class == 136:  # SoundSetClip
                    entry_id = struct.unpack('>I', f.read(4))[0]
                    entry_trackid = struct.unpack('>I', f.read(4))[0]
                    entry_isactive = struct.unpack('>I', f.read(4))[0]
                    entry_starttime = struct.unpack('>I', f.read(4))[0]
                    entry_duration = struct.unpack('>I', f.read(4))[0]
                    f.read(4) # Empty
                    pathlen = struct.unpack('>I', f.read(4))[0]
                    path = f.read(pathlen).decode("utf-8", errors="ignore")
                    filelen = struct.unpack('>I', f.read(4))[0]
                    filename = f.read(filelen).decode("utf-8", errors="ignore")
                    f.read(4)
                    if entries > 1:
                        f.read(12)
                    
                    clips.append({
                        "__class": "SoundSetClip",
                        "Id": entry_id,
                        "TrackId": entry_trackid,
                        "IsActive": entry_isactive,
                        "StartTime": entry_starttime,
                        "Duration": entry_duration,
                        "SoundSetPath": path.replace('jd2015', 'maps') + filename,
                        "SoundChannel": 0,
                        "StartOffset": 0,
                        "StopsOnEnd": 0,
                        "AccountedForDuration": 0
                    })
                elif entry_class == 160: # TapeReferenceClip
                    entry_id = struct.unpack('>I', f.read(4))[0]
                    entry_trackid = struct.unpack('>I', f.read(4))[0]
                    entry_isactive = struct.unpack('>I', f.read(4))[0]
                    entry_starttime = struct.unpack('>I', f.read(4))[0]
                    entry_duration = struct.unpack('>I', f.read(4))[0]
                    pathlen = struct.unpack('>I', f.read(4))[0]
                    path = f.read(pathlen).decode("utf-8", errors="ignore")
                    filelen = struct.unpack('>I', f.read(4))[0]
                    filename = f.read(filelen).decode("utf-8", errors="ignore")
                    f.read(4)
                    serLoop = struct.unpack('>I', f.read(4))[0]
                    if entries > 1:
                        f.read(12)
                        
                    clips.append({
                        "__class": "TapeReferenceClip",
                        "Id": entry_id,
                        "TrackId": entry_trackid,
                        "IsActive": entry_isactive,
                        "StartTime": entry_starttime,
                        "Duration": entry_duration,
                        "Path": path.replace('jd2015', 'maps') + filename,
                        "Loop": serLoop
                    })
                else:
                    # Generic skip fallback if unknown class
                    # We don't know the exact length, so just break out to avoid desync
                    break
    except Exception as e:
        logger.warning(f"binary_ckd: partial/failed parse on cinematic tape '{os.path.basename(filepath)}': {e}")
        
    return {
        "__class": "Tape",
        "Clips": clips,
        "TapeClock": 0,
        "TapeBarCount": 1,
        "FreeResourcesAfterPlay": 0,
        "MapName": map_name,
        "SoundwichEvent": ""
    }

def _parse_autodance_from_reader(r: _Reader) -> dict:
    """Parse JD_AutodanceTemplate (legacy binary)."""
    _unk1 = r.u32()   # 0x714
    map_name = r.len_string()
    return {
        "COMPONENTS": [{
            "MapName": map_name
        }]
    }

def _parse_sound_from_reader(r: _Reader) -> dict:
    """Parse SoundComponent_Template (legacy binary)."""
    _unk1 = r.u32()   # 0x118
    entry_count = r.u32()
    sounds = []
    for _ in range(entry_count):
        r.skip(36)     # unk fixed block
        file_count = r.u32()
        files = []
        for _ in range(file_count):
            # Each file is a SplitPath
            full_path = r.split_path()
            files.append(full_path)
        sounds.append({"files": files})
    
    return {
        "COMPONENTS": [{
            "soundList": sounds
        }]
    }

def parse_binary_ckd(filepath):
    """Dispatch binary CKD parse based on the Actor header template class CRC.

    For musictrack and songdesc files the format is determined from the binary
    header itself (not the filename), making the dispatch reliable regardless
    of naming conventions.  Tape files (dtape / ktape / stape / adtape etc) are
    still dispatched by filename since they use a different container format.
    """
    name = os.path.basename(filepath).lower()
    
    # Timeline/Tape containers (Header 0x01, TimelineVersion, EntryCount)
    if "dtape" in name:
        return parse_dtape(filepath)
    if "ktape" in name:
        return parse_ktape(filepath)
    if ".tape.ckd" in name or ".stape.ckd" in name or ".adtape.ckd" in name or ".adrecording.ckd" in name or ".advideo.ckd" in name:
        return parse_cinematic_tape(filepath)

    # For CKD TPL files: read Actor header and dispatch on template class CRC
    with open(filepath, "rb") as fh:
        data = fh.read()
    r = _Reader(data)

    try:
        template_crc = _read_actor_header(r)
    except (struct.error, ValueError) as exc:
        raise ValueError(
            f"binary_ckd: failed to read Actor header in "
            f"'{os.path.basename(filepath)}': {exc}"
        ) from exc

    try:
        if template_crc == _MUSICTRACK_TEMPLATE_CRC:
            result = _parse_musictrack_from_reader(r)
            logger.debug(
                "binary_ckd: parsed musictrack '%s' (%d markers)",
                os.path.basename(filepath),
                len(result["COMPONENTS"][0]["trackData"]["structure"]["markers"]),
            )
            return result

        if template_crc == _SONGDESC_TEMPLATE_CRC:
            result = _parse_songdesc_from_reader(r)
            logger.debug(
                "binary_ckd: parsed songdesc '%s' title='%s'",
                os.path.basename(filepath),
                result["COMPONENTS"][0].get("Title", "?"),
            )
            return result

        if template_crc == _AUTODANCE_TEMPLATE_CRC:
            result = _parse_autodance_from_reader(r)
            logger.debug(
                "binary_ckd: parsed autodance '%s' map='%s'",
                os.path.basename(filepath),
                result["COMPONENTS"][0].get("MapName", "?"),
            )
            return result

        if template_crc == _SOUND_COMPONENT_TEMPLATE_CRC:
            result = _parse_sound_from_reader(r)
            logger.debug(
                "binary_ckd: parsed ambient sound '%s' (%d sounds)",
                os.path.basename(filepath),
                len(result["COMPONENTS"][0].get("soundList", [])),
            )
            return result

    except (struct.error, IndexError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"binary_ckd: parse error in '{os.path.basename(filepath)}': {exc}"
        ) from exc

    raise ValueError(
        f"binary_ckd: unsupported template class 0x{template_crc:08X} "
        f"in '{os.path.basename(filepath)}'"
    )
