@echo off
echo ===================================================
echo   Rebuilding Starships Map from Scratch
echo ===================================================

set MAP_DIR=d:\jd2021pc\jd21\data\World\MAPS\Starships
set CACHE_DIR=d:\jd2021pc\jd21\data\cache\itf_cooked\pc\world\maps\starships

echo [1] Deleting old Map and Cache dirs ...
if exist "%MAP_DIR%" (
    rmdir /S /Q "%MAP_DIR%"
)
if exist "%CACHE_DIR%" (
    rmdir /S /Q "%CACHE_DIR%"
)

echo [2] Generating config files (build_starships_fix.py) ...
python d:\jd2021pc\build_starships_fix.py

echo [3] Restoring media files and converting .ogg to .wav ...
python d:\jd2021pc\restore_starships_media.py

echo [4] Decoding MenuArt CKD textures ...
python d:\jd2021pc\ckd_decode.py --batch "%MAP_DIR%\MenuArt\textures" "%MAP_DIR%\MenuArt\textures"

echo [5] Converting choreography tapes to Lua ...
python d:\jd2021pc\json_to_lua.py "d:\jd2021pc\ipk_extracted_fixed\cache\itf_cooked\pc\world\maps\starships\timeline\starships_tml_dance.dtape.ckd" "%MAP_DIR%\Timeline\Starships_TML_Dance.dtape"
python d:\jd2021pc\json_to_lua.py "d:\jd2021pc\ipk_extracted_fixed\cache\itf_cooked\pc\world\maps\starships\timeline\starships_tml_karaoke.ktape.ckd" "%MAP_DIR%\Timeline\Starships_TML_Karaoke.ktape"

echo [6] Generating dummy pictograms ...
python d:\jd2021pc\make_dummy_pictos.py

echo ===================================================
echo   Build Complete! You can now run the game.
echo ===================================================
