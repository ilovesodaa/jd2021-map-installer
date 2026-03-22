@echo off
echo [1/2] Installing Python dependencies...
pip install -r requirements.txt

echo.
echo [2/2] Installing Chromium for Playwright...
python -m playwright install chromium

echo.
echo Setup complete!
timeout /t 5