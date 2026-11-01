# PRD Ref: §10 · ADR50 — minute Python queue check, model only on authorized requests.
param([switch]$StageOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pythonw = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
& $python -X utf8 -m src.analysis.pro_worker --check
if ($LASTEXITCODE -ne 0) { throw 'Pro queue schema preflight failed; existing tasks unchanged.' }
$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-X utf8 -m telegram_bridge.pro_runner' -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3) -StartWhenAvailable
$taskName = 'HeimdallrProAnalysisRunner'
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'ADR50 Pro-only draft/review/publish; idle Python only' -Force | Out-Null
if ($StageOnly) {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    return
}
foreach ($legacyName in @('HeimdallrDashboardAnalysis', 'HeimdallrKairosDeckRunner')) {
    if (Get-ScheduledTask -TaskName $legacyName -ErrorAction SilentlyContinue) {
        Disable-ScheduledTask -TaskName $legacyName | Out-Null
        Stop-ScheduledTask -TaskName $legacyName
    }
}
Start-ScheduledTask -TaskName $taskName
Write-Host 'Pro-only runner installed. Listener and collector tasks preserved.'
