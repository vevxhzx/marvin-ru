@echo off
chcp 65001 >nul
title Джарвис
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
    echo Джарвис уже запущен в другом окне. Закройте это окно.
    pause
    exit /b
)
echo.
echo Джарвис остановился. Перезапуск через 5 секунд (Ctrl+C — выход)...
timeout /t 5 >nul
goto loop
