@echo off
echo [1/2] Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
	echo.
	echo [ERROR] Python dependency installation failed.
	echo Re-run setup after fixing the issue above.
	exit /b 1
)

echo.
echo [2/2] Installing Chromium for Playwright...
python -m playwright install chromium
if errorlevel 1 (
	echo.
	echo [ERROR] Playwright Chromium installation failed.
	echo Re-run setup after fixing the issue above.
	exit /b 1
)

echo.
echo Setup complete!
timeout /t 5