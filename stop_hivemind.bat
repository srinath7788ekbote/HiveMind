@echo off
REM ============================================================
REM  HiveMind — Stop Background Watcher
REM ============================================================
REM  Kills the repo watcher daemon via its PID file.
REM ============================================================

echo.
echo ============================================================
echo   HiveMind — Stopping Background Watcher
echo ============================================================
echo.

cd /d "%~dp0"

if not exist memory\watcher.pid (
    echo No watcher PID file found. Watcher may not be running.
    exit /b 0
)

set /p PID=<memory\watcher.pid

echo Stopping watcher (PID: %PID%)...

taskkill /PID %PID% /F >nul 2>nul
if errorlevel 1 (
    echo Process %PID% not found. It may have already exited.
) else (
    echo Watcher stopped.
)

del memory\watcher.pid 2>nul

echo.
echo ============================================================
echo   HiveMind watcher stopped.
echo ============================================================
echo.
