param(
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
# Some managed Windows shells expose both `Path` and `PATH`. Start-Process
# builds a case-insensitive environment dictionary and aborts on that duplicate.
# Collapse it once so API/worker startup is reliable from PowerShell y CI.
$pathValue = $env:Path
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) {
    $venvPython
} else {
    (Get-Command python -ErrorAction Stop).Source
}
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$readyUrl = "http://127.0.0.1:$ApiPort/ready"
$apiProcess = $null
$ownsApiProcess = $false
$workerProcess = $null

function Test-ProraApi {
    try {
        $response = Invoke-RestMethod -Uri $readyUrl -TimeoutSec 2
        return $response.status -eq "ready"
    } catch {
        return $false
    }
}

if (-not (Test-ProraApi)) {
    Write-Host "Iniciando PRORA API en http://127.0.0.1:$ApiPort ..."
    $apiProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -WorkingDirectory $backend `
        -NoNewWindow `
        -PassThru
    $ownsApiProcess = $true

    $apiReady = $false
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if ($apiProcess.HasExited) {
            throw "La API termino durante el arranque con codigo $($apiProcess.ExitCode)."
        }
        if (Test-ProraApi) {
            $apiReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $apiReady) {
        throw "La API no alcanzo el estado ready en 20 segundos."
    }
} else {
    Write-Host "PRORA API ya estaba operativa en http://127.0.0.1:$ApiPort."
}

try {
    Write-Host "Iniciando trabajador de sincronizacion y entrenamiento ..."
    $workerProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "app.jobs.worker", "--poll-seconds", "2") `
        -WorkingDirectory $backend `
        -WindowStyle Hidden `
        -PassThru

    Write-Host "API lista. Iniciando web en http://127.0.0.1:$WebPort ..."
    Push-Location $root
    # En desarrollo usamos la API directa. FastAPI autoriza ambos orígenes
    # locales y así el frontend no depende del proxy del servidor de Vite.
    $env:VITE_API_BASE_URL = "http://127.0.0.1:$ApiPort/api/v1"
    & $npm run dev -- --host 127.0.0.1 --port $WebPort --strictPort
    if ($LASTEXITCODE -ne 0) {
        throw "Vite termino con codigo $LASTEXITCODE."
    }
} finally {
    Pop-Location
    if ($workerProcess -and -not $workerProcess.HasExited) {
        Stop-Process -Id $workerProcess.Id
        $workerProcess.WaitForExit()
    }
    if ($ownsApiProcess -and $apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id
        $apiProcess.WaitForExit()
    }
}
