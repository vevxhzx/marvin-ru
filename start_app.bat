@echo off
title Marvin - app
cd /d "%~dp0"

:: Ядро живёт в .venv — окно должно запускаться тем же интерпретатором, иначе нет fastapi/aiogram и run.py падает.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=py -3.12"

%PY% -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo Python not found. Run install.bat first.
    pause
    exit /b 1
)

:: отдельное окно без браузера — один раз доставляем pywebview (в тот же интерпретатор)
%PY% -c "import webview" >nul 2>nul
if errorlevel 1 (
    echo Installing pywebview for the standalone window [one time]...
    %PY% -m pip install -r requirements-windows.txt --disable-pip-version-check
)

%PY% desktop_app.py %*
if errorlevel 1 (
    echo.
    echo Could not start the app. Diagnostics:
    %PY% desktop_app.py --check
    pause
    exit /b 1
)
