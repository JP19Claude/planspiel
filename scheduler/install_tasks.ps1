# Legt die Aufgaben im Windows-Aufgabenplaner an (als aktueller Benutzer, nur wenn angemeldet).
#   Handelslauf: Mo-Fr 10:00 und 16:30
#   Wochen-Review: So 18:00
# Aufruf (PowerShell im Projektordner):
#   powershell -ExecutionPolicy Bypass -File scheduler\install_tasks.ps1
# Entfernen: powershell -ExecutionPolicy Bypass -File scheduler\uninstall_tasks.ps1
param([string]$Project = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Stop"

function New-AgentAction([string]$Script) {
    $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Project\$Script`""
    New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $Project
}

$weekdays = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$tradeTriggers = @(
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "10:00"),
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $weekdays -At "16:30")
)
Register-ScheduledTask -TaskName "boerse-agent Handelslauf" -TaskPath "\boerse-agent\" `
    -Action (New-AgentAction "run_agent.ps1") -Trigger $tradeTriggers -Settings $settings `
    -Description "Planspiel Boerse: autonomer Handelslauf (Claude Code headless)" -Force | Out-Null

$reviewTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "18:00"
Register-ScheduledTask -TaskName "boerse-agent Wochen-Review" -TaskPath "\boerse-agent\" `
    -Action (New-AgentAction "run_weekly_review.ps1") -Trigger $reviewTrigger -Settings $settings `
    -Description "Planspiel Boerse: woechentlicher Review mit Opus" -Force | Out-Null

Get-ScheduledTask -TaskPath "\boerse-agent\" | Select-Object TaskName, State
Write-Host "Fertig. Test: Start-ScheduledTask -TaskPath '\boerse-agent\' -TaskName 'boerse-agent Handelslauf'"
