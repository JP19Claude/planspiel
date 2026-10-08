"""Startet einen Agentenlauf (Claude Code headless) mit allen Schutzgeräten.

    python tools/run_agent.py --mode trading            # Handelslauf (Sonnet)
    python tools/run_agent.py --mode review             # Wochen-Review (Opus)
    python tools/run_agent.py --mode trading --dry-run  # Testlauf: Orders nur simuliert
    python tools/run_agent.py --mode trading --show-command

Ablauf:
  1. STOP?  -> sofort Ende
  2. Siegel prüfen -> bei Abweichung kein Lauf
  3. Sperrdatei gegen parallele Läufe
  4. claude -p "<Prompt>" --model <aus config.yaml> --allowedTools ...
     --settings agent-settings.json (deny-Regeln + Hook)
     Ausgabe komplett nach logs/runs/<id>.jsonl
  5. Während des Laufs: STOP-Datei angelegt -> Prozess wird sofort beendet
  6. Danach: Siegel prüfen. Hat der Agent Schutz-Dateien verändert, wird STOP angelegt.
     Wurde der Kernauftrag in mission.md verändert, wird er wiederhergestellt.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from core import common, guards, integrity

EXIT_STOPPED = 2


def claude_command(cfg: dict, mode: str, dry_run: bool) -> list[str]:
    acfg = cfg["agent"]
    model = cfg["models"]["weekly_review" if mode == "review" else "trading_run"]
    prompt = acfg["prompts"][mode]
    if dry_run:
        prompt += (" — TESTLAUF: BOERSE_DRY_RUN ist gesetzt, alle Werkzeuge laufen im Testmodus, "
                   "Orders werden nur simuliert. Verhalte dich sonst genau wie im echten Lauf.")
    command = acfg.get("claude_command") or "claude"
    exe = [str(c) for c in command] if isinstance(command, list) else resolve_claude(str(command))
    cmd = exe + [
        "-p", prompt,
        "--model", model,
        "--allowedTools", acfg["allowed_tools"],
        "--settings", str(common.paths.root / "agent-settings.json"),
        "--output-format", "stream-json",
        "--verbose",
    ]
    if mode == "trading":
        cmd += ["--disallowedTools", "Edit(/mission.md)"]
    if acfg.get("max_budget_usd"):
        cmd += ["--max-budget-usd", str(acfg["max_budget_usd"])]
    cmd += [str(a) for a in (acfg.get("extra_args") or [])]
    return cmd


def resolve_claude(command: str) -> list[str]:
    """Findet die Claude-CLI. Unter Windows wird ein npm-.cmd-Shim über node
    gestartet (sonst gehen Umlaute im Prompt über cmd.exe kaputt)."""
    found = shutil.which(command) or command
    if os.name == "nt" and found.lower().endswith((".cmd", ".bat")):
        cli = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        node = shutil.which("node")
        if cli.exists() and node:
            return [node, str(cli)]
    return [found]


# ---------------------------------------------------------------- Sperrdatei

def acquire_lock(timeout_minutes: float) -> Path | None:
    lock = common.paths.logs / "run.lock"
    common.paths.logs.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        age_min = (time.time() - lock.stat().st_mtime) / 60
        if age_min < timeout_minutes + 10:
            return None
        lock.unlink(missing_ok=True)  # verwaist
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({"pid": os.getpid(), "started": dt.datetime.now().isoformat()}))
    return lock


# ---------------------------------------------------------------- Prozess

def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def describe(event: dict) -> str | None:
    """Kurze Konsolenzeile für ein stream-json-Ereignis."""
    etype = event.get("type")
    if etype == "assistant":
        parts = []
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                parts.append("  " + block["text"].strip().replace("\n", "\n  "))
            elif block.get("type") == "tool_use":
                inp = block.get("input") or {}
                detail = inp.get("command") or inp.get("file_path") or inp.get("query") or inp.get("url") or ""
                parts.append(f"  > {block.get('name')}: {str(detail).splitlines()[0][:160] if detail else ''}")
        return "\n".join(parts) or None
    if etype == "result":
        cost = event.get("total_cost_usd")
        return (f"  = Ergebnis: {event.get('subtype')} | Runden: {event.get('num_turns')} | "
                f"Kosten: {cost if cost is not None else '?'} USD")
    return None


def pump(stream, log_path: Path, events: list) -> None:
    with log_path.open("a", encoding="utf-8") as log:
        for raw in iter(stream.readline, ""):
            log.write(raw)
            log.flush()
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print("  " + line[:300], flush=True)
                continue
            if event.get("type") == "result":
                events.append(event)
            text = describe(event)
            if text:
                print(text, flush=True)


def journal_note(title: str, text: str) -> None:
    try:
        from journal import append
        append(title, text)
    except Exception as exc:  # pragma: no cover
        common.log_action("runner", "journal_error", error=str(exc))


def run(mode: str, dry_run: bool, show_command: bool = False, poll_seconds: float = 1.0) -> int:
    common.configure_stdout()
    cfg = common.load_config()
    acfg = cfg["agent"]
    rid = dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + mode + "_" + uuid.uuid4().hex[:6]
    cmd = claude_command(cfg, mode, dry_run)
    if show_command:
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        return 0

    def log(event: str, **data):
        common.log_action("runner", event, **{"run_id": rid, "mode": mode, "dry_run": dry_run, **data})
        print(f"[runner] {event}: " + ", ".join(f"{k}={v}" for k, v in data.items() if k != "command"),
              flush=True)

    # 1. STOP
    if guards.stop_active():
        log("abort_stop", reason=guards.stop_reason())
        return EXIT_STOPPED
    # 2. Siegel
    seal = integrity.verify()
    if not seal["ok"]:
        log("abort_integrity", **{k: seal.get(k) for k in ("message", "changed", "missing", "added")})
        return EXIT_STOPPED
    if seal.get("mission_core_changed"):
        restored = integrity.restore_mission_core()
        log("mission_core_restored_before_run", **restored)
    # 3. Sperre
    timeout_min = float(acfg.get("timeout_minutes") or 45)
    lock = acquire_lock(timeout_min)
    if lock is None:
        log("abort_locked", message="Es läuft bereits ein Agentenlauf (logs/run.lock).")
        return EXIT_STOPPED

    common.paths.runs.mkdir(parents=True, exist_ok=True)
    log_path = common.paths.runs / f"{rid}.jsonl"
    journal_before = common.paths.journal.stat().st_mtime if common.paths.journal.exists() else None
    env = dict(os.environ)
    env.update({"BOERSE_RUN_ID": rid, "BOERSE_RUN_MODE": mode})
    env.pop("BOERSE_DRY_RUN", None)
    if dry_run:
        env["BOERSE_DRY_RUN"] = "1"
    venv_bin = Path(sys.executable).parent
    env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    log("start", model=cmd[cmd.index("--model") + 1], log=str(log_path.relative_to(common.paths.root)),
        command=cmd)
    started = time.monotonic()
    reason = "finished"
    events: list = []
    try:
        popen_kw: dict = {}
        if os.name == "nt":
            popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            popen_kw["start_new_session"] = True
        try:
            proc = subprocess.Popen(cmd, cwd=common.paths.root, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", **popen_kw)
        except FileNotFoundError:
            log("abort_no_claude", message=f"Claude-CLI nicht gefunden: {cmd[0]} (config.yaml agent.claude_command)")
            return 1
        reader = threading.Thread(target=pump, args=(proc.stdout, log_path, events), daemon=True)
        reader.start()
        while proc.poll() is None:
            if guards.stop_active():
                reason = "stop"
                log("stop_detected", message="STOP-Datei angelegt – Lauf wird sofort beendet")
                kill_tree(proc)
                break
            if time.monotonic() - started > timeout_min * 60:
                reason = "timeout"
                log("timeout", minutes=timeout_min)
                kill_tree(proc)
                break
            time.sleep(poll_seconds)
        proc.wait()
        reader.join(timeout=10)
        exit_code = proc.returncode
    finally:
        lock.unlink(missing_ok=True)

    # 6. Nachkontrolle
    after = integrity.verify()
    tampered = not after["ok"]
    if tampered:
        common.paths.stop.write_text(
            f"Automatisch angelegt am {dt.datetime.now():%Y-%m-%d %H:%M} von run_agent.py (Lauf {rid}):\n"
            f"Geschützte Dateien wurden während des Laufs verändert: "
            f"{after.get('changed')} {after.get('missing')} {after.get('added')}\n"
            "Bitte prüfen (git diff), ggf. zurücksetzen, neu siegeln und STOP löschen.\n", encoding="utf-8")
        log("tamper_detected", changed=after.get("changed"), missing=after.get("missing"), added=after.get("added"))
        journal_note("Schutzgerät ausgelöst",
                     "Während des Laufs wurden geschützte Dateien verändert. STOP wurde angelegt; "
                     f"ein Mensch muss prüfen. Details: {after}")
    if after.get("mission_core_changed"):
        restored = integrity.restore_mission_core()
        log("mission_core_restored", **restored)
        journal_note("mission.md zurückgesetzt",
                     "Der Kernauftrag in mission.md wurde verändert und aus dem Siegel wiederhergestellt. "
                     "Lehren dürfen nur im Abschnitt '## Lehren …' ergänzt werden.")

    journal_after = common.paths.journal.stat().st_mtime if common.paths.journal.exists() else None
    if reason == "stop":
        journal_note("Lauf durch STOP abgebrochen", f"Lauf {rid} wurde wegen der STOP-Datei sofort beendet.")
    elif reason == "timeout":
        journal_note("Lauf wegen Zeitüberschreitung abgebrochen", f"Lauf {rid} lief länger als {timeout_min} Minuten.")
    elif journal_after == journal_before:
        journal_note("Lauf ohne Journal-Eintrag beendet",
                     f"Lauf {rid} endete mit Exit-Code {exit_code}, ohne dass der Agent ins Journal schrieb. "
                     f"Protokoll: logs/runs/{rid}.jsonl")

    result = events[-1] if events else {}
    summary = {"run_id": rid, "mode": mode, "dry_run": dry_run, "reason": reason, "exit_code": exit_code,
               "duration_s": round(time.monotonic() - started, 1), "tampered": tampered,
               "cost_usd": result.get("total_cost_usd"), "num_turns": result.get("num_turns"),
               "result_subtype": result.get("subtype")}
    (common.paths.runs / f"{rid}.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log("end", **summary)
    if tampered or reason != "finished":
        return EXIT_STOPPED
    return 0 if exit_code == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Agentenlauf starten")
    p.add_argument("--mode", choices=["trading", "review"], default="trading")
    p.add_argument("--dry-run", action="store_true", help="Testlauf: alle Werkzeuge im Testmodus")
    p.add_argument("--show-command", action="store_true", help="nur den claude-Befehl anzeigen")
    args = p.parse_args(argv)
    return run(args.mode, args.dry_run, args.show_command)


if __name__ == "__main__":
    sys.exit(main())
