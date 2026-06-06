@echo off
setlocal EnableExtensions
REM ── Bhoot FM Archive — one-click live deploy ──────────────────────
REM
REM This is the only file you need to double-click for normal deploys.
REM It updates this checkout from GitHub, relaunches the latest copy of itself,
REM builds/uploads archive.prod.db locally, pushes GitHub main, and lets GitHub
REM Actions mirror the code snapshot to the Hugging Face Space.
REM
REM One-time setup on this PC:
REM   1. Run setup.bat / pip install -r requirements.txt.
REM   2. Run: huggingface-cli login  (token must have WRITE access to Dataset)
REM   3. Add GitHub repo secret HF_TOKEN (token must have WRITE access to Space)

cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 ( echo ERROR: git is not on PATH & pause & exit /b 1 )

where python >nul 2>nul
if errorlevel 1 ( echo ERROR: python is not on PATH & pause & exit /b 1 )

if /I not "%~1"=="--after-update" (
    echo [0/5] Updating local checkout from GitHub...
    git fetch origin main
    if errorlevel 1 ( echo ERROR: git fetch failed & pause & exit /b 1 )

    git checkout main
    if errorlevel 1 (
        echo ERROR: could not switch to main. Commit or stash local code changes, then try again.
        pause & exit /b 1
    )

    git pull --ff-only origin main
    if errorlevel 1 (
        echo ERROR: could not fast-forward main from GitHub.
        echo        If you have local code changes, commit or stash them, then try again.
        pause & exit /b 1
    )

    REM Relaunch after pull so any updated deploy_live.bat logic is used now.
    call "%~f0" --after-update
    exit /b %errorlevel%
)

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set CURRENT_BRANCH=%%b
if not "%CURRENT_BRANCH%"=="main" (
    echo ERROR: deploy must run from the local main branch. Current branch: %CURRENT_BRANCH%
    echo        Commit/stash your work, then run: git checkout main
    pause & exit /b 1
)

if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo [1/4] Ingesting latest transcripts into dev DB...
python ingest.py
if errorlevel 1 ( echo ERROR: ingest.py failed & pause & exit /b 1 )

echo [2/4] Building production DB (strips local paths, rewrites IA URLs)...
python prepare_production_db.py
if errorlevel 1 ( echo ERROR: prepare_production_db.py failed & pause & exit /b 1 )

echo [3/4] Uploading prod DB to companion HF Dataset...
python scripts\upload_db_to_dataset.py
if errorlevel 1 ( echo ERROR: upload_db_to_dataset.py failed. Did you run huggingface-cli login? & pause & exit /b 1 )

echo [4/4] Committing + pushing main to GitHub...
REM archive.prod.db is gitignored -- it is never committed.
git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "redeploy"
    if errorlevel 1 ( echo ERROR: git commit failed & pause & exit /b 1 )
) else (
    echo    (no file changes -- creating empty redeploy commit to trigger GitHub Actions)
    git commit --allow-empty -m "redeploy"
    if errorlevel 1 ( echo ERROR: empty git commit failed & pause & exit /b 1 )
)

git push origin main
if errorlevel 1 ( echo ERROR: git push to GitHub failed & pause & exit /b 1 )

echo.
echo Done locally. GitHub Actions is now deploying the Hugging Face Space.
echo 1. Watch GitHub Actions until the deploy workflow is green:
echo    https://github.com/xer2ten/bhoot-fm-archive/actions/workflows/deploy-huggingface.yml
echo 2. Then watch the Space rebuild / open the live site:
echo    https://huggingface.co/spaces/xer2ten/bhoot-fm-archive
echo.
choice /C YN /N /M "Open the GitHub Actions page now? [Y/N] "
if errorlevel 2 goto :skip_open
start "" "https://github.com/xer2ten/bhoot-fm-archive/actions/workflows/deploy-huggingface.yml"
:skip_open
pause
endlocal
