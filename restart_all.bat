@echo off
:: ============================================================
::  BHANDARI TRADING TERMINAL  —  restart_all.bat
::  Stops all services, then starts them fresh
:: ============================================================

setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Write-Host '' ; ^
   Write-Host '  [RESTART] Restarting Trading Terminal...' -ForegroundColor Cyan ; ^
   Write-Host '' "

if exist "%ROOT%\launcher.py" (
    "%PYTHON%" "%ROOT%\launcher.py" --restart %*
) else (
    call "%ROOT%\stop_all.bat"
    timeout /t 2 /nobreak >nul
    call "%ROOT%\start_all.bat" %*
)

endlocal
