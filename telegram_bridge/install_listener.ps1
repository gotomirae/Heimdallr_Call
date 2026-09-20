# PRD Ref: §8.1 · Telegram getUpdates는 이 전용 로컬 작업만 수행한다.
param([switch]$StageOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonw = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$listener = Join-Path $PSScriptRoot 'listener_once.py'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Project .venv pythonw.exe is missing.' }

& $python -X utf8 $listener --check
if ($LASTEXITCODE -ne 0) { throw 'Telegram listener preflight failed.' }

$taskName = 'HeimdallrTelegramListener'
$taskRun = '"' + $pythonw + '" -X utf8 "' + $listener + '"'
if ($StageOnly) {
    $tomorrow = (Get-Date).AddDays(1)
    schtasks.exe /Create /TN $taskName /SC ONCE /SD $tomorrow.ToString('yyyy/MM/dd') /ST 23:59 /TR $taskRun /F | Out-Null
} else {
    schtasks.exe /Create /TN $taskName /SC MINUTE /MO 1 /TR $taskRun /F | Out-Null
}
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Heimdallr Telegram listener.' }
if ($StageOnly) {
    schtasks.exe /Change /TN $taskName /Disable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Failed to stage disabled Telegram listener.' }
    Write-Host 'Heimdallr Telegram listener staged but disabled.'
    return
}
schtasks.exe /Run /TN $taskName | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to start Heimdallr Telegram listener.' }
Write-Host 'Heimdallr Telegram listener installed and started.'
