# Manual Map Porting Guide (Just Dance 2021 PC)

This guide details the technical process of manually porting a map from Just Dance Unlimited (JDU) to the Just Dance 2021 PC engine without relying on the automated `map_installer.py` script.

## 1. Asset Acquisition
Identify and download the following core assets from the JDU server URLs:
- **Audio**: `.ogg` or `.wav` gameplay track.
- **Video**: `.webm` ultra/high quality background video.
- **Archive**: `.ipk` or `.zip` (SCENE) containing the choreography tapes and coach textures.

## 2. Audio & Video Synchronization
JDU maps often have an offset between the start of the video and the start of the audio track.
1. Determine the `videoStartTime` (in seconds) from the JDU metadata.
2. Use FFmpeg to trim or pad the audio relative to the video:
   - **Negative Offset (Trim)**: `ffmpeg -i input.ogg -af "atrim=start=ABS_OFFSET,asetpts=PTS-STARTPTS" output.wav`
   - **Positive Offset (Delay)**: `ffmpeg -i input.ogg -af "adelay=OFFSET_MS|OFFSET_MS" output.wav`
3. Convert the finalized audio to 48kHz WAV for gameplay and OGG for menu previews.

## 3. Tape Conversion (.ckd to .lua)
The game engine requires timings in a specific Lua table format (`.dtape` for dance, `.ktape` for karaoke).
1. Extract the `*_tml_dance.dtape.ckd` or `*_tml_karaoke.ktape.ckd` from the IPK.
2. Strip the UbiArt CKD header (binary) to reveal the JSON/BSON content.
3. Convert the JSON clips and tracks into the `params = { Tape = { Clips = { ... } } }` Lua structure.
   - **Crucial**: Ensure primitive arrays (like `PartsScale`) are wrapped in `{ VAL = x }` properties to avoid engine crashes.

## 4. Template (TPL) and Actor (ACT) Creation
Each map component needs a Template (logic definition) and an Actor (instance definition).
- **SongDesc**: Defines metadata (Artist, Title, Difficulty).
- **MusicTrack**: Links the audio file and defines the `videoStartTime`.
- **Timeline**: References the `.dtape` or `.ktape` file paths.
- **Autodance**: Defines the paths for `.adtape` and `.advideo`.
  - **Note**: The component MUST be named `JD_AutodanceComponent`.

## 5. Scene Assembly (ISC)
1. **_tml.isc**: Assemble the dance and karaoke actors into a combined timeline scene.
2. **_MAIN_SCENE.isc**: Create the master scene that pulls in the `SongDesc`, `MusicTrack`, `Autodance`, and `_tml` sub-scenes.
   - Use `SubSceneActor` nodes to link external `.isc` files.

## 6. Game Integration
1. **File Placement**: Move the generated folder structure to `jd21/data/World/MAPS/[MapName]/`.
2. **Database Registration**: Open `SkuScene_Maps_PC_All.isc` and add a new entry referencing your map's `SongDesc.tpl`.
3. **Localisation**: (Optional) Add the map name to the `localisation.ckd` strings if you want translated titles.

## 7. Verification
- Launch the game.
- Verify the map appears in the song list.
- Check audio/video sync and picto timings in-game.
