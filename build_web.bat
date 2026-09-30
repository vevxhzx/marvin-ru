@echo off
title J.A.R.V.I.S. - build web
cd /d "%~dp0web"
where npm >nul 2>nul || (echo Node.js not found: https://nodejs.org && pause && exit /b 1)
call npm install
call npm run build
echo Done. Site built to web\site. Restart start.bat
pause
