# Starts the whole demo, each part in its own window (minimized by default):
#   backend (Spring Boot) -> AI agent -> sensor simulator -> dashboard (Vite)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1            # windows start minimized
#   powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Visible   # windows start normal
#   powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -Build     # always rebuild backend
#   powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -SkipBackend
#       # backend is already running elsewhere (e.g. IntelliJ); start only agent, sensors, dashboard
#   powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1 -OpcUa
#       # instead of the sensor simulator, start the virtual PLC (OPC UA server, port 4840)
#       # and the edge gateway (OPC UA -> MQTT telemetry, MQTT commands -> OPC UA setpoint writes)
# Prerequisites: see README (Mosquitto service, PostgreSQL DB, python venv, application-local.yml)
param(
    [switch]$Build,
    [switch]$Visible,
    [switch]$SkipBackend,
    [switch]$OpcUa,
    [string]$Mvn = "C:\Program Files\JetBrains\IntelliJ IDEA 2025.3.3\plugins\maven\lib\maven3\bin\mvn.cmd"
)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$jar = Join-Path $root "backend\target\backend-0.0.1-SNAPSHOT.jar"
$py = Join-Path $root "python\.venv\Scripts\python.exe"
$dashboard = Join-Path $root "dashboard"
$vite = Join-Path $dashboard "node_modules\vite\bin\vite.js"
$windowStyle = if ($Visible) { "Normal" } else { "Minimized" }

if ((Get-Service mosquitto -ErrorAction SilentlyContinue).Status -ne "Running") {
    throw "Mosquitto service is not running. Run: Start-Service mosquitto"
}
if (-not (Test-Path $py)) {
    throw "Python venv not found at $py. See README > Setup."
}
if (-not $SkipBackend -and ($Build -or -not (Test-Path $jar))) {
    Write-Host "Building backend..."
    & $Mvn -q -f (Join-Path $root "backend\pom.xml") -DskipTests package
    if ($LASTEXITCODE -ne 0) { throw "Backend build failed" }
}
if (-not (Test-Path $vite)) {
    Write-Host "Installing dashboard packages..."
    npm install --prefix $dashboard --no-audit --no-fund
}

function Start-Window([string]$Title, [string]$WorkDir, [string]$Command) {
    # -EncodedCommand avoids quoting problems with paths that contain spaces
    $script = "`$host.UI.RawUI.WindowTitle = '$Title'; $Command"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    Start-Process powershell -WorkingDirectory $WorkDir -WindowStyle $windowStyle `
        -ArgumentList "-NoExit", "-EncodedCommand", $encoded | Out-Null
}

if (-not $SkipBackend) {
    Start-Window "demo: backend" $root "java -jar '$jar'"
}

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
if (-not $ready) {
    if ($SkipBackend) { throw "Backend is not responding on :8080. Start BackendApplication first (IntelliJ Services)." }
    throw "Backend did not start in 60s. Check the 'demo: backend' window."
}

Start-Window "demo: ai-agent" (Join-Path $root "python") "`$env:PYTHONIOENCODING = 'utf-8'; & '$py' -m agent.agent"
if ($OpcUa) {
    $pyDir = Join-Path $root "python"
    Start-Window "demo: virtual-plc" $pyDir "`$env:PYTHONIOENCODING = 'utf-8'; & '$py' -m plc.virtual_plc"
    Start-Window "demo: edge-gateway" $pyDir "`$env:PYTHONIOENCODING = 'utf-8'; & '$py' -m plc.edge_gateway"
} else {
    Start-Window "demo: sensors" $root "& '$py' python\sensors\virtual_sensors.py"
}
# Run vite with node directly: "npm run" overwrites the window title,
# and the absolute path lets stop-demo.ps1 find the process.
Start-Window "demo: dashboard" $dashboard "node '$vite'"

Write-Host ""
Write-Host "Dashboard      : http://localhost:5173"
Write-Host "Inject anomaly : powershell -File scripts\inject.ps1 mixer_vibration"
if ($OpcUa) {
    Write-Host "Data source    : virtual PLC opc.tcp://localhost:4840/factory/line1/ -> edge gateway -> MQTT"
    Write-Host "Setpoint demo  : powershell -File scripts\inject.ps1 mixer_resonance  (then approve the AI setpoint card)"
}
Write-Host "Stop everything: powershell -File scripts\stop-demo.ps1"
if (-not $Visible) { Write-Host "Logs           : demo windows are minimized in the taskbar ('demo: ...')" }
