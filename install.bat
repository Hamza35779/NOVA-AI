@echo off
setlocal enabledelayedexpansion
title NOVA AI Installer

echo =======================================================
echo              NOVA AI - Automated Installer
echo =======================================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found on PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

echo [1/3] Setting up Python dependencies...
python -m pip install --upgrade pip
python -m pip install -e ".[server,tools-search,voice,screen]"

echo.
echo [2/3] Verifying installation...
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
python -m nova_ai.cli doctor

echo.
echo [3/3] Done! You can now start NOVA AI by double-clicking 'start.bat'
echo or running 'python -m nova_ai.cli chat' in this directory.
echo.
pause
