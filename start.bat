@echo off
title Marvin
cd /d "%~dp0"
chcp 65001 >nul

if not exist .venv\Scripts\python.exe (
    echo   [!] Marvin ещё не установлен. Сначала запустите install.bat
    pause
    exit /b 1
)

rem после обновления проекта дотягиваем новые библиотеки (быстро, если всё на месте)
.venv\Scripts\python.exe -m pip install -r requirements.txt -q --disable-pip-version-check >nul 2>nul

set /a retries=0
:loop
.venv\Scripts\python.exe run.py
set RC=%ERRORLEVEL%

rem код 3 = уже запущено в другом окне (см. run.py)
if "%RC%"=="3" (
    echo.
    echo   Marvin уже запущен в другом окне. Закройте это.
    pause
    exit /b 3
)

set /a retries+=1
if %retries% GEQ 3 (
    echo.
    echo   Marvin остановился с кодом %RC% и больше не перезапускается.
    echo   Что не так — покажет doctor.bat
    pause
    exit /b %RC%
)

echo.
echo   Код выхода %RC%. Перезапуск через 3 сек [попытка %retries% из 3] (Ctrl+C — выйти^)...
timeout /t 3 >nul
goto loop
