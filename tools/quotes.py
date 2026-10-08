"""Kurse, Historie, Kennzahlen und News über yfinance.

    python tools/quotes.py SAP.DE SIE.DE                 # aktuelle Kurse
    python tools/quotes.py SAP.DE --history 6mo          # Historie + Kennzahlen (SMA, RSI, Vola …)
    python tools/quotes.py SAP.DE --info                 # Fundamentaldaten
    python tools/quotes.py SAP.DE --news                 # aktuelle Schlagzeilen
    python tools/quotes.py --search "DE0007164600"       # ISIN/Name -> Yahoo-Ticker

Yahoo-Ticker: .DE = Xetra, .SG = Stuttgart (Handelsplatz des Spiels), .F = Frankfurt.
Achtung: yfinance-Kurse sind nicht die Spielkurse – maßgeblich ist die Website.
"""
from __future__ import annotations

import argparse
import math
import sys
from typing import Any

from core import common, guards

INFO_KEYS = [
    "longName", "shortName", "quoteType", "exchange", "currency", "sector", "industry", "country",
    "marketCap", "trailingPE", "forwardPE", "priceToBook", "pegRatio", "dividendYield", "payoutRatio",
    "beta", "profitMargins", "operatingMargins", "returnOnEquity", "revenueGrowth", "earningsGrowth",
    "debtToEquity", "freeCashflow", "totalRevenue", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "recommendationKey", "recommendationMean", "numberOfAnalystOpinions", "targetMeanPrice",
    "targetHighPrice", "targetLowPrice", "isin",
]


def _yf():
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise common.ConfigError("yfinance fehlt: pip install -r requirements.txt") from exc
    return yf


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def quote(yf, symbol: str) -> dict:
    t = yf.Ticker(symbol)
    fi = t.fast_info

    def raw(name: str) -> Any:
        try:
            return getattr(fi, name)
        except Exception:
            return None

    def get(name: str) -> float | None:
        return _num(raw(name))

    last, prev = get("last_price"), get("previous_close")
    out = {
        "symbol": symbol,
        "currency": raw("currency"),
        "last": last,
        "previous_close": prev,
        "change_pct": round((last / prev - 1) * 100, 2) if last and prev else None,
        "open": get("open"),
        "day_high": get("day_high"),
        "day_low": get("day_low"),
        "volume": get("last_volume"),
        "year_high": get("year_high"),
        "year_low": get("year_low"),
        "sma50": get("fifty_day_average"),
        "sma200": get("two_hundred_day_average"),
        "market_cap": get("market_cap"),
    }
    if last is None:
        out["error"] = "kein Kurs gefunden (Ticker prüfen, z. B. mit --search)"
    return out


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains, losses = [], []
    for a, b in zip(closes[-period - 1:-1], closes[-period:]):
        diff = b - a
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain, avg_loss = sum(gains) / period, sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def history_stats(closes: list[float]) -> dict:
    def ret(n: int) -> float | None:
        return round((closes[-1] / closes[-n - 1] - 1) * 100, 2) if len(closes) > n else None

    def sma(n: int) -> float | None:
        return round(sum(closes[-n:]) / n, 4) if len(closes) >= n else None

    daily = [b / a - 1 for a, b in zip(closes[:-1], closes[1:]) if a]
    vol = None
    if len(daily) > 2:
        mean = sum(daily) / len(daily)
        vol = round(math.sqrt(sum((d - mean) ** 2 for d in daily) / (len(daily) - 1)) * math.sqrt(252) * 100, 2)
    peak, max_dd = closes[0] if closes else 0, 0.0
    for c in closes:
        peak = max(peak, c)
        if peak:
            max_dd = min(max_dd, c / peak - 1)
    return {
        "last_close": closes[-1] if closes else None,
        "return_1d_pct": ret(1), "return_5d_pct": ret(5), "return_1m_pct": ret(21),
        "return_3m_pct": ret(63), "return_6m_pct": ret(126),
        "return_period_pct": round((closes[-1] / closes[0] - 1) * 100, 2) if len(closes) > 1 else None,
        "sma20": sma(20), "sma50": sma(50), "sma200": sma(200),
        "rsi14": rsi(closes),
        "volatility_annual_pct": vol,
        "max_drawdown_pct": round(max_dd * 100, 2),
    }


