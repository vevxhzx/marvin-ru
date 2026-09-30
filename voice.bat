@echo off
setlocal
if not defined JARVIS_VOICE_KEEP (
    set "JARVIS_VOICE_KEEP=1"
    start "J.A.R.V.I.S. - voice" cmd /k call "%~f0" %*
    exit /b
)
title J.A.R.V.I.S. - voice (PC)
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
echo.
echo   J.A.R.V.I.S. - voice client
echo   folder: %CD%
echo   log:    data\voice.log
echo.

if not exist "%PY%" goto :novenv

echo   [1/3] checking voice packages...
"%PY%" voice_client.py --deps >nul 2>nul
if errorlevel 1 goto :install
goto :check

:install
echo         missing - installing (first time, 1-3 min, needs internet)...
"%PY%" -m pip install -r requirements-voice.txt --disable-pip-version-check
if errorlevel 1 goto :pipfail

:check
echo   [2/3] self-check...
"%PY%" voice_client.py --check
if errorlevel 1 goto :checkfail

echo   [3/3] starting. Say "Jarvis, ..." or press the hotkey. Close this window to stop.
echo.
"%PY%" voice_client.py %*
set "EC=%errorlevel%"
echo.
if "%EC%"=="0" goto :clean
echo   [!] voice client exited with code %EC%. Details above and in data\voice.log
goto :stay

:novenv
echo   [!] .venv not found - run install.bat first, then start.bat, then voice.bat
goto :stay

:pipfail
echo.
echo   [!] pip install failed. Check internet / antivirus and run voice.bat again.
goto :stay

:checkfail
echo.
echo   [!] self-check failed - see lines marked FAIL above and data\voice.log
goto :stay

:clean
echo   voice client stopped.
timeout /t 3 >nul
exit

:stay
echo.
echo   (window stays open so you can read the error; send data\voice.log to the developer)
echo.
