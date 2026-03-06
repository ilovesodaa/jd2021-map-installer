import os
import shutil
import json
import argparse
import subprocess
import glob
import zipfile
from log_config import get_logger
from helpers import load_ckd_json, AUDIO_PREVIEW_FADE_S, MAX_JD_VERSION


def _prefer_non_legacy(paths):
    """Sort CKD paths so non-legacy (JSON) files come before main_legacy (binary) ones."""
    non_legacy = [p for p in paths if "main_legacy" not in os.path.basename(p).lower()]
    legacy = [p for p in paths if "main_legacy" in os.path.basename(p).lower()]
    return non_legacy + legacy

logger = get_logger("map_builder")

def lua_long_string(text):
    """Wrap text in a Lua long string literal, handling edge cases.

    Standard: [[text]]
    If text contains ']]': use [=[text]=]
    If text contains ']=]': use [==[text]==]
    And so on, incrementing the level until safe.
    """
    if text is None:
        text = ""
    text = str(text)

    level = 0
    while True:
        close_marker = "]" + ("=" * level) + "]"
        if close_marker not in text:
            break
        level += 1

    open_marker = "[" + ("=" * level) + "["
    close_marker = "]" + ("=" * level) + "]"
    return f"{open_marker}{text}{close_marker}"




def color_array_to_hex(val, default="0xFFFFFFFF"):
    if isinstance(val, str) and val.startswith("0x"):
        return val
    if isinstance(val, (list, tuple)) and len(val) >= 4:
        comps = [int(round(max(0, min(1, c)) * 255)) for c in val[:4]]
        return "0x" + "".join(f"{c:02X}" for c in comps)
    if isinstance(val, (list, tuple)) and val:
        comps = [int(round(max(0, min(1, c)) * 255)) for c in val]
        comps += [255] * (4 - len(comps))
        return "0x" + "".join(f"{c:02X}" for c in comps[:4])
    return default

def setup_dirs(target_dir):
    os.makedirs(os.path.join(target_dir, "Audio"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "Timeline"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "Cinematics"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "VideosCoach"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "MenuArt/Actors"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "MenuArt/textures"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "Timeline/pictos"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "Timeline/Moves"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "Autodance"), exist_ok=True)

def _has_non_ascii(text):
    """Return True if text contains any non-ASCII characters."""
    if not text:
        return False
    try:
        str(text).encode('ascii')
        return False
    except UnicodeEncodeError:
        return True


def check_metadata_encoding(ipk_dir):
    """Scan CKD songdesc for non-ASCII characters in Title, Artist, Credits.

    Returns a dict of {field_name: original_value} for any field that contains
    non-ASCII characters.  Returns empty dict if all fields are clean.
    """
    songdesc_paths = _prefer_non_legacy(
        glob.glob(os.path.join(ipk_dir, "**", "*songdesc*.tpl.ckd"), recursive=True))
    if not songdesc_paths:
        return {}

    try:
        sd_data = load_ckd_json(songdesc_paths[0])
    except (UnicodeDecodeError, Exception) as e:
        logger.warning("metadata encoding check failed: %s", e)
        return {}
    sd_struct = sd_data["COMPONENTS"][0]

    problems = {}
    for field in ('Title', 'Artist', 'Credits', 'DancerName'):
        val = sd_struct.get(field)
        if val and _has_non_ascii(str(val)):
            problems[field] = str(val)
    return problems


