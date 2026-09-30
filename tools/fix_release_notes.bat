@echo off
REM Rewrites the notes of an ALREADY published GitHub release so they cover every version since the previous tag.
REM Usage: double-click (it will ask), or: tools\fix_release_notes.bat 0.10.1 [v0.9.15]
cd /d "%~dp0\.."
set PY=.venv\Scripts\python.exe
if not exist %PY% set PY=python
set VER=%1
set PREV=%2
if "%VER%"=="" for /f "delims=" %%v in ('%PY% -c "from core import VERSION; print(VERSION)"') do set VER=%%v
echo Release to fix: v%VER%
if "%PREV%"=="" (
    echo.
    echo Previous PUBLISHED tag, from which to collect notes ^(e.g. v0.9.15^).
    echo Press Enter to take the previous tag automatically.
    set /p PREV=Previous tag: 
)
set NOTES=%TEMP%\release-notes-%VER%.md
%PY% tools\release_notes.py %VER% "%NOTES%" %PREV% || (pause && exit /b 1)
echo.
echo --- notes preview (first lines) ---
%PY% -c "import sys;print(''.join(open(sys.argv[1],encoding='utf-8').readlines()[:12]))" "%NOTES%"
echo -----------------------------------
gh release edit "v%VER%" --notes-file "%NOTES%" || (echo [!] gh failed - is GitHub CLI installed and 'gh auth login' done? && pause && exit /b 1)
echo Done: notes of v%VER% updated.
gh release view "v%VER%" --web
pause
