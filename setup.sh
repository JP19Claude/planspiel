#!/usr/bin/env bash
# Einrichtung in einem Rutsch (Linux/Mac). Im Projektordner ausfuehren:  ./setup.sh
# 1. Python-Umgebung + Pakete + Chromium  2. .env (optional)  3. Login  4. Seitenanalyse
set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n==> %s\n' "$1"; }

step "Voraussetzungen pruefen"
PYTHON="$(command -v python3 || command -v python || true)"
[ -n "$PYTHON" ] || { echo "Python 3.11+ fehlt."; exit 1; }
command -v claude >/dev/null || echo "Hinweis: Claude Code ('claude') nicht gefunden - fuer den Agenten spaeter noetig."

step "Python-Umgebung (.venv) und Pakete"
[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
PY=.venv/bin/python
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r requirements.txt
"$PY" -m playwright install chromium

step "Zugangsdaten (.env) - fuer automatisches Neu-Einloggen spaeter"
if [ -f .env ]; then
  echo ".env existiert schon - bleibt unveraendert."
else
  read -r -p "Planspiel-Benutzername/E-Mail (leer = ueberspringen): " user
  if [ -n "$user" ]; then
    read -r -s -p "Planspiel-Passwort (wird nicht angezeigt): " pass; echo
    esc() { local v=${1//\\/\\\\}; printf '"%s"' "${v//\"/\\\"}"; }
    umask 077
    printf 'PLANSPIEL_USERNAME=%s\nPLANSPIEL_PASSWORD=%s\n' "$(esc "$user")" "$(esc "$pass")" > .env
    echo ".env gespeichert (nur auf diesem Rechner, wird nie hochgeladen)."
  fi
fi

step "Login - ein Browser oeffnet sich"
echo "Logge dich im Browser ein (Captcha/2FA selbst loesen), dann hier ENTER druecken."
"$PY" tools/login.py --manual

step "Seitenanalyse - der Browser oeffnet sich erneut (schon eingeloggt)"
echo "Klick dich zu: Depot, Ordermaske (NICHTS abschicken!), Orderuebersicht."
echo "Auf jeder Seite hier ENTER druecken. Zum Schluss q + ENTER."
"$PY" tools/explore.py --interactive

step "Fertig"
echo "Lade die PNG- und JSON-Dateien aus diesem Ordner im Chat hoch:"
ls -d logs/explore/*/ | tail -1
