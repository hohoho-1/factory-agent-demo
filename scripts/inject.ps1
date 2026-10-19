# Injects an anomaly scenario into the running sensor simulator (via MQTT).
# Usage: powershell -File scripts\inject.ps1 <scenario>
#   tank_overheat | tank_low_level | mixer_vibration | mixer_overcurrent | filler_slowdown
#   mixer_bearing_wear (slow rise, for the trend forecast demo) | random
#   For the setpoint approval demo (start-demo.ps1 -OpcUa):
#   mixer_resonance (vibration stays in warning until the mixer speed setpoint is lowered)
#   tank_sp_misentry (TANK-02 temperature setpoint mistyped as 55C; virtual PLC only)
param(
    [ValidateSet("tank_overheat", "tank_low_level", "mixer_vibration", "mixer_overcurrent", "filler_slowdown",
                 "mixer_bearing_wear", "mixer_resonance", "tank_sp_misentry", "random")]
    [string]$Scenario = "random"
)
& "C:\Program Files\mosquitto\mosquitto_pub.exe" -h localhost -t factory/line1/sim/anomaly -q 1 -m $Scenario
if ($LASTEXITCODE -eq 0) { Write-Host "injected: $Scenario" }
