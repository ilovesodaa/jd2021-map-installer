"""Unified data models for the JD2021 Map Installer pipeline.

All stages of the Extract -> Normalize -> Install pipeline produce or
consume these dataclasses.  The ``NormalizedMapData`` is the single
canonical representation of a map, regardless of source format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Difficulty(IntEnum):
    EASY = 1
    MEDIUM = 2
    HARD = 3
    EXTREME = 4


class LyricsType(IntEnum):
    NONE = 0
    NORMAL = 1
    HIGHLIGHTED = 2


class BackgroundType(IntEnum):
    AUTO = 0
    BACKGROUND_1 = 1
    BACKGROUND_2 = 2


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

@dataclass
class MusicSignature:
    """Time signature marker within a music track."""
    beats: int
    marker: int


@dataclass
class MusicSection:
    """Section marker within a music track (intro, verse, chorus, etc.)."""
    section_type: int
    marker: int


@dataclass
class MusicTrackStructure:
    """The full timing/beat structure of a song.

    Parsed from a musictrack CKD. Contains beat markers used for
    synchronizing dance moves, karaoke, and video playback.
    """
    markers: List[int]
    signatures: List[MusicSignature]
    sections: List[MusicSection]
    start_beat: int
    end_beat: int
    video_start_time: float
    preview_entry: float = 0.0
    preview_loop_start: float = 0.0
    preview_loop_end: float = 0.0
    volume: float = 0.0
    fade_in_duration: float = 0.0
    fade_in_type: int = 0
    fade_out_duration: float = 0.0
    fade_out_type: int = 0


@dataclass
class DefaultColors:
    """Song theme/lyrics RGBA colour palette."""
    theme: List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0, 1.0])
    lyrics: List[float] = field(default_factory=lambda: [1.0, 0.106, 0.204, 0.667])
    song_color_1a: List[float] = field(default_factory=lambda: [0.0, 0.82, 0.816, 0.816])
    song_color_1b: List[float] = field(default_factory=lambda: [0.96, 0.0, 0.02, 0.816])
    song_color_2a: List[float] = field(default_factory=lambda: [0.0, 0.82, 0.816, 0.816])
    song_color_2b: List[float] = field(default_factory=lambda: [0.96, 0.0, 0.02, 0.816])
    extra: Dict[str, List[float]] = field(default_factory=dict)


@dataclass
class MotionClip:
    """A single dance move clip from a timeline dtape."""
    id: int
    track_id: int
    is_active: int
    start_time: int
    duration: int
    classifier_path: str
    gold_move: int
    coach_id: int
    move_type: int
    color: List[float] = field(default_factory=lambda: [1, 0.968, 0.164, 0.552])


@dataclass
class PictogramClip:
    """A pictogram clip from a timeline dtape."""
    id: int
    track_id: int
    is_active: int
    start_time: int
    duration: int
    picto_path: str
    coach_count: int


@dataclass
class GoldEffectClip:
    """A gold effect clip from a timeline dtape."""
    id: int
    track_id: int
    is_active: int
    start_time: int
    duration: int
    effect_type: int


@dataclass
class KaraokeClip:
    """A karaoke (lyrics) clip from a ktape."""
    id: int
    track_id: int
    is_active: int
    start_time: int
    duration: int
    pitch: float
    lyrics: str
    is_end_of_line: int
    content_type: int = 0
    start_time_tolerance: int = 4
    end_time_tolerance: int = 4
    semitone_tolerance: float = 5.0


@dataclass
class SoundSetClip:
    """A sound-set clip from a cinematic tape."""
    id: int
    track_id: int
    is_active: int
    start_time: int
    duration: int
    sound_set_path: str
    sound_channel: int = 0
    start_offset: int = 0
    stops_on_end: int = 0
    accounted_for_duration: int = 0


@dataclass
class TapeReferenceClip:
    """A tape-reference clip from a cinematic tape."""
    id: int
    track_id: int
    is_active: int
    start_time: int
    duration: int
    path: str
    loop: int = 0


@dataclass
class DanceTape:
    """Container for dance timeline clips (dtape)."""
    clips: List[MotionClip | PictogramClip | GoldEffectClip]
    map_name: str


@dataclass
class KaraokeTape:
    """Container for karaoke timeline clips (ktape)."""
    clips: List[KaraokeClip]
    map_name: str


@dataclass
class CinematicTape:
    """Container for cinematic tape clips (stape/MainSequence)."""
    clips: List[SoundSetClip | TapeReferenceClip]
    map_name: str
    soundwich_event: str = ""


@dataclass
class SongDescription:
    """Metadata extracted from a songdesc CKD."""
    map_name: str
    title: str
    artist: str
    dancer_name: str = "Unknown Dancer"
    credits: str = ""
    num_coach: int = 1
    main_coach: int = -1
    difficulty: int = 2
    sweat_difficulty: int = 1
    background_type: int = 0
    lyrics_type: int = 0
    energy: int = 1
    tags: List[str] = field(default_factory=lambda: ["Main"])
    status: int = 3
    locale_id: int = 4294967295
    mojo_value: int = 0
    jd_version: int = 2021
    original_jd_version: int = 2021
    default_colors: DefaultColors = field(default_factory=DefaultColors)
    phone_images: Dict[str, str] = field(default_factory=dict)

    def sanitize(self) -> None:
        """Sanitize Title and Artist fields by removing/replacing non-ASCII characters.
        
        Uses NFKD normalization to strip accents and preserves only ASCII.
        """
        import unicodedata
        for field_name in ("title", "artist"):
            val = getattr(self, field_name)
            if not val:
                continue
            # Normalize to NFKD and strip accents
            nfkd_form = unicodedata.normalize('NFKD', val)
            ascii_val = nfkd_form.encode('ASCII', 'ignore').decode('ASCII').strip()
            if ascii_val:
                setattr(self, field_name, ascii_val)


@dataclass
class MapMedia:
    """Paths to all media assets for a map."""
    video_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    cover_path: Optional[Path] = None
    banner_path: Optional[Path] = None
    coach_images: List[Path] = field(default_factory=list)
    pictogram_dir: Optional[Path] = None
    moves_dir: Optional[Path] = None
    map_preview_video: Optional[Path] = None


@dataclass
class MapSync:
    """Sync offsets for the map UI."""
    audio_ms: float = 0.0
    video_ms: float = 0.0


# ---------------------------------------------------------------------------
# Top-level normalized model
# ---------------------------------------------------------------------------

@dataclass
class NormalizedMapData:
    """The single, canonical representation of a JD map.

    This is the output of the Normalizer pipeline and the input to
    the Installer.  All source formats (HTML/web, IPK archives,
    and mixed CKD binary/JSON) are normalized into this structure.
    """
    codename: str
    song_desc: SongDescription
    music_track: MusicTrackStructure
    dance_tape: Optional[DanceTape] = None
    karaoke_tape: Optional[KaraokeTape] = None
    cinematic_tape: Optional[CinematicTape] = None
    media: MapMedia = field(default_factory=MapMedia)
    sync: MapSync = field(default_factory=MapSync)
    source_dir: Optional[Path] = None
    video_start_time_override: Optional[float] = None
    has_autodance: bool = True

    @property
    def effective_video_start_time(self) -> float:
        """Return the override if set, otherwise the CKD value."""
        if self.video_start_time_override is not None:
            return self.video_start_time_override
        return self.music_track.video_start_time
