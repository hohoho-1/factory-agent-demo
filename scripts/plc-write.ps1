# Sends a setpoint command straight to the edge gateway, bypassing backend approval (interlock demo).
# The virtual PLC interlock rejects unsafe values; the result shows up in the dashboard setpoint history.
# Requires: start-demo.ps1 -OpcUa
# Usage:
#   powershell -File scripts\plc-write.ps1 MIXER-01 speed_sp 95     # out of range -> interlock
#   powershell -File scripts\plc-write.ps1 TANK-02 temp_sp 58       # raise while temperature >= 50 -> interlock
param(
    [Parameter(Mandatory = $true)][string]$Equipment,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][double]$Value
)
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "python\.venv\Scripts\python.exe"
Push-Location (Join-Path $root "python")
try {
    & $py -m plc.direct_write $Equipment $Tag $Value
} finally {
    Pop-Location
}
