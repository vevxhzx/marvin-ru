@echo off
REM Rewrites the notes of an ALREADY published GitHub release so they cover every version since the previous tag.
REM Usage: tools\fix_release_notes.bat 0.10.1 [previous tag, e.g. v0.9.15]
cd /d "%~dp0\.."
if "%1"=="" (echo Usage: tools\fix_release_notes.bat VERSION [PREV_TAG] && pause && exit /b 1)
set PY=.venv\Scripts\python.exe
if not exist %PY% set PY=python
set NOTES=%TEMP%\release-notes-%1.md
%PY% tools\release_notes.py %1 "%NOTES%" %2 || (pause && exit /b 1)
gh release edit "v%1" --notes-file "%NOTES%" || (pause && exit /b 1)
echo Done: notes of v%1 updated.
gh release view "v%1" --web
pause
