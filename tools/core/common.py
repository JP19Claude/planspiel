"""Pfade, Konfiguration, JSON-Ausgabe und Aktionsprotokoll.

Bewusst gibt es keine Umgebungsvariable, die das Projektverzeichnis umbiegt:
STOP-Datei, Handelszeiten und Siegel sollen sich nicht per Variable
aushebeln lassen.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import yaml

# Exit-Codes aller Werkzeuge (stehen auch in CLAUDE.md)
EXIT_OK = 0
EXIT_ERROR = 1          # allgemeiner Fehler / falsche Argumente
EXIT_BLOCKED = 2        # Schutzgerät hat abgebrochen (STOP, Handelszeit, Siegel, ...)
EXIT_PAGE_STATE = 3     # unerwarteter Seitenzustand -> abgebrochen statt geraten
EXIT_UNVERIFIED = 4     # Order abgeschickt, aber Ergebnis nicht bestätigt -> manuell prüfen
EXIT_LOGIN = 5          # Session abgelaufen / manueller Login nötig
EXIT_REJECTED = 6       # Website hat die Order abgelehnt (z. B. zu wenig Cash)


@dataclass
class Paths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def selectors(self) -> Path:
        return self.root / "selectors.yaml"

    @property
    def env(self) -> Path:
        return self.root / ".env"

    @property
    def stop(self) -> Path:
        return self.root / "STOP"

    @property
    def journal(self) -> Path:
        return self.root / "journal.md"

    @property
    def mission(self) -> Path:
        return self.root / "mission.md"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def actions_log(self) -> Path:
        return self.logs / "actions.jsonl"

    @property
    def screenshots(self) -> Path:
        return self.logs / "screenshots"

    @property
    def runs(self) -> Path:
        return self.logs / "runs"

    @property
    def explore(self) -> Path:
        return self.logs / "explore"

    @property
    def portfolio_history(self) -> Path:
        return self.logs / "portfolio_history.jsonl"

    @property
    def auth_dir(self) -> Path:
        return self.root / ".auth"


PROJECT_ROOT = Path(__file__).resolve().parents[2]
paths = Paths(PROJECT_ROOT)


class ToolError(Exception):
    """Fehler mit Code und Exit-Code, wird als JSON ausgegeben."""

    code = "error"
    exit_code = EXIT_ERROR

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.message = message
        self.details = details


class ConfigError(ToolError):
    code = "config"


class GuardBlocked(ToolError):
    code = "blocked"
    exit_code = EXIT_BLOCKED


class PageStateError(ToolError):
    code = "page_state"
    exit_code = EXIT_PAGE_STATE


class LoginRequired(ToolError):
    code = "login_required"
    exit_code = EXIT_LOGIN


# ---------------------------------------------------------------- Konfiguration

DEFAULT_CONFIG: dict[str, Any] = {
    "models": {"trading_run": "claude-sonnet-5-5", "weekly_review": "claude-opus-5-5"},
    "agent": {
        "claude_command": "claude",
        "allowed_tools": "Bash,Read,Write,Edit,WebSearch,WebFetch",
        "timeout_minutes": 45,
        "max_budget_usd": None,
        "extra_args": [],
        "prompts": {
            "trading": "Lies mission.md und journal.md und führe einen Handelslauf aus",
            "review": "Lies mission.md, journal.md und CLAUDE.md und führe den wöchentlichen Review aus",
        },
    },
    "game": {
        "name": "Planspiel Börse",
        "base_url": "https://www.planspiel-boerse.de",
        "timezone": "Europe/Berlin",
        "start": None,
        "end": None,
        "start_capital": None,
        "trading_hours": {"days": ["mon", "tue", "wed", "thu", "fri"], "open": "08:00", "close": "22:00"},
        "holidays": [],
    },
    "browser": {
        "headless": True,
        "channel": None,
        "executable_path": None,
        "storage_state": ".auth/storage_state.json",
        "timeout_ms": 15000,
        "slow_mo_ms": 0,
        "viewport": {"width": 1400, "height": 1000},
    },
    "order": {
        "verify_attempts": 6,
        "verify_wait_seconds": 5,
        "number_format": "de",
    },
}


def deep_merge(base: dict, override: dict | None) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} muss ein YAML-Mapping sein")
    return data


def load_config() -> dict:
    return deep_merge(DEFAULT_CONFIG, load_yaml(paths.config))


def load_env() -> dict[str, str]:
    """Liest Zugangsdaten nur aus .env (nicht aus dem Prozess-Environment)."""
    if not paths.env.exists():
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(paths.env).items() if v is not None}


def tz(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg["game"].get("timezone") or "Europe/Berlin")


def now(cfg: dict | None = None) -> dt.datetime:
    zone = tz(cfg) if cfg else ZoneInfo("Europe/Berlin")
    return dt.datetime.now(zone)


def resolve(path_str: str | Path) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else paths.root / p


# ---------------------------------------------------------------- Laufkontext

def run_id() -> str | None:
    return os.environ.get("BOERSE_RUN_ID") or None


def run_mode() -> str | None:
    return os.environ.get("BOERSE_RUN_MODE") or None


def in_agent_run() -> bool:
    return run_id() is not None


def env_dry_run() -> bool:
    return os.environ.get("BOERSE_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "ja"}


# ---------------------------------------------------------------- Protokoll

def json_default(obj: Any) -> Any:
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if hasattr(obj, "item"):  # numpy-Skalare
        return obj.item()
    return str(obj)


def clean_json(obj: Any) -> Any:
    """NaN/Inf -> None, damit die Ausgabe gültiges JSON ist."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    return obj


