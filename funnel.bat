@echo off
title Marvin - Telegram Mini App (Tailscale Funnel)
cd /d "%~dp0"
echo.
echo  === Telegram Mini App: public HTTPS address via Tailscale Funnel ===
echo.
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% funnel_setup.py %*
echo.
pause
