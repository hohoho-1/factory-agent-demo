# Stops everything started by start-demo.ps1 (backend, AI agent, simulator, dashboard).
# Mosquitto and PostgreSQL services keep running.
$patterns = @(
    "*backend-0.0.1-SNAPSHOT.jar*",
    "*agent.agent*",
    "*virtual_sensors.py*",
    "*factory-agent-demo*dashboard*vite*"
)
$stopped = 0
Get-CimInstance Win32_Process | Where-Object {
    $cmd = $_.CommandLine
    $cmd -and ($patterns | Where-Object { $cmd -like $_ })
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "stopped $($_.Name) ($($_.ProcessId))"
    $stopped++
}
Get-Process powershell -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like "demo: *" } | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Write-Host "done ($stopped processes)"
