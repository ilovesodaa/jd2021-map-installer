import os
import shutil
import subprocess

# --- Config ---
MAP_NAME = "Starships"
MAP_NAME_LOWER = MAP_NAME.lower()
SRC_DIR = r"d:\jd2021pc\Starships"
IPK_EXTRACTED = os.path.join(SRC_DIR, "ipk_extracted")
DECODED_DIR = os.path.join(SRC_DIR, "decoded")
TARGET_DIR = rf"d:\jd2021pc\jd21\data\World\MAPS\{MAP_NAME}"

# --- Asset Mapping ---
ASSETS = {
    # Textures
    'coach_1': 'dbe3c08891c1859cc22bd27c962e2268.tga',
    'cover_generic': '8c69e5b8d670d7f19880388e995ff064.tga',
    'cover_online': '86e08b8e5c89f8389db5723f136b81d7.tga',
    'cover_albumbkg': '7285efe8d585ac76b882c2115989a4f8.tga',
    'cover_albumcoach': '370d94f300a9f5c48d372f3fad0cec8e.tga',
    'map_bkg': '440d6ce474051538b9d98b0d0dab2341.tga',
    'banner_bkg': '650d843e8d21e55a4cd58a17d6588005.tga',

    # Media
    'full_video': '0ac1f08ec9cd2070cb1f70295661efa3.webm',
    'preview_video': '2711a81cdc6f55f17f11db75b59e3d33.webm',  # Using vp8 preview
    'full_audio': '80f47be6f8293430ae764027a56847a4.ogg',
    'autodance_audio': 'b6ea5be7d5e70cda982f9d35fb6bfeba.ogg',
}

# --- Extracted Binary Files ---
BIN_FILES = {
    'dtape': rf"cache\itf_cooked\pc\world\maps\{MAP_NAME_LOWER}\timeline\{MAP_NAME_LOWER}_tml_dance.dtape.ckd",
    'ktape': rf"cache\itf_cooked\pc\world\maps\{MAP_NAME_LOWER}\timeline\{MAP_NAME_LOWER}_tml_karaoke.ktape.ckd",
    'stape': rf"cache\itf_cooked\pc\world\maps\{MAP_NAME_LOWER}\cinematics\{MAP_NAME_LOWER}_mainsequence.tape.ckd",
}

def create_dirs():
    dirs = [
        "Audio",
        "Autodance",
        "cinematics",
        "MenuArt/Actors",
        "MenuArt/Textures",
        "Timeline",
        "VideosCoach",
    ]
    for d in dirs:
        os.makedirs(os.path.join(TARGET_DIR, d), exist_ok=True)

