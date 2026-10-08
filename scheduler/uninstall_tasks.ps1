# Entfernt die boerse-agent Aufgaben aus dem Windows-Aufgabenplaner.
$ErrorActionPreference = "Stop"
Get-ScheduledTask -TaskPath "\boerse-agent\" -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false
Write-Host "boerse-agent Aufgaben entfernt."
