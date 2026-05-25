#Requires -Version 5.1
<#
.SYNOPSIS
  Live status monitor for Bhandari Trading Terminal.
  Run in a separate PowerShell window to watch service health.

.USAGE
  powershell -ExecutionPolicy Bypass -File monitor.ps1
  powershell -ExecutionPolicy Bypass -File monitor.ps1 -Interval 5
#>

param(
    [int]$Interval   = 3,
    [int]$BackendPort  = 8000,
    [int]$FrontendPort = 3000
)

$BackendUrl  = "http://127.0.0.1:$BackendPort/api/status"
$FrontendUrl = "http://127.0.0.1:$FrontendPort"
$LogDir      = Join-Path $PSScriptRoot "logs"

function Test-Port {
    param([int]$Port)
    $tcp = New-Object System.Net.Sockets.TcpClient
    try {
        $tcp.Connect("127.0.0.1", $Port)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

function Get-HttpStatus {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return $r.StatusCode
    } catch {
        return $null
    }
}

function Get-LogTail {
    param([string]$File, [int]$Lines = 4)
    if (-not (Test-Path $File)) { return @("(no log yet)") }
    return Get-Content $File -Tail $Lines
}

$prevBeState = $null
$prevFeState = $null

# Hide cursor for cleaner rendering
[Console]::CursorVisible = $false

try {
    while ($true) {
        $now = Get-Date -Format "HH:mm:ss"

        # ── Check services ────────────────────────────────────────────────
        $bePort   = Test-Port $BackendPort
        $fePort   = Test-Port $FrontendPort
        $beHttp   = if ($bePort) { Get-HttpStatus $BackendUrl  } else { $null }
        $feHttp   = if ($fePort) { Get-HttpStatus $FrontendUrl } else { $null }
        $beOk     = ($beHttp -ne $null -and $beHttp -lt 400)
        $feOk     = ($feHttp -ne $null -and $feHttp -lt 400)

        # ── Print dashboard ───────────────────────────────────────────────
        Clear-Host

        Write-Host ""
        Write-Host "  ▸ TRADING TERMINAL  MONITOR" -ForegroundColor Cyan -NoNewline
        Write-Host ("  " + $now) -ForegroundColor DarkGray
        Write-Host ("  " + ("─" * 52)) -ForegroundColor DarkGray
        Write-Host ""

        # Backend
        if ($beOk) {
            Write-Host "  [BACKEND]  " -ForegroundColor Green -NoNewline
            Write-Host "● RUNNING  " -ForegroundColor Green -NoNewline
            Write-Host "port $BackendPort  HTTP $beHttp" -ForegroundColor DarkGray
        } elseif ($bePort) {
            Write-Host "  [BACKEND]  " -ForegroundColor Yellow -NoNewline
            Write-Host "◑ BOOTING  " -ForegroundColor Yellow -NoNewline
            Write-Host "port $BackendPort" -ForegroundColor DarkGray
        } else {
            Write-Host "  [BACKEND]  " -ForegroundColor Red -NoNewline
            Write-Host "○ STOPPED" -ForegroundColor Red
        }

        # Frontend
        if ($feOk) {
            Write-Host "  [FRONTEND] " -ForegroundColor Cyan -NoNewline
            Write-Host "● RUNNING  " -ForegroundColor Cyan -NoNewline
            Write-Host "port $FrontendPort  HTTP $feHttp" -ForegroundColor DarkGray
        } elseif ($fePort) {
            Write-Host "  [FRONTEND] " -ForegroundColor Yellow -NoNewline
            Write-Host "◑ BOOTING  " -ForegroundColor Yellow -NoNewline
            Write-Host "port $FrontendPort" -ForegroundColor DarkGray
        } else {
            Write-Host "  [FRONTEND] " -ForegroundColor Red -NoNewline
            Write-Host "○ STOPPED" -ForegroundColor Red
        }

        Write-Host ""
        Write-Host ("  " + ("─" * 52)) -ForegroundColor DarkGray

        # ── Backend log tail ──────────────────────────────────────────────
        Write-Host "  Backend log  ($LogDir\backend.log)" -ForegroundColor DarkGray
        $beTail = Get-LogTail (Join-Path $LogDir "backend.log") 3
        foreach ($line in $beTail) {
            Write-Host ("  " + $line.Substring(0, [Math]::Min($line.Length, 72))) `
                -ForegroundColor DarkGray
        }

        Write-Host ""
        Write-Host "  Frontend log  ($LogDir\frontend.log)" -ForegroundColor DarkGray
        $feTail = Get-LogTail (Join-Path $LogDir "frontend.log") 3
        foreach ($line in $feTail) {
            Write-Host ("  " + $line.Substring(0, [Math]::Min($line.Length, 72))) `
                -ForegroundColor DarkGray
        }

        Write-Host ""
        Write-Host ("  " + ("─" * 52)) -ForegroundColor DarkGray
        Write-Host "  Refreshing every ${Interval}s  |  Ctrl+C to exit" -ForegroundColor DarkGray

        # ── Detect state changes for alert sounds ────────────────────────
        if ($prevBeState -eq $true -and -not $beOk) {
            [Console]::Beep(800, 250)
            Write-Host "  ! BACKEND WENT DOWN" -ForegroundColor Red
        }
        if ($prevFeState -eq $true -and -not $feOk) {
            [Console]::Beep(600, 250)
            Write-Host "  ! FRONTEND WENT DOWN" -ForegroundColor Red
        }
        if ($prevBeState -eq $false -and $beOk) {
            Write-Host "  ✔ BACKEND CAME ONLINE" -ForegroundColor Green
        }
        if ($prevFeState -eq $false -and $feOk) {
            Write-Host "  ✔ FRONTEND CAME ONLINE" -ForegroundColor Cyan
        }

        $prevBeState = $beOk
        $prevFeState = $feOk

        Start-Sleep -Seconds $Interval
    }
} finally {
    [Console]::CursorVisible = $true
}
