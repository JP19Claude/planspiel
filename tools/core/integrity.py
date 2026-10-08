"""Siegel über alle Schutz-Dateien.

`python tools/integrity.py seal` speichert SHA-256-Hashes der geschützten
Dateien AUSSERHALB des Projektordners (~/.boerse-agent/<projekt>/). Vor jedem
Lauf und vor jeder Order wird verglichen. Ändert der Agent eine geschützte
Datei (auch auf Umwegen über Bash/Python), fällt das auf: Der Lauf bricht ab,
der Runner legt STOP an.

Zusätzlich wird der Kern von mission.md (alles vor "## Lehren") gesiegelt.
Der Wochen-Review darf Lehren anhängen, aber den Auftrag nicht umschreiben.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from core import common

SEAL_BASE = Path.home() / ".boerse-agent"
SEAL_VERSION = 1

# Muster relativ zum Projektordner (Path.glob-Syntax)
PROTECTED_GLOBS = [
    "tools/**/*.py",
    "config.yaml",
    "selectors.yaml",
    "agent-settings.json",
    "CLAUDE.md",
    "requirements.txt",
    "run_agent.sh",
    "run_agent.ps1",
    "run_weekly_review.sh",
    "run_weekly_review.ps1",
    "scheduler/*",
    ".claude/**/*",
]

LESSONS_MARKER = re.compile(r"^##\s+Lehren", re.MULTILINE)


def seal_dir(root: Path | None = None) -> Path:
    root = (root or common.paths.root).resolve()
    key = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
    return SEAL_BASE / f"{root.name}-{key}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_files(root: Path | None = None) -> list[str]:
    root = root or common.paths.root
    found: set[str] = set()
    for pattern in PROTECTED_GLOBS:
        for p in root.glob(pattern):
            if p.is_file() and "__pycache__" not in p.parts:
                found.add(p.relative_to(root).as_posix())
    return sorted(found)


def mission_parts(text: str) -> tuple[str, str]:
    """Teilt mission.md in (Kernauftrag, Lehren-Abschnitt)."""
    text = text.replace("\r\n", "\n")
    m = LESSONS_MARKER.search(text)
    if not m:
        return text.strip(), ""
    return text[: m.start()].strip(), text[m.start():].strip()


def _mission_core(root: Path) -> str | None:
    mission = root / "mission.md"
    if not mission.exists():
        return None
    return mission_parts(mission.read_text(encoding="utf-8"))[0]


def seal(root: Path | None = None) -> dict:
    root = root or common.paths.root
    files = {rel: _sha256(root / rel) for rel in protected_files(root)}
    core = _mission_core(root)
    data = {
        "version": SEAL_VERSION,
        "project_root": str(root.resolve()),
        "sealed_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": files,
        "mission_core_sha256": hashlib.sha256(core.encode("utf-8")).hexdigest() if core is not None else None,
    }
    target = seal_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    (target / "seal.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if core is not None:
        (target / "mission_core.md").write_text(core + "\n", encoding="utf-8")
    return {"sealed": True, "files": len(files), "seal_dir": str(target)}


def load_seal(root: Path | None = None) -> dict | None:
    f = seal_dir(root) / "seal.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def verify(root: Path | None = None) -> dict:
    """Vergleicht den Ist-Zustand mit dem Siegel."""
    root = root or common.paths.root
    data = load_seal(root)
    if data is None:
        return {"ok": False, "sealed": False,
                "message": "Noch nicht gesiegelt. Bitte einmal 'python tools/integrity.py seal' ausführen."}
    expected: dict[str, str] = data.get("files", {})
    current = protected_files(root)
    changed, missing = [], []
    for rel, digest in expected.items():
        p = root / rel
        if not p.exists():
            missing.append(rel)
        elif _sha256(p) != digest:
            changed.append(rel)
    added = [rel for rel in current if rel not in expected]
    core = _mission_core(root)
    core_sha = hashlib.sha256(core.encode("utf-8")).hexdigest() if core is not None else None
    mission_changed = data.get("mission_core_sha256") != core_sha
    ok = not (changed or missing or added)
    result = {
        "ok": ok,
        "sealed": True,
        "sealed_at": data.get("sealed_at"),
        "changed": changed,
        "missing": missing,
        "added": added,
        "mission_core_changed": mission_changed,
    }
    if not ok:
        result["message"] = ("Geschützte Dateien weichen vom Siegel ab. Wenn DU sie geändert hast: "
                             "prüfen und neu siegeln mit 'python tools/integrity.py seal'.")
    return result


def restore_mission_core(root: Path | None = None) -> dict:
    """Stellt den gesiegelten Kernauftrag wieder her, behält angehängte Lehren."""
    root = root or common.paths.root
    backup = seal_dir(root) / "mission_core.md"
    if not backup.exists():
        return {"restored": False, "message": "keine Sicherung des Kernauftrags vorhanden"}
    core = backup.read_text(encoding="utf-8").strip()
    mission = root / "mission.md"
    lessons = ""
    if mission.exists():
        lessons = mission_parts(mission.read_text(encoding="utf-8"))[1]
    text = core + "\n" + (f"\n{lessons}\n" if lessons else "")
    mission.write_text(text, encoding="utf-8")
    return {"restored": True, "kept_lessons": bool(lessons)}
