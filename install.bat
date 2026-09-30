@echo off
title J.A.R.V.I.S. - install
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.12 from https://www.python.org/downloads/
    echo IMPORTANT: check "Add python.exe to PATH" during install.
    pause
    exit /b 1
)
python setup.py
