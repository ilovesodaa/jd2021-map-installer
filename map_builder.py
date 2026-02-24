import os
import shutil
import json
import argparse
import subprocess
import glob
import zipfile

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

def generate_text_files(map_name, ipk_dir, target_dir, video_start_time_override=None):
    map_lower = map_name.lower()
    
    # Find musictrack.tpl.ckd
    ckd_json_paths = glob.glob(os.path.join(ipk_dir, "**", "*musictrack.tpl.ckd"), recursive=True)
    if not ckd_json_paths:
        print("Error: Could not find musictrack.tpl.ckd")
        return None
    ckd_json_path = ckd_json_paths[0]
    
    # NEW: Find and parse songdesc.tpl.ckd for metadata
    songdesc_paths = glob.glob(os.path.join(ipk_dir, "**", "*songdesc.tpl.ckd"), recursive=True)
    sd_struct = {}
    if songdesc_paths:
        with open(songdesc_paths[0], "r", encoding="utf-8") as f:
            sd_data = json.loads(f.read().strip('\x00\r\n '))
            sd_struct = sd_data["COMPONENTS"][0]

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
    
    with open(ckd_json_path, "r", encoding="utf-8") as f:
        mt_data = json.loads(f.read().strip('\x00\r\n '))
    mt_struct = mt_data["COMPONENTS"][0]["trackData"]["structure"]
    
    markers = ", ".join(f"{{ VAL = {m} }}" for m in mt_struct["markers"])
    sigs = ", ".join(f"{{ MusicSignature = {{ beats = {s['beats']}, marker = {s['marker']} }} }}" for s in mt_struct["signatures"])
    sects = ", ".join(f"{{ MusicSection = {{ sectionType = {s['sectionType']}, marker = {s['marker']} }} }}" for s in mt_struct["sections"])

    video_start_time = video_start_time_override if video_start_time_override is not None else mt_struct['videoStartTime']

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

    # Determine Coach Number from downloaded images
    coach_imgs = [f for f in os.listdir(os.path.join(target_dir, "MenuArt/textures")) if "_coach_" in f.lower() and f.endswith(".png")]
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
    audio_prev_fade = 2.0 if float(mt_struct.get('previewEntry', 0)) > 0 else 0.0

    # Extract tags from CKD, fall back to ["Main"]
    raw_tags = sd_struct.get("Tags", ["Main"]) or ["Main"]
    tags_lua = ""
    for t in raw_tags:
        tags_lua += f'''
						{{
							VAL = "{t}"
						}},'''
    tags_lua = tags_lua.rstrip(",")

    # 1. SongDesc.tpl
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
					JDVersion = {sd_struct.get('JDVersion', 2021)},
					OriginalJDVersion = {sd_struct.get('OriginalJDVersion', 2021)},
					Artist = [[{sd_struct.get('Artist', 'Unknown Artist')}]],
					DancerName = "{sd_struct.get('DancerName', 'Unknown Dancer')}",
					Title = [[{sd_struct.get('Title', map_name)}]],
					Credits = [[{sd_struct.get('Credits', 'All rights of the producer and other rightholders to the recorded work reserved. Unless otherwise authorized, the duplication, rental, loan, exchange or use of this video game for public performance, broadcasting and online distribution to the public are prohibited.')}]],
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
					Status = {sd_struct.get('Status', 3)},
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

    # 2. SongDesc.act
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

    # 3. {map_name}_musictrack.tpl
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

    # 4. {map_name}_sequence.tpl
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

    # 5. {map_name}.stape
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

    # 6. {map_name}_audio.isc
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

    # 7. Timeline TPLs and ACTs
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

    # 8. {map_name}_tml.isc
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

    # 9. VideosCoach
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

    # 10. MenuArt Actors
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

    # 11. MenuArt ISC & Main Scene ISC
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

    # 11.5 Autodance Templates
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

    with open(os.path.join(target_dir, f"Autodance/{map_name}_autodance.tpl"), "w") as f:
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
							video_structure = {{}},
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

    # 12. Cinematics tape, cine isc, tpl, act
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

    # 13. Audio ConfigMusic.sfi (sound format config per platform)
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

    return video_start_time

def main():
    pass

if __name__ == "__main__":
    pass
