@echo off
title J.A.R.V.I.S. - update
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo .venv not found. Run install.bat first.
    pause
    exit /b 1
)
echo Updating packages (first time with voice: 5-10 min, ~700 MB)...
echo v0.8.0: no new packages (Google Calendar works over httpx). v0.7.0 added psutil, pdfplumber, openpyxl
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Update FAILED. Check internet / VPN and run again.
    pause
    exit /b 1
)
echo.
echo Checking version...
.venv\Scripts\python.exe -c "from core import VERSION; print(\"Jarvis core v\" + VERSION)"
echo.
echo Done. Now run start.bat
pause
