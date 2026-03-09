@echo off
REM ============================================================
REM  HiveMind — Setup
REM ============================================================
REM  Creates a Python venv, installs dependencies, and builds
REM  the VS Code extension. Run this once after cloning the repo.
REM ============================================================

echo.
echo ============================================================
echo   HiveMind Setup
echo ============================================================
echo.

cd /d "%~dp0"

REM --- Python virtual environment ---
echo [1/4] Creating Python virtual environment...
if not exist .venv (
    python -m venv .venv
    echo       Created .venv
) else (
    echo       .venv already exists.
)

REM Activate venv
call .venv\Scripts\activate.bat

REM --- Python dependencies ---
echo [2/4] Installing Python dependencies...
pip install -r requirements.txt 2>nul
pip install chromadb 2>nul
echo       (chromadb is optional — JSON fallback will be used if unavailable)
echo.

REM --- VS Code extension ---
echo [3/4] Building VS Code extension...
cd vscode-extension
if exist package.json (
    call npm install
    call npm run compile
    echo       Extension built successfully.
) else (
    echo       WARNING: vscode-extension/package.json not found. Skipping.
)
cd /d "%~dp0"
echo.

REM --- Create memory directory ---
echo [4/4] Creating memory directory...
if not exist memory mkdir memory
echo       memory\ directory ready.
echo.

echo ============================================================
echo   Setup complete!
echo.
echo   Next steps:
echo     1. Run install_extension.bat to package and install the extension
echo     2. Run start_hivemind.bat to start the background watcher
echo     3. Open VS Code and type @hivemind in Copilot Chat
echo ============================================================
echo.
