@echo off
title Assistant - phone access
cd /d "%~dp0"
echo.
echo  === Open port 8765 in Windows Firewall (needs admin) ===
net session >nul 2>&1
if errorlevel 1 (
    echo  Requesting administrator rights...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
netsh advfirewall firewall delete rule name="Assistant 8765" >nul 2>&1
netsh advfirewall firewall add rule name="Assistant 8765" dir=in action=allow protocol=TCP localport=8765 profile=any >nul
if errorlevel 1 (
    echo  FAILED to add firewall rule.
) else (
    echo  OK: firewall rule "Assistant 8765" added.
)
echo.
echo  === Addresses for your phone (the assistant must be running) ===
python phone_info.py
echo.
pause
