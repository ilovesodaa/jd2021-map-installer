@echo off
echo [1/6] Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
	echo.
	echo [ERROR] Python dependency installation failed.
	echo Re-run setup after fixing the issue above.
	exit /b 1
)

echo.
echo [2/6] Installing Chromium for Playwright...
python -m playwright install chromium
if errorlevel 1 (
	echo.
	echo [ERROR] Playwright Chromium installation failed.
	echo Re-run setup after fixing the issue above.
	exit /b 1
)

echo.
echo [3/6] Cloning AssetStudio
if not exist 3rdPartyTools\JDNextTools mkdir 3rdPartyTools\JDNextTools

call :ensure_git_clone https://github.com/Perfare/AssetStudio.git 3rdPartyTools\JDNextTools\AssetStudio master
if errorlevel 1 exit /b 1

echo.
echo [4/6] Cloning UnityPy
call :ensure_git_clone https://github.com/K0lb3/UnityPy.git 3rdPartyTools\JDNextTools\UnityPy master
if errorlevel 1 exit /b 1

echo.
echo [5/6] Cloning Unity2UbiArt
call :ensure_git_clone https://github.com/Itaybl14/Unity2UbiArt.git 3rdPartyTools\Unity2UbiArt main
if errorlevel 1 exit /b 1

echo.
echo [6/6] Installing vgmstream toolchain...
if not exist tools\vgmstream mkdir tools\vgmstream

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $zip='tools/vgmstream/vgmstream-win64.zip'; $extract='tools/vgmstream/_extract'; if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }; Invoke-WebRequest -Uri 'https://github.com/vgmstream/vgmstream-releases/releases/download/nightly/vgmstream-win64.zip' -OutFile $zip; Expand-Archive -Path $zip -DestinationPath $extract -Force; $bin = Get-ChildItem -Path $extract -Recurse -File | Where-Object { $_.Name -in @('vgmstream-cli.exe','vgmstream.exe') } | Select-Object -First 1; if (-not $bin) { throw 'vgmstream executable not found in archive' }; $runtimeRoot = $bin.Directory.FullName; Get-ChildItem -Path $runtimeRoot -Force | ForEach-Object { Copy-Item -Path $_.FullName -Destination 'tools/vgmstream' -Recurse -Force }; Remove-Item -Recurse -Force $extract; Remove-Item -Force $zip"
if errorlevel 1 (
	echo.
	echo [WARNING] vgmstream auto-install failed.
	echo IPK X360 audio decode may fail until vgmstream is installed in tools\vgmstream.
) else (
	echo [OK] vgmstream installed in tools\vgmstream
)

echo.
echo Setup complete!
timeout /t 5

goto :eof

:ensure_git_clone
set "REPO_URL=%~1"
set "DEST_DIR=%~2"
set "REPO_BRANCH=%~3"

if exist "%DEST_DIR%\.git" (
	echo [OK] %DEST_DIR% already present
	exit /b 0
)

if exist "%DEST_DIR%" (
	echo [WARNING] %DEST_DIR% exists but is not a git checkout. Skipping clone.
	exit /b 0
)

echo [INFO] Cloning %REPO_URL% into %DEST_DIR%
git clone --depth 1 --branch %REPO_BRANCH% %REPO_URL% "%DEST_DIR%"
if errorlevel 1 (
	echo [ERROR] Failed to clone %REPO_URL%
	exit /b 1
)

exit /b 0