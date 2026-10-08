"""Seitenanalyse für Schritt 6: Screenshots + Struktur der Planspiel-Seiten.

Klickt selbst NICHTS an. Erfasst nur, was gerade angezeigt wird.

    python tools/explore.py --interactive
        Browser öffnet sich sichtbar (mit gespeicherter Session). Du klickst dich
        selbst zu Depot, Orderformular (nicht abschicken!) und Orderübersicht.
        Im Terminal: ENTER = aktuelle Seite erfassen, Name+ENTER = mit Namen
        erfassen, q = beenden.

    python tools/explore.py --url https://www.planspiel-boerse.de/
        Erfasst die angegebenen Seiten ohne Interaktion (headless).

Ergebnis in logs/explore/<zeit>/: PNG-Screenshot, HTML, JSON mit Formularen,
Feldern, Buttons, Tabellen, iframes und Vorschlägen für Selektoren, plus
report.md als Übersicht. Achtung: enthält deine Depotdaten. Vor dem Teilen
durchsehen.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from core import common
from core.site import browser_page, save_state, storage_state_path

DOM_SUMMARY_JS = r"""
() => {
  const txt = (e) => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const uniq = (sel) => { try { return document.querySelectorAll(sel).length === 1; } catch (_) { return false; } };
  const looksDynamic = (v) => /\d{4,}|[0-9a-f]{8,}|^(ember|react|mui|ng-)/i.test(v || '');
  const suggest = (e) => {
    const tag = e.tagName.toLowerCase();
    for (const a of ['data-testid', 'data-test', 'data-qa', 'data-cy']) {
      const v = e.getAttribute(a); if (v && uniq(`[${a}="${v}"]`)) return `[${a}="${v}"]`;
    }
    if (e.id && !looksDynamic(e.id) && uniq('#' + CSS.escape(e.id))) return '#' + CSS.escape(e.id);
    const name = e.getAttribute('name');
    if (name && uniq(`${tag}[name="${name}"]`)) return `${tag}[name="${name}"]`;
    const aria = e.getAttribute('aria-label');
    if (aria && uniq(`${tag}[aria-label="${aria}"]`)) return `${tag}[aria-label="${aria}"]`;
    const t = txt(e);
    if (t && t.length <= 40 && ['button', 'a'].includes(tag)) return `${tag}:has-text("${t}")`;
    if (e.getAttribute('placeholder')) return `${tag}[placeholder="${e.getAttribute('placeholder')}"]`;
    return null;
  };
  const labelOf = (e) => {
    if (e.labels && e.labels.length) return txt(e.labels[0]);
    const l = e.closest('label'); return l ? txt(l) : null;
  };
  const base = (e) => ({ tag: e.tagName.toLowerCase(), id: e.id || null, name: e.getAttribute('name'),
    classes: (e.className && typeof e.className === 'string') ? e.className.slice(0, 120) : null,
    testid: e.getAttribute('data-testid') || e.getAttribute('data-test') || null,
    visible: vis(e), selector: suggest(e) });
  const inputs = Array.from(document.querySelectorAll('input, select, textarea')).slice(0, 200).map(e => ({
    ...base(e), type: e.getAttribute('type'), placeholder: e.getAttribute('placeholder'),
    aria_label: e.getAttribute('aria-label'), label: labelOf(e),
    options: e.tagName === 'SELECT' ? Array.from(e.options).slice(0, 30).map(o => o.text.trim()) : undefined,
    value: (e.type === 'password') ? '***' : undefined }));
  const buttons = Array.from(document.querySelectorAll('button, [role=button], input[type=submit], input[type=button]'))
    .slice(0, 200).map(e => ({ ...base(e), text: txt(e) || e.value || null, type: e.getAttribute('type') }));
  const links = Array.from(document.querySelectorAll('a[href]')).slice(0, 250).map(e => ({
    text: txt(e), href: e.href.slice(0, 200), visible: vis(e), selector: suggest(e) }));
  const tables = Array.from(document.querySelectorAll('table, [role=table], [role=grid]')).slice(0, 30).map((t, i) => {
    const headers = Array.from(t.querySelectorAll('th, [role=columnheader]')).map(txt);
    const rows = Array.from(t.querySelectorAll('tbody tr, [role=row]')).slice(0, 4)
      .map(r => Array.from(r.querySelectorAll('td, [role=cell], [role=gridcell]')).map(txt));
    return { index: i, ...base(t), headers, row_count: t.querySelectorAll('tr, [role=row]').length, sample_rows: rows };
  });
  const forms = Array.from(document.forms).map(f => ({ ...base(f), action: f.getAttribute('action'),
    method: f.getAttribute('method'), fields: f.elements.length }));
  const headings = Array.from(document.querySelectorAll('h1, h2, h3')).slice(0, 40).map(h => h.tagName + ': ' + txt(h));
  const iframes = Array.from(document.querySelectorAll('iframe')).map(f => ({ src: f.src, id: f.id || null,
    name: f.name || null, visible: vis(f) }));
  const testids = Array.from(document.querySelectorAll('[data-testid], [data-test], [data-qa]')).slice(0, 150)
    .map(e => ({ ...base(e), text: txt(e) }));
  return { url: location.href, title: document.title, headings, forms, inputs, buttons, tables, iframes,
           testids, links };
}
"""


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:50] or "seite"


def capture(page, out_dir: Path, index: int, name: str | None) -> dict:
    label = f"{index:02d}_{slug(name or page.title() or 'seite')}"
    png = out_dir / f"{label}.png"
    page.screenshot(path=str(png), full_page=True)
    (out_dir / f"{label}.html").write_text(page.content(), encoding="utf-8")
    summary = page.evaluate(DOM_SUMMARY_JS)
    frames = []
    for frame in page.frames[1:]:
        try:
            frames.append({"url": frame.url, "summary": frame.evaluate(DOM_SUMMARY_JS)})
        except Exception as exc:  # fremde Domain o. ä.
            frames.append({"url": frame.url, "error": str(exc)[:200]})
    summary["frames"] = frames
    (out_dir / f"{label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    rel = lambda p: str(p.relative_to(common.paths.root))  # noqa: E731
    return {"name": name, "url": page.url, "title": page.title(), "screenshot": rel(png),
            "json": rel(out_dir / f"{label}.json"), "inputs": len(summary["inputs"]),
            "buttons": len(summary["buttons"]), "tables": len(summary["tables"]), "iframes": len(summary["iframes"])}


def write_report(out_dir: Path, pages: list[dict]) -> Path:
    lines = ["# Seitenanalyse Planspiel Börse", "", f"Erstellt: {dt.datetime.now():%Y-%m-%d %H:%M}", ""]
    for p in pages:
        lines += [f"## {p.get('name') or p['title']}", "", f"- URL: {p['url']}", f"- Screenshot: `{p['screenshot']}`",
                  f"- Struktur: `{p['json']}` ({p['inputs']} Felder, {p['buttons']} Buttons, "
                  f"{p['tables']} Tabellen, {p['iframes']} iframes)", ""]
    report = out_dir / "report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Planspiel-Seiten erfassen (Screenshots + Struktur)")
    p.add_argument("--interactive", action="store_true", help="sichtbarer Browser, du navigierst")
    p.add_argument("--url", action="append", default=[], help="Seite erfassen (mehrfach möglich)")
    p.add_argument("--no-session", action="store_true", help="ohne gespeicherte Session (ausgeloggt)")
    return p


def handler(args: argparse.Namespace, dry_run: bool) -> dict:
    cfg = common.load_config()
    urls = args.url or ([] if args.interactive else [cfg["game"]["base_url"]])
    out_dir = common.paths.explore / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if dry_run:
        return {"would_capture": urls or "interaktiv", "out_dir": str(out_dir.relative_to(common.paths.root))}
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    use_state = not args.no_session
    with browser_page(cfg, headless=not args.interactive, use_state=use_state) as (context, page):
        for url in urls:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            pages.append(capture(page, out_dir, len(pages) + 1, None))
        if args.interactive:
            if not urls:
                page.goto(cfg["game"]["base_url"], wait_until="domcontentloaded")
            print("\nBrowser offen. Navigiere selbst (NICHTS abschicken!).\n"
                  "ENTER = Seite erfassen | Name + ENTER = mit Namen erfassen | q + ENTER = Ende", file=sys.stderr)
            while True:
                try:
                    cmd = input().strip()
                except EOFError:
                    break
                if cmd.lower() in {"q", "quit", "exit"}:
                    break
                current = context.pages[-1] if context.pages else page
                info = capture(current, out_dir, len(pages) + 1, cmd or None)
                pages.append(info)
                print(f"  erfasst: {info['screenshot']}  ({info['url']})", file=sys.stderr)
        if use_state and storage_state_path(cfg).exists():
            save_state(context, cfg)
    report = write_report(out_dir, pages)
    return {"out_dir": str(out_dir.relative_to(common.paths.root)), "report": str(report.relative_to(common.paths.root)),
            "pages": pages,
            "hint": "Screenshots + JSON enthalten persönliche Depotdaten – vor dem Teilen prüfen."}


if __name__ == "__main__":
    sys.exit(common.run_cli("explore", build_parser(), handler))
