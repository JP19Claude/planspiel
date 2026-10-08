"""JSON-Ausgabe und Exit-Codes der Kommandozeilen-Werkzeuge (ohne Netz)."""
from __future__ import annotations

import json
import types

import pandas as pd
import pytest

import order
import quotes
from core import common


def cli(capsys, module, name, argv):
    code = common.run_cli(name, module.build_parser(), module.handler, argv)
    return code, json.loads(capsys.readouterr().out)


def test_order_cli_stop_returns_json_and_exit_2(project, capsys):
    (project / "STOP").write_text("Halt", encoding="utf-8")
    code, out = cli(capsys, order, "order", ["--symbol", "SAP", "--qty", "1", "--side", "buy"])
    assert code == 2
    assert out["ok"] is False and out["error"]["guard"] == "stop"
    log = common.paths.actions_log.read_text(encoding="utf-8")
    assert '"tool": "order"' in log and '"event": "end"' in log


def test_order_cli_bad_qty(project, capsys):
    code, out = cli(capsys, order, "order", ["--symbol", "SAP", "--qty", "0", "--side", "buy"])
    assert code == 1 and "qty" in out["error"]["message"]


def test_order_cli_dry_run_env_forces_dry_run(project, capsys, monkeypatch):
    monkeypatch.setenv("BOERSE_DRY_RUN", "1")
    (project / "STOP").touch()
    _, out = cli(capsys, order, "order", ["--symbol", "SAP", "--qty", "1", "--side", "buy"])
    assert out["dry_run"] is True


# ------------------------------------------------------------------ quotes (yfinance gemockt)

class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol
        self.fast_info = types.SimpleNamespace(last_price=110.0, previous_close=100.0, currency="EUR", open=101.0,
                                               day_high=111.0, day_low=99.0, last_volume=1000, year_high=120.0,
                                               year_low=80.0, fifty_day_average=105.0,
                                               two_hundred_day_average=95.0, market_cap=float("nan"))
        self.info = {"longName": "Test AG", "trailingPE": 15.2, "sector": "Tech"}
        self.calendar = {}
        self.news = [{"content": {"title": "Test AG hebt Prognose", "provider": {"displayName": "dpa"},
                                  "pubDate": "2026-10-08", "canonicalUrl": {"url": "https://example.com"}}}]

    def history(self, period, interval, auto_adjust):
        idx = pd.date_range("2026-01-01", periods=250, freq="B")
        close = [100 + i * 0.1 for i in range(250)]
        return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": [1] * 250},
                            index=idx)


class FakeYF:
    Ticker = FakeTicker

    class Search:
        def __init__(self, query, max_results, news_count):
            self.quotes = [{"symbol": "SAP.DE", "longname": "SAP SE", "exchange": "GER", "quoteType": "EQUITY"}]


@pytest.fixture
def fake_yf(monkeypatch):
    monkeypatch.setattr(quotes, "_yf", lambda: FakeYF)


def test_quotes_snapshot(project, capsys, fake_yf):
    code, out = cli(capsys, quotes, "quotes", ["TEST.DE"])
    assert code == 0
    q = out["quotes"][0]
    assert q["last"] == 110.0 and q["change_pct"] == 10.0
    assert q["market_cap"] is None  # NaN -> null


def test_quotes_history_info_news_search(project, capsys, fake_yf):
    code, out = cli(capsys, quotes, "quotes", ["TEST.DE", "--history", "1y", "--info", "--news", "--rows", "3",
                                               "--search", "DE0007164600"])
    assert code == 0
    entry = out["quotes"][0]
    assert len(entry["recent"]) == 3
    stats = entry["stats"]
    assert stats["rsi14"] == 100.0 and stats["max_drawdown_pct"] == 0.0
    assert stats["sma200"] is not None and stats["return_1m_pct"] > 0
    assert entry["info"]["longName"] == "Test AG"
    assert entry["news"][0]["publisher"] == "dpa"
    assert out["search"]["results"][0]["symbol"] == "SAP.DE"


def test_quotes_requires_symbol(project, capsys, fake_yf):
    code, out = cli(capsys, quotes, "quotes", [])
    assert code == 1 and out["ok"] is False
