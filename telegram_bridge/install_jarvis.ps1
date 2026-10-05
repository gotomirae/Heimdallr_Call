# PRD Ref: §8.7 G. Run in the user's ordinary logged-in Windows session.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pythonw = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$claude = (Get-Command claude.exe -ErrorAction Stop).Source
$skill = Join-Path $env:USERPROFILE '.claude\skills\kairos-deck\SKILL.md'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Install project .venv first.' }
if (-not (Test-Path -LiteralPath $skill)) { throw 'kairos-deck skill is missing.' }
if (-not (Test-Path -LiteralPath 'G:\내 드라이브\1. 주식 자본\2. 아이언맨의 투자 분석')) {
    throw 'Google Drive for Desktop root is unavailable.'
}
& $python -X utf8 -m src.db.init
if ($LASTEXITCODE -ne 0) { throw 'Verify G then H migrations: kairos_jarvis.sql and kairos_claude.sql.' }
& $python -X utf8 -m telegram_bridge.jarvis_registry
if ($LASTEXITCODE -ne 0) { throw 'Configure SEC_USER_AGENT and verify registry sync.' }
# Uses sanitized subscription environment; this check does not generate a deck.
# PS 5.1 strips nested quotes in native -c arguments; execute a saved Python probe.
$loginProbe = Join-Path $PSScriptRoot 'claude_login.py'
$loginJson = & $python -X utf8 $loginProbe
if ($LASTEXITCODE -ne 0) { throw 'Claude login check failed.' }
$login = $loginJson | ConvertFrom-Json
if (-not $login.loggedIn -or $login.authMethod -ne 'claude.ai') { throw 'Run claude auth login using subscription first.' }
# PDF export uses the installed PowerPoint COM server.
$powerpointKey = Get-ItemProperty -LiteralPath 'Registry::HKEY_CLASSES_ROOT\PowerPoint.Application\CLSID' -ErrorAction SilentlyContinue
if (-not $powerpointKey) { throw 'Microsoft PowerPoint desktop is required for PDF export.' }
& (Join-Path $PSScriptRoot 'install_collector.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Collector installation failed.' }

$runner = Join-Path $PSScriptRoot 'deck_runner.py'
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('-X utf8 "' + $runner + '"') -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 125) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'HeimdallrKairosDeckRunner' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host 'Collector and headless deck runner installed. Deck runner executes once a minute while logged in.'
