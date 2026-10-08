# Einrichtung in einem Rutsch (Windows). Im Projektordner ausfuehren:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# 1. Python-Umgebung + Pakete + Chromium
# 2. Zugangsdaten in .env (optional, bleibt nur auf diesem PC)
# 3. Login im sichtbaren Browser (du loggst dich selbst ein)
# 4. Seitenanalyse: du klickst dich zu Depot, Ordermaske, Orderuebersicht
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Check([string]$What) { if ($LASTEXITCODE -ne 0) { Write-Host "FEHLER bei: $What" -ForegroundColor Red; exit 1 } }

Step "Voraussetzungen pruefen"
$hasPyLauncher = [bool](Get-Command py -ErrorAction SilentlyContinue)
$hasPython = [bool](Get-Command python -ErrorAction SilentlyContinue)
if (-not $hasPyLauncher -and -not $hasPython) {
    Write-Host "Python fehlt. Installieren von https://www.python.org/downloads/ (Haken bei 'Add python.exe to PATH'), dann neu starten." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "Hinweis: Claude Code ('claude') nicht gefunden. Fuer Login und Seitenanalyse nicht noetig, fuer den Agenten spaeter schon." -ForegroundColor Yellow
}

Step "Python-Umgebung (.venv) und Pakete - dauert ein paar Minuten"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if ($hasPyLauncher) { & py -3 -m venv .venv } else { & python -m venv .venv }
    Check "venv anlegen"
}
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip; Check "pip"
& $py -m pip install --quiet -r requirements.txt; Check "pip install"
& $py -m playwright install chromium; Check "Chromium installieren"

Step "Zugangsdaten (.env) - fuer automatisches Neu-Einloggen spaeter"
if (Test-Path ".env") {
    Write-Host ".env existiert schon - bleibt unveraendert."
} else {
    $user = Read-Host "Planspiel-Benutzername/E-Mail (leer = ueberspringen)"
    if ($user) {
        $secure = Read-Host "Planspiel-Passwort (wird nicht angezeigt)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        $esc = { param($v) '"' + ($v -replace '\\', '\\' -replace '"', '\"') + '"' }
        $text = "PLANSPIEL_USERNAME=" + (& $esc $user) + "`nPLANSPIEL_PASSWORD=" + (& $esc $plain) + "`n"
        [IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $text, (New-Object Text.UTF8Encoding($false)))
        Write-Host ".env gespeichert (nur auf diesem PC, wird nie hochgeladen)."
    }
}

Step "Login - ein Browser oeffnet sich"
Write-Host "Geh im Browser zur Anmeldung, logge dich ein (Captcha/2FA selbst loesen)."
Write-Host "Wenn du eingeloggt bist: zurueck in dieses Fenster und ENTER druecken."
& $py tools\login.py --manual; Check "Login"

Step "Seitenanalyse - der Browser oeffnet sich erneut (schon eingeloggt)"
Write-Host "Klick dich nacheinander zu: Depot, Ordermaske (NICHTS abschicken!), Orderuebersicht."
Write-Host "Auf jeder Seite hier im Fenster ENTER druecken. Zum Schluss q + ENTER."
& $py tools\explore.py --interactive; Check "Seitenanalyse"

$latest = Get-ChildItem "logs\explore" -Directory | Sort-Object Name | Select-Object -Last 1
Step "Fertig"
Write-Host "Lade die PNG- und JSON-Dateien aus diesem Ordner im Chat hoch:"
Write-Host "  $($latest.FullName)" -ForegroundColor Green
if ($latest) { Start-Process explorer.exe $latest.FullName }
