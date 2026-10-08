"""Login per Playwright, Session wird als storage_state gespeichert.

    python tools/login.py            # Session prüfen, sonst automatisch mit .env einloggen
    python tools/login.py --manual   # Browser sichtbar öffnen, du loggst dich selbst ein
    python tools/login.py --check    # nur prüfen, ob die gespeicherte Session noch gilt
    python tools/login.py --dry-run  # zeigt, was passieren würde, schickt keine Zugangsdaten ab

Zugangsdaten kommen nur aus .env (PLANSPIEL_USERNAME, PLANSPIEL_PASSWORD).
Bei Captcha/2FA öffnet sich der Browser sichtbar (nur wenn ein Mensch am
Terminal sitzt). Im Agentenlauf gibt es dann Exit-Code 5 und der Agent bricht ab.
"""
from __future__ import annotations

import argparse
import sys
import time

from core import common, guards
from core.common import ConfigError, LoginRequired
from core.site import PlaywrightSite, Selectors, browser_page, save_state, storage_state_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Login ins Planspiel Börse")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--manual", action="store_true", help="sichtbarer Browser, manueller Login")
    mode.add_argument("--check", action="store_true", help="nur Session prüfen")
    p.add_argument("--wait-minutes", type=float, default=10, help="max. Wartezeit beim manuellen Login")
    return p


def interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty() and not common.in_agent_run()


def login_url(cfg: dict, sel: Selectors) -> str:
    url = sel.get("urls.login") or cfg["game"]["base_url"]
    return cfg["game"]["base_url"].rstrip("/") + url if url.startswith("/") else url


def session_valid(cfg: dict, sel: Selectors) -> bool | None:
    """True/False, oder None wenn kein Erkennungs-Selektor konfiguriert ist."""
    if not storage_state_path(cfg).exists():
        return False
    if not sel.get("login.logged_in_indicator"):
        return None
    with browser_page(cfg) as (_context, page):
        site = PlaywrightSite(page, sel, cfg, label="login")
        try:
            site.ensure_logged_in()
            return True
        except LoginRequired:
            return False


def manual_login(cfg: dict, sel: Selectors, creds: dict, wait_minutes: float) -> dict:
    if not interactive():
        raise LoginRequired("Manueller Login nötig, aber kein Mensch am Terminal. "
                            "Bitte 'python tools/login.py --manual' selbst ausführen.")
    url = login_url(cfg, sel)
    with browser_page(cfg, headless=False, use_state=True) as (context, page):
        site = PlaywrightSite(page, sel, cfg, label="login")
        page.goto(url, wait_until="domcontentloaded")
        site.dismiss_cookies()
        # Zugangsdaten vorausfüllen, falls Selektoren und .env vorhanden sind
        if creds.get("PLANSPIEL_USERNAME") and sel.get("login.username_input"):
            try:
                site.one("login.username_input", timeout=5000).fill(creds["PLANSPIEL_USERNAME"])
                if creds.get("PLANSPIEL_PASSWORD") and sel.get("login.password_input"):
                    site.one("login.password_input", timeout=5000).fill(creds["PLANSPIEL_PASSWORD"])
            except Exception:
                pass
        print(f"\nBrowser ist offen: {url}", file=sys.stderr)
        if sel.get("login.logged_in_indicator"):
            print("Bitte einloggen (Captcha/2FA lösen). Ich erkenne den Login automatisch …", file=sys.stderr)
            deadline = time.monotonic() + wait_minutes * 60
            ok = False
            while time.monotonic() < deadline:
                if site._visible("login.logged_in_indicator"):
                    ok = True
                    break
                time.sleep(1)
            if not ok:
                raise LoginRequired("Login wurde nicht innerhalb der Wartezeit erkannt.")
        else:
            print("Bitte einloggen und danach hier ENTER drücken (Session wird gespeichert) …", file=sys.stderr)
            input()
        time.sleep(1)
        saved = save_state(context, cfg)
        shot = site.screenshot("nach_login")
    return {"status": "logged_in", "method": "manual", "storage_state": saved, "screenshot": shot}


def handler(args: argparse.Namespace, dry_run: bool) -> dict:
    guards.check_stop(strict=common.in_agent_run())
    cfg = common.load_config()
    sel = Selectors.load()
    creds = common.load_env()
    state = storage_state_path(cfg)
    info = {
        "login_url": login_url(cfg, sel),
        "storage_state_exists": state.exists(),
        "credentials_in_env": bool(creds.get("PLANSPIEL_USERNAME") and creds.get("PLANSPIEL_PASSWORD")),
        "selectors_confirmed": sel.confirmed,
    }

    if args.manual:
        if dry_run:
            return {**info, "status": "dry_run", "message": "Würde den Browser sichtbar öffnen (manueller Login)."}
        return {**info, **manual_login(cfg, sel, creds, args.wait_minutes)}

    valid = session_valid(cfg, sel)
    info["session_valid"] = valid
    if args.check or dry_run:
        if valid is None:
            info["message"] = "login.logged_in_indicator fehlt in selectors.yaml – Session nicht prüfbar."
        status = {True: "session_valid", False: "session_invalid", None: "unknown"}[valid]
        exit_code = common.EXIT_OK if valid else common.EXIT_LOGIN
        if dry_run and not args.check:
            info["message"] = info.get("message") or "Testmodus: keine Zugangsdaten abgeschickt."
            exit_code = common.EXIT_OK
        return {**info, "status": status, "exit_code": exit_code}
    if valid:
        return {**info, "status": "session_valid"}

    # Automatischer Login mit .env
    if not info["credentials_in_env"]:
        if interactive():
            return {**info, **manual_login(cfg, sel, creds, args.wait_minutes)}
        raise LoginRequired("Keine Zugangsdaten in .env und keine gültige Session.", **info)
    for key in ("login.username_input", "login.password_input", "login.submit_button", "login.logged_in_indicator"):
        if not sel.get(key):
            if interactive():
                return {**info, **manual_login(cfg, sel, creds, args.wait_minutes)}
            raise ConfigError(f"'{key}' fehlt in selectors.yaml – automatischer Login nicht möglich", **info)

    with browser_page(cfg) as (context, page):
        site = PlaywrightSite(page, sel, cfg, label="login")
        outcome = site.login(creds["PLANSPIEL_USERNAME"], creds["PLANSPIEL_PASSWORD"])
        if outcome == "ok":
            saved = save_state(context, cfg)
            return {**info, "status": "logged_in", "method": "auto", "storage_state": saved}
        shot = site.screenshot(f"login_{outcome}")
    info["auto_login_outcome"] = outcome
    info["screenshot"] = shot
    if outcome in ("captcha", "2fa", "unknown") and interactive():
        return {**info, **manual_login(cfg, sel, creds, args.wait_minutes)}
    raise LoginRequired(f"Automatischer Login nicht möglich ({outcome}). "
                        "Bitte 'python tools/login.py --manual' ausführen.", **info)


if __name__ == "__main__":
    sys.exit(common.run_cli("login", build_parser(), handler))
