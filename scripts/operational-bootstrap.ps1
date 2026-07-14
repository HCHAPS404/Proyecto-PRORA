<#
.SYNOPSIS
  Comprueba readiness, encola entrenamiento de las 6 enfermedades y reporta
  si el sistema puede pasar a alerta temprana operativa.

.DESCRIPTION
  GitHub Pages solo hospeda el frontend. Este script se ejecuta contra una API
  con worker activo (local, Docker o VPS). No inventa datos frescos: si el corte
  SIVIGILA supera 35 dias, informa los bloqueos y deja el estado research_only.

.PARAMETER ApiBase
  Origen de la API (sin /api/v1). Por defecto http://127.0.0.1:8000

.PARAMETER Token
  Bearer JWT de operador (analyst/admin). Si se omite, solo consulta endpoints publicos.

.PARAMETER ForceTrain
  Si es true, encola POST /models/train para cada enfermedad priorizada.
#>
param(
    [string]$ApiBase = "http://127.0.0.1:8000",
    [string]$Token = "",
    [switch]$ForceTrain
)

$ErrorActionPreference = "Stop"
$api = $ApiBase.TrimEnd('/')
$headers = @{}
if ($Token) { $headers["Authorization"] = "Bearer $Token" }

function Invoke-Prora {
    param([string]$Path, [string]$Method = "GET", [object]$Body = $null)
    $uri = "$api$Path"
    if ($Body -ne $null) {
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -ContentType "application/json" -Body ($Body | ConvertTo-Json -Compress)
    }
    return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers
}

Write-Host "=== PRORA operational bootstrap ===" -ForegroundColor Cyan
Write-Host "API: $api"

$ready = Invoke-Prora "/ready"
if ($ready.status -ne "ready") {
    throw "La API no esta ready: $($ready | ConvertTo-Json -Compress)"
}
Write-Host "ready: OK"

$portfolio = Invoke-Prora "/api/v1/models/readiness/portfolio"
$diseases = @($portfolio.diseases)
Write-Host ""
Write-Host "Readiness por enfermedad:" -ForegroundColor Yellow
$blockers = @()
foreach ($item in $diseases) {
    $ops = [bool]$item.operational_forecast_eligible
    $age = $item.data.observation_age_days
    $level = $item.readiness_level
    $models = ($item.models | ForEach-Object { "h$($_.horizon)=$($_.state)" }) -join ", "
    $color = if ($ops) { "Green" } else { "DarkYellow" }
    Write-Host ("  {0,-14} level={1,-14} ops={2} age={3} models=[{4}]" -f $item.disease, $level, $ops, $age, $models) -ForegroundColor $color
    if (-not $ops) {
        foreach ($lim in @($item.limitations)) {
            if ($lim.severity -eq "blocking" -or $lim.code) {
                $blockers += "$($item.disease): $($lim.code) — $($lim.message)"
            }
        }
    }
}

$opsCount = @($diseases | Where-Object { $_.operational_forecast_eligible }).Count
Write-Host ""
if ($opsCount -eq 0) {
    Write-Host "NINGUNA enfermedad es operativa todavia." -ForegroundColor Red
    Write-Host "Bloqueos tipicos (datos publicos llegan solo hasta 2024):" -ForegroundColor Red
    Write-Host "  - Corte epidemiologico > 35 dias (stale_epidemiological_cutoff)"
    Write-Host "  - Sin ceros explicitos / panel incompleto (no_explicit_zero_case_reports)"
    Write-Host ""
    Write-Host "Para activar operativo:" -ForegroundColor Cyan
    Write-Host "  1. Cargue SIVIGILA agregado reciente en sivigila-current-authorized"
    Write-Host "     POST /api/v1/sources/sivigila-current-authorized/upload"
    Write-Host "  2. Vuelva a ejecutar este script con -ForceTrain y un token de operador"
    Write-Host "  3. Publique la API HTTPS y defina PRORA_API_BASE_URL en GitHub Pages"
} else {
    Write-Host "$opsCount enfermedad(es) elegibles para pronostico operativo." -ForegroundColor Green
}

if ($ForceTrain) {
    if (-not $Token) {
        throw "ForceTrain requiere -Token (JWT analyst/admin)."
    }
    Write-Host ""
    Write-Host "Encolando entrenamiento h3+h4..." -ForegroundColor Yellow
    foreach ($name in @("dengue", "malaria", "chikunguna", "zika", "leishmaniasis", "ira")) {
        try {
            $job = Invoke-Prora "/api/v1/models/train" -Method POST -Body @{ disease = $name }
            Write-Host "  $name -> job $($job.job_id) status=$($job.status)"
        } catch {
            Write-Host "  $name -> ERROR: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    Write-Host "Espere al worker. Consulte /api/v1/models/readiness/portfolio"
}

Write-Host ""
Write-Host "GitHub Pages (frontend): https://hchaps404.github.io/Proyecto-PRORA/" -ForegroundColor Cyan
Write-Host "Mapa operativo estricto: GET /api/v1/risk/map?disease=dengue&horizon=4&include_research=false"
if ($blockers.Count -gt 0) {
    Write-Host ""
    Write-Host "Detalle de bloqueos:" -ForegroundColor DarkYellow
    $blockers | Select-Object -Unique | ForEach-Object { Write-Host "  - $_" }
}
