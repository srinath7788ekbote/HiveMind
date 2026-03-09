@echo off
REM ============================================================
REM  HiveMind — Install VS Code Extension
REM ============================================================
REM  Packages the extension as a .vsix and installs it into VS Code.
REM ============================================================

echo.
echo ============================================================
echo   HiveMind — Install Extension
echo ============================================================
echo.

cd /d "%~dp0\vscode-extension"

REM --- Check prerequisites ---
where node >nul 2>nul
if errorlevel 1 (
    echo ERROR: Node.js is not installed. Please install Node.js 18+.
    exit /b 1
)

where code >nul 2>nul
if errorlevel 1 (
    echo WARNING: VS Code CLI not found in PATH. You may need to install the extension manually.
)

REM --- Install dependencies if needed ---
if not exist node_modules (
    echo [1/3] Installing npm dependencies...
    call npm install
) else (
    echo [1/3] Dependencies already installed.
)

REM --- Compile ---
echo [2/3] Compiling TypeScript...
call npm run compile
if errorlevel 1 (
    echo ERROR: Compilation failed.
    exit /b 1
)

REM --- Package ---
echo [3/3] Packaging extension...
call npm run package
if errorlevel 1 (
    echo ERROR: Packaging failed. Trying npx directly...
    call npx @vscode/vsce package --no-dependencies
)

REM --- Install ---
for %%f in (*.vsix) do (
    echo.
    echo Installing %%f into VS Code...
    code --install-extension "%%f" --force
    if errorlevel 1 (
        echo WARNING: Could not auto-install. Please run:
        echo   code --install-extension "%%~dpf%%f"
    ) else (
        echo Extension installed successfully!
    )
    goto :done
)

echo ERROR: No .vsix file found. Packaging may have failed.
exit /b 1

:done
cd /d "%~dp0"
echo.
echo ============================================================
echo   Extension installed. Reload VS Code to activate.
echo   Type @hivemind in Copilot Chat to start.
echo ============================================================
echo.