def log_action(tool: str, event: str, **data: Any) -> None:
    """Hängt eine Zeile an logs/actions.jsonl an. Darf nie den Ablauf stören."""
    try:
        paths.logs.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
            "tool": tool,
            "event": event,
            "run_id": run_id(),
            "pid": os.getpid(),
            **data,
        }
        with paths.actions_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(clean_json(entry), ensure_ascii=False, default=json_default) + "\n")
    except Exception:  # pragma: no cover - Logging darf nie crashen
        pass


def configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass


def emit(payload: dict) -> None:
    print(json.dumps(clean_json(payload), ensure_ascii=False, indent=2, default=json_default))


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Testmodus: nichts Endgültiges tun (keine Order, kein Schreiben)",
    )


def run_cli(tool: str, parser: argparse.ArgumentParser, handler: Callable[[argparse.Namespace, bool], dict],
            argv: list[str] | None = None) -> int:
    """Gemeinsamer Rahmen: Argumente, Protokoll, JSON-Ausgabe, Exit-Code."""
    configure_stdout()
    add_common_args(parser)
    args = parser.parse_args(argv)
    dry_run = bool(getattr(args, "dry_run", False) or getattr(args, "dry_run_sub", False)) or env_dry_run()
    log_action(tool, "start", argv=list(argv if argv is not None else sys.argv[1:]), dry_run=dry_run)
    try:
        result = handler(args, dry_run) or {}
        exit_code = int(result.pop("exit_code", EXIT_OK if result.get("ok", True) else EXIT_ERROR))
        result.pop("ok", None)
        payload = {"ok": exit_code == EXIT_OK, "tool": tool, "dry_run": dry_run, **result}
    except ToolError as exc:
        exit_code = exc.exit_code
        payload = {
            "ok": False,
            "tool": tool,
            "dry_run": dry_run,
            "error": {"code": exc.code, "message": exc.message, **exc.details},
        }
    except KeyboardInterrupt:
        exit_code = EXIT_ERROR
        payload = {"ok": False, "tool": tool, "dry_run": dry_run,
                   "error": {"code": "interrupted", "message": "abgebrochen"}}
    except Exception as exc:  # unerwartet -> sauber als JSON melden
        exit_code = EXIT_ERROR
        payload = {
            "ok": False,
            "tool": tool,
            "dry_run": dry_run,
            "error": {"code": "unexpected", "message": f"{type(exc).__name__}: {exc}",
                      "trace": traceback.format_exc(limit=5)},
        }
    payload["exit_code"] = exit_code
    logged = json.dumps(clean_json(payload), ensure_ascii=False, default=json_default)
    log_action(tool, "end", exit_code=exit_code,
               result=payload if len(logged) <= 20000 else {"truncated": logged[:20000]})
    emit(payload)
    return exit_code
