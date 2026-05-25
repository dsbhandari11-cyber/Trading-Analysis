@echo off
setlocal

set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"
set "URL=http://127.0.0.1:3000/"
set "API_URL=http://127.0.0.1:8000/api/status"

if exist "%ROOT%.venv\Scripts\python.exe" (
  set "PYTHON=%ROOT%.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

where npm >nul 2>nul
if errorlevel 1 (
  echo npm was not found. Please install Node.js, then try again.
  pause
  exit /b 1
)

"%PYTHON%" --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python or create the project virtual environment, then try again.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing '%API_URL%' -TimeoutSec 2; if ($r.StatusCode -ge 200) { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
  echo Starting Trading Dashboard API...
  start "Trading Dashboard API" /D "%ROOT%" /min "%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing '%URL%' -TimeoutSec 2; if ($r.StatusCode -ge 200) { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
  echo Starting Trading Dashboard...
  start "Trading Dashboard Dev Server" /D "%FRONTEND%" /min npm.cmd run dev -- --host 127.0.0.1
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$url = '%URL%'; for ($i = 0; $i -lt 40; $i++) { try { $r = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 2; if ($r.StatusCode -ge 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
)

start "" "%URL%"
exit /b 0
