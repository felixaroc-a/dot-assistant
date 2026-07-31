param(
  [string]$Serial = "",
  [switch]$Force,
  [switch]$NoInstaller,
  [string]$Installer = "",
  [string]$RecoveryOut = ""
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Nordik - Asistente de provision USB" -ForegroundColor Cyan
Write-Host "-----------------------------------"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodeScript = Join-Path $scriptDir "provision-pendrive-delivery.cjs"

if (-not (Test-Path $nodeScript)) {
  Write-Host "No se encontro el script Node: $nodeScript" -ForegroundColor Red
  exit 1
}

$argsList = @()
$argsList += "--require-registered"

if ($Serial.Trim()) {
  $argsList += "--serial"
  $argsList += $Serial.Trim()
}
if ($Force.IsPresent) {
  $argsList += "--force"
}
if ($NoInstaller.IsPresent) {
  $argsList += "--no-installer"
}
if ($Installer.Trim()) {
  $argsList += "--installer"
  $argsList += $Installer.Trim()
}
if ($RecoveryOut.Trim()) {
  $argsList += "--recovery-out"
  $argsList += $RecoveryOut.Trim()
}

Write-Host ""
Write-Host "Ejecutando provisión..." -ForegroundColor Yellow
Write-Host "node $nodeScript $($argsList -join ' ')" -ForegroundColor DarkGray
Write-Host ""

node $nodeScript @argsList
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
  Write-Host "Proceso completado correctamente." -ForegroundColor Green
} else {
  Write-Host "Proceso finalizo con errores (codigo $exitCode)." -ForegroundColor Red
}
Write-Host ""
exit $exitCode
