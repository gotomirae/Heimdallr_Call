# PRD Ref: §7 · §9.1 — GitHub 예약 지연을 보완하는 로컬 클릭형 LLM worker.
param([switch]$StageOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonw = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Project .venv pythonw.exe is missing.' }

# 자격증명·스키마·import를 실제 worker 진입 전 확인한다. 유료 LLM은 호출하지 않는다.
& $python -X utf8 -m src.db.init
if ($LASTEXITCODE -ne 0) { throw 'Supabase schema preflight failed.' }
& $python -X utf8 -c 'from src.analysis.dashboard_requests import pending_rows;print(len(pending_rows(1)))'
if ($LASTEXITCODE -ne 0) { throw 'Dashboard analysis worker preflight failed.' }

$taskName = 'HeimdallrDashboardAnalysis'
$taskRun = '"' + $pythonw + '" -X utf8 -m src.analysis.dashboard_requests --limit 1 --max-seconds 240'
if ($StageOnly) {
    $tomorrow = (Get-Date).AddDays(1)
    schtasks.exe /Create /TN $taskName /SC ONCE /SD $tomorrow.ToString('yyyy/MM/dd') /ST 23:59 /TR $taskRun /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Failed to stage dashboard analysis worker.' }
    schtasks.exe /Change /TN $taskName /Disable | Out-Null
    Write-Host 'Heimdallr dashboard analysis worker staged but disabled.'
    return
}
schtasks.exe /Create /TN $taskName /SC MINUTE /MO 1 /TR $taskRun /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to install dashboard analysis worker.' }
schtasks.exe /Run /TN $taskName | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to start dashboard analysis worker.' }
Write-Host 'Heimdallr dashboard analysis worker installed and started.'
