<#
.SYNOPSIS
  Arranca API + worker + frontend en PC para demo funcional completa.

.DESCRIPTION
  - API en http://127.0.0.1:8000
  - Frontend en http://127.0.0.1:5173 (VITE_API_BASE_URL apuntando a la API local)
  - Worker en segundo plano para sync/train en cola

  GitHub Pages solo muestra el front. Este script es el camino para probar
  el sistema completo en su maquina.
#>
param(
    [string]$DatabaseUrl = "sqlite+aiosqlite:///./prora.db",
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "No existe $python. Cree el venv en backend y ejecute: pip install -e `".[dev,ml]`""
}

function Test-PortOpen([int]$Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(400)
        if ($ok -and $client.Connected) { $client.Close(); return $true }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

Write-Host "=== PRORA demo local ===" -ForegroundColor Cyan
Write-Host "Repo: $root"

# Liberar puertos ocupados por instancias previas (solo procesos PRORA conocidos).
foreach ($pattern in @("*uvicorn app.main*", "*app.jobs.worker*", "*vite*--port*$WebPort*")) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like $pattern } |
        ForEach-Object {
            Write-Host "Deteniendo PID $($_.ProcessId) ($pattern)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}
Start-Sleep -Seconds 1

$pathValue = $env:Path
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
$env:PRORA_DATABASE_URL = $DatabaseUrl
$env:VITE_API_BASE_URL = "http://127.0.0.1:$ApiPort/api/v1"
$env:CI = "true"

Write-Host "Iniciando API..." -ForegroundColor Yellow
$api = Start-Process -FilePath $python `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
    -WorkingDirectory $backend `
    -PassThru `
    -WindowStyle Hidden

Write-Host "Iniciando worker..." -ForegroundColor Yellow
$worker = Start-Process -FilePath $python `
    -ArgumentList @("-m", "app.jobs.worker", "--poll-seconds", "2") `
    -WorkingDirectory $backend `
    -PassThru `
    -WindowStyle Hidden

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$ApiPort/ready" -TimeoutSec 2
        if ($health.status -eq "ready") { $ready = $true; break }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $ready) {
    Stop-Process -Id $api.Id, $worker.Id -Force -ErrorAction SilentlyContinue
    throw "La API no respondio /ready a tiempo"
}

Write-Host "API ready. Iniciando frontend..." -ForegroundColor Yellow
Write-Host ""
Write-Host "Abra:" -ForegroundColor Green
Write-Host "  UI:   http://127.0.0.1:$WebPort/"
Write-Host "  API:  http://127.0.0.1:$ApiPort/docs"
Write-Host "  Ready http://127.0.0.1:$ApiPort/ready"
Write-Host ""
Write-Host "Ctrl+C detiene Vite; luego se intentara cerrar API y worker." -ForegroundColor DarkYellow

try {
    Push-Location $root
    pnpm run dev -- --host 127.0.0.1 --port $WebPort --strictPort
} finally {
    Pop-Location
    Write-Host "Cerrando API/worker..."
    Stop-Process -Id $api.Id, $worker.Id -Force -ErrorAction SilentlyContinue
}
