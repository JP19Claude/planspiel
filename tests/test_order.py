"""Order-Logik und Abbruchbedingungen mit gemockter Seite."""
from __future__ import annotations

import pytest

from conftest import TRADING_TIME, FakeSite, at, factory_for, forbidden_factory
from core import common, integrity
from core.common import GuardBlocked, LoginRequired, PageStateError, ToolError
from core.orderflow import OrderRequest, execute_order, side_of


def run(req, site, cfg, sel, *, dry_run=False, now=TRADING_TIME, factory=None, sleeps=None):
    times = now if callable(now) else (lambda: now)
    return execute_order(req, cfg=cfg, sel=sel, dry_run=dry_run, site_factory=factory or factory_for(site),
                         now_fn=times, sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


BUY = OrderRequest("DE0007164600", 10, "buy")


# ------------------------------------------------------------------ Erfolg

def test_market_buy_is_placed_and_verified(sealed, cfg, sel):
    site = FakeSite()
    res = run(BUY, site, cfg, sel)
    assert res["status"] == "placed"
    assert res["exit_code"] == common.EXIT_OK
    assert site.submitted == 1
    assert res["verified"]["section"] == "open"
    labels = [c for c in site.calls if c.startswith("shot:")]
    assert labels == ["shot:vorher", "shot:nachher", "shot:orderuebersicht"]
    for path in res["screenshots"]:
        assert (common.paths.root / path).exists()
    assert site.calls.index("shot:vorher") < site.calls.index("submit") < site.calls.index("shot:nachher")


def test_limit_sell_passes_limit_and_matches_sell_row(sealed, cfg, sel):
    site = FakeSite()
    res = run(OrderRequest("DE0007164600", 5, "sell", 245.5), site, cfg, sel)
    assert site.filled == ("sell", 5, 245.5)
    assert res["status"] == "placed"
    assert res["verified"]["row"]["Art"] == "Verkauf"


def test_table_with_name_only_matches_via_form_identity(sealed, cfg, sel):
    # Agent sucht per ISIN, die Übersicht zeigt nur "SAP SE"
    site = FakeSite(table_name="SAP SE")
    assert run(BUY, site, cfg, sel)["status"] == "placed"


def test_side_of_distinguishes_verkauf_from_kauf():
    labels = {"buy": ["Kauf"], "sell": ["Verkauf"]}
    assert side_of("Verkauf", labels) == "sell"
    assert side_of("Kauf", labels) == "buy"
    assert side_of("Limit-Kauf", labels) == "buy"
    assert side_of("Storno", labels) is None


# ------------------------------------------------------------------ STOP

def test_stop_file_blocks_before_browser(sealed, cfg, sel):
    (sealed / "STOP").write_text("Urlaub", encoding="utf-8")
    with pytest.raises(GuardBlocked) as exc:
        run(BUY, None, cfg, sel, factory=forbidden_factory)
    assert exc.value.details["guard"] == "stop"
    assert exc.value.details["stop_reason"] == "Urlaub"


def test_stop_file_blocks_even_in_dry_run(sealed, cfg, sel):
    (sealed / "STOP").touch()
    with pytest.raises(GuardBlocked):
        run(BUY, None, cfg, sel, dry_run=True, factory=forbidden_factory)


def test_stop_created_during_order_aborts_before_submit(sealed, cfg, sel):
    site = FakeSite(on={"fill": lambda: (sealed / "STOP").touch()})
    with pytest.raises(GuardBlocked):
        run(BUY, site, cfg, sel)
    assert site.submitted == 0
    assert "submit" not in site.calls


# ------------------------------------------------------------------ Handelszeiten

@pytest.mark.parametrize("now,reason", [
    (at(2026, 10, 17, 11), "kein Handelstag"),        # Samstag
    (at(2026, 10, 18, 11), "kein Handelstag"),        # Sonntag
    (at(2026, 10, 14, 7, 59), "außerhalb"),            # vor Öffnung
    (at(2026, 10, 14, 22, 0), "außerhalb"),            # Schluss
    (at(2026, 12, 24, 11), "handelsfreier Tag"),      # Feiertag
    (at(2026, 9, 30, 11), "beginnt erst"),            # vor Spielstart
    (at(2027, 1, 26, 11), "beendet"),                 # nach Spielende
])
def test_outside_trading_hours_blocks_before_browser(sealed, cfg, sel, now, reason):
    with pytest.raises(GuardBlocked) as exc:
        run(BUY, None, cfg, sel, now=now, factory=forbidden_factory)
    assert exc.value.details["guard"] == "trading_hours"
    assert reason in exc.value.message


def test_trading_hours_rechecked_right_before_submit(sealed, cfg, sel):
    times = iter([at(2026, 10, 14, 21, 59, 50), at(2026, 10, 14, 22, 0, 1)])
    site = FakeSite()
    with pytest.raises(GuardBlocked):
        run(BUY, site, cfg, sel, now=lambda: next(times))
    assert site.submitted == 0


def test_utc_time_is_converted_to_berlin(sealed, cfg, sel):
    import datetime as dt
    # 20:30 UTC = 22:30 Berlin (Sommerzeit) -> geschlossen
    late = dt.datetime(2026, 10, 14, 20, 30, tzinfo=dt.timezone.utc)
    with pytest.raises(GuardBlocked):
        run(BUY, None, cfg, sel, now=late, factory=forbidden_factory)


# ------------------------------------------------------------------ Testmodus

def test_dry_run_fills_form_but_never_submits(sealed, cfg, sel):
    site = FakeSite()
    res = run(BUY, site, cfg, sel, dry_run=True)
    assert res["status"] == "dry_run"
    assert site.submitted == 0
    assert "abandon" in site.calls
    assert "shot:vorher" in site.calls


def test_dry_run_outside_hours_only_warns(sealed, cfg, sel):
    site = FakeSite()
    res = run(BUY, site, cfg, sel, dry_run=True, now=at(2026, 10, 17, 11))
    assert res["status"] == "dry_run"
    assert any("Handelszeit" in w for w in res["warnings"])
    assert site.submitted == 0


# ------------------------------------------------------------------ Seitenzustand

def test_wrong_security_in_form_aborts(sealed, cfg, sel):
    site = FakeSite(identity="Siemens AG | WKN 723610 | ISIN DE0007236101")
    with pytest.raises(PageStateError) as exc:
        run(BUY, site, cfg, sel)
    assert "anderes Wertpapier" in exc.value.message
    assert site.submitted == 0


def test_missing_element_aborts_with_screenshot(sealed, cfg, sel):
    site = FakeSite(fail_at="fill")
    with pytest.raises(PageStateError) as exc:
        run(BUY, site, cfg, sel)
    assert site.submitted == 0
    assert "shot:abbruch" in site.calls
    assert exc.value.details["screenshots"]


def test_unexpected_exception_before_submit_is_page_state(sealed, cfg, sel):
    site = FakeSite(fail_at="open", fail_exc=RuntimeError("Timeout 15000ms"))
    with pytest.raises(PageStateError) as exc:
        run(BUY, site, cfg, sel)
    assert exc.value.exit_code == common.EXIT_PAGE_STATE
    assert site.submitted == 0


def test_order_table_columns_must_match_before_submit(sealed, cfg, sel):
    site = FakeSite(headers=["Name", "Typ", "Anzahl"])
    with pytest.raises(PageStateError):
        run(BUY, site, cfg, sel)
    assert site.submitted == 0


def test_not_logged_in_aborts(sealed, cfg, sel):
    site = FakeSite(logged_in=False)
    with pytest.raises(LoginRequired):
        run(BUY, site, cfg, sel)
    assert site.submitted == 0


# ------------------------------------------------------------------ nach dem Absenden

def test_rejected_by_website(sealed, cfg, sel):
    site = FakeSite(outcome={"success": False, "message": "Nicht genügend Liquidität"},
                    add_order_on_submit=False)
    res = run(BUY, site, cfg, sel)
    assert res["status"] == "rejected"
    assert res["exit_code"] == common.EXIT_REJECTED
    assert "Liquidität" in res["message"]
    assert site.submitted == 1


def test_order_missing_in_overview_is_unverified(sealed, cfg, sel):
    site = FakeSite(add_order_on_submit=False)
    sleeps = []
    res = run(BUY, site, cfg, sel, sleeps=sleeps)
    assert res["status"] == "unverified"
    assert res["exit_code"] == common.EXIT_UNVERIFIED
    assert site.calls.count("orders") == 1 + cfg["order"]["verify_attempts"]
    assert len(sleeps) == cfg["order"]["verify_attempts"] - 1
    assert site.submitted == 1  # niemals automatisch wiederholt


def test_error_after_submit_is_unklar_and_not_retried(sealed, cfg, sel):
    site = FakeSite(fail_at="outcome")
    res = run(BUY, site, cfg, sel)
    assert res["status"] == "unklar"
    assert res["exit_code"] == common.EXIT_UNVERIFIED
    assert site.submitted == 1


def test_identical_old_order_is_not_mistaken_for_new_one(sealed, cfg, sel):
    old = {"Wertpapier": "SAP SE", "Art": "Kauf", "Stück": "10", "Status": "offen"}
    site = FakeSite(history=[], add_order_on_submit=False)
    site.open.append(dict(old))
    assert run(BUY, site, cfg, sel)["status"] == "unverified"
    site2 = FakeSite()
    site2.open.append(dict(old))  # gleiche alte Order + neue identische -> zwei Zeilen
    assert run(BUY, site2, cfg, sel)["status"] == "placed"


# ------------------------------------------------------------------ Eingaben & Konfiguration

@pytest.mark.parametrize("req", [
    OrderRequest("SAP", 0, "buy"),
    OrderRequest("SAP", -3, "buy"),
    OrderRequest("SAP", 1, "hold"),
    OrderRequest("SAP", 1, "buy", 0),
    OrderRequest("SAP", 1, "buy", -5.0),
    OrderRequest(" ", 1, "buy"),
])
def test_invalid_arguments_rejected_before_browser(sealed, cfg, sel, req):
    with pytest.raises(ToolError):
        run(req, None, cfg, sel, factory=forbidden_factory)


def test_unconfirmed_selectors_block_live_orders(sealed, cfg, sel):
    sel.data["confirmed"] = False
    with pytest.raises(GuardBlocked) as exc:
        run(BUY, None, cfg, sel, factory=forbidden_factory)
    assert exc.value.details["guard"] == "selectors"
    res = run(BUY, FakeSite(), cfg, sel, dry_run=True)
    assert res["status"] == "dry_run"


def test_tampered_protected_file_blocks_live_orders(sealed, cfg, sel):
    (sealed / "config.yaml").write_text("game: {trading_hours: {open: '00:00', close: '23:59'}}\n")
    with pytest.raises(GuardBlocked) as exc:
        run(BUY, None, cfg, sel, factory=forbidden_factory)
    assert exc.value.details["guard"] == "integrity"
    assert "config.yaml" in exc.value.details["integrity"]["changed"]


def test_unsealed_project_blocks_live_orders(project, cfg, sel):
    with pytest.raises(GuardBlocked):
        run(BUY, None, cfg, sel, factory=forbidden_factory)


def test_all_steps_are_logged(sealed, cfg, sel):
    run(BUY, FakeSite(), cfg, sel)
    log = common.paths.actions_log.read_text(encoding="utf-8")
    assert '"event": "preflight_ok"' in log
    assert '"event": "submit"' in log
    assert integrity.verify()["ok"]
