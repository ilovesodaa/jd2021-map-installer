@echo off
REM ===================================================
REM   Rebuild Starships Map — Sync Override Settings
REM ===================================================
REM
REM  VIDEO_OVERRIDE: When does the video file start relative to beat 0 (seconds, negative = before beat 0).
REM    JDU source value: -1.901
REM    Set to 0 for Starships PC (video plays perfectly at 0).
REM
REM  AUDIO_OFFSET: Shifts the audio WAV start relative to the beat grid.
REM    Negative = trim the start of the audio (audio content starts earlier).
REM    Positive = pad silence at the start (audio content starts later).
REM    Set to -1.901 to match the JDU video offset so pictos/karaoke/scoring align.
REM    Adjust this value until pictos and karaoke hit correctly.

set VIDEO_OVERRIDE=-1.901
set AUDIO_OFFSET=-1.901

REM ===================================================

set MAP_DIR=d:\jd2021pc\jd21\data\World\MAPS\Starships
set CACHE_DIR=d:\jd2021pc\jd21\data\cache\itf_cooked\pc\world\maps\starships
set PICTO_SRC=d:\jd2021pc\Starships\ipk_extracted\cache\itf_cooked\pc\world\maps\starships\timeline\pictos

REM [1] Clean old map and cache
if exist "%MAP_DIR%" rmdir /S /Q "%MAP_DIR%"
if exist "%CACHE_DIR%" rmdir /S /Q "%CACHE_DIR%"

REM [2] Generate config files with video override
python build_starships_fix.py --video-start-time-override %VIDEO_OVERRIDE%

REM [3] Restore media files and convert audio with offset
python restore_starships_media.py --audio-start-offset %AUDIO_OFFSET%

REM [4] Decode MenuArt CKD textures
python ckd_decode.py --batch "%MAP_DIR%\MenuArt\textures" "%MAP_DIR%\MenuArt\textures"

REM [5] Convert choreography tapes to Lua
python json_to_lua.py "d:\jd2021pc\ipk_extracted_fixed\cache\itf_cooked\pc\world\maps\starships\timeline\starships_tml_dance.dtape.ckd" "%MAP_DIR%\Timeline\Starships_TML_Dance.dtape"
python json_to_lua.py "d:\jd2021pc\ipk_extracted_fixed\cache\itf_cooked\pc\world\maps\starships\timeline\starships_tml_karaoke.ktape.ckd" "%MAP_DIR%\Timeline\Starships_TML_Karaoke.ktape"

REM [6] Decode pictogram textures
for %%f in ("%PICTO_SRC%\*.png.ckd") do (
    python ckd_decode.py "%%f" "%MAP_DIR%\Timeline\pictos\%%~nf"
)

REM ===================================================
REM   Build Complete! You can now run the game.
REM ===================================================
