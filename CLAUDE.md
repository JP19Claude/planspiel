# boerse-agent – Handbuch für den Handelsagenten

Du läufst headless über `tools/run_agent.py` (gestartet von `run_agent.*` bzw.
`run_weekly_review.*`). Dein Auftrag steht in **mission.md**, dein Gedächtnis ist
**journal.md**. Diese Datei erklärt Werkzeuge, Regeln und Schutzgeräte.

## Ablauf eines Handelslaufs

1. **Journal lesen:** `python tools/journal.py tail --n 8`. Die Datei wird lang, deshalb `tail`
   statt die ganze Datei. Bei Bedarf mehr Einträge.
2. **Depot und Cash holen:** `python tools/portfolio.py`. Die Website ist die Wahrheit, schätze
   nichts aus dem Journal.
3. **Markt und Nachrichten recherchieren:** mit WebSearch/WebFetch und `python tools/quotes.py …`.
4. **Entscheiden:** Strategie, Risiko und Streuung wählst du selbst (siehe mission.md).
5. **Orders platzieren:** `python tools/order.py --symbol <ISIN> --qty <N> --side buy|sell [--limit <P>]`.
6. **Ergebnis prüfen:** Lies das JSON von order.py (`status`) und danach
   `python tools/portfolio.py --section orders`.
7. **Journal ergänzen:** Was hast du getan, warum, und was lernst du daraus?

```bash
python tools/journal.py add --title "Kauf 20 SAP" <<'EOF'
**Was:** 20 SAP (DE0007164600) market gekauft, Order bestätigt (status placed).
**Warum:** …
**Lehre:** …
**Nächster Lauf:** …
EOF
```

Schreibe **in jedem Lauf** genau einen zusammenfassenden Journal-Eintrag, auch wenn du nichts
handelst oder abbrichst.

## Werkzeuge

Alle Werkzeuge geben JSON aus (`ok`, `exit_code`, bei Fehlern `error.code` + `error.message`).

| Befehl | Zweck |
|---|---|
| `python tools/portfolio.py [--section depot\|orders]` | Depot, Cash, Positionen, offene Orders, Orderhistorie von der Website |
| `python tools/portfolio.py --history` | gespeicherte Depotstände früherer Läufe (für die Performance) |
| `python tools/order.py --symbol X --qty N --side buy\|sell [--limit P]` | Order platzieren und in der Orderübersicht prüfen |
| `python tools/quotes.py SAP.DE SIE.SG` | aktuelle Kurse (yfinance) |
| `python tools/quotes.py SAP.DE --history 6mo [--interval 1d] [--rows 15]` | Historie + SMA20/50/200, RSI14, Volatilität, Drawdown, Renditen |
| `python tools/quotes.py SAP.DE --info --news` | Fundamentaldaten, Termine, Schlagzeilen |
| `python tools/quotes.py --search DE0007164600` | Yahoo-Ticker zu ISIN/Name finden |
| `python tools/journal.py tail --n 5` / `add --title …` | Journal lesen / anhängen |
| `python tools/login.py --check` | prüfen, ob die Session noch gilt |

**Symbole:** `order.py --symbol` erwartet das, was die Suche im Spiel findet. Nimm am besten die
**ISIN** (oder WKN). Namen sind oft mehrdeutig, dann kommt Exit-Code 3 mit `candidates`.
`quotes.py` nutzt dagegen Yahoo-Ticker: `.DE` ist Xetra, `.SG` ist Stuttgart (der Handelsplatz des
Spiels), US-Werte ohne Suffix in USD. Den Ticker findest du mit `quotes.py --search <ISIN>`.
Die yfinance-Kurse sind nicht die Spielkurse.

### Exit-Codes und was du dann tust

| Code | Bedeutung | Reaktion |
|---|---|---|
| 0 | ok | weiter |
| 1 | Fehler/falsche Argumente | Aufruf korrigieren, höchstens einmal neu versuchen |
| 2 | **Schutzgerät** (STOP, Handelszeit, Siegel, Selektoren unbestätigt) | nicht umgehen. Bei Handelszeit: keine Order, Plan fürs nächste Mal ins Journal. Bei STOP/Siegel: Lauf beenden, Journal |
| 3 | unerwarteter Seitenzustand | **abbrechen**, ins Journal schreiben (Fehlermeldung + Screenshot-Pfad), nicht raten |
| 4 | Order abgeschickt, Ergebnis unklar (`unverified`/`unklar`) | **nie wiederholen**. Mit `portfolio.py` prüfen, Journal |
| 5 | Session abgelaufen / Login nötig | abbrechen, Journal: „Mensch muss `python tools/login.py --manual` ausführen“ |
| 6 | Website hat die Order abgelehnt | Grund lesen (z. B. zu wenig Cash), höchstens einmal angepasst neu versuchen |

## Spielregeln (Recherchestand Oktober 2026, selbst verifizieren)

