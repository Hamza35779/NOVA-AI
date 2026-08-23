@echo off
setlocal enabledelayedexpansion
title NOVA AI Launcher

echo =======================================================
echo               NOVA AI - Personal AI Assistant
echo =======================================================
echo.

:: Check Python installation
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found on PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Set PYTHONPATH to src
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

:: Display Menu
echo Choose an option to start:
echo [1] Interactive Chat (CLI)
echo [2] Voice Conversation Mode (Speak with Nova)
echo [3] Web/Desktop Backend Server (API & Desktop App)
echo [4] Memory Wiki Manager
echo [5] Run System Diagnostics (doctor)
echo [6] Exit
echo.
set /p choice="Enter option (1-6) [default: 1]: "

if "%choice%"=="" set choice=1

if "%choice%"=="1" (
    echo Starting NOVA AI Chat...
    python -m nova_ai.cli chat
) else if "%choice%"=="2" (
    echo Starting Voice Mode...
    python -m nova_ai.cli voice
) else if "%choice%"=="3" (
    echo Starting NOVA AI Server at http://127.0.0.1:8000...
    python -m nova_ai.cli serve
) else if "%choice%"=="4" (
    python -m nova_ai.cli memory-wiki list
    echo.
    python -m nova_ai.cli memory-wiki show profile
) else if "%choice%"=="5" (
    python -m nova_ai.cli doctor
) else (
    exit /b 0
)

pause
