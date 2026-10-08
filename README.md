# boerse-agent

Ein autonomer KI-Agent verwaltet dein Konto im **Planspiel Börse**. Der Agent ist **Claude Code
im Headless-Modus**. Er entscheidet bei jedem Lauf selbst, was er kauft und verkauft, recherchiert
mit seiner eigenen Websuche und führt die Orders über die Spiel-Website aus. Eine feste Strategie
gibt es nicht. Auftrag: [`mission.md`](mission.md), Handbuch des Agenten: [`CLAUDE.md`](CLAUDE.md).

```
 Aufgabenplaner / cron
        │
 run_agent.ps1|.sh ──► tools/run_agent.py ──► claude -p "Lies mission.md und journal.md …"
 run_weekly_review.*      │ STOP-Wache            --model (config.yaml)  --settings agent-settings.json
                          │ Siegel vorher/nachher        │
                          │ Protokoll logs/runs/         ├─ WebSearch / WebFetch  (Recherche)
                          ▼                              └─ Bash: python tools/*.py
                   logs/ (alles)                               │
                                                 ┌─────────────┼───────────────┬──────────────┐
                                           portfolio.py    order.py       quotes.py      journal.py
                                           (Website)       (Website)      (yfinance)     (journal.md)
```

## Schnellstart (Windows)