Zur Prüfung: planspiel-boerse.de (Spielregeln/FAQ) und die Hinweise auf der Spielseite.
Unsichere Punkte sind markiert.

- **Zeitraum:** 01.10.2026 bis 25.01.2027. Bewertet wird der Depotgesamtwert am Ende.
  Zwischenbewertung am 11.11.2026 (laut Drittquelle).
- **Startkapital:** 50.000 € Spielgeld.
- **Handelsplatz:** Börse Stuttgart, Kurse in EUR. Handelszeiten nach Stuttgart: Aktien ca. 7:30 bis 22:00,
  strukturierte Produkte ab 8:00. `order.py` lässt Orders nur **Mo–Fr 08:00–22:00 Uhr** (Europe/Berlin)
  zu, nicht an Feiertagen und nur im Spielzeitraum.
- **Ordertypen:** Market, Limit und Stop. Limits können bis zu 14 Tage gelten. `order.py` kann zurzeit
  Market und Limit. Ein Kauflimit wird ausgeführt, wenn der Kurs ≤ Limit ist, ein Verkaufslimit bei Kurs ≥ Limit.
- **Gebühren:** Jede Order kostet eine virtuelle Gebühr. Laut Drittquelle (unbestätigt) sind es
  **0,3 % vom Kurswert, mindestens 15 €**. Kleine Orders sind dann teuer, und häufiges Umschichten kostet.
  Prüfe die tatsächliche Gebühr in der Orderhistorie bzw. auf der Ordermaske.
- **Handelbar** sind nur Papiere der Wertpapierliste des Spiels: Aktien aus DAX, MDAX, TecDAX, SDAX,
  EuroStoxx 50, Dow Jones, Nasdaq 100 und weiteren Indizes, dazu ETFs, Fonds und Anleihen. Was die
  Spielsuche nicht findet, ist nicht handelbar.
- Leerverkäufe und Kredit gibt es vermutlich nicht. Verkaufen kannst du nur, was im Depot liegt.
- Die Liquidität wird beim Erfassen geprüft. Ist das Cash zu knapp, lehnt die Seite ab (Exit-Code 6).

## Schutzgeräte (technisch erzwungen, nicht verhandelbar)

- **STOP-Datei** im Projektordner: Jeder Lauf und jede Order bricht sofort ab, und ein laufender
  Agentenlauf wird beendet. Lege STOP niemals an und lösche es niemals. Das macht nur der Mensch.
- **Geschützte Dateien:** `tools/`, `config.yaml`, `selectors.yaml`, `agent-settings.json`, `CLAUDE.md`,
  die Start-Skripte, `scheduler/`, `.claude/` und `logs/`. Sie sind gesiegelt. Schreibversuche
  blockieren deny-Regeln und der Hook. Erkennt der Runner danach eine Änderung, legt er STOP an
  und ein Mensch muss eingreifen.
- **Zugangsdaten** (`.env`, `.auth/`) sind für dich gesperrt. Den Login macht nur `tools/login.py`.
- **Keine eigene Browser-Automatisierung:** Orders laufen ausschließlich über `tools/order.py`, das
  Depot nur über `tools/portfolio.py`. Eigene Skripte mit Playwright/Selenium sind verboten und werden blockiert.
- **Testmodus:** Ist `BOERSE_DRY_RUN` gesetzt (Testlauf), simuliert `order.py` nur (`status: dry_run`)
  und das Journal markiert die Einträge als TESTLAUF. Verhalte dich sonst wie im echten Lauf.
- **mission.md:** Im Handelslauf schreibgeschützt. Im Wochen-Review darfst du nur den Abschnitt
  `## Lehren aus den Wochen-Reviews` ergänzen. Änderungen am Kernauftrag darüber setzt der Runner zurück.

Wenn etwas unklar ist oder die Seite sich komisch verhält: **abbrechen und ins Journal schreiben.**

## Wochen-Review (Modus `review`, sonntags, Opus)

1. Journal der Woche lesen (`python tools/journal.py tail --n 30`), außerdem `python tools/portfolio.py --history`
   und den aktuellen Stand mit `python tools/portfolio.py`.
2. Performance bewerten: Rendite seit Start (50.000 €) und seit letzter Woche, Vergleich mit dem DAX
   (`python tools/quotes.py ^GDAXI --history 1mo`), Gebührenlast, Trefferquote und Fehler.
3. **mission.md ergänzen:** unter `## Lehren aus den Wochen-Reviews` (anlegen, falls er fehlt) einen
   Unterabschnitt `### KW <Nr> (<Datum>)` mit 3–7 konkreten, überprüfbaren Lehren. Den Text darüber
   nicht verändern.
4. Einen Journal-Eintrag „Wochen-Review KW <Nr>“ mit Zahlen und Fazit schreiben.
5. **Keine Orders** im Review.

## Hinweis für Menschen/Entwicklung

Nach Änderungen an geschützten Dateien: `python tools/integrity.py verify`, dann
`python tools/integrity.py seal` (interaktiv). Tests: `python -m pytest`.
