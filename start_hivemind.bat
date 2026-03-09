@echo off
REM ============================================================
REM  HiveMind — Start Background Watcher
REM ============================================================
REM  Launches the repo watcher daemon that monitors for Git
REM  changes and re-indexes automatically.
REM ============================================================

echo.
echo ============================================================
echo   HiveMind — Starting Background Watcher
echo ============================================================
echo.

cd /d "%~dp0"

REM --- Check if already running ---
if exist memory\watcher.pid (
    set /p PID=<memory\watcher.pid
    tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
    if not errorlevel 1 (
        echo Watcher is already running (PID: %PID%).
        echo Run stop_hivemind.bat to stop it first.
        exit /b 0
    ) else (
        echo Stale PID file found. Cleaning up...
        del memory\watcher.pid
    )
)

REM --- Create memory directory ---
if not exist memory mkdir memory

REM --- Activate venv ---
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

REM --- Read active client ---
set CLIENT=
if exist memory\active_client.txt (
    set /p CLIENT=<memory\active_client.txt
)
if "%CLIENT%"=="" (
    echo ERROR: No active client configured.
    echo.
    echo   To get started:
    echo     1. Copy clients\_example\ to clients\your-client\
    echo     2. Edit clients\your-client\repos.yaml with your repos
    echo     3. Run: echo your-client ^> memory\active_client.txt
    echo     4. Re-run start_hivemind.bat
    echo.
    exit /b 1
)

REM --- Run initial ingest ---
echo [1/2] Running initial ingest for client: %CLIENT%...
python ingest\crawl_repos.py --client %CLIENT% --config clients\%CLIENT%\repos.yaml --verbose
echo.

REM --- Start watcher ---
echo [2/2] Starting background watcher...
start /B "HiveMind Watcher" python sync\watch_repos.py

REM --- Wait a moment and check ---
timeout /t 2 /nobreak >nul

if exist memory\watcher.pid (
    set /p PID=<memory\watcher.pid
    echo Watcher started (PID: %PID%).
) else (
    echo Watcher started (PID file not yet written).
)

echo.
echo ============================================================
echo   HiveMind is running.
echo   The watcher will re-index repos when changes are detected.
echo   Run stop_hivemind.bat to stop the watcher.
echo ============================================================
echo.
