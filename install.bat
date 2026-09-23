@echo off
setlocal enabledelayedexpansion
title NOVA AI Installer

echo =======================================================
echo              NOVA AI - Automated Installer
echo =======================================================
echo.
echo This installer will:
echo   1. Install Python dependencies
echo   2. Install opencode CLI (if missing)
echo   3. Configure opencode.json for NOVA AI
echo   4. Verify the installation
echo.

:: Check Python installation
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found on PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

echo.
echo =======================================================
echo  Step 1/4: Installing Python dependencies
echo =======================================================
python -m pip install --upgrade pip
python -m pip install -e ".[server,tools-search,voice,screen]"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install Python dependencies.
    pause
    exit /b 1
)

echo.
echo =======================================================
echo  Step 2/4: Installing opencode CLI
echo =======================================================
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
python -m nova_ai.cli opencode install
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] opencode CLI install skipped.
    echo You can install it manually later with:
    echo   npm install -g opencode-ai
    echo   OR: curl -fsSL https://opencode.ai/install ^| bash
)

echo.
echo =======================================================
echo  Step 3/4: Configuring opencode.json for NOVA AI
echo =======================================================
python -m nova_ai.cli opencode init
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] opencode.json not written.
    echo Run 'python -m nova_ai.cli opencode init' later.
)

echo.
echo =======================================================
echo  Step 4/4: Verifying installation
echo =======================================================
python -m nova_ai.cli doctor

echo.
echo =======================================================
echo  Installation Complete!
echo =======================================================
echo.
echo NOTE: The browser web UI is not built by this installer (it needs Node.js).
echo The API works without it; to get the browser app run:
echo   cd frontend ^&^& npm install ^&^& npm run build
echo   then start the server again.
echo.
echo Quick start:
echo   1. Start the backend:  python -m nova_ai.cli serve
echo   2. Launch opencode:    python -m nova_ai.cli opencode launch
echo   OR use start.bat for a menu of options.
echo.
echo For opencode model switching:
echo   python -m nova_ai.cli opencode model --list
echo   python -m nova_ai.cli opencode model
echo.
echo NOTE: Screen OCR needs Tesseract engine.
echo Install from: https://github.com/UB-Mannheim/tesseract/wiki
echo.
pause
