@echo off
title J.A.R.V.I.S. - phone access
cd /d "%~dp0"
echo.
echo  === Open port 8765 in Windows Firewall (needs admin) ===
net session >nul 2>&1
if errorlevel 1 (
    echo  Requesting administrator rights...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
netsh advfirewall firewall delete rule name="Jarvis 8765" >nul 2>&1
netsh advfirewall firewall add rule name="Jarvis 8765" dir=in action=allow protocol=TCP localport=8765 profile=any >nul
if errorlevel 1 (
    echo  FAILED to add firewall rule.
) else (
    echo  OK: firewall rule "Jarvis 8765" added.
)
echo.
echo  === Addresses for your phone (Jarvis must be running) ===
python phone_info.py
echo.
pause
