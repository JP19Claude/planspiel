"""Siegel der Schutz-Dateien verwalten (nur für den Menschen).

    python tools/integrity.py verify   # Ist alles unverändert?
    python tools/integrity.py seal     # nach eigenen Änderungen neu siegeln (fragt nach)

Siegeln geht nur interaktiv an einem echten Terminal und nicht aus einem
Claude-Code-Lauf heraus. Der Agent kann sich so nicht selbst freischalten.
"""
from __future__ import annotations

import argparse
import os
import sys

from core import common, integrity


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Siegel der Schutz-Dateien")
    p.add_argument("cmd", choices=["verify", "seal", "list"], nargs="?", default="verify")
    return p


def seal_allowed() -> tuple[bool, str]:
    if os.environ.get("CLAUDECODE") or common.in_agent_run():
        return False, "Siegeln ist innerhalb von Claude Code / eines Agentenlaufs gesperrt."
    if sys.stdin is None or not sys.stdin.isatty():
        return False, "Siegeln nur an einem interaktiven Terminal."
    return True, ""


def handler(args: argparse.Namespace, dry_run: bool) -> dict:
    if args.cmd == "list":
        return {"protected_files": integrity.protected_files(), "seal_dir": str(integrity.seal_dir())}
    if args.cmd == "verify":
        result = integrity.verify()
        return {**result, "exit_code": common.EXIT_OK if result["ok"] else common.EXIT_BLOCKED}
    ok, why = seal_allowed()
    if not ok:
        raise common.GuardBlocked(why, guard="integrity")
    before = integrity.verify()
    if before.get("sealed"):
        print("Abweichungen zum alten Siegel:", file=sys.stderr)
        for key in ("changed", "missing", "added"):
            for rel in before.get(key, []):
                print(f"  {key:8s} {rel}", file=sys.stderr)
        if before.get("mission_core_changed"):
            print("  changed  mission.md (Kernauftrag)", file=sys.stderr)
    print("Aktuellen Stand als vertrauenswürdig siegeln? Tippe 'ja': ", end="", file=sys.stderr, flush=True)
    if input().strip().lower() != "ja":
        return {"sealed": False, "message": "abgebrochen", "exit_code": common.EXIT_ERROR}
    if dry_run:
        return {"sealed": False, "message": "Testmodus – nicht gesiegelt", "previous": before}
    return {**integrity.seal(), "previous": before}


if __name__ == "__main__":
    sys.exit(common.run_cli("integrity", build_parser(), handler))
