@echo off
title Marvin - doctor
cd /d "%~dp0"
chcp 65001 >nul

if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe doctor.py %*
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo   [!] Python не найден, и .venv тоже нет.
        echo   Поставьте Python 3.11+ и запустите install.bat
    ) else (
        echo   [i] .venv нет — запускаю проверку обычным Python.
        python doctor.py %*
    )
)
echo.
pause
