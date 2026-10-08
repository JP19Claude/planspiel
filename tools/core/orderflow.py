"""Order-Ablauf, unabhängig vom Browser (testbar mit einer Fake-Seite).

Reihenfolge:
  1. Argumente prüfen
  2. Schutzgeräte: STOP, Siegel, Selektoren bestätigt, Handelszeit
  3. eingeloggt? Orderübersicht als Ausgangslage lesen
  4. Wertpapier suchen und prüfen, dass das Formular das richtige Papier zeigt
  5. Formular füllen, Screenshot "vorher"
  6. STOP und Handelszeit nochmal prüfen, dann genau EIN Klick auf Absenden
  7. Erfolg/Fehlermeldung lesen, Screenshot "nachher"
  8. in der Orderübersicht nach der neuen Order suchen
Nach dem Absenden wird nie automatisch wiederholt. Wenn danach etwas schiefgeht,
lautet der Status "unklar" und ein Mensch muss im Spiel nachsehen.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Callable, ContextManager

from core import common, guards, integrity
from core.common import EXIT_OK, EXIT_REJECTED, EXIT_UNVERIFIED, GuardBlocked, PageStateError, ToolError
from core.numbers import parse_number
from core.site import GameSite, Selectors, normalize


@dataclass
class OrderRequest:
    symbol: str
    qty: int
    side: str
    limit: float | None = None

    def validate(self) -> None:
        if not self.symbol or not self.symbol.strip():
            raise ToolError("--symbol fehlt")
        if self.side not in ("buy", "sell"):
            raise ToolError("--side muss buy oder sell sein")
        if not isinstance(self.qty, int) or isinstance(self.qty, bool) or self.qty <= 0:
            raise ToolError("--qty muss eine ganze Zahl > 0 sein")
        if self.limit is not None and not (self.limit > 0):
            raise ToolError("--limit muss > 0 sein")


# ---------------------------------------------------------------- Abgleich

def _signature(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def _all_rows(orders: dict) -> list[tuple[str, dict]]:
    return [(section, row) for section in ("open", "history") for row in orders.get(section) or []]


def side_of(cell: str, labels: dict) -> str | None:
    text = normalize(cell)
    # "Verkauf" enthält "kauf" -> Verkauf zuerst prüfen
    for side in ("sell", "buy"):
        for label in labels.get(side) or []:
            if normalize(label) and normalize(label) in text:
                return side
    return None


def security_matches(cell: str, symbol: str, identity: str) -> bool:
    cell_n, sym_n, ident_n = normalize(cell), normalize(symbol), normalize(identity)
    if not cell_n:
        return False
    # Tabelle zeigt evtl. nur den Namen, das Formular zeigte Name + WKN/ISIN
    return sym_n in cell_n or (len(cell_n) >= 3 and bool(ident_n) and cell_n in ident_n)


def row_matches(row: dict, req: OrderRequest, identity: str, sel: Selectors) -> bool:
    cols = sel.get("order_columns", {}) or {}
    labels = sel.get("side_labels", {}) or {}
    sec_col, side_col, qty_col = cols.get("security"), cols.get("side"), cols.get("quantity")
    if not (sec_col and side_col and qty_col):
        raise PageStateError("order_columns (security/side/quantity) in selectors.yaml unvollständig")
    if not security_matches(row.get(sec_col, ""), req.symbol, identity):
        return False
    if side_of(row.get(side_col, ""), labels) != req.side:
        return False
    return parse_number(row.get(qty_col)) == float(req.qty)


def check_order_columns(orders: dict, sel: Selectors) -> None:
    """Spalten der Orderübersicht müssen zu selectors.yaml passen – vor dem Absenden."""
    cols = sel.get("order_columns", {}) or {}
    needed = [cols.get(k) for k in ("security", "side", "quantity")]
    if not all(needed):
        raise PageStateError("order_columns (security/side/quantity) in selectors.yaml unvollständig")
    for section in ("open", "history"):
        headers = orders.get(f"{section}_headers")
        if headers is None:
            continue
        missing = [c for c in needed if c not in headers]
        if missing:
            raise PageStateError(
                f"Orderübersicht ({section}) hat nicht die erwarteten Spalten {missing}",
                headers=headers)


def find_new_order(before: dict, after: dict, req: OrderRequest, identity: str, sel: Selectors) -> dict | None:
    old = Counter(_signature(r) for _, r in _all_rows(before))
    for section, row in _all_rows(after):
        sig = _signature(row)
        if old[sig] > 0:
            old[sig] -= 1
            continue
        if row_matches(row, req, identity, sel):
            return {"section": section, "row": row}
    return None


# ---------------------------------------------------------------- Ablauf

SiteFactory = Callable[[], ContextManager[GameSite]]


def preflight(req: OrderRequest, *, cfg: dict, sel: Selectors, dry_run: bool, now: dt.datetime) -> dict:
    """Alle Prüfungen, bevor ein Browser geöffnet wird."""
    req.validate()
    guards.check_stop(strict=True)
    warnings: list[str] = []
    seal = integrity.verify()
    if not seal["ok"]:
        if dry_run:
            warnings.append("Siegel stimmt nicht: " + seal.get("message", ""))
        else:
            raise GuardBlocked("Integritätsprüfung fehlgeschlagen – keine Order.", guard="integrity", integrity=seal)
    if not sel.confirmed:
        if dry_run:
            warnings.append("selectors.yaml ist noch nicht bestätigt (confirmed: false)")
        else:
            raise GuardBlocked("selectors.yaml ist noch nicht bestätigt (confirmed: false) – keine echte Order.",
                               guard="selectors")
    status = guards.trading_status(now, cfg)
    if not status["open"]:
        if dry_run:
            warnings.append("Außerhalb der Handelszeit: " + status["reason"])
        else:
            raise GuardBlocked(f"Order außerhalb der Handelszeiten des Spiels: {status['reason']}",
                               guard="trading_hours", trading=status)
    return {"warnings": warnings, "trading": status}


def execute_order(req: OrderRequest, *, cfg: dict, sel: Selectors, dry_run: bool,
                  site_factory: SiteFactory, now_fn: Callable[[], dt.datetime] | None = None,
                  sleep: Callable[[float], None] = time.sleep) -> dict:
    now_fn = now_fn or (lambda: common.now(cfg))
    pre = preflight(req, cfg=cfg, sel=sel, dry_run=dry_run, now=now_fn())
    result: dict[str, Any] = {"order": asdict(req), "warnings": pre["warnings"], "trading": pre["trading"],
                              "screenshots": [], "steps": []}
    step = result["steps"].append
    shots = result["screenshots"]
    submit_clicked = False
    common.log_action("order", "preflight_ok", order=asdict(req), dry_run=dry_run, warnings=pre["warnings"])

    def shot(site: GameSite, label: str) -> None:
        path = site.screenshot(label)
        if path:
            shots.append(path)

    with site_factory() as site:
        try:
            site.ensure_logged_in()
            step("eingeloggt")
            before = site.read_orders()
            check_order_columns(before, sel)
            step("Orderübersicht vorher gelesen")

            identity = site.open_order_form(req.symbol)
            result["security"] = identity
            if not security_matches(identity, req.symbol, ""):
                raise PageStateError(
                    f"Formular zeigt ein anderes Wertpapier ('{identity[:120]}') als verlangt ('{req.symbol}')")
            step("Wertpapier im Formular geprüft")

            site.fill_order(req.side, req.qty, req.limit)
            step("Formular ausgefüllt")
            shot(site, "vorher")

            if dry_run:
                site.abandon_order()
                step("Testmodus: NICHT abgeschickt")
                result.update(status="dry_run", exit_code=EXIT_OK,
                              message="Testmodus – Formular gefüllt, aber nicht abgeschickt.")
                return result

            # Letzte Kontrolle direkt vor dem Klick
            guards.check_stop(strict=True)
            guards.check_trading_hours(now_fn(), cfg)
            common.log_action("order", "submit", order=asdict(req), security=identity)
            submit_clicked = True
            site.submit_order()
            step("abgeschickt")

            outcome = site.read_submit_outcome()
            result["site_message"] = outcome.get("message")
            shot(site, "nachher")
            if outcome.get("success") is False:
                result.update(status="rejected", exit_code=EXIT_REJECTED,
                              message=f"Website hat die Order abgelehnt: {outcome.get('message')}")
                return result

            attempts = int(cfg["order"].get("verify_attempts", 6))
            wait = float(cfg["order"].get("verify_wait_seconds", 5))
            found = None
            for attempt in range(attempts):
                after = site.read_orders()
                found = find_new_order(before, after, req, identity, sel)
                if found:
                    break
                if attempt < attempts - 1:
                    sleep(wait)
            shot(site, "orderuebersicht")
            if found:
                result.update(status="placed", exit_code=EXIT_OK, verified=found,
                              message="Order in der Orderübersicht gefunden.")
            else:
                result.update(status="unverified", exit_code=EXIT_UNVERIFIED,
                              message="Order abgeschickt, aber NICHT in der Orderübersicht gefunden. "
                                      "Nicht wiederholen – erst manuell/über portfolio.py prüfen.")
            return result
        except ToolError as exc:
            with contextlib.suppress(Exception):
                shot(site, "abbruch")
            if submit_clicked:
                result.update(status="unklar", exit_code=EXIT_UNVERIFIED,
                              message=f"Fehler NACH dem Absenden: {exc.message}. Order-Status unklar – "
                                      "nicht wiederholen, erst prüfen.",
                              error={"code": exc.code, "message": exc.message, **exc.details})
                return result
            exc.details.setdefault("screenshots", shots)
            exc.details.setdefault("steps", result["steps"])
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                shot(site, "abbruch")
            if submit_clicked:
                result.update(status="unklar", exit_code=EXIT_UNVERIFIED,
                              message=f"Fehler NACH dem Absenden: {type(exc).__name__}: {exc}. "
                                      "Order-Status unklar – nicht wiederholen, erst prüfen.")
                return result
            raise PageStateError(f"Unerwarteter Seitenzustand: {type(exc).__name__}: {exc}",
                                 screenshots=shots, steps=result["steps"]) from exc

