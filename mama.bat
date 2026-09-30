@echo off
title J.A.R.V.I.S. - second copy for mom
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
    echo Run install.bat first - the second copy shares this .venv.
    pause
    exit /b 1
)
.venv\Scripts\python.exe mama_setup.py %*
echo.
pause
