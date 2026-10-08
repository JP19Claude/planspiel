"""Journal: Einträge an journal.md anhängen und die letzten lesen.

    python tools/journal.py tail --n 5
    python tools/journal.py add --title "Kauf SAP" --text "Was, warum, was ich lerne …"
    python tools/journal.py add --title "Handelslauf" <<'EOF'
    **Was:** …
    **Warum:** …
    **Lehre:** …
    EOF

Es wird nur angehängt, nie überschrieben.
"""
from __future__ import annotations

import argparse
import re
import sys

from core import common, guards

HEADER = re.compile(r"^## ", re.MULTILINE)
MODE_NAMES = {"trading": "Handelslauf", "review": "Wochen-Review"}


def parse_entries(text: str) -> list[dict]:
    starts = [m.start() for m in HEADER.finditer(text)]
    entries = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[start:end].strip()
        header, _, body = block.partition("\n")
        entries.append({"header": header[3:].strip(), "body": body.strip()})
    return entries


def tail(n: int) -> dict:
    f = common.paths.journal
    if not f.exists():
        return {"entries": [], "total": 0, "message": "Journal ist noch leer"}
    entries = parse_entries(f.read_text(encoding="utf-8"))
    return {"entries": entries[-n:] if n > 0 else entries, "total": len(entries)}


def format_entry(title: str, text: str, cfg: dict) -> str:
    stamp = common.now(cfg).strftime("%Y-%m-%d %H:%M")
    parts = [stamp]
    mode = common.run_mode()
    if mode:
        parts.append(MODE_NAMES.get(mode, mode))
    if common.env_dry_run():
        parts.append("TESTLAUF")
    parts.append(title.strip() or "Eintrag")
    header = "## " + " · ".join(parts)
    meta = f"<!-- run_id: {common.run_id()} -->\n" if common.run_id() else ""
    return f"{header}\n{meta}\n{text.strip()}\n"


def append(title: str, text: str, dry_run: bool = False) -> dict:
    cfg = common.load_config()
    entry = format_entry(title, text, cfg)
    if dry_run:
        return {"would_append": entry, "written": False}
    f = common.paths.journal
    prefix = ""
    if not f.exists():
        prefix = "# Journal\n\nNeueste Einträge stehen unten.\n\n"
    else:
        existing = f.read_text(encoding="utf-8")
        if existing and not existing.endswith("\n\n"):
            prefix = "\n" if existing.endswith("\n") else "\n\n"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(prefix + entry)
    return {"appended": entry, "written": True}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Journal lesen und ergänzen")
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("tail", help="letzte Einträge ausgeben")
    t.add_argument("--n", type=int, default=5)
    a = sub.add_parser("add", help="Eintrag anhängen")
    a.add_argument("--title", required=True)
    a.add_argument("--text", help="Text (sonst aus --file oder stdin)")
    a.add_argument("--file", help="Text aus Datei lesen")
    a.add_argument("--dry-run", dest="dry_run_sub", action="store_true", help="nichts schreiben")
    return p


def handler(args: argparse.Namespace, dry_run: bool) -> dict:
    cmd = args.cmd or "tail"
    if cmd == "tail":
        warning = guards.check_stop(strict=guards.stop_strict_for_reader())
        out = tail(getattr(args, "n", 5))
        if warning:
            out["warnings"] = [warning]
        return out
    guards.check_stop(strict=common.in_agent_run())
    text = args.text
    if text is None and args.file:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    if text is None:
        if sys.stdin is None or sys.stdin.isatty():
            raise common.ToolError("Kein Text: --text, --file oder stdin verwenden")
        text = sys.stdin.read()
    if not text.strip():
        raise common.ToolError("Leerer Journal-Eintrag")
    # Im Testlauf (BOERSE_DRY_RUN) wird trotzdem geschrieben – markiert als TESTLAUF –,
    # damit der Mensch das Journal lesen kann. Nur das explizite --dry-run schreibt nicht.
    explicit = bool(getattr(args, "dry_run", False) or getattr(args, "dry_run_sub", False))
    return append(args.title, text, dry_run=explicit)


if __name__ == "__main__":
    sys.exit(common.run_cli("journal", build_parser(), handler))
