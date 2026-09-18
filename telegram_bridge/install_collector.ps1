# PRD Ref: §8 · Supabase 큐만 확인한다. Telegram getUpdates를 호출하지 않는다.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonw = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$bridge = Join-Path $PSScriptRoot 'bridge.py'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Project .venv pythonw.exe is missing.' }

# 설치 전 운영 DB와 로컬 자격증명을 확인한다. 실패 시 예약 작업을 만들지 않는다.
& $python -X utf8 -m src.db.init
if ($LASTEXITCODE -ne 0) { throw 'Supabase schema preflight failed.' }
& $python -X utf8 $bridge status
if ($LASTEXITCODE -ne 0) { throw 'Kairos bridge preflight failed.' }

$taskName = 'HeimdallrKairosCollector'
$taskRun = '"' + $pythonw + '" -X utf8 "' + $bridge + '" ingest'
schtasks.exe /Create /TN $taskName /SC MINUTE /MO 1 /TR $taskRun /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Heimdallr Kairos collector.' }
schtasks.exe /Run /TN $taskName | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to start Heimdallr Kairos collector.' }
Write-Host 'Heimdallr Kairos collector installed and started.'
