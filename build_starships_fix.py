import os
import shutil
import json

# --- Config ---
MAP_NAME = "Starships"
MAP_NAME_LOWER = MAP_NAME.lower()
SRC_DIR = r"d:\jd2021pc\Starships"
DECODED_DIR = os.path.join(SRC_DIR, "decoded")
TARGET_DIR = rf"d:\jd2021pc\jd21\data\World\MAPS\{MAP_NAME}"

def generate_text_files():
    print("Generating text files...")
    
    os.makedirs(os.path.join(TARGET_DIR, "Audio"), exist_ok=True)
    os.makedirs(os.path.join(TARGET_DIR, "Timeline"), exist_ok=True)
    os.makedirs(os.path.join(TARGET_DIR, "Cinematics"), exist_ok=True)
    os.makedirs(os.path.join(TARGET_DIR, "VideosCoach"), exist_ok=True)
    os.makedirs(os.path.join(TARGET_DIR, "MenuArt/Actors"), exist_ok=True)
    os.makedirs(os.path.join(TARGET_DIR, "MenuArt/textures"), exist_ok=True)
    os.makedirs(os.path.join(TARGET_DIR, "Timeline/pictos"), exist_ok=True)
    
    # Generate music track structure from ORIGINAL JDU timing data
    ckd_json_path = os.path.join(SRC_DIR, "ipk_extracted/cache/itf_cooked/pc/world/maps/starships/audio/starships_musictrack.tpl.ckd")
    with open(ckd_json_path, "r") as f:
        mt_data = json.loads(f.read().strip('\x00\r\n '))
    mt_struct = mt_data["COMPONENTS"][0]["trackData"]["structure"]
    
    # Convert JSON arrays to Lua format
    markers = ", ".join(f"{{ VAL = {m} }}" for m in mt_struct["markers"])
    sigs = ", ".join(
        f"{{ MusicSignature = {{ beats = {s['beats']}, marker = {s['marker']} }} }}"
        for s in mt_struct["signatures"]
    )
    sects = ", ".join(
        f"{{ MusicSection = {{ sectionType = {s['sectionType']}, marker = {s['marker']} }} }}"
        for s in mt_struct["sections"]
    )
    
    trk_content = (
        f"structure = {{ MusicTrackStructure = {{ markers = {{ {markers} }}, "
        f"signatures = {{ {sigs} }}, "
        f"sections = {{ {sects} }}, "
        f"startBeat = {mt_struct['startBeat']}, endBeat = {mt_struct['endBeat']}, "
        f"fadeStartBeat = {mt_struct['fadeStartBeat']}, useFadeStartBeat = {int(mt_struct['useFadeStartBeat'])}, "
        f"fadeEndBeat = {mt_struct['fadeEndBeat']}, useFadeEndBeat = {int(mt_struct['useFadeEndBeat'])}, "
        f"videoStartTime = {mt_struct['videoStartTime']:.6f}, "
        f"previewEntry = {float(mt_struct['previewEntry']):.1f}, "
        f"previewLoopStart = {float(mt_struct['previewLoopStart']):.1f}, "
        f"previewLoopEnd = {float(mt_struct['previewLoopEnd']):.1f}, "
        f"volume = {float(mt_struct['volume']):.6f}, "
        f"fadeInDuration = {mt_struct['fadeInDuration']}, fadeInType = {mt_struct['fadeInType']}, "
        f"fadeOutDuration = {mt_struct['fadeOutDuration']}, fadeOutType = {mt_struct['fadeOutType']}, "
        f"entryPoints = {{ }} }} }}"
    )
    with open(os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}.trk"), "w") as f:
        f.write(trk_content)
        
    # 1. SongDesc.tpl (LUA)
    with open(os.path.join(TARGET_DIR, "SongDesc.tpl"), "w") as f:
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
					MapName = "{MAP_NAME}",
					JDVersion = 2021,
					OriginalJDVersion = 2021,
					Artist = "Nicki Minaj",
					DancerName = "Unknown Dancer",
					Title = "{MAP_NAME}",
					Credits = "Credits Here",
					ChoreoCreator = "Choreographer",
					NumCoach = 1,
					MainCoach = -1,
					Difficulty = 2,
					SweatDifficulty = 1,
					BackgroundType = 0,
					LyricsType = 0,
					Tags = 
					{{
						{{
							VAL = "Main"
						}}
					}},
					Status = 3,
					LocaleID = 4294967295,
					MojoValue = 0,
					CountInProgression = 1,
					PhoneImages = 
					{{
						{{
							KEY = "cover",
							VAL = "world/maps/{MAP_NAME_LOWER}/menuart/textures/{MAP_NAME_LOWER}_cover_phone.jpg"
						}},
						{{
							KEY = "coach1",
							VAL = "world/maps/{MAP_NAME_LOWER}/menuart/textures/{MAP_NAME_LOWER}_coach_1_phone.png"
						}}
					}},
					DefaultColors = 
					{{
						{{
							KEY = "lyrics",
							VAL = "0xFFFFFFFF"
						}},
						{{
							KEY = "theme",
							VAL = "0xFFFFFFFF"
						}},
						{{
							KEY = "songColor_1A",
							VAL = "0x00D1D0D0"
						}},
						{{
							KEY = "songColor_1B",
							VAL = "0xF50005D0"
						}},
						{{
							KEY = "songColor_2A",
							VAL = "0x00D1D0D0"
						}},
						{{
							KEY = "songColor_2B",
							VAL = "0xF50005D0"
						}}
					}},
					VideoPreviewPath = "",
					Mode = 6,
					AudioPreviewFadeTime = 0.000000
				}},
			}},
		}},
	}},
}}''')

    # 2. SongDesc.act (LUA)
    with open(os.path.join(TARGET_DIR, "SongDesc.act"), "w") as f:
        f.write(f'''params =
{{
    NAME="Actor",
    Actor =
    {{
        LUA = "World/MAPS/{MAP_NAME}/songdesc.tpl",
        COMPONENTS =
        {{
            {{
                NAME = "JD_SongDescComponent",
                JD_SongDescComponent =
                {{
                }},
            }},
        }},
    }}
}}''')

    # 3. Audio (LUA & XML format mix)
    with open(os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}_musictrack.tpl"), "w") as f:
        f.write(f'''includeReference("World/MAPS/{MAP_NAME}/audio/{MAP_NAME}.trk")

