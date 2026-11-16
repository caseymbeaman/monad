"""Offline tests for engine/universe.py (FMP screener and profiles faked)."""

import pytest

from engine import universe


def row(sym, name, cap, country="US", vol=1_000_000, **kw):
    return {"symbol": sym, "companyName": name, "marketCap": cap, "country": country, "avgVolume": vol,
            "exchangeShortName": kw.pop("ex", "NYSE"), "isEtf": False, "isFund": False, "isActivelyTrading": True,
            "sector": "Tech", "industry": "Software", **kw}


SCREEN = [
    row("AAA", "Alpha Inc", 900e9), row("GOOG", "Alphabet Inc.", 800e9, vol=30e6),
    row("GOOGL", "Alphabet Inc.", 800e9, vol=20e6), row("BRK-A", "Berkshire Hathaway", 700e9, vol=200),
    row("BRK-B", "Berkshire Hathaway", 700e9), row("BAC-PB", "Bank Pref", 600e9),
    row("ETFX", "Some ETF", 500e9, isEtf=True), row("FUND", "Some Fund", 500e9, isFund=True),
    row("OTC1", "Otc Co", 500e9, ex="OTC"), row("THIN", "Thin Co", 400e9, vol=50_000),
    row("TSM", "Taiwan Semi", 300e9, country="TW"), row("SAP", "SAP SE", 200e9, country="DE"),
    row("UNIT-UN", "Some Units", 100e9), row("BBB", "Beta Corp", 50e9),
]


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(universe, "screener_rows", lambda: [dict(r) for r in SCREEN])
    monkeypatch.setattr(universe, "TOP_US", 3)
    monkeypatch.setattr(universe, "TOP_INTL", 1)
    themes = {"t": {"references": {"High": [{"ticker": "SMALL"}], "Moderate": []},
                    "direct_classification": [{"ticker": "GOOGL"}]}}
    monkeypatch.setattr(universe, "load_all", lambda: themes)
    profiles = {"SMALL": {"companyName": "Small Co", "country": "US", "marketCap": 1e9, "exchange": "NASDAQ"},
                "GOOGL": {"companyName": "Alphabet Inc.", "country": "US", "marketCap": 800e9, "exchange": "NASDAQ"}}
    monkeypatch.setattr(universe.fmp, "profile", lambda t: [profiles[t]] if t in profiles else [])


def test_filters_top_n_and_theme_names():
    rows = universe.build_universe("2026-11-15")
    tickers = [r["ticker"] for r in rows]
    # top 3 US by cap after filters: AAA, GOOG (most traded Alphabet class), BRK-B; top 1 intl: TSM
    # then GOOGL (Tier 2) replaces GOOG, and SMALL (a theme reference under $2B) is added.
    assert set(tickers) == {"AAA", "GOOGL", "BRK-B", "TSM", "SMALL"}
    src = {r["ticker"]: r["source"] for r in rows}
    assert src["TSM"] == "screener: top international" and src["SMALL"] == "theme reference" and src["GOOGL"] == "Tier 2"
    assert all(r["source_date"] == "2026-11-15" for r in rows)


@pytest.mark.parametrize("sym, ok", [("AAA", True), ("BAC-PB", False), ("UNIT-UN", False), ("X.U", False),
                                     ("WARR-WT", False), ("BRK-B", True)])
def test_common_stock_symbols(sym, ok):
    assert universe.is_common_stock(row(sym, "x", 1e10)) is ok


def test_load_universe_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(universe, "UNIVERSE_CSV", tmp_path / "nope.csv")
    with pytest.raises(FileNotFoundError, match="python -m engine.universe"):
        universe.load_universe()
