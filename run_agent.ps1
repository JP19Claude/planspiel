# Handelslauf starten (Windows PowerShell). Optionen: -DryRun, -ShowCommand
#
# Effektiv wird ausgefuehrt (Modell + Prompt aus config.yaml):
#   claude -p "Lies mission.md und journal.md und fuehre einen Handelslauf aus" `
#     --model claude-sonnet-5-5 --allowedTools "Bash,Read,Write,Edit,WebSearch,WebFetch" `
#     --settings agent-settings.json --output-format stream-json --verbose `
#     --disallowedTools "Edit(/mission.md)"
# eingebettet in tools\run_agent.py (STOP-Wache, Siegel, Protokoll in logs\).
param([switch]$DryRun, [switch]$ShowCommand)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$extra = @()
if ($DryRun) { $extra += "--dry-run" }
if ($ShowCommand) { $extra += "--show-command" }
& $py "tools\run_agent.py" --mode trading @extra
exit $LASTEXITCODE
