#!/usr/bin/env bash
# Woechentlicher Review starten (Linux/Mac), Modell: models.weekly_review in config.yaml (Opus).
# Der Review prueft Journal + Performance und darf mission.md um Lehren ergaenzen.
# Optionen: --dry-run, --show-command
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
exec "$PY" tools/run_agent.py --mode review "$@"
