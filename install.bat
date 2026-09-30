@echo off
title Marvin - install
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo   Marvin - установка
echo   ==================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo   [!] Python не найден.
    echo.
    echo   Поставьте Python 3.11+ с https://www.python.org/downloads/
    echo   ВАЖНО: при установке отметьте галочку "Add python.exe to PATH",
    echo   потом закройте это окно и запустите install.bat ещё раз.
    echo.
    pause
    exit /b 1
)

python setup.py
set RC=%ERRORLEVEL%

if not "%RC%"=="0" (
    echo.
    echo   [!] Установка завершилась с ошибкой. Что делать — написано выше.
    pause
    exit /b %RC%
)

echo.
echo   Дальше: запустите start.bat — откроется браузер с мастером настройки.
echo   Если что-то не работает: doctor.bat покажет, чего не хватает.
echo.
pause