def copy_assets():
    print("Copying assets...")
    # Textures
    for key, filename in ASSETS.items():
        if key in ['full_video', 'preview_video', 'full_audio', 'autodance_audio']: continue
        src = os.path.join(DECODED_DIR, filename)
        dst = os.path.join(TARGET_DIR, f"MenuArt/Textures/{MAP_NAME}_{key}.tga")
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  Copied texture: {key}")
        else:
            print(f"  WARNING: Missing texture {src}")

    # Bins
    ipk_base = IPK_EXTRACTED
    for key, path in BIN_FILES.items():
        src = os.path.join(ipk_base, path)
        if key == 'dtape': dst = os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML_Dance.dtape")
        elif key == 'ktape': dst = os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML_Karaoke.ktape")
        elif key == 'stape': dst = os.path.join(TARGET_DIR, f"cinematics/{MAP_NAME}_MainSequence.tape")
        
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  Copied {key}")
        else:
            print(f"  WARNING: Missing binary {src}")

    # Media
    shutil.copy2(os.path.join(SRC_DIR, ASSETS['full_video']), os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}.webm"))
    # The game expects .webm in mpd, copy preview
    shutil.copy2(os.path.join(SRC_DIR, ASSETS['preview_video']), os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}_MapPreview.webm"))
    
    shutil.copy2(os.path.join(SRC_DIR, ASSETS['full_audio']), os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}.ogg"))
    shutil.copy2(os.path.join(SRC_DIR, ASSETS['autodance_audio']), os.path.join(TARGET_DIR, f"Autodance/{MAP_NAME}.ogg"))
    print("  Copied media files")

    # Convert audio to wav
    wav_path = os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}.wav")
    print("Converting audio to WAV...")
    subprocess.run(["ffmpeg", "-y", "-i", os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}.ogg"), wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def generate_text_files():
    print("Generating text files...")
    
    # 1. SongDesc.tpl
    with open(os.path.join(TARGET_DIR, "SongDesc.tpl"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<tpl>
    <classes>
        <class name="JD_SongDescTemplate" />
    </classes>
    <JD_SongDescTemplate>
        <MapName>{MAP_NAME}</MapName>
        <JDVersion>11</JDVersion>
        <NumCoach>1</NumCoach>
        <Mode>1</Mode>
        <Difficulty>2</Difficulty>
        <SweatDifficulty>2</SweatDifficulty>
        <Title>{MAP_NAME}</Title>
        <Artist>Nicki Minaj</Artist>
        <Credits>Credits Here</Credits>
        <ChoreoCreator>Choreographer</ChoreoCreator>
        <DefaultColors>
            <color>
                <songcolor_2A>0.000000 0.819600 0.815680 1.000000</songcolor_2A>
                <songcolor_1A>0.000000 0.819600 0.815680 0.000000</songcolor_1A>
                <songcolor_2B>0.960780 0.000000 0.019600 1.000000</songcolor_2B>
                <songcolor_1B>0.960780 0.000000 0.019600 0.000000</songcolor_1B>
                <lyrics>1.000000 1.000000 1.000000 1.000000</lyrics>
                <theme>1.000000 1.000000 1.000000 1.000000</theme>
            </color>
        </DefaultColors>
    </JD_SongDescTemplate>
</tpl>''')

    # 2. SongDesc.act
    with open(os.path.join(TARGET_DIR, "SongDesc.act"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<actor>
    <components>
        <component class="JD_SongDescComponent">
            <JD_SongDescComponent />
        </component>
    </components>
    <PleoActor>
        <LUA>World/MAPS/{MAP_NAME}/SongDesc.tpl</LUA>
    </PleoActor>
</actor>''')

    # 3. Audio TPLs and ISC
    with open(os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}_MusicTrack.tpl"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<tpl>
    <classes>
        <class name="MusicTrackTemplate" />
    </classes>
    <MusicTrackTemplate>
        <trackData>
            <MusicTrackData>
                <structure>
                    <markers />
                    <signatures />
                    <sections />
                    <startBeat>0</startBeat>
                    <endBeat>0</endBeat>
                    <videoStartTime>0.000000</videoStartTime>
                    <previewEntry>0.000000</previewEntry>
                    <previewLoopStart>0.000000</previewLoopStart>
                    <previewLoopEnd>0.000000</previewLoopEnd>
                    <volume>1.000000</volume>
                    <fadeInDuration>0.000000</fadeInDuration>
                    <fadeOutDuration>0.000000</fadeOutDuration>
                </structure>
                <path>World/MAPS/{MAP_NAME}/audio/{MAP_NAME}.wav</path>
                <url>jmcs://jd-contents/{MAP_NAME}/{MAP_NAME}.ogg</url>
            </MusicTrackData>
        </trackData>
    </MusicTrackTemplate>
</tpl>''')

    with open(os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}_Sequence.tpl"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<tpl>
    <classes>
        <class name="SequenceTemplate" />
    </classes>
    <SequenceTemplate>
        <data>
            <SequenceData>
                <Clips>
                    <MusicTrackClip>
                        <Id>0</Id>
                        <IsActive>1</IsActive>
                        <StartTime>0.000000</StartTime>
                        <Duration>-1.000000</Duration>
                        <TrackId>0</TrackId>
                    </MusicTrackClip>
                </Clips>
                <Configurator />
            </SequenceData>
        </data>
        <tape>World/MAPS/{MAP_NAME}/cinematics/{MAP_NAME}_MainSequence.tape</tape>
    </SequenceTemplate>
</tpl>''')

    with open(os.path.join(TARGET_DIR, f"Audio/{MAP_NAME}_AUDIO.isc"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<scene>
    <ACTORS>
        <Actor name="MusicTrack">
            <LUA>World/MAPS/{MAP_NAME}/audio/{MAP_NAME}_MusicTrack.tpl</LUA>
            <COMPONENTS>
                <MusicTrackComponent />
            </COMPONENTS>
        </Actor>
        <Actor name="Sequence">
            <LUA>World/MAPS/{MAP_NAME}/audio/{MAP_NAME}_Sequence.tpl</LUA>
            <COMPONENTS>
                <SequenceComponent />
            </COMPONENTS>
        </Actor>
    </ACTORS>
</scene>''')

    # 4. Timeline
    with open(os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML_Dance.tpl"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<tpl>
    <classes>
        <class name="SequenceTemplate" />
    </classes>
    <SequenceTemplate>
        <data>
            <SequenceData>
                <Clips />
                <Configurator />
            </SequenceData>
        </data>
        <tape>World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Dance.dtape</tape>
    </SequenceTemplate>
</tpl>''')

    with open(os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML_Karaoke.tpl"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<tpl>
    <classes>
        <class name="SequenceTemplate" />
    </classes>
    <SequenceTemplate>
        <data>
            <SequenceData>
                <Clips />
                <Configurator />
            </SequenceData>
        </data>
        <tape>World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Karaoke.ktape</tape>
    </SequenceTemplate>
</tpl>''')

    with open(os.path.join(TARGET_DIR, f"Timeline/{MAP_NAME}_TML.isc"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<scene>
    <ACTORS>
        <Actor name="TML_Dance">
            <LUA>World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Dance.tpl</LUA>
            <COMPONENTS>
                <TimelineComponent />
            </COMPONENTS>
        </Actor>
        <Actor name="TML_Karaoke">
            <LUA>World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML_Karaoke.tpl</LUA>
            <COMPONENTS>
                <TimelineComponent />
            </COMPONENTS>
        </Actor>
    </ACTORS>
</scene>''')

    # 5. Video
    with open(os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}.mpd"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" minBufferTime="PT1.500000S" type="static" mediaPresentationDuration="PT181.000000S" profiles="urn:mpeg:dash:profile:isoff-live:2011">
  <Period id="0" duration="PT181.000000S">
    <AdaptationSet id="0" mimeType="video/webm" segmentAlignment="true" startWithSAP="1" maxWidth="1920" maxHeight="1080" maxFrameRate="30">
      <Representation id="0" codecs="vp8" width="1920" height="1080" frameRate="30" bandwidth="4000000">
        <BaseURL>{MAP_NAME}.webm</BaseURL>
        <SegmentBase indexRange="0-1000">
          <Initialization range="0-500" />
        </SegmentBase>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>''')

    with open(os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}_MapPreview.mpd"), "w") as f:
        f.write(f'''<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" minBufferTime="PT1.500000S" type="static" mediaPresentationDuration="PT20.000000S" profiles="urn:mpeg:dash:profile:isoff-live:2011">
  <Period id="0" duration="PT20.000000S">
    <AdaptationSet id="0" mimeType="video/webm" segmentAlignment="true" startWithSAP="1" maxWidth="1920" maxHeight="1080" maxFrameRate="30">
      <Representation id="0" codecs="vp8" width="1920" height="1080" frameRate="30" bandwidth="4000000">
        <BaseURL>{MAP_NAME}_MapPreview.webm</BaseURL>
        <SegmentBase indexRange="0-1000">
          <Initialization range="0-500" />
        </SegmentBase>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>''')

    with open(os.path.join(TARGET_DIR, f"VideosCoach/video_player_main.act"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<actor>
    <components>
        <component class="PleoComponent">
            <PleoComponent>
                <Video>World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}.webm</Video>
                <dashMPD>World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}.mpd</dashMPD>
            </PleoComponent>
        </component>
    </components>
    <PleoActor>
        <LUA>World/Components/PleoComponent.tpl</LUA>
    </PleoActor>
</actor>''')

    with open(os.path.join(TARGET_DIR, f"VideosCoach/video_player_map_preview.act"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<actor>
    <components>
        <component class="PleoComponent">
            <PleoComponent>
                <Video>World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}_MapPreview.webm</Video>
                <dashMPD>World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}_MapPreview.mpd</dashMPD>
                <channelID>1</channelID>
            </PleoComponent>
        </component>
    </components>
    <PleoActor>
        <LUA>World/Components/PleoComponent.tpl</LUA>
    </PleoActor>
</actor>''')

    with open(os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}_VIDEO.isc"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<scene>
    <ACTORS>
        <Actor name="VideoPlayer">
            <LUA>World/MAPS/{MAP_NAME}/videoscoach/video_player_main.act</LUA>
        </Actor>
    </ACTORS>
</scene>''')

    with open(os.path.join(TARGET_DIR, f"VideosCoach/{MAP_NAME}_VIDEO_MAP_PREVIEW.isc"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<scene>
    <ACTORS>
        <Actor name="VideoPlayerMapPreview">
            <LUA>World/MAPS/{MAP_NAME}/videoscoach/video_player_map_preview.act</LUA>
        </Actor>
    </ACTORS>
</scene>''')

    # 6. Autodance
    with open(os.path.join(TARGET_DIR, f"Autodance/{MAP_NAME}_Autodance.tpl"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<tpl>
    <classes>
        <class name="AutodanceComponentTemplate" />
    </classes>
    <AutodanceComponentTemplate>
        <SongName>{MAP_NAME}</SongName>
        <AutodanceFormat>0</AutodanceFormat>
        <AudioPath>World/MAPS/{MAP_NAME}/autodance/{MAP_NAME}.ogg</AudioPath>
    </AutodanceComponentTemplate>
</tpl>''')

    with open(os.path.join(TARGET_DIR, f"Autodance/{MAP_NAME}_AUTODANCE.isc"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<scene>
    <ACTORS>
        <Actor name="Autodance">
            <LUA>World/MAPS/{MAP_NAME}/autodance/{MAP_NAME}_Autodance.tpl</LUA>
            <COMPONENTS>
                <AutodanceComponent />
            </COMPONENTS>
        </Actor>
    </ACTORS>
</scene>''')

    # 7. MenuArt actors
    for art in ['banner_bkg', 'Coach_1', 'Cover_AlbumBkg', 'Cover_AlbumCoach', 'Cover_Generic', 'Cover_Online', 'map_bkg']:
        with open(os.path.join(TARGET_DIR, f"MenuArt/Actors/{MAP_NAME}_{art}.act"), "w") as f:
            f.write(f'''<?xml version="1.0"?>
<actor>
    <components>
        <component class="TextureGraphicComponent">
            <TextureGraphicComponent>
                <size>1024.000000 1024.000000</size>
                <material>
                    <Material>
                        <textureSet>
                            <TextureSet>
                                <textures>
                                    <diffuse>World/MAPS/{MAP_NAME}/menuart/textures/{MAP_NAME}_{art.lower()}.tga</diffuse>
                                </textures>
                            </TextureSet>
                        </textureSet>
                    </Material>
                </material>
            </TextureGraphicComponent>
        </component>
    </components>
    <PleoActor>
        <LUA>world/components/menuartcomponent.tpl</LUA>
    </PleoActor>
</actor>''')

    # 8. MAIN SCENE
    with open(os.path.join(TARGET_DIR, f"{MAP_NAME}_MAIN_SCENE.isc"), "w") as f:
        f.write(f'''<?xml version="1.0"?>
<scene>
    <SCENES>
        <Scene>
            <PATH>World/MAPS/{MAP_NAME}/audio/{MAP_NAME}_AUDIO.isc</PATH>
        </Scene>
        <Scene>
            <PATH>World/MAPS/{MAP_NAME}/timeline/{MAP_NAME}_TML.isc</PATH>
        </Scene>
        <Scene>
            <PATH>World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}_VIDEO.isc</PATH>
        </Scene>
        <Scene>
            <PATH>World/MAPS/{MAP_NAME}/autodance/{MAP_NAME}_AUTODANCE.isc</PATH>
        </Scene>
        <Scene>
            <PATH>World/MAPS/{MAP_NAME}/videoscoach/{MAP_NAME}_VIDEO_MAP_PREVIEW.isc</PATH>
        </Scene>
    </SCENES>
</scene>''')

if __name__ == '__main__':
    create_dirs()
    copy_assets()
    generate_text_files()
    print("Done generating map folder structure!")
