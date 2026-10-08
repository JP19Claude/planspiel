"""Zugriff auf die Planspiel-Website über Playwright.

Alle Selektoren kommen aus selectors.yaml. Grundregel: Wenn ein erwartetes
Element fehlt oder mehrdeutig ist, wird mit PageStateError abgebrochen statt
geraten. Geklickt wird nur auf Elemente, die genau einmal sichtbar sind.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import re
import time
from pathlib import Path
from typing import Any, Iterator, Protocol
from urllib.parse import quote

from core import common
from core.common import ConfigError, LoginRequired, PageStateError
from core.numbers import format_number, parse_number


# ---------------------------------------------------------------- Selektoren

class Selectors:
    def __init__(self, data: dict):
        self.data = data or {}

    @classmethod
    def load(cls, path: Path | None = None) -> "Selectors":
        return cls(common.load_yaml(path or common.paths.selectors))

    @property
    def confirmed(self) -> bool:
        return bool(self.data.get("confirmed"))

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return default if node in (None, "") else node

    def require(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise ConfigError(f"Selektor/Eintrag '{key}' fehlt in selectors.yaml", key=key)
        return value


# ---------------------------------------------------------------- Hilfen

def normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def rows_from_table(headers: list[str], rows: list[list[str]]) -> tuple[list[dict], list[str]]:
    """Macht aus Kopfzeile + Zeilen eine Liste von Dicts. Einzelzellen-Zeilen
    (z. B. "Keine Orders vorhanden") landen in notes."""
    keys: list[str] = []
    for i, h in enumerate(headers):
        key = (h or "").strip() or f"col_{i + 1}"
        while key in keys:
            key += f"_{i + 1}"
        keys.append(key)
    out, notes = [], []
    for cells in rows:
        if not any(c.strip() for c in cells):
            continue
        if len(cells) == 1 and len(keys) > 1:
            notes.append(cells[0])
            continue
        row = {}
        for i, cell in enumerate(cells):
            key = keys[i] if i < len(keys) else f"col_{i + 1}"
            row[key] = cell
        out.append(row)
    return out, notes


_TABLE_JS = """
(el) => {
  const txt = (c) => (c.innerText || c.textContent || '').replace(/\\s+/g, ' ').trim();
  let headers = Array.from(el.querySelectorAll('thead th, thead td')).map(txt);
  let body = Array.from(el.querySelectorAll('tbody tr'));
  const all = Array.from(el.querySelectorAll('tr'));
  if (!headers.length && all.length) {
    headers = Array.from(all[0].querySelectorAll('th,td')).map(txt);
    body = all.slice(1);
  }
  if (!body.length) body = all.filter(r => !r.closest('thead'));
  const rows = body.map(r => Array.from(r.querySelectorAll('td,th')).map(txt));
  return {headers, rows};
}
"""


# ---------------------------------------------------------------- Protokoll

class GameSite(Protocol):
    """Schnittstelle, die order.py/portfolio.py benutzen (Tests: FakeSite)."""

    def ensure_logged_in(self) -> None: ...
    def read_portfolio(self) -> dict: ...
    def read_orders(self) -> dict: ...
    def open_order_form(self, symbol: str) -> str: ...
    def fill_order(self, side: str, qty: int, limit: float | None) -> None: ...
    def submit_order(self) -> None: ...
    def read_submit_outcome(self) -> dict: ...
    def abandon_order(self) -> None: ...
    def screenshot(self, label: str) -> str | None: ...


class PlaywrightSite:
    def __init__(self, page: Any, selectors: Selectors, cfg: dict, label: str = "site"):
        self.page = page
        self.sel = selectors
        self.cfg = cfg
        self.label = label
        self.timeout = int(cfg["browser"].get("timeout_ms", 15000))
        self.number_format = cfg.get("order", {}).get("number_format", "de")
        frame = selectors.get("frame")
        self.root = page.frame_locator(frame) if frame else page

    # ------------------------------------------------------------ Grundlagen

    @property
    def url(self) -> str:
        try:
            return self.page.url
        except Exception:  # pragma: no cover
            return ""

    def _url(self, key: str) -> str:
        url = self.sel.require(f"urls.{key}")
        if url.startswith("/"):
            url = self.cfg["game"]["base_url"].rstrip("/") + url
        return url

    def goto(self, key: str, **fmt: str) -> None:
        url = self._url(key)
        if fmt:
            url = url.format(**{k: quote(str(v)) for k, v in fmt.items()})
        self.open_url(url)

    def open_url(self, url: str) -> None:
        try:
            self.page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise PageStateError(f"Seite nicht erreichbar: {first_line}", url=url) from exc
        self.dismiss_cookies()

    def dismiss_cookies(self) -> None:
        sel = self.sel.get("common.cookie_accept")
        if not sel:
            return
        with contextlib.suppress(Exception):
            loc = self.root.locator(sel)
            loc.first.wait_for(state="visible", timeout=2500)
            loc.first.click()

    def _loc(self, key: str):
        return self.root.locator(self.sel.require(key))

    def _visible(self, key: str, timeout: int = 0) -> bool:
        sel = self.sel.get(key)
        if not sel:
            return False
        loc = self.root.locator(sel)
        try:
            if timeout:
                loc.first.wait_for(state="visible", timeout=timeout)
            return loc.first.is_visible()
        except Exception:
            return False

    def one(self, key: str, timeout: int | None = None):
        """Genau ein sichtbares Element – sonst Abbruch."""
        loc = self._loc(key)
        try:
            loc.first.wait_for(state="visible", timeout=timeout or self.timeout)
        except Exception:
            raise PageStateError(f"Erwartetes Element '{key}' nicht gefunden", selector=self.sel.get(key),
                                 url=self.url)
        visible = [i for i in range(loc.count()) if loc.nth(i).is_visible()]
        if len(visible) != 1:
            raise PageStateError(f"Element '{key}' ist mehrdeutig ({len(visible)} sichtbare Treffer)",
                                 selector=self.sel.get(key), url=self.url)
        return loc.nth(visible[0])

    def text(self, key: str) -> str:
        return self.one(key).inner_text().strip()

    def read_table(self, key: str) -> tuple[list[dict], list[str], list[str]]:
        data = self.one(key).evaluate(_TABLE_JS)
        rows, notes = rows_from_table(data["headers"], data["rows"])
        return rows, notes, data["headers"]

    def wait_first(self, keys: list[str], timeout_ms: int) -> str | None:
        """Wartet, bis eines der Elemente sichtbar ist; gibt dessen Schlüssel zurück."""
        deadline = time.monotonic() + timeout_ms / 1000
        keys = [k for k in keys if self.sel.get(k)]
        while time.monotonic() < deadline:
            for key in keys:
                if self._visible(key):
                    return key
            time.sleep(0.25)
        return None

    def screenshot(self, label: str) -> str | None:
        day = dt.datetime.now().strftime("%Y-%m-%d")
        target = common.paths.screenshots / day
        target.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{self.label}_{label}")[:80]
        path = target / f"{dt.datetime.now():%H%M%S}_{safe}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except Exception:
            return None
        return str(path.relative_to(common.paths.root))

    # ------------------------------------------------------------ Login

    def logged_in(self) -> bool:
        return self._visible("login.logged_in_indicator", timeout=min(self.timeout, 8000))

    def ensure_logged_in(self) -> None:
        if self.sel.get("urls.depot"):
            self.goto("depot")
        else:
            self.open_url(self.cfg["game"]["base_url"])
        if not self.sel.get("login.logged_in_indicator"):
            raise ConfigError("login.logged_in_indicator fehlt in selectors.yaml")
        if not self.logged_in():
            raise LoginRequired("Nicht eingeloggt (Session abgelaufen?). Bitte 'python tools/login.py' ausführen.",
                                url=self.url)

    def login(self, username: str, password: str) -> str:
        """Füllt das Login-Formular. Rückgabe: 'ok' | 'captcha' | '2fa' | 'error' | 'unknown'."""
        self.goto("login")
        first = self.wait_first(["login.logged_in_indicator", "login.username_input"], self.timeout)
        if first == "login.logged_in_indicator":
            return "ok"
        self.one("login.username_input").fill(username)
        self.one("login.password_input").fill(password)
        self.one("login.submit_button").click()
        found = self.wait_first(
            ["login.logged_in_indicator", "login.captcha_indicator", "login.twofa_indicator", "login.error_message"],
            self.timeout,
        )
        return {
            "login.logged_in_indicator": "ok",
            "login.captcha_indicator": "captcha",
            "login.twofa_indicator": "2fa",
            "login.error_message": "error",
        }.get(found or "", "unknown")

    # ------------------------------------------------------------ Lesen

    def _value(self, key: str) -> dict | None:
        if not self.sel.get(key):
            return None
        raw = self.text(key)
        return {"text": raw, "value": parse_number(raw, self.number_format)}

    def read_portfolio(self) -> dict:
        self.goto("depot")
        result: dict[str, Any] = {"url": self.url}
        for name in ("cash", "total_value", "depot_value", "performance"):
            v = self._value(f"depot.{name}")
            if v is not None:
                result[name] = v
        if self._visible("depot.empty_indicator", timeout=1500):
            result["positions"] = []
            result["positions_note"] = "Depot leer (laut Seite)"
        else:
            rows, notes, headers = self.read_table("depot.positions_table")
            result["positions"] = rows
            result["positions_headers"] = headers
            if notes:
                result["positions_note"] = " | ".join(notes)
        return result

    def read_orders(self) -> dict:
        self.goto("orders")
        out: dict[str, Any] = {"url": self.url}
        for section, key in (("open", "orders.open_orders_table"), ("history", "orders.history_table")):
            if not self.sel.get(key):
                continue
            empty_key = f"orders.{section}_empty_indicator"
            if self._visible(empty_key, timeout=1000):
                out[section] = []
                continue
            rows, notes, headers = self.read_table(key)
            out[section] = rows
            out[f"{section}_headers"] = headers
            if notes:
                out[f"{section}_note"] = " | ".join(notes)
        return out

    # ------------------------------------------------------------ Order

    def open_order_form(self, symbol: str) -> str:
        template = self.sel.get("urls.order_form") or ""
        if "{symbol}" in template:
            self.goto("order_form", symbol=symbol)
        else:
            self.goto("order_form")
            search = self.one("order_form.search_input")
            search.fill(symbol)
            if self.sel.get("order_form.search_submit"):
                self.one("order_form.search_submit").click()
            results = self._loc("order_form.search_result_item")
            try:
                results.first.wait_for(state="visible", timeout=self.timeout)
            except Exception:
                raise PageStateError(f"Keine Suchergebnisse für '{symbol}'", url=self.url)
            wanted = normalize(symbol)
            matches = [i for i in range(results.count())
                       if results.nth(i).is_visible() and wanted in normalize(results.nth(i).inner_text())]
            if len(matches) != 1:
                candidates = [results.nth(i).inner_text().strip()[:120] for i in range(min(results.count(), 10))]
                raise PageStateError(
                    f"Suche nach '{symbol}' nicht eindeutig ({len(matches)} passende Treffer). "
                    "Mit ISIN oder WKN erneut versuchen.",
                    candidates=candidates, url=self.url)
            results.nth(matches[0]).click()
        identity = self.text("order_form.security_identity")
        return identity

    def _choose(self, click_key: str, select_key: str, label: str | None) -> None:
        if self.sel.get(select_key):
            if not label:
                raise ConfigError(f"Für '{select_key}' fehlt das Options-Label")
            self.one(select_key).select_option(label=label)
        elif self.sel.get(click_key):
            self.one(click_key).click()
        else:
            raise ConfigError(f"Weder '{click_key}' noch '{select_key}' in selectors.yaml gesetzt")

    def _fill_checked(self, key: str, text: str, expected: float) -> None:
        field = self.one(key)
        field.fill(text)
        back = field.input_value()
        if parse_number(back, self.number_format) != expected:
            raise PageStateError(f"Feld '{key}' zeigt '{back}' statt '{text}'", url=self.url)

    def fill_order(self, side: str, qty: int, limit: float | None) -> None:
        labels = self.sel.get("order_form.select_labels", {}) or {}
        self._choose(f"order_form.side_{side}", "order_form.side_select", labels.get(side))
        self._fill_checked("order_form.quantity_input", str(qty), float(qty))
        if limit is not None:
            self._choose("order_form.order_type_limit", "order_form.order_type_select", labels.get("limit"))
            self._fill_checked("order_form.limit_input", format_number(limit, self.number_format), float(limit))
        elif self.sel.get("order_form.order_type_market") or self.sel.get("order_form.order_type_select"):
            self._choose("order_form.order_type_market", "order_form.order_type_select", labels.get("market"))

    def submit_order(self) -> None:
        if self.sel.get("order_form.preview_button"):
            self.one("order_form.preview_button").click()
        self.one("order_form.submit_button").click()
        if self.sel.get("order_form.confirm_button"):
            self.one("order_form.confirm_button").click()

    def read_submit_outcome(self) -> dict:
        found = self.wait_first(["order_form.success_indicator", "order_form.error_message"], self.timeout)
        if found == "order_form.success_indicator":
            return {"success": True, "message": self.text(found)}
        if found == "order_form.error_message":
            return {"success": False, "message": self.text(found)}
        return {"success": None, "message": "Weder Erfolg noch Fehlermeldung erkannt"}

    def abandon_order(self) -> None:
        with contextlib.suppress(Exception):
            self.goto("depot")


# ---------------------------------------------------------------- Browser

def storage_state_path(cfg: dict) -> Path:
    return common.resolve(cfg["browser"].get("storage_state") or ".auth/storage_state.json")


@contextlib.contextmanager
def browser_page(cfg: dict, *, headless: bool | None = None, use_state: bool = True) -> Iterator[tuple[Any, Any]]:
    """Startet Chromium mit gespeicherter Session. Liefert (context, page)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("Playwright fehlt: pip install -r requirements.txt && python -m playwright install chromium") from exc

    bcfg = cfg["browser"]
    state = storage_state_path(cfg)
    launch: dict[str, Any] = {
        "headless": bcfg.get("headless", True) if headless is None else headless,
        "slow_mo": int(bcfg.get("slow_mo_ms") or 0),
    }
    if bcfg.get("channel"):
        launch["channel"] = bcfg["channel"]
    if bcfg.get("executable_path"):
        launch["executable_path"] = bcfg["executable_path"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch)
        try:
            context = browser.new_context(
                storage_state=str(state) if (use_state and state.exists()) else None,
                locale="de-DE",
                timezone_id=cfg["game"].get("timezone") or "Europe/Berlin",
                viewport=bcfg.get("viewport") or {"width": 1400, "height": 1000},
            )
            context.set_default_timeout(int(bcfg.get("timeout_ms", 15000)))
            page = context.new_page()
            yield context, page
        finally:
            with contextlib.suppress(Exception):
                browser.close()


def save_state(context: Any, cfg: dict) -> str:
    path = storage_state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(path))
    return str(path.relative_to(common.paths.root)) if path.is_relative_to(common.paths.root) else str(path)
