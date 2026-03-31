@echo off
echo [1/3] Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
	echo.
	echo [ERROR] Python dependency installation failed.
	echo Re-run setup after fixing the issue above.
	exit /b 1
)

echo.
echo [2/3] Installing Chromium for Playwright...
python -m playwright install chromium
if errorlevel 1 (
	echo.
	echo [ERROR] Playwright Chromium installation failed.
	echo Re-run setup after fixing the issue above.
	exit /b 1
)

echo.
echo [3/3] Installing vgmstream toolchain...
if not exist tools\vgmstream mkdir tools\vgmstream

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $zip='tools/vgmstream/vgmstream-win64.zip'; $extract='tools/vgmstream/_extract'; if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }; Invoke-WebRequest -Uri 'https://github.com/vgmstream/vgmstream-releases/releases/download/nightly/vgmstream-win64.zip' -OutFile $zip; Expand-Archive -Path $zip -DestinationPath $extract -Force; Get-ChildItem -Path $extract -Recurse -File | Where-Object { $_.Name -in @('vgmstream-cli.exe','vgmstream.exe') } | ForEach-Object { Copy-Item -Path $_.FullName -Destination ('tools/vgmstream/' + $_.Name) -Force }; Remove-Item -Recurse -Force $extract; Remove-Item -Force $zip"
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