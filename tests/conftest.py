from __future__ import annotations

import contextlib
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from core import common, integrity  # noqa: E402
from core.common import LoginRequired, PageStateError  # noqa: E402
from core.site import Selectors  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")


def at(y, m, d, hh=11, mm=0, ss=0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, ss, tzinfo=BERLIN)


# Mittwoch, 14.10.2026, 11:00 – mitten in der Handelszeit
TRADING_TIME = at(2026, 10, 14, 11, 0)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Leerer Projektordner im tmp, Siegel ebenfalls im tmp."""
    root = tmp_path / "proj"
    (root / "logs").mkdir(parents=True)
    monkeypatch.setattr(common, "paths", common.Paths(root))
    monkeypatch.setattr(integrity, "SEAL_BASE", tmp_path / "seal")
    for var in ("BOERSE_RUN_ID", "BOERSE_RUN_MODE", "BOERSE_DRY_RUN", "CLAUDECODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def sealed(project):
    (project / "config.yaml").write_text("models: {}\n", encoding="utf-8")
    (project / "mission.md").write_text("Kernauftrag.\n", encoding="utf-8")
    integrity.seal(project)
    return project


@pytest.fixture
def cfg():
    return common.deep_merge(common.DEFAULT_CONFIG, {
        "game": {
            "start": dt.date(2026, 10, 1),
            "end": dt.date(2027, 1, 25),
            "trading_hours": {"days": ["mon", "tue", "wed", "thu", "fri"], "open": "08:00", "close": "22:00"},
            "holidays": [dt.date(2026, 12, 24), dt.date(2026, 12, 25)],
        },
        "order": {"verify_attempts": 3, "verify_wait_seconds": 0},
    })


@pytest.fixture
def sel():
    return Selectors({
        "confirmed": True,
        "order_columns": {"security": "Wertpapier", "side": "Art", "quantity": "Stück"},
        "side_labels": {"buy": ["Kauf"], "sell": ["Verkauf"]},
    })


HEADERS = ["Wertpapier", "Art", "Stück", "Status"]


class FakeSite:
    """Gemockte Spielseite. Protokolliert alle Schritte in self.calls."""

    def __init__(self, *, logged_in=True, identity="SAP SE | WKN 716460 | ISIN DE0007164600",
                 history=None, add_order_on_submit=True, outcome=None, fail_at=None, fail_exc=None,
                 on=None, headers=None, table_name="SAP SE"):
        self.logged_in = logged_in
        self.identity = identity
        self.history = list(history or [])
        self.open: list[dict] = []
        self.add_order_on_submit = add_order_on_submit
        self.outcome = outcome or {"success": True, "message": "Ihre Order wurde erteilt"}
        self.fail_at = fail_at
        self.fail_exc = fail_exc
        self.on = on or {}
        self.headers = headers or HEADERS
        self.table_name = table_name
        self.calls: list[str] = []
        self.submitted = 0
        self.filled = None

    def _step(self, name):
        self.calls.append(name)
        if name in self.on:
            self.on[name]()
        if self.fail_at == name:
            raise self.fail_exc or PageStateError(f"Element für '{name}' nicht gefunden")

    def ensure_logged_in(self):
        self._step("login")
        if not self.logged_in:
            raise LoginRequired("nicht eingeloggt")

    def read_orders(self):
        self._step("orders")
        return {"open": [dict(r) for r in self.open], "history": [dict(r) for r in self.history],
                "open_headers": self.headers, "history_headers": self.headers}

    def read_portfolio(self):
        return {}

    def open_order_form(self, symbol):
        self._step("open")
        return self.identity

    def fill_order(self, side, qty, limit):
        self._step("fill")
        self.filled = (side, qty, limit)

    def submit_order(self):
        self._step("submit")
        self.submitted += 1
        if self.add_order_on_submit:
            side, qty, limit = self.filled
            self.open.append({"Wertpapier": self.table_name, "Art": "Kauf" if side == "buy" else "Verkauf",
                              "Stück": str(qty), "Status": "offen"})

    def read_submit_outcome(self):
        self._step("outcome")
        return self.outcome

    def abandon_order(self):
        self._step("abandon")

    def screenshot(self, label):
        self.calls.append(f"shot:{label}")
        target = common.paths.screenshots / f"{label}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"png")
        return str(target.relative_to(common.paths.root))


def factory_for(site):
    return lambda: contextlib.nullcontext(site)


def forbidden_factory():
    raise AssertionError("Browser hätte gar nicht geöffnet werden dürfen")