params =
{{
	NAME = "Actor_Template",
	Actor_Template =
	{{
		COMPONENTS = 
		{{
			{{
				NAME="MusicTrackComponent_Template",
				MusicTrackComponent_Template =
				{{
					trackData = {{
						MusicTrackData = {{
						path = "World/MAPS/{MAP_NAME}/audio/{MAP_NAME}.wav",
                        url = "jmcs://jd-contents/{MAP_NAME}/{MAP_NAME}.ogg",
						structure = structure
						}}
					}}
				}}
			}},
		}}
	}}
}}''')

    with open(os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}_sequence.tpl"), "w") as f:
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
                                            Path = "World/MAPS/{MAP_NAME}/audio/{MAP_NAME}.stape",
                                        }},
                                    }},
                                }},
                            }},
                        }},
                     }},
                }},
			}},
		}}
	}}
}}''')

    with open(os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}_audio.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="55299" GRIDUNIT="0.500000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000">
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="MusicTrack" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="World/MAPS/{MAP_NAME}/audio/{MAP_NAME}_musictrack.tpl">
				<COMPONENTS NAME="MusicTrackComponent">
					<MusicTrackComponent />
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000001" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_sequence" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="World/MAPS/{MAP_NAME}/audio/{MAP_NAME}_sequence.tpl">
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

    # 4. Timeline
    with open(os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML_Dance.tpl"), "w") as f:
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
                                            Label = "TML_Motion",
                                            Path = "World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Dance.dtape",
                                        }},
                                    }},
                                }},
                            }},
                        }},
                     }},
                }},
            }}
        }}
    }}
}}''')

    with open(os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML_Karaoke.tpl"), "w") as f:
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
                                            Label = "TML_Karaoke",
                                            Path = "World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Karaoke.ktape",
                                        }},
                                    }},
                                }},
                            }},
                        }},
                     }},
                }},
            }}
        }}
    }}
}}''')

    with open(os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML_Dance.act"), "w") as f:
        f.write(f'''params = 
{{
    NAME = "Actor",
    Actor =
    {{
        LUA = "World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Dance.tpl",
        COMPONENTS =
        {{
            {{
                NAME = "TapeCase_Component",
            }}
        }}
    }}
}}''')

    with open(os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML_Karaoke.act"), "w") as f:
        f.write(f'''params = 
{{
    NAME = "Actor",
    Actor =
    {{
        LUA = "World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Karaoke.tpl",
        COMPONENTS =
        {{
            {{
                NAME = "TapeCase_Component",
            }}
        }}
    }}
}}''')

    with open(os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_tml.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
    <Scene>
        <ACTORS NAME="Actor">
            <Actor name="TML_Dance" RELATIVEZ="0.0" SCALE="1.0 1.0" xFLIPPED="0" USERFRIENDLY="TML_Dance" POS2D="0 0" ANGLE="0.0" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Dance.act" LUA="World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Dance.tpl">
                <COMPONENTS NAME="TapeCase_Component">
                    <TapeCase_Component />
                </COMPONENTS>
            </Actor>
        </ACTORS>
        <ACTORS NAME="Actor">
            <Actor name="TML_Karaoke" RELATIVEZ="0.0" SCALE="1.0 1.0" xFLIPPED="0" USERFRIENDLY="TML_Karaoke" POS2D="0 0" ANGLE="0.0" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Karaoke.act" LUA="World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Karaoke.tpl">
                <COMPONENTS NAME="TapeCase_Component">
                    <TapeCase_Component />
                </COMPONENTS>
            </Actor>
        </ACTORS>
    </Scene>
</root>''')

    # 5. Video .mpd manifests! (The crucial fix!)
    
    # Main Video
    with open(os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}.mpd"), "w") as f:
         f.write(f'''<?xml version="1.0"?>
<MPD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="urn:mpeg:DASH:schema:MPD:2011" xsi:schemaLocation="urn:mpeg:DASH:schema:MPD:2011" type="static" mediaPresentationDuration="PT230S" minBufferTime="PT1S" profiles="urn:webm:dash:profile:webm-on-demand:2012">
	<Period id="0" start="PT0S" duration="PT230S">
		<AdaptationSet id="0" mimeType="video/webm" codecs="vp9" lang="eng" maxWidth="1920" maxHeight="1080" subsegmentAlignment="true" subsegmentStartsWithSAP="1" bitstreamSwitching="true">
			<Representation id="0" bandwidth="4000000">
				<BaseURL>jmcs://jd-contents/{MAP_NAME}/{MAP_NAME}.webm</BaseURL>
				<SegmentBase indexRange="0-1000">
					<Initialization range="0-500" />
				</SegmentBase>
			</Representation>
		</AdaptationSet>
	</Period>
</MPD>''')

    # Map Preview Video
    with open(os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}_MapPreview.mpd"), "w") as f:
         f.write(f'''<?xml version="1.0"?>
<MPD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="urn:mpeg:DASH:schema:MPD:2011" xsi:schemaLocation="urn:mpeg:DASH:schema:MPD:2011" type="static" mediaPresentationDuration="PT20S" minBufferTime="PT1S" profiles="urn:webm:dash:profile:webm-on-demand:2012">
	<Period id="0" start="PT0S" duration="PT20S">
		<AdaptationSet id="0" mimeType="video/webm" codecs="vp9" lang="eng" maxWidth="1920" maxHeight="1080" subsegmentAlignment="true" subsegmentStartsWithSAP="1" bitstreamSwitching="true">
			<Representation id="0" bandwidth="4000000">
				<BaseURL>jmcs://jd-contents/{MAP_NAME}/{MAP_NAME}_MapPreview.webm</BaseURL>
				<SegmentBase indexRange="0-1000">
					<Initialization range="0-500" />
				</SegmentBase>
			</Representation>
		</AdaptationSet>
	</Period>
</MPD>''')

    with open(os.path.join(TARGET_DIR, f"VideosCoach/video_player_main.act"), "w") as f:
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
                    Video = "World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}.webm",
					dashMPD = "World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}.mpd",
                }},
            }},
        }},
    }},
}}''')

    with open(os.path.join(TARGET_DIR, f"VideosCoach/video_player_map_preview.act"), "w") as f:
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
                    Video = "World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}.webm",
					dashMPD = "World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}.mpd",
					channelID = "{MAP_NAME}",
                }},
            }},
        }},
    }},
}}''')

    with open(os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}_video.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
    <Scene>
        <ACTORS NAME="Actor">
            <Actor RELATIVEZ="-1.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="VideoScreen" POS2D="0.000000 -4.500000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/videoscoach/video_player_main.act" LUA="world/_common/videoscreen/video_player_main.tpl">
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

    with open(os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}_video_map_preview.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
    <Scene>
        <ACTORS NAME="Actor">
            <Actor RELATIVEZ="-1.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="VideoScreenPreview" POS2D="0.000000 -4.500000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/videoscoach/video_player_map_preview.act" LUA="world/_common/videoscreen/video_player_map_preview.tpl">
            </Actor>
        </ACTORS>
    </Scene>
</root>''')

    # 7. MenuArt actors
    for art in ['banner_bkg', 'coach_1', 'cover_albumbkg', 'cover_albumcoach', 'cover_generic', 'cover_online', 'map_bkg']:
        with open(os.path.join(TARGET_DIR, f"MenuArt/Actors/{MAP_NAME}_{art}.act"), "w") as f:
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
                                    diffuse = "World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_{art}.tga",
                                }},
                            }},
                            shaderPath = "World/_COMMON/MatShader/MultiTexture_1Layer.msh",
                        }},
                    }},
                }},
            }},
        }},
    }}
}}''')

    # 7.5 MenuArt isc (full inline components matching GetGetDown reference)
    with open(os.path.join(TARGET_DIR, f"MenuArt/{MAP_NAME}_menuart.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="140999" GRIDUNIT="0.500000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" viewFamily="1">
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="0.300000 0.300000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_cover_generic" POS2D="266.087555 197.629959" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/menuart/actors/{MAP_NAME}_cover_generic.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
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
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_cover_generic.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
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
			<Actor RELATIVEZ="0.000000" SCALE="0.300000 0.300000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_cover_online" POS2D="-150.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/menuart/actors/{MAP_NAME}_cover_online.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
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
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_cover_online.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
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
			<Actor RELATIVEZ="0.000000" SCALE="0.300000 0.300000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_cover_albumcoach" POS2D="738.106323 359.612030" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/menuart/actors/{MAP_NAME}_cover_albumcoach.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
				<COMPONENTS NAME="MaterialGraphicComponent">
					<MaterialGraphicComponent colorComputerTagId="0" renderInTarget="0" disableLight="0" disableShadow="-1" AtlasIndex="0" customAnchor="0.000000 0.000000" SinusAmplitude="0.000000 0.000000 0.000000" SinusSpeed="1.000000" AngleX="0.000000" AngleY="0.000000">
						<PrimitiveParameters>
							<GFXPrimitiveParam colorFactor="1.000000 1.000000 1.000000 1.000000" FrontLightBrightness="0.000000" FrontLightContrast="1.000000" BackLightBrightness="0.000000" BackLightContrast="1.000000" colorFog="0.000000 0.000000 0.000000 0.000000" DynamicFogFactor="1.000000" useStaticFog="0" RenderInReflections="1">
								<ENUM NAME="gfxOccludeInfo" SEL="0" />
							</GFXPrimitiveParam>
						</PrimitiveParameters>
						<ENUM NAME="anchor" SEL="6" />
						<material>
							<GFXMaterialSerializable ATL_Channel="0" shaderPath="World/_COMMON/MatShader/MultiTexture_1Layer.msh" stencilTest="0" alphaTest="4294967295" alphaRef="4294967295">
								<textureSet>
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_cover_albumcoach.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
								</textureSet>
								<materialParams>
									<GFXMaterialSerializableParam Reflector_factor="0.000000" />
								</materialParams>
							</GFXMaterialSerializable>
						</material>
						<ENUM NAME="oldAnchor" SEL="6" />
					</MaterialGraphicComponent>
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="0.300000 0.300000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_cover_albumbkg" POS2D="1067.972168 201.986328" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/menuart/actors/{MAP_NAME}_cover_albumbkg.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
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
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_cover_albumbkg.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
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
			<Actor RELATIVEZ="0.000000" SCALE="256.000000 128.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_banner_bkg" MARKER="" POS2D="1487.410156 -32.732918" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/menuart/actors/{MAP_NAME}_banner_bkg.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
				<COMPONENTS NAME="MaterialGraphicComponent">
					<MaterialGraphicComponent colorComputerTagId="0" renderInTarget="0" disableLight="0" disableShadow="1" AtlasIndex="0" customAnchor="0.000000 0.000000" SinusAmplitude="0.000000 0.000000 0.000000" SinusSpeed="1.000000" AngleX="0.000000" AngleY="0.000000">
						<PrimitiveParameters>
							<GFXPrimitiveParam colorFactor="1.000000 1.000000 1.000000 1.000000">
								<ENUM NAME="gfxOccludeInfo" SEL="0" />
							</GFXPrimitiveParam>
						</PrimitiveParameters>
						<ENUM NAME="anchor" SEL="1" />
						<material>
							<GFXMaterialSerializable ATL_Channel="0" ATL_Path="" shaderPath="world/_common/matshader/multitexture_1layer.msh" stencilTest="0" alphaTest="4294967295" alphaRef="4294967295">
								<textureSet>
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_banner_bkg.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
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
			<Actor RELATIVEZ="0.000000" SCALE="0.290211 0.290211" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_coach_1" POS2D="212.784500 663.680176" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/menuart/actors/{MAP_NAME}_coach_1.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
				<COMPONENTS NAME="MaterialGraphicComponent">
					<MaterialGraphicComponent colorComputerTagId="0" renderInTarget="0" disableLight="0" disableShadow="-1" AtlasIndex="0" customAnchor="0.000000 0.000000" SinusAmplitude="0.000000 0.000000 0.000000" SinusSpeed="1.000000" AngleX="0.000000" AngleY="0.000000">
						<PrimitiveParameters>
							<GFXPrimitiveParam colorFactor="1.000000 1.000000 1.000000 1.000000" FrontLightBrightness="0.000000" FrontLightContrast="1.000000" BackLightBrightness="0.000000" BackLightContrast="1.000000" colorFog="0.000000 0.000000 0.000000 0.000000" DynamicFogFactor="1.000000" useStaticFog="0" RenderInReflections="1">
								<ENUM NAME="gfxOccludeInfo" SEL="0" />
							</GFXPrimitiveParam>
						</PrimitiveParameters>
						<ENUM NAME="anchor" SEL="6" />
						<material>
							<GFXMaterialSerializable ATL_Channel="0" shaderPath="World/_COMMON/MatShader/MultiTexture_1Layer.msh" stencilTest="0" alphaTest="4294967295" alphaRef="4294967295">
								<textureSet>
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_coach_1.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
								</textureSet>
								<materialParams>
									<GFXMaterialSerializableParam Reflector_factor="0.000000" />
								</materialParams>
							</GFXMaterialSerializable>
						</material>
						<ENUM NAME="oldAnchor" SEL="6" />
					</MaterialGraphicComponent>
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="256.000000 128.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_map_bkg" DEFAULTENABLE="1" POS2D="1487.410034 350.000000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/menuart/actors/{MAP_NAME}_map_bkg.act" LUA="enginedata/actortemplates/tpl_materialgraphiccomponent2d.tpl">
				<COMPONENTS NAME="MaterialGraphicComponent">
					<MaterialGraphicComponent colorComputerTagId="0" renderInTarget="0" disableLight="0" disableShadow="1" AtlasIndex="0" customAnchor="0.000000 0.000000" SinusAmplitude="0.000000 0.000000 0.000000" SinusSpeed="1.000000" AngleX="0.000000" AngleY="0.000000">
						<PrimitiveParameters>
							<GFXPrimitiveParam colorFactor="1.000000 1.000000 1.000000 1.000000">
								<ENUM NAME="gfxOccludeInfo" SEL="0" />
							</GFXPrimitiveParam>
						</PrimitiveParameters>
						<ENUM NAME="anchor" SEL="1" />
						<material>
							<GFXMaterialSerializable ATL_Channel="0" ATL_Path="" shaderPath="world/_common/matshader/multitexture_1layer.msh" stencilTest="0" alphaTest="4294967295" alphaRef="4294967295">
								<textureSet>
									<GFXMaterialTexturePathSet diffuse="World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_map_bkg.tga" back_light="" normal="" separateAlpha="" diffuse_2="" back_light_2="" anim_impostor="" diffuse_3="" diffuse_4="" />
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
		<sceneConfigs>
			<SceneConfigs activeSceneConfig="0" />
		</sceneConfigs>
	</Scene>
</root>''')

    # 8. MAIN SCENE (fully structured matching GetGetDown reference)
    with open(os.path.join(TARGET_DIR, f"{MAP_NAME}_MAIN_SCENE.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="81615" GRIDUNIT="2.000000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000">
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_AUDIO" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{MAP_NAME}/audio/{MAP_NAME}_audio.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_CINE" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{MAP_NAME}/cinematics/{MAP_NAME}_cine.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_TML" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_tml.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_VIDEO" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}_video.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
				<ENUM NAME="viewType" SEL="2" />
			</SubSceneActor>
		</ACTORS>
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME} : Nicki Minaj - Starships" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/songdesc.act" LUA="World/MAPS/{MAP_NAME}/songdesc.tpl">
				<COMPONENTS NAME="JD_SongDescComponent">
					<JD_SongDescComponent />
				</COMPONENTS>
			</Actor>
		</ACTORS>
		<ACTORS NAME="SubSceneActor">
			<SubSceneActor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_menuart" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="" LUA="enginedata/actortemplates/subscene.tpl" RELATIVEPATH="World/MAPS/{MAP_NAME}/menuart/{MAP_NAME}_menuart.isc" EMBED_SCENE="0" IS_SINGLE_PIECE="0" ZFORCED="1" DIRECT_PICKING="1">
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

    # 9. Main Sequence Tape (Clean of Ambient Audio)
    with open(os.path.join(TARGET_DIR, f"Cinematics/{MAP_NAME}_MainSequence.tape"), "w") as f:
        f.write('''params =
{
    NAME = "Tape",
    Tape = 
    {
        Clips = {
        },
        TapeClock = 0,
        TapeBarCount = 1,
        FreeResourcesAfterPlay = 0,
        MapName = "Starships",
        SoundwichEvent = "",
    },
}''')

    # 10. Cinematics ISC (scene that loads the MainSequence)
    with open(os.path.join(TARGET_DIR, f"Cinematics/{MAP_NAME}_cine.isc"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene ENGINE_VERSION="55299" GRIDUNIT="0.500000" DEPTH_SEPARATOR="0" NEAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000" FAR_SEPARATOR="1.000000 0.000000 0.000000 0.000000, 0.000000 1.000000 0.000000 0.000000, 0.000000 0.000000 1.000000 0.000000, 0.000000 0.000000 0.000000 1.000000">
		<ACTORS NAME="Actor">
			<Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" USERFRIENDLY="{MAP_NAME}_MainSequence" POS2D="0.000000 0.000000" ANGLE="0.000000" INSTANCEDATAFILE="World/MAPS/{MAP_NAME}/cinematics/{MAP_NAME}_mainsequence.act" LUA="World/MAPS/{MAP_NAME}/cinematics/{MAP_NAME}_mainsequence.tpl">
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

    # 11. Cinematics MainSequence template
    with open(os.path.join(TARGET_DIR, f"Cinematics/{MAP_NAME}_MainSequence.tpl"), "w") as f:
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
                    TapePath = "World/MAPS/{MAP_NAME}/Cinematics/{MAP_NAME}_MainSequence.tape"
                }}
            }}
        }}
    }}
}}''')

    # 12. Cinematics MainSequence actor
    with open(os.path.join(TARGET_DIR, f"Cinematics/{MAP_NAME}_MainSequence.act"), "w") as f:
        f.write(f'''params = 
{{
    NAME = "Actor", 
    Actor = 
    {{
        LUA = "World/MAPS/{MAP_NAME}/cinematics/{MAP_NAME}_mainsequence.tpl", 
        COMPONENTS = 
        {{
            {{
                NAME = "MasterTape"
            }}
        }}
    }}
}}''')

    # 13. Audio ConfigMusic.sfi (sound format config per platform)
    with open(os.path.join(TARGET_DIR, f"Audio/ConfigMusic.sfi"), "w") as f:
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

    # 14. Audio sequence tape (stape)
    with open(os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}.stape"), "w") as f:
        f.write(f'''params =
{{
    NAME="Tape",
    Tape = 
    {{
		TapeClock = 0,
        MapName = "{MAP_NAME}",
    }},
}}''')

if __name__ == '__main__':
    generate_text_files()
    print("Done generating corrected template files!")
