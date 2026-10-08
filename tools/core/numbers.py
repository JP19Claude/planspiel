"""Zahlen im deutschen Format lesen und schreiben ("1.234,56 €" <-> 1234.56)."""
from __future__ import annotations

import re

_NUM = re.compile(r"[-+−]?\d[\d.,'\s]*")


def parse_number(text: str | None, fmt: str = "de") -> float | None:
    """Erste Zahl im Text. Deutsch: Punkt = Tausender, Komma = Dezimal."""
    if text is None:
        return None
    m = _NUM.search(str(text).replace("\xa0", " "))
    if not m:
        return None
    raw = m.group(0).strip().replace(" ", "").replace("'", "").replace("−", "-")
    if fmt == "de":
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(".") >= 1 and re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", raw):
            raw = raw.replace(".", "")
    else:
        raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def format_number(value: float, fmt: str = "de", decimals: int | None = None) -> str:
    """Formatiert eine Zahl für ein Eingabefeld (ohne Tausenderpunkte)."""
    if decimals is None:
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        if "." in text and len(text.split(".")[1]) < 2:
            text = f"{value:.2f}"
    else:
        text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if fmt == "de" else text