def history(yf, symbol: str, period: str, interval: str, rows: int) -> dict:
    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return {"symbol": symbol, "error": "keine Historie"}
    closes = [float(c) for c in df["Close"].tolist() if _num(c) is not None]
    recent = []
    for idx, row in df.tail(rows).iterrows():
        recent.append({
            "date": idx.strftime("%Y-%m-%d %H:%M") if interval.endswith(("m", "h")) else idx.strftime("%Y-%m-%d"),
            "open": _num(row.get("Open")), "high": _num(row.get("High")), "low": _num(row.get("Low")),
            "close": _num(row.get("Close")), "volume": _num(row.get("Volume")),
        })
    return {"symbol": symbol, "period": period, "interval": interval, "points": len(df),
            "stats": history_stats(closes), "recent": recent}


def info(yf, symbol: str) -> dict:
    t = yf.Ticker(symbol)
    raw = t.info or {}
    out = {"symbol": symbol, **{k: raw.get(k) for k in INFO_KEYS if raw.get(k) is not None}}
    try:
        cal = t.calendar
        if isinstance(cal, dict):
            out["calendar"] = {k: (str(v) if not isinstance(v, (int, float, str)) else v) for k, v in cal.items()}
    except Exception:
        pass
    return out


def news(yf, symbol: str, limit: int = 8) -> dict:
    items = []
    for n in (yf.Ticker(symbol).news or [])[:limit]:
        content = n.get("content", n)
        items.append({
            "title": content.get("title"),
            "publisher": (content.get("provider") or {}).get("displayName") or content.get("publisher"),
            "published": content.get("pubDate") or content.get("providerPublishTime"),
            "url": ((content.get("canonicalUrl") or {}).get("url") or content.get("link")),
        })
    return {"symbol": symbol, "news": items}


def search(yf, query: str, limit: int = 10) -> dict:
    res = yf.Search(query, max_results=limit, news_count=0)
    return {"query": query, "results": [
        {"symbol": q.get("symbol"), "name": q.get("longname") or q.get("shortname"),
         "exchange": q.get("exchange"), "type": q.get("quoteType")}
        for q in (res.quotes or [])
    ]}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Kurse und Kennzahlen per yfinance")
    p.add_argument("symbols", nargs="*", help="Yahoo-Ticker, z. B. SAP.DE, SIE.SG, AAPL, ^GDAXI")
    p.add_argument("--history", metavar="PERIOD", help="z. B. 5d, 1mo, 3mo, 6mo, 1y, 2y")
    p.add_argument("--interval", default="1d", help="z. B. 1d, 1h, 15m (Standard 1d)")
    p.add_argument("--rows", type=int, default=15, help="wie viele letzte Kerzen ausgeben")
    p.add_argument("--info", action="store_true", help="Fundamentaldaten")
    p.add_argument("--news", action="store_true", help="Schlagzeilen")
    p.add_argument("--search", metavar="QUERY", help="Ticker zu ISIN/Name suchen")
    return p


def handler(args: argparse.Namespace, dry_run: bool) -> dict:
    warning = guards.check_stop(strict=guards.stop_strict_for_reader())
    yf = _yf()
    out: dict[str, Any] = {}
    if warning:
        out["warnings"] = [warning]
    if args.search:
        out["search"] = search(yf, args.search)
    if not args.symbols and not args.search:
        raise common.ToolError("Mindestens ein Symbol oder --search angeben")
    results = []
    for sym in args.symbols:
        try:
            if args.history:
                entry = history(yf, sym, args.history, args.interval, args.rows)
            else:
                entry = quote(yf, sym)
            if args.info:
                entry["info"] = info(yf, sym)
            if args.news:
                entry["news"] = news(yf, sym)["news"]
        except Exception as exc:
            entry = {"symbol": sym, "error": f"{type(exc).__name__}: {exc}"}
        results.append(entry)
    if args.symbols:
        out["quotes"] = results
    out["source"] = "yfinance (nicht die Spielkurse)"
    return out


if __name__ == "__main__":
    sys.exit(common.run_cli("quotes", build_parser(), handler))
