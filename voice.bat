@echo off
setlocal
if not defined ASSISTANT_VOICE_KEEP (
    set "ASSISTANT_VOICE_KEEP=1"
    start "Assistant - voice" cmd /k call "%~f0" %*
    exit /b
)
title Assistant - voice (PC)
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
echo.
echo   Voice client
echo   folder: %CD%
echo   log:    data\voice.log
echo.
if not exist "%PY%" goto :novenv
echo   [1/2] checking voice packages...
"%PY%" voice_client.py --deps >nul 2>nul
if errorlevel 1 goto :noaddon
echo   [2/2] starting. Say the assistant's name or press the hotkey. Close this window to stop.
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
:noaddon
echo   [!] voice packages are not installed - run install_voice.bat first.
goto :stay
:clean
echo   voice client stopped.
timeout /t 3 >nul
exit
:stay
echo.
echo   (window stays open so you can read the error; see data\voice.log)
echo.
