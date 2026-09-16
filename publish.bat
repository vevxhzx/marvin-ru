@echo off
title Assistant - publish to GitHub
cd /d "%~dp0"
REM ============================================================
REM  One-command publish to GitHub.
REM   first run  - links this folder to your EXISTING repository (keeps its history)
REM                or creates a new one; sets git name/email from your GitHub account
REM   next runs  - commits everything, pushes, tags vX.Y.Z, creates a release with a zip
REM  Needs: git (https://git-scm.com) and GitHub CLI (https://cli.github.com); once: gh auth login
REM  Private stuff (config.yaml, data/, *.db, .venv) never leaves the PC - see .gitignore
REM ============================================================
where git >nul 2>nul || (echo [!] git not found: https://git-scm.com/download/win && pause && exit /b 1)
where gh  >nul 2>nul || (echo [!] GitHub CLI not found: https://cli.github.com  ^(then: gh auth login^) && pause && exit /b 1)
gh auth status >nul 2>nul || (echo [!] Log in once: gh auth login && pause && exit /b 1)

set VER=
for /f "delims=" %%v in ('.venv\Scripts\python.exe -c "from core import VERSION; print(VERSION)" 2^>nul') do set VER=%%v
if "%VER%"=="" for /f "delims=" %%v in ('python -c "from core import VERSION; print(VERSION)" 2^>nul') do set VER=%%v
if "%VER%"=="" (echo [!] Cannot read VERSION from core\__init__.py && pause && exit /b 1)
echo Version: %VER%

REM --- git identity: take login from GitHub, so commits are yours (no "Author identity unknown") ---
set GHUSER=
for /f "delims=" %%u in ('gh api user -q .login 2^>nul') do set GHUSER=%%u
git config user.name >nul 2>nul || git config --global user.name "%GHUSER%"
git config user.email >nul 2>nul || git config --global user.email "%GHUSER%@users.noreply.github.com"

if exist .git goto haveremote
REM --- first run: attach to an existing repository or create a new one ---
echo.
echo First run. Paste the address of your EXISTING GitHub repository, e.g.
echo   https://github.com/%GHUSER%/marvin-ru.git
echo or press Enter to create a new one.
set URL=
set /p URL=Repository URL: 
git init -q -b main
if "%URL%"=="" (
    set REPO=
    set /p REPO=New repository name: 
    gh repo create "%REPO%" --public --source=. --remote=origin || (pause && exit /b 1)
    goto build
)
git remote add origin "%URL%" || (pause && exit /b 1)
echo Fetching history from GitHub...
git fetch -q origin || (echo [!] Cannot reach the repository - check the address && pause && exit /b 1)
git remote set-head origin -a >nul 2>nul

:haveremote
REM --- branch = the one GitHub uses (main or master) ---
set BR=
for /f "delims=" %%b in ('git symbolic-ref -q --short refs/remotes/origin/HEAD 2^>nul') do set BR=%%b
set BR=%BR:origin/=%
if "%BR%"=="" set BR=main
git rev-parse --verify -q HEAD >nul 2>nul
if not errorlevel 1 goto build
REM no local commits yet: sit on top of the remote history, keep private files out of git
git rev-parse --verify -q origin/%BR% >nul 2>nul
if not errorlevel 1 (
    git reset -q --soft origin/%BR%
    git rm -r -q --cached --ignore-unmatch config.yaml data *.db >nul 2>nul
)
git branch -q -M %BR%

:build
if not exist web\src goto commit
if not exist web\node_modules goto commit
echo Building the site...
pushd web
call npm run build --silent
if errorlevel 1 (popd && echo [!] Site build failed && pause && exit /b 1)
popd

:commit
git add -A
git diff --cached --quiet
if errorlevel 1 (git commit -q -m "v%VER%" || (echo [!] commit failed && pause && exit /b 1)) else (echo No changes to commit - release only.)
git push -q -u origin %BR% || (echo [!] push failed && pause && exit /b 1)

git rev-parse -q --verify "refs/tags/v%VER%" >nul 2>nul
if not errorlevel 1 (
    echo Tag v%VER% already exists - release not recreated. Bump VERSION in core\__init__.py.
    pause
    exit /b 0
)
git tag "v%VER%" && git push -q origin "v%VER%"

set NOTES=RELEASE-%VER%.md
if not exist "%NOTES%" set NOTES=CHANGELOG.md
set ZIP=%TEMP%\assistant-%VER%.zip
if exist "%ZIP%" del "%ZIP%"
git archive --format=zip --prefix=assistant/ -o "%ZIP%" HEAD || (echo [!] Archive failed && pause && exit /b 1)
gh release create "v%VER%" "%ZIP%#assistant-%VER%.zip" --title "v%VER%" --notes-file "%NOTES%" || (pause && exit /b 1)
del "%ZIP%"
echo.
echo Done: release v%VER% with zip is published.
gh release view "v%VER%" --web
pause
