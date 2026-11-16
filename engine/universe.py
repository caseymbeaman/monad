"""Way 2 stock universe: individual NYSE + NASDAQ stocks, built from the FMP company screener.

Run:  python -m engine.universe        -> data/universe.csv

Rules (settings below):
- NYSE and NASDAQ only (ADRs of foreign companies included), actively trading, market cap >= $2B,
  average daily volume >= MIN_AVG_VOLUME shares.
- Individual stocks only: no ETFs or funds (FMP isEtf / isFund flags), no preferred shares, units, warrants
  or rights, and one share class per company (the most traded one, e.g. GOOGL over GOOG).
- Top TOP_US US companies + top TOP_INTL international companies by market cap.
- Plus every theme reference company and Tier 2 (direct-classification) name, whatever its size.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from engine import fmp
from engine.theme_loader import load_all

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_CSV = ROOT / "data" / "universe.csv"
EXCHANGES = ("NYSE", "NASDAQ")
MIN_MARKET_CAP = 2_000_000_000
MIN_AVG_VOLUME = 200_000
TOP_US = 500
TOP_INTL = 150
COLUMNS = ["ticker", "name", "country", "sector", "industry", "market_cap", "exchange", "avg_volume",
           "source", "source_date"]
# Preferred shares (BAC-PB), units (-UN, .U), warrants (-WT), rights (-RT)
NOT_COMMON = re.compile(r"-P[A-Z]?$|-(UN|WT|WS|RT|R)$|\.(U|W|R)$")


def screener_rows() -> list[dict]:
    rows = []
    for ex in EXCHANGES:
        rows += fmp.get("company-screener", {
            "exchange": ex, "isEtf": "false", "isFund": "false", "isActivelyTrading": "true",
            "marketCapMoreThan": MIN_MARKET_CAP, "limit": 5000}) or []
    return rows


def is_common_stock(r: dict) -> bool:
    return (not r.get("isEtf") and not r.get("isFund") and r.get("isActivelyTrading", True)
            and r.get("exchangeShortName") in EXCHANGES and not NOT_COMMON.search(r.get("symbol", "")))


def one_class_per_company(rows: list[dict]) -> list[dict]:
    """Keep the most traded listing of each company (GOOGL vs GOOG, BRK-B vs BRK-A).

    A theme's own ticker (e.g. GOOGL in AI) later replaces whichever class was kept.
    """
    best: dict[str, dict] = {}
    for r in rows:
        key = re.sub(r"[^a-z0-9]", "", (r.get("companyName") or r["symbol"]).lower())
        if key not in best or (r.get("avgVolume") or 0) > (best[key].get("avgVolume") or 0):
            best[key] = r
    return list(best.values())


def _row(r: dict, source: str, today: str) -> dict:
    return {"ticker": r["symbol"], "name": r.get("companyName"), "country": r.get("country") or "",
            "sector": r.get("sector") or "", "industry": r.get("industry") or "",
            "market_cap": int(r.get("marketCap") or 0), "exchange": r.get("exchangeShortName") or r.get("exchange") or "",
            "avg_volume": int(r.get("avgVolume") or 0), "source": source, "source_date": today}


def theme_names(themes: dict) -> dict[str, str]:
    """{ticker: 'theme reference' or 'Tier 2'} for every theme."""
    out = {}
    for th in themes.values():
        for g in ("High", "Moderate"):
            for r in th["references"].get(g, []):
                out[r["ticker"]] = "theme reference"
        for d in th.get("direct_classification", []):
            out.setdefault(d["ticker"], "Tier 2")
    return out


def build_universe(today: str | None = None) -> list[dict]:
    today = today or date.today().isoformat()
    rows = [r for r in screener_rows() if is_common_stock(r) and (r.get("avgVolume") or 0) >= MIN_AVG_VOLUME]
    rows = sorted(one_class_per_company(rows), key=lambda r: -(r.get("marketCap") or 0))
    us = [r for r in rows if r.get("country") == "US"][:TOP_US]
    intl = [r for r in rows if r.get("country") and r.get("country") != "US"][:TOP_INTL]
    out = {r["symbol"]: _row(r, "screener: top US", today) for r in us}
    out.update({r["symbol"]: _row(r, "screener: top international", today) for r in intl})
    def company_key(name, symbol):
        return re.sub(r"[^a-z0-9]", "", (name or symbol).lower())

    by_company = {company_key(r["name"], r["ticker"]): r["ticker"] for r in out.values()}
    for t, src in theme_names(load_all()).items():
        if t in out:
            continue
        p = (fmp.profile(t) or [{}])[0]
        if not p:
            continue
        other = by_company.get(company_key(p.get("companyName"), t))
        if other:  # another share class of the same company is already in; keep the theme's ticker instead
            del out[other]
        out[t] = {"ticker": t, "name": p.get("companyName"), "country": p.get("country") or "",
                  "sector": p.get("sector") or "", "industry": p.get("industry") or "",
                  "market_cap": int(p.get("marketCap") or 0), "exchange": p.get("exchange") or "",
                  "avg_volume": int(p.get("averageVolume") or p.get("volAvg") or 0), "source": src, "source_date": today}
    return sorted(out.values(), key=lambda r: -r["market_cap"])


def load_universe() -> list[dict]:
    if not UNIVERSE_CSV.exists():
        raise FileNotFoundError("data/universe.csv is missing. Run: python -m engine.universe")
    with UNIVERSE_CSV.open() as f:
        return list(csv.DictReader(f))


def main():
    rows = build_universe()
    UNIVERSE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with UNIVERSE_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    n_us = sum(r["country"] == "US" for r in rows)
    by_src = {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    print(f"Wrote {len(rows)} stocks to data/universe.csv: {n_us} US, {len(rows) - n_us} international. By source: {by_src}")


if __name__ == "__main__":
    main()
