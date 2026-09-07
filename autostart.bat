@echo off
title Assistant - autostart
set "SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Assistant.lnk"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"%SHORTCUT%\"); $s.TargetPath=\"%~dp0start.bat\"; $s.WorkingDirectory=\"%~dp0\"; $s.WindowStyle=7; $s.Save()"
set "SHORTCUT2=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Assistant Voice.lnk"
choice /C YN /M "Also start voice client (voice.bat, microphone) with Windows"
if errorlevel 2 goto done
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"%SHORTCUT2%\"); $s.TargetPath=\"%~dp0voice.bat\"; $s.WorkingDirectory=\"%~dp0\"; $s.WindowStyle=7; $s.Save()"
echo Voice client added too.
:done
echo Done: the assistant will start with Windows.
echo To remove, delete: %SHORTCUT%
pause
