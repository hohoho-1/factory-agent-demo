# Starts the whole demo, each part in its own window:
#   backend (Spring Boot) -> AI agent -> sensor simulator -> dashboard (Vite)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1          # build backend only if jar is missing
#   powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Build   # always rebuild backend
# Prerequisites: see README (Mosquitto service, PostgreSQL DB, python venv, application-local.yml)
param(
    [switch]$Build,
    [string]$Mvn = "C:\Program Files\JetBrains\IntelliJ IDEA 2025.3.3\plugins\maven\lib\maven3\bin\mvn.cmd"
)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$jar = Join-Path $root "backend\target\backend-0.0.1-SNAPSHOT.jar"
$py = Join-Path $root "python\.venv\Scripts\python.exe"

if ((Get-Service mosquitto -ErrorAction SilentlyContinue).Status -ne "Running") {
    throw "Mosquitto service is not running. Run: Start-Service mosquitto"
}
if (-not (Test-Path $py)) {
    throw "Python venv not found at $py. See README > Setup."
}
if ($Build -or -not (Test-Path $jar)) {
    Write-Host "Building backend..."
    & $Mvn -q -f (Join-Path $root "backend\pom.xml") -DskipTests package
    if ($LASTEXITCODE -ne 0) { throw "Backend build failed" }
}
if (-not (Test-Path (Join-Path $root "dashboard\node_modules"))) {
    Write-Host "Installing dashboard packages..."
    npm install --prefix (Join-Path $root "dashboard") --no-audit --no-fund
}

function Start-Window([string]$Title, [string]$WorkDir, [string]$Command) {
    # -EncodedCommand avoids quoting problems with paths that contain spaces
    $script = "`$host.UI.RawUI.WindowTitle = '$Title'; $Command"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    Start-Process powershell -WorkingDirectory $WorkDir -ArgumentList "-NoExit", "-EncodedCommand", $encoded | Out-Null
}

Start-Window "demo: backend" $root "java -jar '$jar'"

Write-Host -NoNewline "Waiting for backend"
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        Invoke-WebRequest -UseBasicParsing "http://localhost:8080/api/alarm-rules" -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    } catch {
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 1
    }
}
Write-Host ""
if (-not $ready) { throw "Backend did not start in 60s. Check the 'demo: backend' window." }

Start-Window "demo: ai-agent" (Join-Path $root "python") "`$env:PYTHONIOENCODING = 'utf-8'; & '$py' -m agent.agent"
Start-Window "demo: sensors" $root "& '$py' python\sensors\virtual_sensors.py"
Start-Window "demo: dashboard" (Join-Path $root "dashboard") "npm run dev"

Write-Host ""
Write-Host "Dashboard      : http://localhost:5173"
Write-Host "Inject anomaly : powershell -File scripts\inject.ps1 mixer_vibration"
Write-Host "Stop everything: powershell -File scripts\stop-demo.ps1"
