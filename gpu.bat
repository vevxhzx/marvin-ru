@echo off
title J.A.R.V.I.S. - GPU speech recognition (optional)
cd /d "%~dp0"
echo   Speech recognition on NVIDIA GPU: whisper 0.3 s instead of 2-3 s.
echo   Downloads CUDA libraries (about 1 GB). Needs NVIDIA driver (GeForce Experience / nvidia.com).
echo   Press Ctrl+C to cancel, or
pause
.venv\Scripts\python.exe -m pip install -r requirements-gpu.txt --disable-pip-version-check
if errorlevel 1 goto :fail
.venv\Scripts\python.exe voice_client.py --gpu-on
if errorlevel 1 goto :nogpu
echo.
echo   done. Restart voice.bat and start.bat - whisper will use the GPU.
pause
exit /b 0
:nogpu
echo.
echo   [!] libraries installed, but the GPU is not visible. Update the NVIDIA driver and run gpu.bat again.
pause
exit /b 1
:fail
echo.
echo   [!] install failed. Check internet and free disk space, then run gpu.bat again.
pause
exit /b 1
