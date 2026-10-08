"""Hook, der Agenten-Befehle gegen Schutzgeräte prüft."""
from __future__ import annotations

import pytest

import agent_hook


def bash(cmd: str) -> str | None:
    return agent_hook.decide({"tool_name": "Bash", "tool_input": {"command": cmd}})


ALLOWED = [
    "python tools/portfolio.py",
    "python tools/order.py --symbol DE0007164600 --qty 10 --side buy --limit 245.5",
    "python tools/quotes.py SAP.DE --history 6mo | head -50",
    "python tools/journal.py tail --n 5",
    "python tools/journal.py add --title 'Kauf SAP' <<'EOF'\n**Was:** 10 SAP\nKurs > 5 % gestiegen, rm-Risiko, write-off\n"
    "Stop-Loss bei 200 €\nEOF",
    "python tools/journal.py add --title \"Kurs > 100\" --text \"Gewinne laufen lassen; > 5%\"",
    "cat config.yaml",
    "ls tools logs",
    "cat logs/actions.jsonl | tail -20",
    "python -m pip list",
    "date",
    "python3 -c \"print(1+1)\"",
    "echo hallo > analyse.txt",
]

BLOCKED = [
    "rm STOP",
    "rm -f ./STOP",
    "echo weiter > STOP",
    "mv STOP STOP.bak",
    "sed -i 's/22:00/23:59/' config.yaml",
    "cp /tmp/x.py tools/order.py",
    "echo 'pass' > tools/core/guards.py",
    "cat x >> selectors.yaml",
    "python -c \"open('tools/core/guards.py','w').write('')\"",
    "python - <<'EOF'\nopen('tools/order.py','w').write('x')\nEOF",
    "BOERSE_DRY_RUN=0 python tools/order.py --symbol X --qty 1 --side buy",
    "env -u BOERSE_RUN_ID python tools/order.py --symbol X --qty 1 --side buy",
    "python tools/integrity.py seal",
    "cat .env",
    "grep PASS ./.env",
    "cat .auth/storage_state.json",
    "ls ~/.boerse-agent",
    "git checkout tools/",
    "cd tools && rm order.py",
    "rm -rf logs",
    "tee agent-settings.json < /dev/null",
    "chmod +w CLAUDE.md",
    "echo x > mission.md",
    "python -c \"from playwright.sync_api import sync_playwright\"",
    "python - <<'EOF'\nimport json; json.load(open('.auth/storage_state.json'))\nEOF",
    "pip install selenium",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_normal_agent_commands_pass(project, cmd):
    assert bash(cmd) is None, cmd


@pytest.mark.parametrize("cmd", BLOCKED)
def test_tampering_commands_are_blocked(project, cmd):
    assert bash(cmd), cmd


def test_project_root_absolute_path_blocked(project):
    assert bash(f"rm -rf {project}")
    assert bash(f"cp evil.py {project}/tools/order.py")


def test_review_mode_may_edit_mission_but_not_order(project, monkeypatch):
    monkeypatch.setenv("BOERSE_RUN_MODE", "review")
    assert bash("python tools/order.py --symbol X --qty 1 --side buy")
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(project / "mission.md")}}
    assert agent_hook.decide(edit) is None
    monkeypatch.setenv("BOERSE_RUN_MODE", "trading")
    assert agent_hook.decide(edit)


@pytest.mark.parametrize("tool,path,blocked", [
    ("Edit", "tools/order.py", True),
    ("Write", "tools/new_helper.py", True),
    ("Write", "config.yaml", True),
    ("Write", "STOP", True),
    ("Edit", "logs/actions.jsonl", True),
    ("Write", ".claude/settings.json", True),
    ("Edit", "journal.md", False),
    ("Write", "notizen/analyse.md", False),
    ("Read", ".env", True),
    ("Read", ".auth/storage_state.json", True),
    ("Read", "tools/order.py", False),
    ("Read", "config.yaml", False),
])
def test_file_tools(project, tool, path, blocked):
    res = agent_hook.decide({"tool_name": tool, "tool_input": {"file_path": str(project / path)}})
    assert bool(res) is blocked


def test_seal_dir_blocked_for_file_tools(project):
    from pathlib import Path
    res = agent_hook.decide({"tool_name": "Read",
                             "tool_input": {"file_path": str(Path.home() / ".boerse-agent" / "x" / "seal.json")}})
    assert res


def test_main_exit_codes(project, monkeypatch, capsys):
    import io
    import json
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm STOP"}})))
    assert agent_hook.main() == 2
    assert "BLOCKIERT" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})))
    assert agent_hook.main() == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("kein json"))
    assert agent_hook.main() == 0  # Hook-Fehler legen den Lauf nicht lahm (Siegel fängt den Rest)


def test_own_browser_scripts_are_blocked(project):
    write = lambda path, content: agent_hook.decide(  # noqa: E731
        {"tool_name": "Write", "tool_input": {"file_path": str(project / path), "content": content}})
    assert write("bot.py", "from playwright.sync_api import sync_playwright")
    assert write("x.py", "open('tools/order.py','w').write('')")
    assert write("analyse.py", "import yfinance as yf\nprint(yf.Ticker('SAP.DE').history())") is None
    assert write("notizen.md", "Playwright-Fehler beim Login beobachtet") is None
