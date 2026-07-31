param(
  [Parameter(Mandatory = $true)]
  [string]$InstallDir,
  [switch]$InstallNode,
  [switch]$InstallPython,
  [switch]$InstallOpenClaw
)

$ErrorActionPreference = "Stop"

function Test-Command {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Install-PythonIfNeeded {
  if (Test-Command "python") {
    Write-Host "[installer] Python ya está instalado."
    return
  }

  if (-not $InstallPython) {
    throw "Python no está instalado. Repite la instalación activando 'Instalar Python automáticamente'."
  }

  $pythonUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
  $pythonInstaller = Join-Path $env:TEMP "nordik-python-installer.exe"
  Write-Host "[installer] Descargando Python..."
  Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonInstaller
  Write-Host "[installer] Instalando Python..."
  Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait -NoNewWindow
}

function Resolve-PythonCommand {
  if (Test-Command "python") {
    return "python"
  }
  $commonPath = "C:\Program Files\Python312\python.exe"
  if (Test-Path $commonPath) {
    return $commonPath
  }
  throw "No se pudo localizar Python después de la instalación."
}

function Install-NodeIfNeeded {
  if (Test-Command "node") {
    Write-Host "[installer] Node.js ya está instalado."
    return
  }

  if (-not $InstallNode) {
    throw "Node.js no está instalado. Repite la instalación activando 'Instalar Node.js automáticamente'."
  }

  $nodeUrl = "https://nodejs.org/dist/v20.19.5/node-v20.19.5-x64.msi"
  $nodeInstaller = Join-Path $env:TEMP "nordik-node-installer.msi"
  Write-Host "[installer] Descargando Node.js..."
  Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeInstaller
  Write-Host "[installer] Instalando Node.js..."
  Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$nodeInstaller`" /qn /norestart" -Wait -NoNewWindow
}

function Resolve-NpmCommand {
  if (Test-Command "npm") {
    return "npm"
  }
  $commonPath = "C:\Program Files\nodejs\npm.cmd"
  if (Test-Path $commonPath) {
    return $commonPath
  }
  throw "No se pudo localizar npm después de la instalación."
}

function Initialize-BackendVenv {
  param([string]$PythonCommand)

  $backendDir = Join-Path $InstallDir "backend"
  $venvDir = Join-Path $backendDir ".venv"
  $venvPython = Join-Path $venvDir "Scripts\python.exe"

  if (-not (Test-Path $backendDir)) {
    throw "No se encontró la carpeta backend en $backendDir."
  }

  if (-not (Test-Path $venvPython)) {
    Write-Host "[installer] Creando entorno virtual para backend..."
    & $PythonCommand -m venv $venvDir
  }

  Write-Host "[installer] Instalando dependencias de backend..."
  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt")
}

function Install-OpenClawCli {
  param([string]$NpmCommand)
  Write-Host "[installer] Instalando OpenClaw CLI global..."
  & $NpmCommand install -g openclaw
}

Install-PythonIfNeeded
Install-NodeIfNeeded

$pythonCommand = Resolve-PythonCommand
Initialize-BackendVenv -PythonCommand $pythonCommand

if ($InstallOpenClaw) {
  $npmCommand = Resolve-NpmCommand
  Install-OpenClawCli -NpmCommand $npmCommand
}

Write-Host "[installer] Bootstrap de runtime finalizado."
