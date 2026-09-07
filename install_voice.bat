@echo off
title Assistant - voice add-on (install)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Run install.bat first.
    pause
    exit /b 1
)
set "PY=.venv\Scripts\python.exe"
echo.
echo   Voice add-on for the PC: wake word, microphone, speech, tray icon.
echo.
echo   [1/3] Base voice packages (whisper, vosk, edge-tts; ~700 MB)
"%PY%" -m pip install -r requirements-voice.txt --disable-pip-version-check
if errorlevel 1 goto :fail
echo.
echo   [2/3] Offline voice Silero (optional, ~2 GB). Without it the assistant speaks
echo         via Microsoft Edge voice and needs internet for speech.
set /p SIL="         Install Silero? [y/N]: "
if /i "%SIL%"=="y" (
    "%PY%" -m pip install -r requirements-silero.txt --disable-pip-version-check --index-url https://download.pytorch.org/whl/cpu
    if errorlevel 1 echo   [!] Silero install failed - skipping, Edge voice will be used.
)
echo.
echo   [3/3] Speech recognition on NVIDIA GPU (optional, ~1 GB CUDA libraries).
echo         Makes whisper 0.3 s instead of 2-3 s. Needs NVIDIA driver.
set /p GPU="         Use GPU for speech recognition? [y/N]: "
if /i "%GPU%"=="y" (
    "%PY%" -m pip install -r requirements-gpu.txt --disable-pip-version-check
    "%PY%" voice_client.py --gpu-on
    if errorlevel 1 echo   [!] GPU not visible - staying on CPU. Update NVIDIA driver and run install_voice.bat again.
)
echo.
"%PY%" voice_client.py --check
echo.
echo   Done. Start the core (start.bat), then run voice.bat.
pause
exit /b 0
:fail
echo.
echo   [!] pip install failed. Check internet / antivirus and run install_voice.bat again.
pause
exit /b 1
