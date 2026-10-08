"""Order platzieren und in der Orderübersicht prüfen.

    python tools/order.py --symbol DE0007164600 --qty 10 --side buy
    python tools/order.py --symbol DE0007164600 --qty 10 --side sell --limit 245.50
    python tools/order.py ... --dry-run     # füllt das Formular, schickt NICHT ab

--symbol ist das, was die Suche im Spiel findet: am sichersten ISIN oder WKN.
Ausgabe: JSON mit status placed | rejected | unverified | unklar | dry_run.
"""
from __future__ import annotations

import argparse
import contextlib
import sys

from core import common
from core.orderflow import OrderRequest, execute_order
from core.site import PlaywrightSite, Selectors, browser_page, save_state


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Order im Planspiel Börse platzieren")
    p.add_argument("--symbol", required=True, help="ISIN, WKN oder Name, wie ihn die Spielsuche findet")
    p.add_argument("--qty", required=True, type=int, help="Stückzahl (ganze Zahl > 0)")
    p.add_argument("--side", required=True, choices=["buy", "sell"])
    p.add_argument("--limit", type=float, default=None, help="Limitpreis in EUR (ohne: Market-Order)")
    p.add_argument("--headed", action="store_true", help="Browser sichtbar öffnen (zum Zuschauen)")
    return p


def handler(args: argparse.Namespace, dry_run: bool) -> dict:
    cfg = common.load_config()
    sel = Selectors.load()
    req = OrderRequest(symbol=args.symbol.strip(), qty=args.qty, side=args.side, limit=args.limit)

    @contextlib.contextmanager
    def site_factory():
        label = f"order_{req.side}_{req.symbol}"
        with browser_page(cfg, headless=False if args.headed else None) as (context, page):
            yield PlaywrightSite(page, sel, cfg, label=label)
            with contextlib.suppress(Exception):
                save_state(context, cfg)

    return execute_order(req, cfg=cfg, sel=sel, dry_run=dry_run, site_factory=site_factory)


if __name__ == "__main__":
    sys.exit(common.run_cli("order", build_parser(), handler))
