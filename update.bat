@echo off
title Assistant - update
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo .venv not found. Run install.bat first.
    pause
    exit /b 1
)
echo Updating packages...
.venv\Scripts\python.exe -m pip install --upgrade pip -q --disable-pip-version-check
.venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo Update FAILED. Check internet / VPN and run again.
    pause
    exit /b 1
)
if exist requirements-voice.txt (
    .venv\Scripts\python.exe voice_client.py --deps >nul 2>nul && .venv\Scripts\python.exe -m pip install -r requirements-voice.txt -q --disable-pip-version-check
)
echo.
.venv\Scripts\python.exe -c "from core import VERSION; print('core v' + VERSION)"
echo.
echo Done. Now run start.bat
pause
