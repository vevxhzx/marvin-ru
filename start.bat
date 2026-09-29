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

set /a retries=0
:loop
.venv\Scripts\python.exe run.py
set RC=%ERRORLEVEL%

:: 3 = порт занят: ассистент уже запущен в другом окне (см. run.py)
if "%RC%"=="3" (
    echo.
    echo The assistant is ALREADY RUNNING in another window. Close this one.
    pause
    exit /b 3
)

set /a retries+=1
if %retries% GEQ 3 (
    echo.
    echo The assistant stopped with exit code %RC% and will not be restarted.
    pause
    exit /b %RC%
)

echo.
echo Exit code %RC%. Restarting in 3 sec [attempt %retries% of 3] (Ctrl+C to exit^)...
timeout /t 3 >nul
goto loop
