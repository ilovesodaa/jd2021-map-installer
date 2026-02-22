@echo off
REM ===================================================
REM   Rebuild Rockabye Map - Sync Override Settings
REM ===================================================
REM
REM  VIDEO_OVERRIDE: When does the video play in relation to the audio track?
REM    Negative = video starts before the audio beat 0.
REM    JDU Source Value (extracted from server): -4.705
REM    
REM    Adjust this value if the choreo/UI preview feels late or early compared to the audio.
REM
REM  AUDIO_OFFSET: Shifts the audio WAV start relative to the beat grid for GAMEPLAY.
REM    Negative = trim the start of the audio (audio content starts earlier).
REM    Positive = pad silence at the start (audio content starts later).
REM    Set to 0.0 to do no audio trimming.
REM    Set to -4.705 to identically mimic the video start time.

set VIDEO_OVERRIDE=-4.705
set AUDIO_OFFSET=0.0

REM ===================================================

echo [Rockabye Override] Building map with VIDEO_OVERRIDE=%VIDEO_OVERRIDE% and AUDIO_OFFSET=%AUDIO_OFFSET%
python map_installer.py --map-name Rockabye --asset-html d:\jd2021pc\Rockabye\rockabye_asset_mapping.html --nohud-html d:\jd2021pc\Rockabye\rockabye_nohud.html --video-override %VIDEO_OVERRIDE%

echo.
echo ===================================================
echo   Build Complete! You can now run the game and test the sync.
echo ===================================================

