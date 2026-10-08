from __future__ import annotations

import journal
from core import common


def test_append_and_tail(project, monkeypatch):
    journal.append("Erster Lauf", "**Was:** nichts\n**Warum:** Markt unklar")
    monkeypatch.setenv("BOERSE_RUN_MODE", "trading")
    monkeypatch.setenv("BOERSE_RUN_ID", "r42")
    journal.append("Kauf SAP", "Was: 10 SAP. Warum: Zahlen. Lehre: Limit nutzen.")
    text = common.paths.journal.read_text(encoding="utf-8")
    assert text.startswith("# Journal")
    assert "· Handelslauf · Kauf SAP" in text
    assert "<!-- run_id: r42 -->" in text
    res = journal.tail(1)
    assert res["total"] == 2
    assert res["entries"][0]["header"].endswith("Kauf SAP")
    assert "Limit nutzen" in res["entries"][0]["body"]


def test_dry_run_does_not_write(project):
    res = journal.append("Test", "Inhalt", dry_run=True)
    assert res["written"] is False
    assert not common.paths.journal.exists()


def test_testlauf_marker(project, monkeypatch):
    monkeypatch.setenv("BOERSE_DRY_RUN", "1")
    journal.append("Probe", "x")
    assert "TESTLAUF" in common.paths.journal.read_text(encoding="utf-8")


def test_cli_add_from_stdin(project, monkeypatch, capsys):
    import io
    import json
    monkeypatch.setattr("sys.stdin", io.StringIO("Zeile 1\nKurs > 5 %\n"))
    code = common.run_cli("journal", journal.build_parser(), journal.handler, ["add", "--title", "Stdin"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["written"] is True
    assert "Kurs > 5 %" in common.paths.journal.read_text(encoding="utf-8")
    code = common.run_cli("journal", journal.build_parser(), journal.handler, ["tail", "--n", "3"])
    assert json.loads(capsys.readouterr().out)["total"] == 1


def test_cli_add_dry_run_flag(project, capsys):
    import json
    code = common.run_cli("journal", journal.build_parser(), journal.handler,
                          ["add", "--title", "T", "--text", "x", "--dry-run"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["dry_run"] is True and not common.paths.journal.exists()


def test_cli_stop_blocks_writes_in_agent_run(project, monkeypatch, capsys):
    import json
    (project / "STOP").touch()
    monkeypatch.setenv("BOERSE_RUN_ID", "r1")
    code = common.run_cli("journal", journal.build_parser(), journal.handler, ["add", "--title", "T", "--text", "x"])
    out = json.loads(capsys.readouterr().out)
    assert code == common.EXIT_BLOCKED and out["error"]["code"] == "blocked"


def test_agent_test_run_still_writes_marked_entries(project, monkeypatch, capsys):
    import json
    monkeypatch.setenv("BOERSE_DRY_RUN", "1")
    code = common.run_cli("journal", journal.build_parser(), journal.handler, ["add", "--title", "T", "--text", "x"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["written"] is True
    assert "TESTLAUF" in common.paths.journal.read_text(encoding="utf-8")
