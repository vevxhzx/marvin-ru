@echo off
title Assistant
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run install.bat first.
    pause
    exit /b 1
)
:: auto-install missing packages after project update (fast if nothing to do)
.venv\Scripts\python.exe -m pip install -r requirements.txt -q --disable-pip-version-check >nul 2>nul
:loop
.venv\Scripts\python.exe run.py
if errorlevel 3 (
    echo.
    echo The assistant is ALREADY RUNNING in another window. Close this one.
    pause
    exit /b
)
echo.
echo Restarting in 3 sec (Ctrl+C to exit)...
timeout /t 3 >nul
goto loop
