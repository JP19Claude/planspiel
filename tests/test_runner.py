"""Runner: STOP-Wache, Siegel, Protokoll, Kommando."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
import yaml

import run_agent
from core import common, integrity

FAKE = str(Path(__file__).with_name("fake_claude.py"))


@pytest.fixture
def runner_project(project, monkeypatch):
    cfg = {"agent": {"claude_command": [sys.executable, FAKE], "timeout_minutes": 1}}
    (project / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (project / "mission.md").write_text("Kernauftrag: Depotwert maximieren.\n", encoding="utf-8")
    integrity.seal(project)
    monkeypatch.setenv("FAKE_CLAUDE", "ok")
    return project


def ran(project) -> dict | None:
    f = project / "claude_ran.json"
    return json.loads(f.read_text()) if f.exists() else None


def test_command_uses_models_settings_and_mission_lock():
    cfg = common.deep_merge(common.DEFAULT_CONFIG, {"agent": {"claude_command": ["claude"]}})
    trading = run_agent.claude_command(cfg, "trading", False)
    assert trading[:3] == ["claude", "-p", "Lies mission.md und journal.md und führe einen Handelslauf aus"]
    assert trading[trading.index("--model") + 1] == "claude-sonnet-5-5"
    assert trading[trading.index("--allowedTools") + 1] == "Bash,Read,Write,Edit,WebSearch,WebFetch"
    assert trading[trading.index("--settings") + 1].endswith("agent-settings.json")
    assert trading[trading.index("--disallowedTools") + 1] == "Edit(/mission.md)"
    review = run_agent.claude_command(cfg, "review", False)
    assert review[review.index("--model") + 1] == "claude-opus-5-5"
    assert "--disallowedTools" not in review
    assert "TESTLAUF" in run_agent.claude_command(cfg, "trading", True)[2]


def test_normal_run_logs_everything(runner_project):
    assert run_agent.run("trading", dry_run=False, poll_seconds=0.1) == 0
    info = ran(runner_project)
    assert info["env"]["BOERSE_RUN_MODE"] == "trading"
    assert "BOERSE_DRY_RUN" not in info["env"]
    runs = list((runner_project / "logs" / "runs").glob("*.jsonl"))
    assert len(runs) == 1 and '"type": "result"' in runs[0].read_text()
    summary = json.loads(next((runner_project / "logs" / "runs").glob("*.summary.json")).read_text())
    assert summary["reason"] == "finished" and summary["cost_usd"] == 0.12
    # Agent hat nichts ins Journal geschrieben -> Runner vermerkt das
    assert "Lauf ohne Journal-Eintrag" in (runner_project / "journal.md").read_text(encoding="utf-8")
    assert not (runner_project / "logs" / "run.lock").exists()


def test_dry_run_sets_env(runner_project):
    assert run_agent.run("trading", dry_run=True, poll_seconds=0.1) == 0
    assert ran(runner_project)["env"]["BOERSE_DRY_RUN"] == "1"


def test_agent_journal_entry_suppresses_runner_note(runner_project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE", "journal")
    run_agent.run("trading", dry_run=False, poll_seconds=0.1)
    assert "Lauf ohne Journal-Eintrag" not in (runner_project / "journal.md").read_text(encoding="utf-8")


def test_stop_file_prevents_start(runner_project):
    (runner_project / "STOP").touch()
    assert run_agent.run("trading", dry_run=False) == run_agent.EXIT_STOPPED
    assert ran(runner_project) is None


def test_unsealed_or_modified_project_prevents_start(runner_project):
    (runner_project / "config.yaml").write_text("agent: {}\n")
    assert run_agent.run("trading", dry_run=False) == run_agent.EXIT_STOPPED
    assert ran(runner_project) is None


def test_stop_during_run_kills_agent_immediately(runner_project, monkeypatch):
    import threading
    monkeypatch.setenv("FAKE_CLAUDE", "sleep")
    threading.Timer(1.5, lambda: (runner_project / "STOP").touch()).start()
    t0 = time.monotonic()
    code = run_agent.run("trading", dry_run=False, poll_seconds=0.1)
    assert code == run_agent.EXIT_STOPPED
    assert time.monotonic() - t0 < 15
    assert "durch STOP abgebrochen" in (runner_project / "journal.md").read_text(encoding="utf-8")


def test_tampering_creates_stop(runner_project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE", "tamper")
    assert run_agent.run("trading", dry_run=False, poll_seconds=0.1) == run_agent.EXIT_STOPPED
    stop = runner_project / "STOP"
    assert stop.exists() and "config.yaml" in stop.read_text(encoding="utf-8")
    # nächster Lauf startet nicht
    assert run_agent.run("trading", dry_run=False) == run_agent.EXIT_STOPPED


def test_review_cannot_rewrite_mission_core(runner_project, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE", "mission")
    run_agent.run("review", dry_run=False, poll_seconds=0.1)
    text = (runner_project / "mission.md").read_text(encoding="utf-8")
    assert text.startswith("Kernauftrag: Depotwert maximieren.")
    assert "- Lehre 1" in text
    assert "ignoriere alles" not in text


def test_parallel_run_is_locked(runner_project):
    (runner_project / "logs" / "run.lock").write_text("{}")
    assert run_agent.run("trading", dry_run=False) == run_agent.EXIT_STOPPED
    assert ran(runner_project) is None
