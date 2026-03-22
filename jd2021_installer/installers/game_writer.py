"""Game file writer — generates UbiArt engine config files from NormalizedMapData.

Takes a ``NormalizedMapData`` dataclass and writes all the .trk, .tpl,
.act, .isc, .mpd, .stape, .sfi files that JD2021 expects inside its
``World/MAPS/<codename>/`` directory structure.

Refactored from the original monolithic ``map_builder.py``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.exceptions import GameWriterError
from jd2021_installer.core.models import (
    MusicTrackStructure,
    NormalizedMapData,
    SongDescription,
)

logger = logging.getLogger("jd2021.installers.game_writer")


# ---------------------------------------------------------------------------
# Lua helpers
# ---------------------------------------------------------------------------

def lua_long_string(text: Optional[str]) -> str:
    """Wrap text in a Lua long string literal, handling nested brackets."""
    if text is None:
        text = ""
    text = str(text)
    level = 0
    while True:
        close = "]" + ("=" * level) + "]"
        if close not in text:
            break
        level += 1
    return f"[{'=' * level}[{text}]{'=' * level}]"


def color_array_to_hex(val, default: str = "0xFFFFFFFF") -> str:
    """Convert a [R,G,B,A] float array to a 0xRRGGBBAA hex string."""
    if isinstance(val, str) and val.startswith("0x"):
        return val
    if isinstance(val, (list, tuple)) and len(val) >= 4:
        comps = [int(round(max(0, min(1, c)) * 255)) for c in val[:4]]
        return "0x" + "".join(f"{c:02X}" for c in comps)
    return default


# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

def setup_dirs(target_dir: str | Path) -> None:
    """Create the standard UbiArt map directory structure."""
    target = Path(target_dir)
    for subdir in (
        "Audio", "Timeline", "Timeline/pictos", "Timeline/Moves",
        "Cinematics", "VideosCoach", "MenuArt/Actors",
        "MenuArt/textures", "Autodance",
    ):
        (target / subdir).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Individual file writers
# ---------------------------------------------------------------------------

def _write_musictrack_trk(target: Path, name: str, mt: MusicTrackStructure, vst: float) -> None:
    """Write the .trk music track structure file."""
    markers = ", ".join(f"{{ VAL = {m} }}" for m in mt.markers)
    sigs = ", ".join(
        f"{{ MusicSignature = {{ beats = {s.beats}, marker = {s.marker} }} }}"
        for s in mt.signatures
    )
    sects = ", ".join(
        f"{{ MusicSection = {{ sectionType = {s.section_type}, marker = {s.marker} }} }}"
        for s in mt.sections
    )

    # Sanitize preview fields
    num_markers = len(mt.markers)
    pe = mt.preview_entry if 0 <= mt.preview_entry <= num_markers else 0.0
    pls = mt.preview_loop_start if 0 <= mt.preview_loop_start <= num_markers else 0.0
    ple = mt.preview_loop_end if 0 <= mt.preview_loop_end <= num_markers else 0.0

    content = (
        f"structure = {{ MusicTrackStructure = {{ markers = {{ {markers} }}, "
        f"signatures = {{ {sigs} }}, sections = {{ {sects} }}, "
        f"startBeat = {mt.start_beat}, endBeat = {mt.end_beat}, "
        f"fadeStartBeat = 0, useFadeStartBeat = 0, "
        f"fadeEndBeat = 0, useFadeEndBeat = 0, "
        f"videoStartTime = {vst:.6f}, "
        f"previewEntry = {pe:.1f}, "
        f"previewLoopStart = {pls:.1f}, "
        f"previewLoopEnd = {ple:.1f}, "
        f"volume = {mt.volume:.6f}, "
        f"fadeInDuration = {mt.fade_in_duration}, fadeInType = {mt.fade_in_type}, "
        f"fadeOutDuration = {mt.fade_out_duration}, fadeOutType = {mt.fade_out_type}, "
        f"entryPoints = {{ }} }} }}"
    )
    (target / f"Audio/{name}.trk").write_text(content, encoding="utf-8")


def _write_songdesc(target: Path, name: str, sd: SongDescription,
                    num_coach: int, vst: float, config: AppConfig) -> None:
    """Write SongDesc.tpl and SongDesc.act."""
    name_lower = name.lower()
    jd_ver = max(config.min_jd_version, min(sd.jd_version, config.max_jd_version))
    orig_ver = max(config.min_jd_version, min(sd.original_jd_version, config.max_jd_version))

    # Tags
    tags_lua = ""
    for t in (sd.tags or ["Main"]):
        tags_lua += f'\n\t\t\t\t\t\t{{\n\t\t\t\t\t\t\tVAL = "{t}"\n\t\t\t\t\t\t}},'
    tags_lua = tags_lua.rstrip(",")

    # PhoneImages
    if sd.phone_images:
        phone_str = ""
        for k, v in sd.phone_images.items():
            phone_str += f'\n\t\t\t\t\t\t{{\n\t\t\t\t\t\t\tKEY = "{k}",\n\t\t\t\t\t\t\tVAL = "{v}"\n\t\t\t\t\t\t}},'
        phone_str = phone_str.rstrip(",")
    else:
        phone_str = f'\n\t\t\t\t\t\t{{\n\t\t\t\t\t\t\tKEY = "cover",\n\t\t\t\t\t\t\tVAL = "world/maps/{name_lower}/menuart/textures/{name_lower}_cover_phone.jpg"\n\t\t\t\t\t\t}}'
        for i in range(1, num_coach + 1):
            phone_str += f',\n\t\t\t\t\t\t{{\n\t\t\t\t\t\t\tKEY = "coach{i}",\n\t\t\t\t\t\t\tVAL = "world/maps/{name_lower}/menuart/textures/{name_lower}_coach_{i}_phone.png"\n\t\t\t\t\t\t}}'

    # DefaultColors
    dc = sd.default_colors
    color_fallbacks = {
        "lyrics": dc.lyrics,
        "theme": dc.theme,
        "songColor_1A": dc.song_color_1a,
        "songColor_1B": dc.song_color_1b,
        "songColor_2A": dc.song_color_2a,
        "songColor_2B": dc.song_color_2b,
    }
    colors_lua = ""
    for key, val in color_fallbacks.items():
        hex_val = color_array_to_hex(val)
        colors_lua += f'\n\t\t\t\t\t\t{{\n\t\t\t\t\t\t\tKEY = "{key}",\n\t\t\t\t\t\t\tVAL = "{hex_val}"\n\t\t\t\t\t\t}},'
    for key, val in dc.extra.items():
        hex_val = color_array_to_hex(val)
        colors_lua += f'\n\t\t\t\t\t\t{{\n\t\t\t\t\t\t\tKEY = "{key}",\n\t\t\t\t\t\t\tVAL = "{hex_val}"\n\t\t\t\t\t\t}},'

    dancer_name = str(sd.dancer_name).replace('"', '\\"').replace('\n', ' ')
    audio_fade = config.audio_preview_fade_s if sd.jd_version >= 2016 else 0.0
    status = 3 if sd.status == 12 else sd.status

    tpl = f'''includeReference("EngineData/Helpers/SongDatabase.ilu")
params =
{{
\tNAME = "Actor_Template",
\tActor_Template =
\t{{
\t\tTAGS =
\t\t{{
\t\t\t{{
\t\t\t\tVAL = "songdescmain"
\t\t\t}}
\t\t}},
\t\tWIP = 0,
\t\tLOWUPDATE = 0,
\t\tUPDATE_LAYER = 0,
\t\tPROCEDURAL = 0,
\t\tSTARTPAUSED = 0,
\t\tFORCEISENVIRONMENT = 0,
\t\tCOMPONENTS =
\t\t{{
\t\t\t{{
\t\t\t\tNAME = "JD_SongDescTemplate",
\t\t\t\tJD_SongDescTemplate =
\t\t\t\t{{
\t\t\t\t\tMapName = "{name}",
\t\t\t\t\tJDVersion = {jd_ver},
\t\t\t\t\tOriginalJDVersion = {orig_ver},
\t\t\t\t\tArtist = {lua_long_string(sd.artist)},
\t\t\t\t\tDancerName = "{dancer_name}",
\t\t\t\t\tTitle = {lua_long_string(sd.title)},
\t\t\t\t\tCredits = {lua_long_string(sd.credits or "All rights reserved.")},
\t\t\t\t\tNumCoach = {num_coach},
\t\t\t\t\tMainCoach = {sd.main_coach},
\t\t\t\t\tDifficulty = {sd.difficulty},
\t\t\t\t\tSweatDifficulty = {sd.sweat_difficulty},
\t\t\t\t\tbackgroundType = {sd.background_type},
\t\t\t\t\tLyricsType = {sd.lyrics_type},
\t\t\t\t\tEnergy = {sd.energy},
\t\t\t\t\tTags =
\t\t\t\t\t{{{tags_lua}
\t\t\t\t\t}},
\t\t\t\t\tStatus = {status},
\t\t\t\t\tLocaleID = {sd.locale_id},
\t\t\t\t\tMojoValue = {sd.mojo_value},
\t\t\t\t\tCountInProgression = 0,
\t\t\t\t\tPhoneImages =
\t\t\t\t\t{{{phone_str}
\t\t\t\t\t}},
                    DefaultColors =
                    {{{colors_lua}
\t\t\t\t\t}},
\t\t\t\t\tVideoPreviewPath = "",
\t\t\t\t\tMode = 0,
\t\t\t\t\tAudioPreviewFadeTime = {audio_fade:.6f}
\t\t\t\t}}
\t\t\t}}
\t\t}}
\t}}
}}'''
    (target / "SongDesc.tpl").write_text(tpl, encoding="utf-8")

    act = f'''params =
{{
    NAME = "Actor",
    Actor =
    {{
        LUA = "World/MAPS/{name}/songdesc.tpl",
        COMPONENTS =
        {{
            {{
                NAME = "JD_SongDescComponent",
                JD_SongDescComponent =
                {{
                }}
            }}
        }}
    }}
}}'''
    (target / "SongDesc.act").write_text(act, encoding="utf-8")


def _write_audio_isc(target: Path, name: str) -> None:
    """Write musictrack.tpl, sequence.tpl, .stape, and audio.isc."""
    # musictrack.tpl
    (target / f"Audio/{name}_musictrack.tpl").write_text(
        f'''includeReference("World/MAPS/{name}/audio/{name}.trk")
params =
{{
\tNAME = "Actor_Template",
\tActor_Template =
\t{{
\t\tCOMPONENTS =
\t\t{{
\t\t\t{{
\t\t\t\tNAME = "MusicTrackComponent_Template",
\t\t\t\tMusicTrackComponent_Template =
\t\t\t\t{{
\t\t\t\t\ttrackData =
\t\t\t\t\t{{
\t\t\t\t\t\tMusicTrackData =
\t\t\t\t\t\t{{
\t\t\t\t\t\t\tpath = "World/MAPS/{name}/audio/{name}.wav",
\t\t\t\t\t\t\turl = "jmcs://jd-contents/{name}/{name}.ogg",
\t\t\t\t\t\t\tstructure = structure
\t\t\t\t\t\t}}
\t\t\t\t\t}}
\t\t\t\t}}
\t\t\t}}
\t\t}}
\t}}
}}''')

    # sequence.tpl
    (target / f"Audio/{name}_sequence.tpl").write_text(
        f'''params =
{{
\tNAME = "Actor_Template",
\tActor_Template =
\t{{
\t\tCOMPONENTS =
\t\t{{
\t\t\t{{
\t\t\t\tNAME = "TapeCase_Template",
                TapeCase_Template =
                {{
                    TapesRack =
                    {{
                        {{
                            TapeGroup =
                            {{
                                Entries =
                                {{
                                    {{
                                        TapeEntry =
                                        {{
                                            Label = "TML_Sequence",
                                            Path = "World/MAPS/{name}/audio/{name}.stape"
                                        }}
                                    }}
                                }}
                            }}
                        }}
                     }}
                }}
\t\t\t}}
\t\t}}
\t}}
}}''', encoding="utf-8")

    # .stape
    (target / f"Audio/{name}.stape").write_text(
        f'''params =
{{
    NAME="Tape",
    Tape =
    {{
\t\tTapeClock = 0,
        MapName = "{name}"
    }}
}}''')

    # audio.isc
    (target / f"Audio/{name}_audio.isc").write_text(
        f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
\t<Scene ENGINE_VERSION="55299" GRIDUNIT="0.500000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000">
\t\t<ACTORS NAME="Actor">
\t\t\t<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="MusicTrack" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="World/MAPS/{name}/audio/{name}_musictrack.tpl">
\t\t\t\t<COMPONENTS NAME="MusicTrackComponent">
\t\t\t\t\t<MusicTrackComponent />
\t\t\t\t</COMPONENTS>
\t\t\t</Actor>
\t\t</ACTORS>
\t\t<ACTORS NAME="Actor">
\t\t\t<Actor RELATIVEZ="0.000001" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{name}_sequence" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="World/MAPS/{name}/audio/{name}_sequence.tpl">
\t\t\t\t<COMPONENTS NAME="TapeCase_Component">
\t\t\t\t\t<TapeCase_Component />
\t\t\t\t</COMPONENTS>
\t\t\t</Actor>
\t\t</ACTORS>
\t\t<sceneConfigs>
\t\t\t<SceneConfigs activeSceneConfig="0" />
\t\t</sceneConfigs>
\t</Scene>
</root>''')

    # ConfigMusic.sfi
    (target / "Audio/ConfigMusic.sfi").write_text(
        '''<root>
  <SoundConfiguration TargetName="PC" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="Durango" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="NX" Format="OPUS" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="ORBIS" Format="ADPCM" IsStreamed="1" IsMusic="1"/>
</root>''')


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_game_files(
    map_data: NormalizedMapData,
    target_dir: str | Path,
    config: Optional[AppConfig] = None,
) -> float:
    """Generate all UbiArt engine files for a map.

    Args:
        map_data:   Normalized map data.
        target_dir: Output directory (the map's World/MAPS/<codename>/ folder).
        config:     App configuration.

    Returns:
        The effective videoStartTime used for the installation.

    Raises:
        GameWriterError: If file generation fails.
    """
    config = config or AppConfig()
    target = Path(target_dir)
    name = map_data.codename
    mt = map_data.music_track
    sd = map_data.song_desc
    vst = map_data.effective_video_start_time

    try:
        setup_dirs(target)

        # Determine coach count
        num_coach = sd.num_coach
        if num_coach < 1:
            textures_dir = target / "MenuArt/textures"
            if textures_dir.exists():
                coach_imgs = [
                    f for f in textures_dir.iterdir()
                    if "coach_" in f.name.lower() and f.suffix in (".png", ".tga")
                ]
                num_coach = len(coach_imgs) if coach_imgs else 1
            else:
                num_coach = 1

        _write_musictrack_trk(target, name, mt, vst)
        _write_songdesc(target, name, sd, num_coach, vst, config)
        _write_audio_isc(target, name)

        logger.info("Game files written for '%s' to %s", name, target)
        return vst

    except Exception as exc:
        raise GameWriterError(f"Failed to write game files for '{name}': {exc}") from exc
