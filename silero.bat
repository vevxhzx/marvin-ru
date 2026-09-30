@echo off
title J.A.R.V.I.S. - Silero offline voice (optional)
cd /d "%~dp0"
echo   Installing offline voice: torch, about 2 GB download, 3 GB disk.
echo   Without it Jarvis speaks via Microsoft voice and needs internet.
echo   Press Ctrl+C to cancel, or
pause
.venv\Scripts\python.exe -m pip install -r requirements-silero.txt --disable-pip-version-check --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :fail
echo.
echo   done. Restart voice.bat - it will use Silero.
pause
exit /b 0
:fail
echo.
echo   [!] install failed. Check internet and free disk space, then run silero.bat again.
pause
exit /b 1
