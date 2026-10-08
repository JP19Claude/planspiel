"""PreToolUse-Hook für Agentenläufe (eingebunden über agent-settings.json).

Zweite Verteidigungslinie neben den deny-Regeln: blockt offensichtliche
Versuche, Schutzgeräte über Bash zu verändern (STOP löschen, Werkzeuge
umschreiben, Siegel erneuern, Testmodus-Variable ändern, Zugangsdaten lesen).
Die Erkennung ist heuristisch. Das Siegel (integrity.py) fängt alles ab, was
hier durchrutscht.

Exit 2 = blockieren (Grund auf stderr), Exit 0 = normale Rechteprüfung.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import common  # noqa: E402

PROTECTED_DIRS = ["tools", "logs", ".auth", ".claude", "scheduler"]
PROTECTED_FILES = ["config.yaml", "selectors.yaml", "agent-settings.json", "CLAUDE.md", "requirements.txt",
                   "run_agent.sh", "run_agent.ps1", "run_weekly_review.sh", "run_weekly_review.ps1",
                   "STOP", ".env", ".gitignore"]
READ_FORBIDDEN = [".env", ".auth"]

BROWSER_AUTOMATION = re.compile(r"playwright|selenium|puppeteer|storage_state|webdriver", re.I)

HARD_DENY = [
    (re.compile(r"\bSTOP\b"), "Die STOP-Datei gehört dem Menschen – nicht anfassen."),
    (re.compile(r"BOERSE_|CLAUDECODE"), "Steuer-Variablen des Laufs (BOERSE_*, CLAUDECODE) sind tabu."),
    (re.compile(r"integrity(\.py)?\b.*\bseal\b", re.S), "Neu siegeln darf nur der Mensch."),
    (re.compile(r"\.boerse-agent"), "Das Siegel-Verzeichnis ist tabu."),
    (re.compile(r"(^|[\s/\\'\"=:<>])\.env\b"), "Zugangsdaten (.env) sind für den Agenten gesperrt."),
    (re.compile(r"(^|[\s/\\'\"=:<>])\.auth\b"), "Die gespeicherte Session (.auth) ist für den Agenten gesperrt."),
    (re.compile(r"disableAllHooks|dangerously-skip|--settings\b|--disallowed", re.I),
     "Änderungen an Claude-Code-Rechten/Hooks sind tabu."),
    (BROWSER_AUTOMATION,
     "Eigene Browser-Automatisierung ist verboten – Orders und Depot nur über tools/order.py und tools/portfolio.py."),
]
CODE_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".ps1", ".psm1", ".bat", ".cmd", ".rb", ".pl")

WRITE_CMDS = {
    "rm", "rmdir", "mv", "cp", "ln", "touch", "truncate", "dd", "chmod", "chown", "chattr", "install",
    "rsync", "tee", "patch", "unlink", "shred", "del", "erase", "copy", "move", "ren", "rename", "xcopy",
    "robocopy", "set-content", "add-content", "out-file", "remove-item", "move-item", "copy-item",
    "new-item", "rename-item", "clear-content", "set-itemproperty",
}
INLINE_INTERPRETERS = {"python", "python3", "py", "node", "perl", "ruby", "bash", "sh", "zsh", "dash",
                       "pwsh", "powershell", "deno", "php", "awk", "gawk", "sed"}
GIT_WRITE = {"checkout", "restore", "reset", "stash", "clean", "apply", "rm", "mv", "am", "revert", "merge",
             "pull", "switch", "cherry-pick", "rebase"}
SEPARATORS = {";", "&&", "||", "|", "&", "\n", "|&"}


def _norm(token: str) -> str:
    return token.replace("\\", "/")


def refers_protected(text: str, extra: list[str] | None = None) -> str | None:
    t = _norm(text)
    root = _norm(str(common.paths.root))
    for d in PROTECTED_DIRS:
        if re.search(r"(^|[\s/'\"=:(,])" + re.escape(d) + r"(/|$|[\s'\")])", t):
            return d + "/"
    for f in PROTECTED_FILES + (extra or []):
        if re.search(r"(^|[\s/'\"=:(,*])" + re.escape(f) + r"($|[\s'\");,])", t):
            return f
    if root and root in t and re.search(re.escape(root) + r"/?(['\"\s]|$)", t):
        return root  # ganzes Projektverzeichnis (z. B. rm -rf <projekt>)
    return None


def _mission_extra() -> list[str]:
    return ["mission.md"] if os.environ.get("BOERSE_RUN_MODE", "trading") != "review" else []


def _tokens(code: str) -> list[str]:
    lex = shlex.shlex(code, posix=True, punctuation_chars=";&|<>")
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:  # z. B. offene Anführungszeichen
        return code.split()


def _split_heredoc(command: str) -> tuple[str, str]:
    """Trennt den Befehl (erste Zeile) vom Heredoc-Inhalt."""
    if "<<" not in command.split("\n", 1)[0]:
        return command, ""
    first, _, rest = command.partition("\n")
    return first, rest


def _simple_commands(tokens: list[str]) -> list[list[str]]:
    cmds, cur = [], []
    for tok in tokens:
        if tok in SEPARATORS or (set(tok) <= set(";&|") and tok):
            if cur:
                cmds.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        cmds.append(cur)
    return cmds


def _cmd_name(token: str) -> str:
    name = _norm(token).rsplit("/", 1)[-1].lower()
    return re.sub(r"\.(exe|cmd|bat)$", "", name)


def check_bash(command: str) -> str | None:
    extra = _mission_extra()
    code, heredoc = _split_heredoc(command)
    tokens = _tokens(code)
    simple = _simple_commands(tokens)
    feeds_interpreter = False
    for cmd in simple:
        name = _cmd_name(cmd[0]) if cmd else ""
        if name in {"env", "sudo", "nohup", "time", "command", "exec", "xargs"} and len(cmd) > 1:
            cmd = cmd[1:]
            name = _cmd_name(cmd[0])
        args = cmd[1:]
        # Interpreter liest Code aus Heredoc/stdin (python - <<EOF, bash <<EOF)
        if name in INLINE_INTERPRETERS and heredoc:
            script_args = [a for a in args if not a.startswith("-") and a not in ("<<", "<")]
            if not script_args or args[:1] == ["-"]:
                feeds_interpreter = True
        if name.startswith("python") and "-m" in args:
            continue  # Module wie pip: unkritisch
        # Umleitungen auf geschützte Ziele
        for i, tok in enumerate(cmd):
            if ">" in tok and set(tok) <= set("<>&|0123456789") and i + 1 < len(cmd):
                hit = refers_protected(cmd[i + 1], extra)
                if hit:
                    return f"Schreiben nach '{hit}' ist gesperrt (geschützte Datei)."
        hit = None
        if name in WRITE_CMDS or (name == "git" and args and args[0] in GIT_WRITE):
            hit = next((h for a in args if (h := refers_protected(a, extra))), None)
        elif name in INLINE_INTERPRETERS and any(a in ("-c", "-e", "-i", "-command", "-Command", "-pe")
                                                 or a.startswith("-i") for a in args):
            hit = next((h for a in args if (h := refers_protected(a, extra))), None)
        elif name in {"cd", "pushd", "set-location"} and args:
            hit = refers_protected(args[0])
        if hit:
            return f"'{name}' auf '{hit}' ist gesperrt (Schutzgerät). Nutze die Werkzeuge in tools/."
    scan = code + ("\n" + heredoc if feeds_interpreter else "")
    for pattern, reason in HARD_DENY:
        if pattern.search(scan):
            return reason
    if os.environ.get("BOERSE_RUN_MODE") == "review" and re.search(r"order\.py", code):
        return "Im Wochen-Review werden keine Orders platziert."
    if feeds_interpreter:
        hit = refers_protected(heredoc, extra)
        if hit:
            return f"Skript berührt geschützten Pfad '{hit}' – gesperrt."
    return None


def _rel(path_str: str) -> str | None:
    try:
        p = Path(path_str)
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        p = p.resolve()
    except (OSError, ValueError):
        return None
    home_seal = (Path.home() / ".boerse-agent").resolve()
    if p == home_seal or home_seal in p.parents:
        return ".boerse-agent"
    try:
        return p.relative_to(common.paths.root.resolve()).as_posix()
    except ValueError:
        return None


def check_file_tool(tool: str, tool_input: dict) -> str | None:
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    if not path:
        return None
    rel = _rel(path)
    if rel is None:
        return None
    if rel == ".boerse-agent":
        return "Das Siegel-Verzeichnis ist tabu."
    first = rel.split("/", 1)[0]
    if tool in ("Read", "Grep", "Glob"):
        if first in READ_FORBIDDEN:
            return "Zugangsdaten/Session sind für den Agenten gesperrt."
        return None
    if first in PROTECTED_DIRS or rel in PROTECTED_FILES or rel in _mission_extra():
        return f"'{rel}' ist geschützt und darf vom Agenten nicht verändert werden."
    if rel.lower().endswith(CODE_SUFFIXES):
        content = " ".join(str(tool_input.get(k) or "") for k in ("content", "new_string"))
        content += " ".join(str(e.get("new_string") or "") for e in tool_input.get("edits") or [] if isinstance(e, dict))
        if BROWSER_AUTOMATION.search(content):
            return "Eigene Browser-Automatisierung ist verboten – Orders nur über tools/order.py."
        if refers_protected(content, _mission_extra()) and re.search(r"open\(|write|unlink|remove|rename|shutil",
                                                                       content):
            return "Skripte, die geschützte Dateien verändern, sind verboten."
    return None


def decide(event: dict) -> str | None:
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    if tool in ("Bash", "PowerShell"):
        return check_bash(str(tool_input.get("command", "")))
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Grep", "Glob"):
        return check_file_tool(tool, tool_input)
    return None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
        reason = decide(event)
    except Exception as exc:  # Hook-Fehler dürfen den Lauf nicht lahmlegen; Siegel bleibt
        common.log_action("hook", "error", error=f"{type(exc).__name__}: {exc}")
        return 0
    if reason:
        common.log_action("hook", "deny", tool_name=event.get("tool_name"), input=event.get("tool_input"), reason=reason)
        print(f"BLOCKIERT (Schutzgerät): {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
