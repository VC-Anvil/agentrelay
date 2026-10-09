param([switch]$Demo, [int]$Port = 8787, [string]$Workers, [string]$Db, [string]$Workspaces)
$ErrorActionPreference = 'Stop'
if ($Workspaces -and ($Demo -or $Workers -or $Db)) { throw '-Workspaces no se combina con -Demo, -Workers o -Db.' }
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $taskRoot '.runtime\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = (Get-Command python -ErrorAction Stop).Source }
$taskData = Join-Path $taskRoot '.agentrelay'
New-Item -ItemType Directory -Path $taskData -Force | Out-Null
try {
    $taskHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
    if ($taskHealth.version) { throw "El puerto $Port ya tiene un servicio activo. Usa otro -Port o abre la instancia existente." }
} catch {
    if ($_.Exception.Message -like '*ya tiene un servicio activo*') { throw }
}
$taskArgs = @('-X', 'utf8', '-m', 'agentrelay', 'serve', '--port', "$Port")
if ($Demo) { $taskArgs += '--demo' }
if ($Workers) {
    $taskWorkerPath = (Resolve-Path -LiteralPath $Workers).Path
    $taskArgs += @('--workers', ('"' + $taskWorkerPath + '"'))
}
if ($Db) {
    $taskDatabasePath = [System.IO.Path]::GetFullPath($Db)
    $taskArgs += @('--db', ('"' + $taskDatabasePath + '"'))
}
if ($Workspaces) {
    $taskWorkspacePath = (Resolve-Path -LiteralPath $Workspaces).Path
    $taskArgs += @('--workspaces', ('"' + $taskWorkspacePath + '"'))
}
$taskChild = Start-Process -FilePath $taskPython -ArgumentList $taskArgs -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskData "web-$Port.out.log") -RedirectStandardError (Join-Path $taskData "web-$Port.err.log") -PassThru
$taskChild.Id | Set-Content -LiteralPath (Join-Path $taskData "web-$Port.pid")
Write-Host "AgentRelay: http://127.0.0.1:$Port (PID $($taskChild.Id))"
Write-Host "Registros: $taskData"
