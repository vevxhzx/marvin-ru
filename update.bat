@echo off
title Assistant - update
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo .venv not found. Run install.bat first.
    pause
    exit /b 1
)
REM marker-tag for rollback (best-effort, git repo only; tag is just a marker, dirty tree ok)
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set UPDATETAG=pre-update-%%T
git rev-parse --is-inside-work-tree >nul 2>nul && git tag %UPDATETAG% >nul 2>nul
if defined UPDATETAG echo Rollback tag: %UPDATETAG% ^(see: git tag^)
REM DB snapshot via existing backup entrypoint (no CLI, one-liner; best-effort)
.venv\Scripts\python.exe -c "from core.services.scheduler import backup_db; print('DB snapshot:', backup_db(force=True))"
if errorlevel 1 echo DB snapshot skipped - no backup taken.
echo Updating packages...
.venv\Scripts\python.exe -m pip install --upgrade pip -q --disable-pip-version-check
.venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo Update FAILED. Check internet / VPN and run again.
    pause
    exit /b 1
)
if exist requirements-voice.txt (
    .venv\Scripts\python.exe voice_client.py --deps >nul 2>nul && .venv\Scripts\python.exe -m pip install -r requirements-voice.txt -q --disable-pip-version-check
)
echo.
echo Smoke test ^(tests/test_core.py^)...
.venv\Scripts\python.exe -m pytest tests/test_core.py -q
if errorlevel 1 (
    echo.
    echo SMOKE TEST FAILED. Core may be broken after update.
    if defined UPDATETAG echo Rollback hint: git checkout %UPDATETAG% ^(code^), restore DB snapshot from backups\ ^(data^).
    if not defined UPDATETAG echo Rollback hint: git checkout . ^(code^), restore DB snapshot from backups\ ^(data^).
    pause
    exit /b 1
)
echo.
.venv\Scripts\python.exe -c "from core import VERSION; print('core v' + VERSION)"
echo.
echo Done. Now run start.bat
pause
