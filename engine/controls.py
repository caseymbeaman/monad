"""Market, style and international controls, and the objective rule for skipping style controls.

Every regression controls for the overall market (SPY) and bonds (TLT). On top of that:

Style controls (daily return spreads):
    VALUE  = IWD  - IWF   value minus growth
    SIZE   = RSP  - SPY   equal-weight minus cap-weight (small vs mega-cap)
    MOM    = MTUM - SPY   momentum minus market
    LOWVOL = USMV - SPY   low-volatility/defensive minus market

International control: a non-US stock (e.g. an ADR) also gets INTL = VXUS - SPY.

Skip rule (objective, the same for every theme): a style control is skipped for a theme if the theme's
Tier 1 reference companies make up more than 15% of that control ETF's holdings (FMP ETF holdings).
For a spread, each non-SPY leg is checked (VALUE checks both IWD and IWF). Controls are never part of
a High/Moderate group and never count in the Bonferroni denominator.
"""

from __future__ import annotations

import csv
from pathlib import Path

from engine import fmp

SKIP_THRESHOLD_PCT = 15.0

STYLE = {"VALUE": ("IWD", "IWF"), "SIZE": ("RSP", "SPY"), "MOM": ("MTUM", "SPY"), "LOWVOL": ("USMV", "SPY")}

# International stocks (ADRs) also get the non-US market swing: all-world-ex-US minus US.
INTL = {"INTL": ("VXUS", "SPY")}

# Every built-in spread series engine/data.py knows how to make.
SPREADS = {**STYLE, **INTL}


def etf_holdings(etf: str) -> dict[str, float]:
    """{ticker: weight %} for an ETF, from FMP."""
    rows = fmp.get("etf/holdings", {"symbol": etf}) or []
    out: dict[str, float] = {}
    for r in rows:
        if r.get("asset") and isinstance(r.get("weightPercentage"), (int, float)):
            out[r["asset"].upper()] = out.get(r["asset"].upper(), 0.0) + float(r["weightPercentage"])
    return out


def tier1_refs(theme: dict) -> list[str]:
    return [r["ticker"] for g in ("High", "Moderate") for r in theme["references"].get(g, [])]


def ref_share(theme: dict, etf: str) -> float:
    """% of `etf` held in the theme's Tier 1 reference companies."""
    h = etf_holdings(etf)
    return round(sum(h.get(t, 0.0) for t in tier1_refs(theme)), 2)


def style_controls(theme: dict) -> tuple[list[str], dict[str, dict[str, float]]]:
    """(style controls kept, {skipped control: {leg: share %}}) for a theme, using the 15% rule."""
    kept, skipped = [], {}
    for name, legs in STYLE.items():
        shares = {leg: ref_share(theme, leg) for leg in legs if leg != "SPY"}
        if any(s > SKIP_THRESHOLD_PCT for s in shares.values()):
            skipped[name] = shares
        else:
            kept.append(name)
    return kept, skipped


UNIVERSE_CSV = Path(__file__).resolve().parent.parent / "data" / "universe.csv"
_UNIVERSE: dict[str, dict] = {}


def _universe_row(ticker: str) -> dict | None:
    if not _UNIVERSE and UNIVERSE_CSV.exists():
        with UNIVERSE_CSV.open() as f:
            for row in csv.DictReader(f):
                _UNIVERSE[row["ticker"]] = row
    return _UNIVERSE.get(ticker)


def _profile_field(ticker: str, field: str) -> str | None:
    """A field from data/universe.csv when the stock is listed there, else from its FMP profile."""
    row = _universe_row(ticker)
    if row is not None:
        return row.get(field) or None
    try:
        rows = fmp.profile(ticker)
    except fmp.FMPError:
        return None
    return (rows[0].get(field) or None) if rows else None


def country_of(ticker: str) -> str | None:
    return _profile_field(ticker, "country")


def industry_of(ticker: str) -> str | None:
    return _profile_field(ticker, "industry")


def intl_control(ticker: str) -> str | None:
    """"INTL" (VXUS minus SPY) for a non-US stock, None for a US stock or unknown country.

    Like every control, it's never in a High/Moderate group and never counts in the Bonferroni denominator.
    """
    c = country_of(ticker)
    return "INTL" if c and c != "US" else None
