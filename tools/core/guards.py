"""Schutzgeräte: STOP-Datei und Handelszeiten.

Diese Prüfungen stehen im Code und nicht in mission.md. Der Agent kann sie
nicht abschalten: Die Dateien sind gesiegelt (siehe integrity.py), für
Edit/Write gesperrt (agent-settings.json) und der Hook blockt offensichtliche
Manipulationsversuche über Bash.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from core import common
from core.common import GuardBlocked

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_NAMES_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


# ---------------------------------------------------------------- STOP

def stop_active() -> bool:
    return common.paths.stop.exists()


def stop_reason() -> str:
    try:
        return common.paths.stop.read_text(encoding="utf-8", errors="replace").strip()[:500]
    except OSError:
        return ""


def check_stop(strict: bool = True) -> dict | None:
    """Bricht ab, wenn STOP existiert.

    strict=False (nur für lesende Werkzeuge außerhalb eines Agentenlaufs):
    gibt stattdessen eine Warnung zurück.
    """
    if not stop_active():
        return None
    reason = stop_reason()
    if strict:
        raise GuardBlocked(
            "STOP-Datei vorhanden – Abbruch. Erst wenn der Mensch STOP löscht, geht es weiter.",
            guard="stop",
            stop_reason=reason,
        )
    return {"guard": "stop", "message": "STOP-Datei vorhanden (nur Lesen erlaubt)", "stop_reason": reason}


def stop_strict_for_reader() -> bool:
    """Lesende Werkzeuge brechen im Agentenlauf ab, von Hand nur Warnung."""
    return common.in_agent_run()


# ---------------------------------------------------------------- Handelszeiten

def _parse_time(value: str) -> dt.time:
    hours, minutes = str(value).split(":")
    return dt.time(int(hours), int(minutes))


def _parse_date(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _status_core(now: dt.datetime, cfg: dict) -> dict:
    game = cfg["game"]
    hours = game.get("trading_hours") or {}
    local = now.astimezone(common.tz(cfg))
    today = local.date()
    days = [d.lower()[:3] for d in hours.get("days", WEEKDAYS[:5])]
    open_t = _parse_time(hours.get("open", "08:00"))
    close_t = _parse_time(hours.get("close", "22:00"))
    holidays = {_parse_date(h) for h in (game.get("holidays") or [])}
    start = _parse_date(game.get("start"))
    end = _parse_date(game.get("end"))

    status = {
        "open": False,
        "local_time": local.isoformat(timespec="minutes"),
        "weekday": WEEKDAY_NAMES_DE[local.weekday()],
        "hours": f"{open_t:%H:%M}-{close_t:%H:%M}",
        "days": days,
    }
    if start and today < start:
        status["reason"] = f"Spiel beginnt erst am {start.isoformat()}"
    elif end and today > end:
        status["reason"] = f"Spiel ist seit {end.isoformat()} beendet"
    elif WEEKDAYS[local.weekday()] not in days:
        status["reason"] = f"kein Handelstag ({WEEKDAY_NAMES_DE[local.weekday()]})"
    elif today in holidays:
        status["reason"] = f"handelsfreier Tag ({today.isoformat()})"
    elif not (open_t <= local.time() < close_t):
        status["reason"] = f"außerhalb der Handelszeit {open_t:%H:%M}-{close_t:%H:%M}"
    else:
        status["open"] = True
        status["reason"] = "Handelszeit"
    return status


def trading_status(now: dt.datetime, cfg: dict) -> dict:
    """Ist jetzt Handelszeit im Spiel? Gibt {open, reason, local_time, ...} zurück."""
    status = _status_core(now, cfg)
    if not status["open"]:
        nxt = next_open(now, cfg)
        status["next_open"] = nxt.isoformat(timespec="minutes") if nxt else None
    return status


def next_open(now: dt.datetime, cfg: dict) -> dt.datetime | None:
    """Nächster Handelsbeginn nach `now` (max. 30 Tage voraus)."""
    local = now.astimezone(common.tz(cfg))
    hours = cfg["game"].get("trading_hours") or {}
    open_t = _parse_time(hours.get("open", "08:00"))
    for offset in range(0, 31):
        day = local.date() + dt.timedelta(days=offset)
        candidate = dt.datetime.combine(day, open_t, tzinfo=local.tzinfo)
        if candidate > local and _status_core(candidate, cfg)["open"]:
            return candidate
    return None


def check_trading_hours(now: dt.datetime, cfg: dict) -> dict:
    status = trading_status(now, cfg)
    if not status["open"]:
        raise GuardBlocked(
            f"Order außerhalb der Handelszeiten des Spiels: {status['reason']}",
            guard="trading_hours",
            trading=status,
        )
    return status
