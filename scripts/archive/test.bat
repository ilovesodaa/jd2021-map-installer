set MAP_DIR=d:\jd2021pc\jd21\data\World\MAPS\Starships
set CACHE_DIR=d:\jd2021pc\jd21\data\cache\itf_cooked\pc\world\maps\starships

echo [1] Deleting old Map and Cache dirs ...
if exist "%MAP_DIR%" (
    rmdir /S /Q "%MAP_DIR%"
)
if exist "%CACHE_DIR%" (
    rmdir /S /Q "%CACHE_DIR%"
)