def extract_musictrack_metadata(ipk_dir):
    """Extract musictrack structure fields needed for marker-based calculations.

    Returns:
        dict with keys: markers (list[int]), start_beat (int), video_start_time (float)
        Returns None if musictrack CKD cannot be found or parsed.
    """
    ckd_paths = _prefer_non_legacy(
        glob.glob(os.path.join(ipk_dir, "**", "*musictrack*.tpl.ckd"), recursive=True))
    if not ckd_paths:
        return None
    try:
        mt_data = load_ckd_json(ckd_paths[0])
        mt_struct = mt_data["COMPONENTS"][0]["trackData"]["structure"]
        return {
            "markers": mt_struct["markers"],
            "start_beat": mt_struct["startBeat"],
            "video_start_time": mt_struct["videoStartTime"],
        }
    except (KeyError, IndexError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("    Warning: Could not extract musictrack metadata: %s", e)
        return None


# ---------------------------------------------------------------------------
# generate_text_files helper functions
# ---------------------------------------------------------------------------

def _write_musictrack_trk(target_dir, map_name, mt_struct, video_start_time):
    """Write the .trk music track structure file."""
    markers = ", ".join(f"{{ VAL = {m} }}" for m in mt_struct["markers"])
    sigs = ", ".join(f"{{ MusicSignature = {{ beats = {s['beats']}, marker = {s['marker']} }} }}" for s in mt_struct["signatures"])
    sects = ", ".join(f"{{ MusicSection = {{ sectionType = {s['sectionType']}, marker = {s['marker']} }} }}" for s in mt_struct["sections"])

    trk_content = (
        f"structure = {{ MusicTrackStructure = {{ markers = {{ {markers} }}, "
        f"signatures = {{ {sigs} }}, sections = {{ {sects} }}, "
        f"startBeat = {mt_struct['startBeat']}, endBeat = {mt_struct['endBeat']}, "
        f"fadeStartBeat = {mt_struct.get('fadeStartBeat', 0)}, useFadeStartBeat = {int(mt_struct.get('useFadeStartBeat', 0))}, "
        f"fadeEndBeat = {mt_struct.get('fadeEndBeat', 0)}, useFadeEndBeat = {int(mt_struct.get('useFadeEndBeat', 0))}, "
        f"videoStartTime = {video_start_time:.6f}, "
        f"previewEntry = {float(mt_struct.get('previewEntry', 0)):.1f}, "
        f"previewLoopStart = {float(mt_struct.get('previewLoopStart', 0)):.1f}, "
        f"previewLoopEnd = {float(mt_struct.get('previewLoopEnd', 0)):.1f}, "
        f"volume = {float(mt_struct.get('volume', 0)):.6f}, "
        f"fadeInDuration = {mt_struct.get('fadeInDuration', 0)}, fadeInType = {mt_struct.get('fadeInType', 0)}, "
        f"fadeOutDuration = {mt_struct.get('fadeOutDuration', 0)}, fadeOutType = {mt_struct.get('fadeOutType', 0)}, "
        f"entryPoints = {{ }} }} }}"
    )
    with open(os.path.join(target_dir, f"Audio/{map_name}.trk"), "w", encoding="utf-8") as f: f.write(trk_content)


def _write_songdesc(target_dir, map_name, sd_struct, num_coach,
                    phone_images_str, default_colors_lua, tags_lua,
                    dancer_name, jd_version_safe, orig_jd_version_safe,
                    audio_prev_fade):
    """Write SongDesc.tpl and SongDesc.act."""
    # SongDesc.tpl
    with open(os.path.join(target_dir, "SongDesc.tpl"), "w", encoding="utf-8") as f:
        f.write(f'''includeReference("EngineData/Helpers/SongDatabase.ilu")
params =
{{
	NAME = "Actor_Template",
	Actor_Template =
	{{
		TAGS =
		{{
			{{
				VAL = "songdescmain"
			}}
		}},
		WIP = 0,
		LOWUPDATE = 0,
		UPDATE_LAYER = 0,
		PROCEDURAL = 0,
		STARTPAUSED = 0,
		FORCEISENVIRONMENT = 0,
		COMPONENTS =
		{{
			{{
				NAME = "JD_SongDescTemplate",
				JD_SongDescTemplate =
				{{
					MapName = "{map_name}",
					JDVersion = {jd_version_safe},
					OriginalJDVersion = {orig_jd_version_safe},
					Artist = {lua_long_string(sd_struct.get('Artist', 'Unknown Artist'))},
					DancerName = "{dancer_name}",
					Title = {lua_long_string(sd_struct.get('Title', map_name))},
					Credits = {lua_long_string(sd_struct.get('Credits', 'All rights of the producer and other rightholders to the recorded work reserved. Unless otherwise authorized, the duplication, rental, loan, exchange or use of this video game for public performance, broadcasting and online distribution to the public are prohibited.'))},
					NumCoach = {num_coach},
					MainCoach = {sd_struct.get('MainCoach', -1)},
					Difficulty = {sd_struct.get('Difficulty', 2)},
					SweatDifficulty = {sd_struct.get('SweatDifficulty', 1)},
					backgroundType = {sd_struct.get('backgroundType', sd_struct.get('BackgroundType', 0))},
					LyricsType = {sd_struct.get('LyricsType', 0)},
					Energy = {sd_struct.get('Energy', 1)},
					Tags =
					{{{tags_lua}
					}},
					Status = {3 if int(sd_struct.get('Status', 3)) == 12 else sd_struct.get('Status', 3)},
					LocaleID = {sd_struct.get('LocaleID', 4294967295)},
					MojoValue = {sd_struct.get('MojoValue', 0)},
					CountInProgression = 0,
					PhoneImages =
					{{{phone_images_str}
					}},
                    DefaultColors =
                    {{{default_colors_lua}
					}},
					VideoPreviewPath = "",
					Mode = 0,
					AudioPreviewFadeTime = {audio_prev_fade:.6f}
				}}
			}}
		}}
	}}
}}''')

    # SongDesc.act
    with open(os.path.join(target_dir, "SongDesc.act"), "w", encoding="utf-8") as f:
        f.write(f'''params =
{{
    NAME = "Actor",
    Actor =
    {{
        LUA = "World/MAPS/{map_name}/songdesc.tpl",
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
}}''')


def _write_audio_isc(target_dir, map_name):
    """Write musictrack.tpl, sequence.tpl, .stape, and audio.isc."""
    # musictrack.tpl
    with open(os.path.join(target_dir, f"Audio/{map_name}_musictrack.tpl"), "w") as f:
        f.write(f'''includeReference("World/MAPS/{map_name}/audio/{map_name}.trk")
params =
{{
	NAME = "Actor_Template",
	Actor_Template =
	{{
		COMPONENTS =
		{{
			{{
				NAME = "MusicTrackComponent_Template",
				MusicTrackComponent_Template =
				{{
					trackData =
					{{
						MusicTrackData =
						{{
							path = "World/MAPS/{map_name}/audio/{map_name}.wav",
							url = "jmcs://jd-contents/{map_name}/{map_name}.ogg",
							structure = structure
						}}
					}}
				}}
			}}
		}}
	}}
}}''')

    # sequence.tpl
    with open(os.path.join(target_dir, f"Audio/{map_name}_sequence.tpl"), "w", encoding="utf-8") as f:
        f.write(f'''params =
{{
	NAME = "Actor_Template",
	Actor_Template =
	{{
		COMPONENTS =
		{{
			{{
				NAME = "TapeCase_Template",
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
                                            Path = "World/MAPS/{map_name}/audio/{map_name}.stape"
                                        }}
                                    }}
                                }}
                            }}
                        }}
                     }}
                }}
			}}
		}}
	}}
}}''')

    # .stape
    with open(os.path.join(target_dir, f"Audio/{map_name}.stape"), "w") as f:
        f.write(f'''params =
{{
    NAME="Tape",
    Tape =
    {{
		TapeClock = 0,
        MapName = "{map_name}"
    }}
}}''')

    # audio.isc
    with open(os.path.join(target_dir, f"Audio/{map_name}_audio.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="55299" GRIDUNIT="0.500000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000">
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="MusicTrack" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="World/MAPS/{map_name}/audio/{map_name}_musictrack.tpl">
				<COMPONENTS NAME="MusicTrackComponent">
					<MusicTrackComponent />
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000001" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_sequence" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="World/MAPS/{map_name}/audio/{map_name}_sequence.tpl">
				<COMPONENTS NAME="TapeCase_Component">
					<TapeCase_Component />
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<sceneConfigs>
			<SceneConfigs activeSceneConfig="0" />
		</sceneConfigs>
	</Scene>
</root>''')


def _write_timeline_files(target_dir, map_name):
    """Write Timeline TPLs, ACTs, and the tml.isc scene file."""
    for ty, tpl_name in [("Dance", "Motion"), ("Karaoke", "Karaoke")]:
        with open(os.path.join(target_dir, f"Timeline/{map_name}_TML_{ty}.tpl"), "w") as f:
            f.write(f'''params =
{{
	NAME = "Actor_Template",
	Actor_Template =
	{{
		COMPONENTS =
		{{
			{{
				NAME = "TapeCase_Template",
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
                                            Label = "TML_{tpl_name}",
                                            Path = "World/MAPS/{map_name}/timeline/{map_name}_TML_{ty}.{ty[0].lower()}tape"
                                        }}
                                    }}
                                }}
                            }}
                        }}
                     }}
                }}
			}}
		}}
	}}
}}''')

        with open(os.path.join(target_dir, f"Timeline/{map_name}_TML_{ty}.act"), "w") as f:
            f.write(f'''params =
{{
    NAME = "Actor",
    Actor =
    {{
        LUA = "World/MAPS/{map_name}/timeline/{map_name}_TML_{ty}.tpl",
        COMPONENTS =
        {{
            {{
                NAME = "TapeCase_Component",
                TapeCase_Component =
                {{
                }}
            }}
        }}
    }}
}}''')

    # tml.isc
    with open(os.path.join(target_dir, f"Timeline/{map_name}_tml.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
    <Scene>
        <ACTORS NAME="Actor">
            <Actor name="TML_Dance" RELATIVEZ="0.0" SCALE="1.0 1.0" xFLIPPED="0" USERFRIENDLY="TML_Dance" POS2D="0 0" ANGLE="0.0" INSTANCEDATAFILE="World/MAPS/{map_name}/timeline/{map_name}_TML_Dance.act" LUA="World/MAPS/{map_name}/timeline/{map_name}_TML_Dance.tpl">
                <COMPONENTS NAME="TapeCase_Component">
                    <TapeCase_Component />
                </COMPONENTS>
            </Actor>
        </ACTORS>
        <ACTORS NAME="Actor">
            <Actor name="TML_Karaoke" RELATIVEZ="0.0" SCALE="1.0 1.0" xFLIPPED="0" USERFRIENDLY="TML_Karaoke" POS2D="0 0" ANGLE="0.0" INSTANCEDATAFILE="World/MAPS/{map_name}/timeline/{map_name}_TML_Karaoke.act" LUA="World/MAPS/{map_name}/timeline/{map_name}_TML_Karaoke.tpl">
                <COMPONENTS NAME="TapeCase_Component">
                    <TapeCase_Component />
                </COMPONENTS>
            </Actor>
        </ACTORS>
    </Scene>
</root>''')


