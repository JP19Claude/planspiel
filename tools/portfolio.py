"""Depot, Cash, offene Orders und Orderhistorie von der Website lesen.

    python tools/portfolio.py                 # alles
    python tools/portfolio.py --section depot # nur Depot + Cash
    python tools/portfolio.py --section orders
    python tools/portfolio.py --history       # Verlauf der gespeicherten Depotstände (logs/)

Die Website ist die Wahrheit: Es wird nichts geschätzt oder zwischengespeichert.
Jeder erfolgreiche Lauf hängt einen Schnappschuss an logs/portfolio_history.jsonl an.
"""
from __future__ import annotations

import argparse
import json
import sys

from core import common, guards
from core.site import PlaywrightSite, Selectors, browser_page, save_state


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Depot und Orders aus dem Planspiel lesen")
    p.add_argument("--section", choices=["all", "depot", "orders"], default="all")
    p.add_argument("--screenshot", action="store_true", help="Screenshot der gelesenen Seiten speichern")
    p.add_argument("--history", action="store_true", help="gespeicherte Depotstände ausgeben statt Website lesen")
    p.add_argument("--headed", action="store_true", help="Browser sichtbar öffnen")
    return p


def read_history(limit: int = 200) -> dict:
    f = common.paths.portfolio_history
    if not f.exists():
        return {"snapshots": [], "message": "noch keine Schnappschüsse"}
    lines = f.read_text(encoding="utf-8").splitlines()[-limit:]
    snaps = []
    for line in lines:
        try:
            snaps.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    cfg = common.load_config()
    start_capital = cfg["game"].get("start_capital")
    summary = {}
    values = [s.get("total_value") for s in snaps if isinstance(s.get("total_value"), (int, float))]
    if values:
        summary = {"first": values[0], "last": values[-1], "max": max(values), "min": min(values)}
        if start_capital:
            summary["return_vs_start_pct"] = round((values[-1] / float(start_capital) - 1) * 100, 2)
    return {"snapshots": snaps, "summary": summary, "start_capital": start_capital}


def snapshot(data: dict) -> None:
    depot = data.get("depot") or {}
    snap = {
        "ts": common.now(common.load_config()).isoformat(timespec="seconds"),
        "run_id": common.run_id(),
        "cash": (depot.get("cash") or {}).get("value"),
        "total_value": (depot.get("total_value") or {}).get("value"),
        "depot_value": (depot.get("depot_value") or {}).get("value"),
        "positions": depot.get("positions"),
    }
    common.paths.logs.mkdir(parents=True, exist_ok=True)
    with common.paths.portfolio_history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(common.clean_json(snap), ensure_ascii=False) + "\n")


def handler(args: argparse.Namespace, dry_run: bool) -> dict:
    warning = guards.check_stop(strict=guards.stop_strict_for_reader())
    if args.history:
        return read_history()
    cfg = common.load_config()
    sel = Selectors.load()
    out: dict = {"source": "website"}
    if warning:
        out["warnings"] = [warning]
    with browser_page(cfg, headless=False if args.headed else None) as (context, page):
        site = PlaywrightSite(page, sel, cfg, label="portfolio")
        site.ensure_logged_in()
        shots = []
        if args.section in ("all", "depot"):
            out["depot"] = site.read_portfolio()
            if args.screenshot:
                shots.append(site.screenshot("depot"))
        if args.section in ("all", "orders"):
            out["orders"] = site.read_orders()
            if args.screenshot:
                shots.append(site.screenshot("orders"))
        if shots:
            out["screenshots"] = [s for s in shots if s]
        save_state(context, cfg)
    out["read_at"] = common.now(cfg).isoformat(timespec="seconds")
    if "depot" in out and not dry_run:
        snapshot(out)
    return out


if __name__ == "__main__":
    sys.exit(common.run_cli("portfolio", build_parser(), handler))
