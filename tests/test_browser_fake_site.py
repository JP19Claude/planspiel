"""Echter Chromium gegen eine lokale Fake-Spielseite (tests/fake_site).

Prüft die Playwright-Schicht (Selektoren, Tabellen lesen, Formular füllen,
Absenden, Verifizieren) ohne die echte Planspiel-Website.
"""
from __future__ import annotations

import contextlib
import functools
import http.server
import threading
from pathlib import Path

import pytest

from conftest import TRADING_TIME
from core import common, integrity
from core.common import PageStateError
from core.orderflow import OrderRequest, execute_order
from core.site import PlaywrightSite, Selectors, browser_page, save_state

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

SITE_DIR = Path(__file__).with_name("fake_site")


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def env(project, server, cfg):
    cfg = common.deep_merge(cfg, {"game": {"base_url": server},
                                  "browser": {"timeout_ms": 5000, "storage_state": ".auth/state.json"},
                                  "order": {"verify_attempts": 2, "verify_wait_seconds": 0.2}})
    sel = Selectors.load(SITE_DIR / "selectors.yaml")
    (project / "config.yaml").write_text("x: 1\n")
    integrity.seal(project)
    try:
        with browser_page(cfg) as (context, page):
            site = PlaywrightSite(page, sel, cfg, label="login")
            assert site.login("tester", "geheim") == "ok"
            save_state(context, cfg)
    except Exception as exc:  # pragma: no cover - kein Chromium installiert
        if "Executable doesn't exist" in str(exc):
            pytest.skip("Chromium nicht installiert (python -m playwright install chromium)")
        raise
    return cfg, sel


def factory(cfg, sel):
    @contextlib.contextmanager
    def make():
        with browser_page(cfg) as (context, page):
            yield PlaywrightSite(page, sel, cfg, label="test")
            save_state(context, cfg)
    return make


def portfolio(cfg, sel):
    with browser_page(cfg) as (_c, page):
        site = PlaywrightSite(page, sel, cfg)
        site.ensure_logged_in()
        return site.read_portfolio(), site.read_orders()


def order(cfg, sel, req, dry_run=False):
    return execute_order(req, cfg=cfg, sel=sel, dry_run=dry_run, site_factory=factory(cfg, sel),
                         now_fn=lambda: TRADING_TIME)


def test_login_outcomes(env):
    cfg, sel = env
    with browser_page(cfg, use_state=False) as (_c, page):
        site = PlaywrightSite(page, sel, cfg)
        assert site.login("captcha", "x") == "captcha"
        assert site.login("tester", "falsch") == "error"


def test_read_empty_depot(env):
    depot, orders = portfolio(*env)
    assert depot["cash"]["value"] == 50000.0
    assert depot["positions"] == []
    assert depot["positions_note"] == "Keine Positionen"
    assert orders["open"] == [] and orders["history"] == []


def test_market_buy_end_to_end(env):
    cfg, sel = env
    res = order(cfg, sel, OrderRequest("DE0007164600", 10, "buy"))
    assert res["status"] == "placed", res
    assert res["verified"]["section"] == "history"
    assert res["security"].startswith("SAP SE")
    for shot in res["screenshots"]:
        assert (common.paths.root / shot).stat().st_size > 1000
    depot, _ = portfolio(cfg, sel)
    assert depot["positions"][0]["Wertpapier"] == "SAP SE"
    assert depot["positions"][0]["Stück"] == "10"
    assert depot["cash"]["value"] == 47600.0


def test_limit_sell_lands_in_open_orders(env):
    cfg, sel = env
    res = order(cfg, sel, OrderRequest("716460", 3, "sell", 255.5))
    assert res["status"] == "placed", res
    assert res["verified"]["section"] == "open"
    assert res["verified"]["row"]["Limit"] == "255,50"


def test_dry_run_does_not_place(env):
    cfg, sel = env
    res = order(cfg, sel, OrderRequest("DE0007164600", 1, "buy"), dry_run=True)
    assert res["status"] == "dry_run"
    _, orders = portfolio(cfg, sel)
    assert orders["open"] == [] and orders["history"] == []


def test_ambiguous_search_aborts(env):
    cfg, sel = env
    with pytest.raises(PageStateError) as exc:
        order(cfg, sel, OrderRequest("Siemens", 1, "buy"))
    assert len(exc.value.details["candidates"]) == 2
    _, orders = portfolio(cfg, sel)
    assert orders["history"] == []


def test_site_rejection_is_reported(env):
    cfg, sel = env
    res = order(cfg, sel, OrderRequest("DE0007164600", 1000, "buy"))
    assert res["status"] == "rejected"
    assert "Liquidität" in res["message"]


def test_expired_session_is_detected(env):
    cfg, sel = env
    common.resolve(cfg["browser"]["storage_state"]).unlink()
    with pytest.raises(common.LoginRequired):
        order(cfg, sel, OrderRequest("DE0007164600", 1, "buy"))


def test_unreachable_site_is_page_state(env):
    cfg, sel = env
    cfg = common.deep_merge(cfg, {"game": {"base_url": "http://127.0.0.1:9"}})
    with browser_page(cfg) as (_c, page):
        site = PlaywrightSite(page, sel, cfg)
        with pytest.raises(PageStateError) as exc:
            site.ensure_logged_in()
    assert "nicht erreichbar" in exc.value.message
