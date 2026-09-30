@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul || (echo Нужен Python 3.12. & pause & exit /b 1)
py -3.12 -c "import webview" >nul 2>nul || py -3.12 -m pip install -r requirements-windows.txt
py -3.12 jarvis_app.py
