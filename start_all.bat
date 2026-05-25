@echo off
:: ============================================================
::  BHANDARI TRADING TERMINAL  —  start_all.bat
::  One-click launcher: FastAPI backend + React/Vite frontend
::  ─────────────────────────────────────────────────────────
::  Double-click this file, OR run from PowerShell / cmd.
:: ============================================================

setlocal EnableDelayedExpansion

:: Switch console to UTF-8 so Python can print Unicode chars
chcp 65001 >nul 2>nul

:: ── Project root (same folder as this .bat file) ─────────────────────────────
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: ── Locate Python (prefer .venv) ─────────────────────────────────────────────
if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        powershell -NoProfile -Command "Write-Host ' ERR  Python not found. Install Python 3.10+ and try again.' -ForegroundColor Red"
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

:: ── Print header via PowerShell (for colour support on all Windows versions) ──
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Write-Host '' ; ^
   Write-Host ('  ' + [char]9608 + ' BHANDARI TRADING TERMINAL') -ForegroundColor Cyan -NoNewline ; ^
   Write-Host '  starting...' -ForegroundColor DarkGray ; ^
   Write-Host '' "

:: ── Verify launcher.py exists ────────────────────────────────────────────────
if not exist "%ROOT%\launcher.py" (
    powershell -NoProfile -Command "Write-Host ' ERR  launcher.py not found in %ROOT%' -ForegroundColor Red"
    pause
    exit /b 1
)

:: ── Hand off to Python launcher (keeps this window as the status console) ─────
"%PYTHON%" "%ROOT%\launcher.py" %*

:: If Python launcher exits cleanly, pause so user can read the log
if errorlevel 1 (
    powershell -NoProfile -Command "Write-Host ' ERR  Launcher exited with an error. See logs\launcher.log' -ForegroundColor Red"
    pause
)
endlocal
