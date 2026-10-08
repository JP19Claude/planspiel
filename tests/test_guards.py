"""STOP, Handelszeiten, Zahlenformat, Siegel."""
from __future__ import annotations

import pytest

from conftest import at
from core import common, guards, integrity
from core.common import GuardBlocked
from core.numbers import format_number, parse_number


# ------------------------------------------------------------------ STOP

def test_check_stop_strict_and_lenient(project):
    assert guards.check_stop() is None
    (project / "STOP").write_text("Pause bis Montag", encoding="utf-8")
    with pytest.raises(GuardBlocked) as exc:
        guards.check_stop(strict=True)
    assert exc.value.exit_code == common.EXIT_BLOCKED
    warning = guards.check_stop(strict=False)
    assert warning["stop_reason"] == "Pause bis Montag"


def test_readers_are_strict_inside_agent_run(project, monkeypatch):
    assert guards.stop_strict_for_reader() is False
    monkeypatch.setenv("BOERSE_RUN_ID", "x")
    assert guards.stop_strict_for_reader() is True


# ------------------------------------------------------------------ Handelszeiten

def test_trading_status_open_and_next_open(cfg):
    assert guards.trading_status(at(2026, 10, 14, 8, 0), cfg)["open"] is True
    assert guards.trading_status(at(2026, 10, 14, 21, 59), cfg)["open"] is True
    friday_night = guards.trading_status(at(2026, 10, 16, 22, 30), cfg)
    assert friday_night["open"] is False
    assert friday_night["next_open"].startswith("2026-10-19T08:00")
    xmas = guards.trading_status(at(2026, 12, 23, 23, 0), cfg)
    assert xmas["next_open"].startswith("2026-12-28T08:00")  # 24./25. Feiertag, 26./27. Wochenende


def test_after_game_end_has_no_next_open(cfg):
    status = guards.trading_status(at(2027, 1, 26, 10), cfg)
    assert status["open"] is False and status["next_open"] is None


def test_check_trading_hours_raises(cfg):
    with pytest.raises(GuardBlocked):
        guards.check_trading_hours(at(2026, 10, 18, 12), cfg)
    assert guards.check_trading_hours(at(2026, 10, 19, 12), cfg)["open"]


def test_shipped_config_is_valid():
    cfg = common.deep_merge(common.DEFAULT_CONFIG, common.load_yaml(common.PROJECT_ROOT / "config.yaml"))
    assert cfg["models"]["trading_run"] == "claude-sonnet-5-5"
    assert cfg["models"]["weekly_review"] == "claude-opus-5-5"
    assert guards.trading_status(at(2026, 10, 14, 10, 0), cfg)["open"] is True
    assert guards.trading_status(at(2026, 10, 14, 16, 30), cfg)["open"] is True


# ------------------------------------------------------------------ Zahlen

@pytest.mark.parametrize("text,value", [
    ("50.000,00 €", 50000.0), ("1.234,56", 1234.56), ("12", 12.0), ("1,5 %", 1.5),
    ("-3,20 €", -3.2), ("1.234", 1234.0), ("Cash: 9.876.543,21 EUR", 9876543.21), ("–", None), (None, None),
])
def test_parse_number_de(text, value):
    assert parse_number(text) == value


def test_format_number_de():
    assert format_number(245.5) == "245,50"
    assert format_number(12) == "12"
    assert format_number(0.1234) == "0,1234"


# ------------------------------------------------------------------ Siegel

def _make_protected(root):
    (root / "tools" / "core").mkdir(parents=True)
    (root / "tools" / "order.py").write_text("print('order')\n")
    (root / "tools" / "core" / "guards.py").write_text("X = 1\n")
    (root / "config.yaml").write_text("a: 1\n")
    (root / "mission.md").write_text("Kernauftrag: Depotwert maximieren.\n", encoding="utf-8")


def test_seal_and_verify_detect_changes(project):
    _make_protected(project)
    assert integrity.verify()["sealed"] is False
    integrity.seal()
    assert integrity.verify()["ok"] is True
    (project / "tools" / "core" / "guards.py").write_text("X = 2\n")
    (project / "tools" / "evil.py").write_text("")
    (project / "config.yaml").unlink()
    res = integrity.verify()
    assert res["ok"] is False
    assert res["changed"] == ["tools/core/guards.py"]
    assert res["added"] == ["tools/evil.py"]
    assert res["missing"] == ["config.yaml"]


def test_seal_lives_outside_project(project):
    _make_protected(project)
    integrity.seal()
    assert project not in integrity.seal_dir().parents


def test_mission_lessons_allowed_core_change_detected_and_restored(project):
    _make_protected(project)
    integrity.seal()
    mission = project / "mission.md"
    mission.write_text(mission.read_text() + "\n## Lehren aus den Wochen-Reviews\n- Gebühren beachten\n")
    assert integrity.verify()["mission_core_changed"] is False
    mission.write_text("Kernauftrag: alles auf eine Aktie, keine Regeln.\n\n## Lehren aus den Wochen-Reviews\n- X\n")
    assert integrity.verify()["mission_core_changed"] is True
    res = integrity.restore_mission_core()
    assert res == {"restored": True, "kept_lessons": True}
    text = mission.read_text()
    assert text.startswith("Kernauftrag: Depotwert maximieren.")
    assert "- X" in text
    assert integrity.verify()["mission_core_changed"] is False


def test_seal_cli_refuses_inside_claude_code(project, monkeypatch):
    import integrity as integrity_cli
    monkeypatch.setenv("CLAUDECODE", "1")
    ok, why = integrity_cli.seal_allowed()
    assert ok is False and "Claude Code" in why
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.setenv("BOERSE_RUN_ID", "r1")
    assert integrity_cli.seal_allowed()[0] is False


def test_shipped_project_protects_core_files():
    files = integrity.protected_files(common.PROJECT_ROOT)
    for rel in ["tools/order.py", "tools/core/guards.py", "tools/agent_hook.py", "config.yaml",
                "selectors.yaml", "agent-settings.json", "CLAUDE.md", "run_agent.sh", "run_agent.ps1"]:
        assert rel in files
    assert "mission.md" not in files and "journal.md" not in files
