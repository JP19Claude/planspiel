# Woechentlicher Review starten (Windows PowerShell), Modell: models.weekly_review in config.yaml (Opus).
# Der Review prueft Journal + Performance und darf mission.md um Lehren ergaenzen.
# Optionen: -DryRun, -ShowCommand
param([switch]$DryRun, [switch]$ShowCommand)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$extra = @()
if ($DryRun) { $extra += "--dry-run" }
if ($ShowCommand) { $extra += "--show-command" }
& $py "tools\run_agent.py" --mode review @extra
exit $LASTEXITCODE
