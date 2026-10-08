#!/usr/bin/env bash
# Handelslauf starten (Linux/Mac). Optionen: --dry-run (Testlauf), --show-command
#
# Effektiv wird ausgefuehrt (Modell + Prompt aus config.yaml):
#   claude -p "Lies mission.md und journal.md und führe einen Handelslauf aus" \
#     --model claude-sonnet-5-5 --allowedTools "Bash,Read,Write,Edit,WebSearch,WebFetch" \
#     --settings agent-settings.json --output-format stream-json --verbose \
#     --disallowedTools "Edit(/mission.md)"
# eingebettet in tools/run_agent.py (STOP-Wache, Siegel, Protokoll in logs/).
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
exec "$PY" tools/run_agent.py --mode trading "$@"
