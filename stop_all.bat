@echo off
:: ============================================================
::  BHANDARI TRADING TERMINAL  —  stop_all.bat
::  Cleanly kills backend (8000) and frontend (3000) processes
:: ============================================================

setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: Locate Python
if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Write-Host '' ; ^
   Write-Host '  [STOP] Stopping all Trading Terminal services...' -ForegroundColor Yellow ; ^
   Write-Host '' "

:: Use the Python launcher for clean shutdown if available
if exist "%ROOT%\launcher.py" (
    "%PYTHON%" "%ROOT%\launcher.py" --stop
    goto :done
)

:: Fallback: kill ports directly with PowerShell
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ports = @(8000, 3000); ^
   foreach ($port in $ports) { ^
     $pids = (netstat -ano | Select-String (':' + $port + ' ') | ^
              Select-String 'LISTENING' | ^
              ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -Unique); ^
     foreach ($p in $pids) { ^
       if ([int]$p -gt 4) { ^
         try { Stop-Process -Id ([int]$p) -Force -ErrorAction Stop; ^
               Write-Host ('  [OK] Killed PID ' + $p + ' on port ' + $port) -ForegroundColor Green } ^
         catch { Write-Host ('  [--] No process on port ' + $port) -ForegroundColor DarkGray } ^
       } ^
     } ^
   } ; ^
   Write-Host '' ; ^
   Write-Host '  All services stopped.' -ForegroundColor Green ; ^
   Write-Host '' "

:done
endlocal