1. Installieren: [Python](https://www.python.org/downloads/) (Haken bei „Add python.exe to PATH“) und
   [Git for Windows](https://git-scm.com/download/win).
2. PowerShell öffnen und einfügen:
   ```powershell
   git clone -b claude/eager-lamport-7dvixq https://github.com/JP19Claude/planspiel $HOME\boerse-agent
   cd $HOME\boerse-agent
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```
3. Das Skript installiert alles, fragt (optional) nach den Zugangsdaten, öffnet den Browser zum
   Einloggen und danach zur Seitenanalyse. Am Ende öffnet sich der Ordner mit den Screenshots.

Linux/Mac: dasselbe mit `./setup.sh`.

## Inhalt

| Datei | Zweck |
|---|---|
| `tools/login.py` | Login per Playwright, Session als `storage_state` in `.auth/` |
| `tools/portfolio.py` | Depot, Cash, offene Orders, Orderhistorie von der Website |
| `tools/order.py` | Order platzieren, in der Orderübersicht prüfen, Screenshots vorher und nachher |
| `tools/quotes.py` | Kurse, Historie, Kennzahlen und News per yfinance |
| `tools/journal.py` | Journal anhängen und lesen |
| `tools/explore.py` | Seitenanalyse: Screenshots und Struktur für die Selektoren |
| `tools/integrity.py` | Siegel der Schutz-Dateien prüfen und erneuern |
| `tools/run_agent.py` | startet Claude Code mit allen Schutzgeräten |
| `tools/agent_hook.py` | Hook, der Manipulationsversuche des Agenten blockt |
| `config.yaml` | Modelle, Spielzeitraum, Handelszeiten, Browser |
| `selectors.yaml` | Selektoren der Spielseite (**noch festzulegen, siehe Schritt 1**) |
| `agent-settings.json` | Claude-Code-Rechte des Agenten (deny-Regeln und Hook) |
| `mission.md` | Auftrag (der Wochen-Review darf Lehren anhängen) |
| `run_agent.ps1/.sh`, `run_weekly_review.ps1/.sh` | Start-Skripte |
| `scheduler/` | Aufgabenplaner (Windows) und crontab (Linux/Mac) |

## Voraussetzungen

- **Python 3.11+**
- **Claude Code CLI**, einmal interaktiv angemeldet (`claude` starten und einloggen) oder
  `ANTHROPIC_API_KEY` gesetzt. Prüfen mit `claude --version`.
- **Windows:** [Git for Windows](https://git-scm.com/download/win). Claude Code braucht Git Bash für sein Bash-Tool.
- Ein Konto im Planspiel Börse (Registrierungscode von der Sparkasse).

## Installation

**Windows (PowerShell):**

```powershell
git clone https://github.com/JP19Claude/planspiel boerse-agent
cd boerse-agent
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
copy .env.example .env      # dann .env mit Benutzername/Passwort füllen
.venv\Scripts\python tools\integrity.py seal
```

**Linux/Mac:**

```bash
git clone https://github.com/JP19Claude/planspiel boerse-agent
cd boerse-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp .env.example .env        # dann .env füllen
.venv/bin/python tools/integrity.py seal
```

Alle folgenden Befehle gehen davon aus, dass das venv aktiv ist (`.venv\Scripts\Activate.ps1`
bzw. `source .venv/bin/activate`). Sonst `python` durch `.venv/bin/python` ersetzen.

> Ohne Playwright-Chromium geht es auch mit dem installierten Edge/Chrome:
> in `config.yaml` `browser.channel: msedge` (oder `chrome`) setzen.

---

## Vorgehen in vier Schritten

### Schritt 1: Login und Depot lesen

1. **Manuell einloggen.** Der Browser öffnet sich sichtbar, du loggst dich ein (Captcha/2FA kein
   Problem) und drückst danach im Terminal ENTER. Die Session landet in `.auth/storage_state.json`.
   ```
   python tools/login.py --manual
   ```
2. **Seiten analysieren** (Schritt 6 der Anforderungen). Der Browser öffnet sich mit deiner Session.
   Klick dich selbst zu Depot, Ordermaske (**nicht abschicken**) und Orderübersicht. Im Terminal
   erfasst ENTER die aktuelle Seite, Name+ENTER erfasst sie mit Namen, `q` beendet.
   ```
   python tools/explore.py --interactive
   ```
   Ergebnis in `logs/explore/<zeit>/`: Screenshots, HTML und JSON mit Feldern, Buttons, Tabellen,
   iframes und Selektor-Vorschlägen, dazu `report.md`. **Schick mir die Screenshots und JSON-Dateien.**
   Wir legen die Selektoren dann gemeinsam in `selectors.yaml` fest. Vorher prüfen: Sie enthalten deine Depotdaten.
3. Nach dem Festlegen der Selektoren: `python tools/integrity.py seal`.
4. **Depot lesen:**
   ```
   python tools/login.py --check
   python tools/portfolio.py --screenshot
   ```
   Vergleiche Cash, Positionen und Orders mit dem, was du im Spiel siehst.

### Schritt 2: Eine winzige Test-Order

```
python tools/order.py --symbol DE0007164600 --qty 1 --side buy --dry-run --headed
```
Füllt die Ordermaske sichtbar aus, schickt aber **nicht** ab. Screenshot in `logs/screenshots/`.
Wenn alles stimmt, setzt du in `selectors.yaml` `confirmed: true`, siegelst neu und platzierst
innerhalb der Handelszeit eine echte Mini-Order:
```
python tools/order.py --symbol DE0007164600 --qty 1 --side buy
```
Das JSON sollte `"status": "placed"` zeigen. Prüfe selbst im Spiel, ob die Order angekommen ist.
Screenshots vorher und nachher und von der Orderübersicht liegen in `logs/screenshots/<datum>/`.

### Schritt 3: Agent-Lauf von Hand

Zuerst als Testlauf. Alle Werkzeuge laufen dann im Testmodus, Orders werden nur simuliert:
```
.\run_agent.ps1 -DryRun          # Windows
./run_agent.sh --dry-run         # Linux/Mac
```
Danach `journal.md` lesen. Wenn es passt, den echten Lauf starten:
```
.\run_agent.ps1                  # bzw. ./run_agent.sh
```
Den genauen claude-Befehl siehst du mit `.\run_agent.ps1 -ShowCommand`. Im Kern ist es
```
claude -p "Lies mission.md und journal.md und führe einen Handelslauf aus" --model claude-sonnet-5-5 --allowedTools "Bash,Read,Write,Edit,WebSearch,WebFetch"
```
plus `--settings agent-settings.json` (Schutzregeln) und `--output-format stream-json --verbose`
(vollständiges Protokoll in `logs/runs/`). Den Wochen-Review startest du von Hand mit
`.\run_weekly_review.ps1` bzw. `./run_weekly_review.sh` (Opus).

### Schritt 4: Zeitplan

Handelslauf werktags **10:00 und 16:30**, Review **sonntags 18:00**.

**Windows-Aufgabenplaner, per Skript:**
```powershell
powershell -ExecutionPolicy Bypass -File scheduler\install_tasks.ps1
Start-ScheduledTask -TaskPath "\boerse-agent\" -TaskName "boerse-agent Handelslauf"   # Testlauf
```
Entfernen: `scheduler\uninstall_tasks.ps1`.

**Windows-Aufgabenplaner, von Hand:**
1. Aufgabenplanung öffnen, dann *Aufgabe erstellen…*. Name: `boerse-agent Handelslauf`.
2. *Allgemein*: „Nur ausführen, wenn der Benutzer angemeldet ist“. So nutzt der Lauf dein Claude-Login.
3. *Trigger*: *Neu…*, *Wöchentlich*, Mo–Fr, 10:00. Einen zweiten Trigger genauso für 16:30 anlegen.
4. *Aktionen*: *Programm starten*, Programm `powershell.exe`, Argumente
   `-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Pfad\zu\boerse-agent\run_agent.ps1"`,
   *Starten in*: `C:\Pfad\zu\boerse-agent`.
5. *Einstellungen*: „Aufgabe so schnell wie möglich nach einem verpassten Start ausführen“,
   „Aufgabe beenden, falls länger als 1 Stunde“, „Keine neue Instanz starten“.
6. Dasselbe für `boerse-agent Wochen-Review`: wöchentlich sonntags 18:00 mit `run_weekly_review.ps1`.

**cron (Linux/Mac):** Vorlage in `scheduler/crontab.example`. Pfade und `PATH` anpassen (`which claude`),
dann `crontab -e`:
```
CRON_TZ=Europe/Berlin
0 10 * * 1-5   /home/DU/boerse-agent/run_agent.sh         >> /home/DU/boerse-agent/logs/cron.log 2>&1
30 16 * * 1-5  /home/DU/boerse-agent/run_agent.sh         >> /home/DU/boerse-agent/logs/cron.log 2>&1
0 18 * * 0     /home/DU/boerse-agent/run_weekly_review.sh >> /home/DU/boerse-agent/logs/cron.log 2>&1
```
Der Rechner muss zu diesen Zeiten an sein. Läufe, die sich überschneiden würden, verhindert die Sperrdatei `logs/run.lock`.

---

## Schutzgeräte

Sie stehen im Code und nicht in `mission.md`. Der Agent kann sie nicht abschalten.

| Schutz | Umsetzung |
|---|---|
| **STOP-Datei** | Liegt eine Datei `STOP` im Projektordner, startet kein Lauf und `order.py` bricht ab (geprüft vor dem Browser und direkt vor dem Absende-Klick). Ein laufender Agent wird innerhalb von etwa 1 s beendet. Im Agentenlauf brechen auch die anderen Werkzeuge ab. Von Hand darfst du bei STOP noch lesen. Inhalt der Datei = Grund (optional). |
| **Protokoll** | `logs/actions.jsonl` (jeder Werkzeugaufruf mit Argumenten und Ergebnis), `logs/runs/<id>.jsonl` (komplettes Agenten-Transkript inkl. aller Tool-Aufrufe), `logs/runs/<id>.summary.json`, `logs/screenshots/`, `logs/portfolio_history.jsonl` |
| **Handelszeiten** | `order.py` erlaubt Orders nur Mo–Fr 08:00–22:00 (Europe/Berlin), nicht an Feiertagen und nur im Spielzeitraum (`config.yaml`). Geprüft vor dem Öffnen und direkt vor dem Absenden. |
| **--dry-run** | Gibt es bei allen Werkzeugen. Bei `order.py` wird das Formular gefüllt, aber nicht abgeschickt. Der Runner-Testlauf setzt `BOERSE_DRY_RUN=1` für alle Werkzeuge des Agenten. |
| **Abbruch statt Raten** | Fehlende oder mehrdeutige Elemente, ein falsches Papier in der Ordermaske oder unerwartete Spalten führen zum Abbruch vor dem Absenden (Exit 3). Nach dem Absenden wird nie automatisch wiederholt. |
| **Selektoren unbestätigt** | Solange `selectors.yaml` `confirmed: false` hat, gibt es keine echte Order. |

**Warum der Agent sie nicht ändern kann:**
1. **deny-Regeln** in `agent-settings.json`: Edit/Write auf `tools/`, `config.yaml`, `selectors.yaml`, `logs/`,
   `STOP`, Start-Skripte und mehr sind verboten, `.env`/`.auth/` sind nicht lesbar. Die Regeln gelten
   auch für `sed`, `tee` und Umleitungen in Bash.
2. **Hook** `tools/agent_hook.py`: blockt Bash-Befehle, die STOP anfassen, geschützte Dateien
   verändern, das Siegel erneuern, `BOERSE_*`-Variablen setzen oder eigene Browser-Automatisierung starten.
3. **Siegel** `tools/integrity.py`: SHA-256 aller Schutz-Dateien, gespeichert **außerhalb** des
   Projekts (`~/.boerse-agent/`). Es wird vor jedem Lauf, vor jeder Order und nach jedem Lauf geprüft. Ändert
   der Agent trotzdem etwas (auch auf Umwegen), legt der Runner STOP an. Neu siegeln geht nur
   interaktiv am Terminal und nicht aus Claude Code heraus.
4. **mission.md:** Im Handelslauf schreibgeschützt. Der Wochen-Review darf nur Lehren anhängen.
   Ändert er den Kernauftrag, stellt der Runner ihn aus dem Siegel wieder her.

Ehrlich gesagt: Ein Agent mit vollem Bash-Zugriff könnte theoretisch Umwege finden, die der Hook nicht
erkennt. Das Siegel bemerkt solche Änderungen trotzdem spätestens nach dem Lauf und stoppt alles
Weitere. Willst du es noch strenger, beschränke in `config.yaml` `agent.allowed_tools` auf
`"Bash(python tools/*),Read,Write,Edit,WebSearch,WebFetch"`.

**Nach eigenen Änderungen** (z. B. an `selectors.yaml` oder `config.yaml`) oder nach `git pull`:
```
python tools/integrity.py verify
python tools/integrity.py seal      # fragt nach, Eingabe: ja
```

**Anhalten:** `STOP` anlegen (`New-Item STOP` / `touch STOP`). **Weiter:** `STOP` löschen.

## Exit-Codes der Werkzeuge

`0` ok · `1` Fehler · `2` Schutzgerät · `3` unerwarteter Seitenzustand · `4` Order abgeschickt, aber
unbestätigt (manuell prüfen) · `5` Login nötig · `6` von der Website abgelehnt

## Tests

```
python -m pytest
```
Getestet werden die Order-Logik und alle Abbruchbedingungen mit gemockter Seite, dazu Handelszeiten,
STOP, Siegel, Hook, Journal, yfinance-Auswertung (gemockt) und der Runner (mit Fake-CLI: STOP
während des Laufs, Manipulation, mission.md). `tests/test_browser_fake_site.py` fährt echtes
Chromium gegen eine lokale Fake-Spielseite (`tests/fake_site/`). Ohne Chromium wird dieser Test übersprungen.

## Fehlersuche

- **`login_required` / Exit 5:** Session abgelaufen, also `python tools/login.py --manual` ausführen.
- **`integrity` / Lauf startet nicht:** `python tools/integrity.py verify` zeigt die geänderten
  Dateien. Wenn du sie geändert hast, neu siegeln.
- **STOP wurde automatisch angelegt:** Lies den Inhalt von `STOP` und prüfe die Änderungen mit
  `git diff`. Gegebenenfalls `git checkout -- <datei>`, dann neu siegeln und STOP löschen.
- **Selektoren passen nicht mehr** (Website geändert): `python tools/explore.py --interactive`,
  dann `selectors.yaml` anpassen und neu siegeln.
- **Claude-CLI nicht gefunden** (Aufgabenplaner/cron): `agent.claude_command` in `config.yaml` auf den
  vollen Pfad setzen (`where claude` / `which claude`).
- **Kosten begrenzen:** `agent.max_budget_usd` in `config.yaml`.