def _write_videoscoach_files(target_dir, map_name):
    """Write VideosCoach MPDs, video player ACTs, and video ISC files."""
    for mpd_name in [map_name, f"{map_name}_MapPreview"]:
        with open(os.path.join(target_dir, f"VideosCoach/{mpd_name}.mpd"), "w") as f:
            f.write(f'''<?xml version="1.0"?>
<MPD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="urn:mpeg:DASH:schema:MPD:2011" xsi:schemaLocation="urn:mpeg:DASH:schema:MPD:2011" type="static" mediaPresentationDuration="PT230S" minBufferTime="PT1S" profiles="urn:webm:dash:profile:webm-on-demand:2012">
	<Period id="0" start="PT0S" duration="PT230S">
		<AdaptationSet id="0" mimeType="video/webm" codecs="vp9" lang="eng" maxWidth="1920" maxHeight="1080" subsegmentAlignment="true" subsegmentStartsWithSAP="1" bitstreamSwitching="true">
			<Representation id="0" bandwidth="4000000">
				<BaseURL>jmcs://jd-contents/{map_name}/{mpd_name}.webm</BaseURL>
				<SegmentBase indexRange="0-1000">
					<Initialization range="0-500" />
				</SegmentBase>
			</Representation>
		</AdaptationSet>
	</Period>
</MPD>''')

    with open(os.path.join(target_dir, f"VideosCoach/video_player_main.act"), "w") as f:
        f.write(f'''params =
{{
    NAME="Actor",
    Actor =
    {{
        LUA = "world/_common/videoscreen/video_player_main.tpl",
        COMPONENTS =
        {{
            {{
                NAME="PleoComponent",
                PleoComponent =
                {{
                    Video = "World/MAPS/{map_name}/videoscoach/{map_name}.webm",
                    dashMPD = "World/MAPS/{map_name}/videoscoach/{map_name}.mpd"
                }}
            }}
        }}
    }}
}}''')

    with open(os.path.join(target_dir, f"VideosCoach/video_player_map_preview.act"), "w") as f:
        f.write(f'''params =
{{
    NAME="Actor",
    Actor =
    {{
        LUA = "world/_common/videoscreen/video_player_map_preview.tpl",
        COMPONENTS =
        {{
            {{
                NAME="PleoComponent",
                PleoComponent =
                {{
                    Video = "World/MAPS/{map_name}/videoscoach/{map_name}.webm",
                    dashMPD = "World/MAPS/{map_name}/videoscoach/{map_name}.mpd",
                    channelID = "{map_name}"
                }}
            }}
        }}
    }}
}}''')

    with open(os.path.join(target_dir, f"VideosCoach/{map_name}_video.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
    <Scene>
        <ACTORS NAME="Actor">
            <Actor RELATIVEZ="-1.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="VideoScreen" POS2D="0.000000 -4.500000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{map_name}/videoscoach/video_player_main.act" LUA="world/_common/videoscreen/video_player_main.tpl">
            </Actor>
        </ACTORS>
        <ACTORS NAME="Actor">
            <Actor RELATIVEZ="0.000000" SCALE="3.941238 2.220000" xFLIPPED="0" USERFRIENDLY="VideoOutput" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="world/_common/videoscreen/video_output_main.act" LUA="world/_common/videoscreen/video_output_main.tpl">
                <COMPONENTS NAME="PleoTextureGraphicComponent">
                    <PleoTextureGraphicComponent customAnchor="0.000000 0.000000" channelID="">
                        <material>
                            <GFXMaterialSerializable shaderPath="world/_common/matshader/pleofullscreen.msh">
                                <textureSet>
                                    <GFXMaterialTexturePathSet diffuse="" />
                                </textureSet>
                            </GFXMaterialSerializable>
                        </material>
                    </PleoTextureGraphicComponent>
                </COMPONENTS>
            </Actor>
        </ACTORS>
    </Scene>
</root>''')

    with open(os.path.join(target_dir, f"VideosCoach/{map_name}_video_map_preview.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
    <Scene>
        <ACTORS NAME="Actor">
            <Actor RELATIVEZ="-1.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="VideoScreenPreview" POS2D="0.000000 -4.500000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{map_name}/videoscoach/video_player_map_preview.act" LUA="world/_common/videoscreen/video_player_map_preview.tpl">
            </Actor>
        </ACTORS>
    </Scene>
</root>''')


def _write_menuart_files(target_dir, map_name, num_coach):
    """Write MenuArt actor ACTs, menuart.isc, and the main scene ISC."""
    # MenuArt Actors
    coach_arts = [f"coach_{i}" for i in range(1, num_coach + 1)] if num_coach > 0 else []
    arts = ['banner_bkg', 'cover_albumbkg', 'cover_albumcoach', 'cover_generic', 'cover_online', 'map_bkg'] + coach_arts
    for art in arts:
        with open(os.path.join(target_dir, f"MenuArt/Actors/{map_name}_{art}.act"), "w") as f:
            f.write(f'''params =
{{
    NAME="Actor",
    Actor =
    {{
        RELATIVEZ = 0,
        LUA = "enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl",
        COMPONENTS =
        {{
            {{
                NAME = "MaterialGraphicComponent",
                MaterialGraphicComponent =
                {{
                    disableLight = 0,
                    material =
                    {{
                        GFXMaterialSerializable =
                        {{
                            textureSet =
                            {{
                                GFXMaterialTexturePathSet =
                                {{
                                    diffuse = "World/MAPS/{map_name}/menuart/textures/{map_name}_{art}.tga"
                                }}
                            }},
                            shaderPath = "World/_COMMON/MatShader/MultiTexture_1Layer.msh"
                        }}
                    }}
                }}
            }}
        }}
    }}
}}''')

    # MenuArt ISC
    with open(os.path.join(target_dir, f"MenuArt/{map_name}_menuart.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="140999" GRIDUNIT="0.500000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" viewFamily="1">
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="0.300000 0.300000" xFLIPPED="0" USERFRIENDLY="{map_name}_cover_generic" POS2D="266.087555 197.629959" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{map_name}/menuart/actors/{map_name}_cover_generic.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
				<COMPONENTS NAME="MaterialGraphicComponent">
					<MaterialGraphicComponent colorComputerTagId="0" renderInTarget="0" disableLight="0" disableShadow="-1" AtlasIndex="0" customAnchor="0.000000 0.000000" SinusAmplitude="0.000000 0.000000 0.000000" SinusSpeed="1.000000" AngleX="0.000000" AngleY="0.000000">
						<PrimitiveParameters>
							<GFXPrimitiveParam colorFactor="1.000000 1.000000 1.000000 1.000000" FrontLightBrightness="0.000000" FrontLightContrast="1.000000" BackLightBrightness="0.000000" BackLightContrast="1.000000" colorFog="0.000000 0.000000 0.000000 0.000000" DynamicFogFactor="1.000000" useStaticFog="0" RenderInReflections="1">
								<ENUM NAME="gfxOccludeInfo" SEL="0" />
							</GFXPrimitiveParam>
						</PrimitiveParameters>
						<ENUM NAME="anchor" SEL="1" />
						<material>
							<GFXMaterialSerializable ATL_Channel="0" shaderPath="World/_COMMON/MatShader/MultiTexture_1Layer.msh" stencilTest="0" alphaTest="4294967295" alphaRef="4294967295">
								<textureSet>
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{map_name}/menuart/textures/{map_name}_cover_generic.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
								</textureSet>
								<materialParams>
									<GFXMaterialSerializableParam Reflector_factor="0.000000" />
								</materialParams>
							</GFXMaterialSerializable>
						</material>
						<ENUM NAME="oldAnchor" SEL="1" />
					</MaterialGraphicComponent>
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="0.300000 0.300000" xFLIPPED="0" USERFRIENDLY="{map_name}_cover_online" POS2D="-150.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{map_name}/menuart/actors/{map_name}_cover_online.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
				<COMPONENTS NAME="MaterialGraphicComponent">
					<MaterialGraphicComponent colorComputerTagId="0" renderInTarget="0" disableLight="0" disableShadow="-1" AtlasIndex="0" customAnchor="0.000000 0.000000" SinusAmplitude="0.000000 0.000000 0.000000" SinusSpeed="1.000000" AngleX="0.000000" AngleY="0.000000">
						<PrimitiveParameters>
							<GFXPrimitiveParam colorFactor="1.000000 1.000000 1.000000 1.000000" FrontLightBrightness="0.000000" FrontLightContrast="1.000000" BackLightBrightness="0.000000" BackLightContrast="1.000000" colorFog="0.000000 0.000000 0.000000 0.000000" DynamicFogFactor="1.000000" useStaticFog="0" RenderInReflections="1">
								<ENUM NAME="gfxOccludeInfo" SEL="0" />
							</GFXPrimitiveParam>
						</PrimitiveParameters>
						<ENUM NAME="anchor" SEL="1" />
						<material>
							<GFXMaterialSerializable ATL_Channel="0" shaderPath="World/_COMMON/MatShader/MultiTexture_1Layer.msh" stencilTest="0" alphaTest="4294967295" alphaRef="4294967295">
								<textureSet>
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{map_name}/menuart/textures/{map_name}_cover_online.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
								</textureSet>
								<materialParams>
									<GFXMaterialSerializableParam Reflector_factor="0.000000" />
								</materialParams>
							</GFXMaterialSerializable>
						</material>
						<ENUM NAME="oldAnchor" SEL="1" />
					</MaterialGraphicComponent>
				</COMPONENTS>
			</Actor>
		</ACTORS>
	</Scene>
</root>''')

    # Main Scene ISC
    with open(os.path.join(target_dir, f"{map_name}_MAIN_SCENE.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="81615" GRIDUNIT="2.000000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000">
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_AUDIO" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{map_name}/audio/{map_name}_audio.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_CINE" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{map_name}/cinematics/{map_name}_cine.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_TML" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{map_name}/timeline/{map_name}_tml.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_AUTODANCE" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{map_name}/autodance/{map_name}_autodance.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_VIDEO" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{map_name}/videoscoach/{map_name}_video.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name} Main" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{map_name}/songdesc.act" LUA="World/MAPS/{map_name}/songdesc.tpl">
				<COMPONENTS NAME="JD_SongDescComponent">
					<JD_SongDescComponent />
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_menuart" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{map_name}/menuart/{map_name}_menuart.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="3" />
			</SubSceneActor>
		</ACTORS>
		<sceneConfigs>
			<SceneConfigs activeSceneConfig="0">
				<sceneConfigs NAME="JD_MapSceneConfig">
					<JD_MapSceneConfig hud="0" cursors="0">
						<ENUM NAME="type" SEL="1" />
						<ENUM NAME="musicscore" SEL="2" />
					</JD_MapSceneConfig>
				</sceneConfigs>
			</SceneConfigs>
		</sceneConfigs>
	</Scene>
</root>''')


def _write_autodance_stubs(target_dir, map_name):
    """Write Autodance ISC, TPL, and ACT stub files.

    Skips writing if the TPL already contains real converted data (>1KB)
    from Step 11 of the pipeline, to avoid overwriting during sync
    refinement re-runs.
    """
    autodance_tpl_path = os.path.join(target_dir, f"Autodance/{map_name}_autodance.tpl")
    _skip_autodance = (os.path.exists(autodance_tpl_path)
                       and os.path.getsize(autodance_tpl_path) >= 1024)

    if _skip_autodance:
        return

    with open(os.path.join(target_dir, f"Autodance/{map_name}_autodance.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="81615" GRIDUNIT="0.500000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000">
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_autodance" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{map_name}/autodance/{map_name}_autodance.act" LUA="World/MAPS/{map_name}/autodance/{map_name}_autodance.tpl">
				<COMPONENTS NAME="JD_AutodanceComponent">
					<JD_AutodanceComponent />
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<sceneConfigs>
			<SceneConfigs activeSceneConfig="0" />
		</sceneConfigs>
	</Scene>
</root>''')

    with open(autodance_tpl_path, "w") as f:
        f.write(f'''params =
{{
	NAME = "Actor_Template",
	Actor_Template =
	{{
		COMPONENTS =
		{{
			{{
				NAME = "JD_AutodanceComponent_Template",
				JD_AutodanceComponent_Template =
				{{
					song = "{map_name}",
					autodanceData =
					{{
						JD_AutodanceData =
						{{
							recording_structure = {{}},
							video_structure = {{
								NAME = "JD_AutodanceVideoStructure",
								JD_AutodanceVideoStructure =
								{{
									SongStartPosition = 0,
									Duration = 0,
									ThumbnailTime = 0,
									FadeOutDuration = 0,
									GroundPlanePath = "invalid ",
									FirstLayerTripleBackgroundPath = "invalid ",
									SecondLayerTripleBackgroundPath = "invalid ",
									ThirdLayerTripleBackgroundPath = "invalid ",
									playback_events = {{}},
								}},
							}},
							autodanceSoundPath = ""
						}}
					}}
				}}
			}},
		}}
	}}
}}''')

    with open(os.path.join(target_dir, f"Autodance/{map_name}_autodance.act"), "w") as f:
        f.write(f'''params =
{{
	NAME = "Actor",
	Actor =
	{{
		LUA = "World/MAPS/{map_name}/autodance/{map_name}_autodance.tpl",
	}}
}}''')


def _write_cinematics_stubs(target_dir, map_name):
    """Write Cinematics tape/ISC/TPL/ACT stubs and ConfigMusic.sfi."""
    # Cinematics tape
    with open(os.path.join(target_dir, f"Cinematics/{map_name}_MainSequence.tape"), "w") as f:
        f.write(f'''params =
{{
    NAME = "Tape",
    Tape =
    {{
        Clips = {{
        }},
        TapeClock = 0,
        TapeBarCount = 1,
        FreeResourcesAfterPlay = 0,
        MapName = "{map_name}",
        SoundwichEvent = ""
    }}
}}''')

    # Cinematics ISC
    with open(os.path.join(target_dir, f"Cinematics/{map_name}_cine.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="55299" GRIDUNIT="0.500000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000">
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{map_name}_MainSequence" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{map_name}/cinematics/{map_name}_mainsequence.act" LUA="World/MAPS/{map_name}/cinematics/{map_name}_mainsequence.tpl">
				<COMPONENTS NAME="MasterTape">
					<MasterTape bankState="4294967295" />
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<sceneConfigs>
			<SceneConfigs activeSceneConfig="0" />
		</sceneConfigs>
	</Scene>
</root>''')

    # Cinematics TPL
    with open(os.path.join(target_dir, f"Cinematics/{map_name}_mainsequence.tpl"), "w") as f:
        f.write(f'''params =
{{
    NAME = "Actor_Template",
    Actor_Template =
    {{
        COMPONENTS =
        {{
            {{
                NAME = "MasterTape_Template",
                MasterTape_Template =
                {{
                    TapePath = "World/MAPS/{map_name}/Cinematics/{map_name}_MainSequence.tape"
                }}
            }}
        }}
    }}
}}''')

    # Cinematics ACT
    with open(os.path.join(target_dir, f"Cinematics/{map_name}_mainsequence.act"), "w") as f:
        f.write(f'''params =
{{
    NAME = "Actor",
    Actor =
    {{
        LUA = "World/MAPS/{map_name}/cinematics/{map_name}_mainsequence.tpl",
        COMPONENTS =
        {{
            {{
                NAME = "MasterTape"
            }}
        }}
    }}
}}''')

    # ConfigMusic.sfi (sound format config per platform)
    with open(os.path.join(target_dir, f"Audio/ConfigMusic.sfi"), "w") as f:
        f.write('''<root>
  <SoundConfiguration TargetName="PC" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="PS3" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="ORBIS" Format="ADPCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="X360" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="Cafe" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="WII" Format="ADPCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="Durango" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="NX" Format="OPUS" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="GGP" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="PROSPERO" Format="PCM" IsStreamed="1" IsMusic="1"/>
  <SoundConfiguration TargetName="SCARLETT" Format="PCM" IsStreamed="1" IsMusic="1"/>
</root>''')


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def generate_text_files(map_name, ipk_dir, target_dir, video_start_time_override=None, metadata_overrides=None):
    """Generate all UbiArt config/scene files for a map installation.

    Parses CKD metadata, then delegates file generation to helper functions.
    """
    map_lower = map_name.lower()

    # Find musictrack.tpl.ckd (prefer non-legacy JSON over binary main_legacy)
    ckd_json_paths = _prefer_non_legacy(
        glob.glob(os.path.join(ipk_dir, "**", "*musictrack*.tpl.ckd"), recursive=True))
    if not ckd_json_paths:
        logger.error("Error: Could not find musictrack.tpl.ckd")
        return None
    ckd_json_path = ckd_json_paths[0]

    # Find and parse songdesc.tpl.ckd for metadata (prefer non-legacy JSON)
    songdesc_paths = _prefer_non_legacy(
        glob.glob(os.path.join(ipk_dir, "**", "*songdesc*.tpl.ckd"), recursive=True))
    sd_struct = {}
    if songdesc_paths:
        try:
            sd_data = load_ckd_json(songdesc_paths[0])
            sd_struct = sd_data["COMPONENTS"][0]
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError, IndexError) as e:
            logger.warning("    Could not parse songdesc CKD: %s", e)
            logger.warning("    Using default metadata")
    else:
        logger.warning("    songdesc.tpl.ckd not found; using default metadata")

    default_colors = sd_struct.get("DefaultColors", {}) if sd_struct else {}

    # Build DefaultColors: use CKD values/keys where available, fall back to hardcoded for missing.
    # Match case-insensitively so CKD "songcolor_1a" maps to fallback "songColor_1A" without duplicating.
    default_color_fallbacks = {
        "lyrics": "0xFF1B34AA",
        "theme": "0xFFFFFFFF",
        "songColor_1A": "0x00D1D0D0",
        "songColor_1B": "0xF50005D0",
        "songColor_2A": "0x00D1D0D0",
        "songColor_2B": "0xF50005D0",
    }
    # lowercase -> (actual_key_from_ckd, raw_value) for fast case-insensitive lookup
    ckd_lower_map = {k.lower(): (k, v) for k, v in default_colors.items()}

    # Each entry is (output_key, hex_value)
    resolved_colors = []
    for fb_key, fb_hex in default_color_fallbacks.items():
        if fb_key.lower() in ckd_lower_map:
            ckd_key, ckd_raw = ckd_lower_map[fb_key.lower()]
            resolved_colors.append((ckd_key, color_array_to_hex(ckd_raw, default=fb_hex)))
        else:
            resolved_colors.append((fb_key, fb_hex))
    # Append any extra CKD keys not covered by fallbacks
    fb_lower_set = {k.lower() for k in default_color_fallbacks}
    for ckd_key, ckd_raw in default_colors.items():
        if ckd_key.lower() not in fb_lower_set:
            resolved_colors.append((ckd_key, color_array_to_hex(ckd_raw)))

    default_colors_lua = ""
    for key, val in resolved_colors:
        default_colors_lua += f'''
						{{
							KEY = "{key}",
							VAL = "{val}"
						}},'''

    try:
        mt_data = load_ckd_json(ckd_json_path)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        logger.error("Error: Cannot parse musictrack CKD (%s): %s",
                     os.path.basename(ckd_json_path), e)
        return None
    mt_struct = mt_data["COMPONENTS"][0]["trackData"]["structure"]

    video_start_time = video_start_time_override if video_start_time_override is not None else mt_struct['videoStartTime']

    # Safety check: if startBeat < 0 (map has pre-roll) but videoStartTime
    # is 0.0, the game engine will assert "adding a brick in the past".
    # This catches cases where the caller should have synthesized a value.
    if video_start_time == 0.0 and mt_struct.get("startBeat", 0) < 0:
        # Synthesize from markers as a last-resort fallback
        markers = mt_struct.get("markers", [])
        idx = abs(mt_struct["startBeat"])
        if markers and idx < len(markers):
            video_start_time = -(markers[idx] / 48.0 / 1000.0)
            logger.warning("    videoStartTime was 0.0 with startBeat=%d; "
                           "auto-synthesized %.5f from markers",
                           mt_struct["startBeat"], video_start_time)
        else:
            logger.warning("    videoStartTime is 0.0 with startBeat=%d. "
                           "The game may assert 'adding a brick in the past'. "
                           "Use VIDEO_OFFSET to set a negative value.",
                           mt_struct["startBeat"])

    # Determine Coach Number: prefer authoritative NumCoach from songdesc CKD,
    # fall back to counting coach image files on disk.
    num_coach = sd_struct.get("NumCoach", 0)
    if not num_coach or num_coach < 1:
        coach_imgs = [f for f in os.listdir(os.path.join(target_dir, "MenuArt/textures"))
                      if "_coach_" in f.lower() and (f.endswith(".png") or f.endswith(".tga"))]
        num_coach = len(coach_imgs) if coach_imgs else 1

    ckd_phone = sd_struct.get("PhoneImages", {})
    if ckd_phone:
        # Use CKD-provided paths (includes cover + all coaches)
        phone_images_str = ""
        for k, v in ckd_phone.items():
            phone_images_str += f'''
						{{
							KEY = "{k}",
							VAL = "{v}"
						}},'''
        phone_images_str = phone_images_str.rstrip(",")
    else:
        # Fallback: reconstruct from convention
        phone_images_str = f'''
						{{
							KEY = "cover",
							VAL = "world/maps/{map_lower}/menuart/textures/{map_lower}_cover_phone.jpg"
						}}'''
        for i in range(1, num_coach + 1):
            phone_images_str += f''',
						{{
							KEY = "coach{i}",
							VAL = "world/maps/{map_lower}/menuart/textures/{map_lower}_coach_{i}_phone.png"
						}}'''

    # Calculate audio preview fade time (usually 2.0s if it exists)
    audio_prev_fade = AUDIO_PREVIEW_FADE_S if float(mt_struct.get('previewEntry', 0)) > 0 else 0.0

    # Apply metadata overrides (for non-ASCII replacement)
    if metadata_overrides:
        for field, replacement in metadata_overrides.items():
            if field in sd_struct or field in ('Title', 'Artist', 'Credits', 'DancerName'):
                sd_struct[field] = replacement

    # Sanitize metadata strings for Lua output
    dancer_name = str(sd_struct.get('DancerName', 'Unknown Dancer'))
    dancer_name = dancer_name.replace('"', '\\"').replace('\n', ' ').replace('\r', '')

    # Extract tags from CKD, fall back to ["Main"]
    raw_tags = sd_struct.get("Tags", ["Main"]) or ["Main"]
    tags_lua = ""
    for t in raw_tags:
        tags_lua += f'''
						{{
							VAL = "{t}"
						}},'''
    tags_lua = tags_lua.rstrip(",")

    # Cap JDVersion and OriginalJDVersion to 2021 to prevent GameManagerConfig crashes on JD2022+ maps
    jd_version_safe = min(int(sd_struct.get('JDVersion', MAX_JD_VERSION)), MAX_JD_VERSION)
    orig_jd_version_safe = min(int(sd_struct.get('OriginalJDVersion', jd_version_safe)), MAX_JD_VERSION)

    # --- Generate all files via helpers ---
    _write_musictrack_trk(target_dir, map_name, mt_struct, video_start_time)
    _write_songdesc(target_dir, map_name, sd_struct, num_coach,
                    phone_images_str, default_colors_lua, tags_lua,
                    dancer_name, jd_version_safe, orig_jd_version_safe,
                    audio_prev_fade)
    _write_audio_isc(target_dir, map_name)
    _write_timeline_files(target_dir, map_name)
    _write_videoscoach_files(target_dir, map_name)
    _write_menuart_files(target_dir, map_name, num_coach)
    _write_autodance_stubs(target_dir, map_name)
    _write_cinematics_stubs(target_dir, map_name)

    return video_start_time

def main():
    pass

if __name__ == "__main__":
    pass
