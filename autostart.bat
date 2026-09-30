@echo off
title Assistant - autostart
rem Shortcut in the Startup folder. A second copy of the assistant in another folder gets its own
rem shortcut "Assistant (folder).lnk" instead of overwriting the first one.
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $dir='%~dp0'.TrimEnd('\'); $st=[Environment]::GetFolderPath('Startup'); $p=Join-Path $st 'Assistant.lnk'; if((Test-Path $p) -and ($ws.CreateShortcut($p).WorkingDirectory.TrimEnd('\') -ne $dir)){ $p=Join-Path $st ('Assistant ('+(Split-Path $dir -Leaf)+').lnk') }; $s=$ws.CreateShortcut($p); $s.TargetPath=Join-Path $dir 'start.bat'; $s.WorkingDirectory=$dir; $s.WindowStyle=7; $s.Save(); Write-Output ('Shortcut: '+$p)"
choice /C YN /M "Also start voice client (voice.bat, microphone) with Windows"
if errorlevel 2 goto done
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $dir='%~dp0'.TrimEnd('\'); $st=[Environment]::GetFolderPath('Startup'); $p=Join-Path $st 'Assistant Voice.lnk'; if((Test-Path $p) -and ($ws.CreateShortcut($p).WorkingDirectory.TrimEnd('\') -ne $dir)){ $p=Join-Path $st ('Assistant Voice ('+(Split-Path $dir -Leaf)+').lnk') }; $s=$ws.CreateShortcut($p); $s.TargetPath=Join-Path $dir 'voice.bat'; $s.WorkingDirectory=$dir; $s.WindowStyle=7; $s.Save(); Write-Output ('Shortcut: '+$p)"
echo Voice client added too.
:done
echo Done: the assistant will start with Windows.
echo To remove, delete the shortcut(s) printed above from:
echo   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
pause
