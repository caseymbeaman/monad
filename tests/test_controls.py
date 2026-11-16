"""Tests for engine/controls.py (FMP ETF holdings and profiles faked)."""

import pytest

from engine import controls, fmp

HOLDINGS = {
    "IWF": {"NVDA": 12.0, "MSFT": 6.0, "AAPL": 9.0},
    "IWD": {"XOM": 2.0, "JPM": 3.0},
    "MTUM": {"NVDA": 4.0, "JNJ": 4.0},
    "RSP": {"NVDA": 0.2}, "USMV": {"MSFT": 1.5},
    "XLK": {"NVDA": 13.0, "MSFT": 12.0}, "XLE": {"XOM": 23.0},
}
PROFILES = {"NVDA": {"country": "US"}}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(fmp, "get", lambda ep, p: [{"asset": a, "weightPercentage": w}
                                                   for a, w in HOLDINGS.get(p["symbol"], {}).items()])
    monkeypatch.setattr(fmp, "profile", lambda t: [PROFILES[t]] if t in PROFILES else [])


def theme(refs, **kw):
    return {"references": {"High": [{"ticker": t} for t in refs], "Moderate": []}, **kw}


def test_style_skip_rule_checks_every_non_spy_leg():
    kept, skipped = controls.style_controls(theme(["NVDA", "MSFT"]))
    assert skipped == {"VALUE": {"IWD": 0.0, "IWF": 18.0}}  # IWF 18% > 15% -> skip VALUE
    assert kept == ["SIZE", "MOM", "LOWVOL"]  # MTUM 4%, RSP 0.2%, USMV 1.5%: under 15%


def test_exactly_15_percent_is_not_skipped():
    HOLDINGS["MTUM"]["XOM"] = 15.0
    try:
        assert "MOM" not in controls.style_controls(theme(["XOM"]))[1]
    finally:
        del HOLDINGS["MTUM"]["XOM"]


def test_intl_control_for_non_us_stocks(monkeypatch):
    monkeypatch.setattr(controls, "_UNIVERSE", {"TSM": {"country": "TW", "industry": "Semiconductors"},
                                                "NVDA": {"country": "US"}, "BLANK": {"country": ""}})
    assert controls.intl_control("TSM") == "INTL"
    assert controls.intl_control("NVDA") is None
    assert controls.intl_control("BLANK") is None
    PROFILES["SAP"] = {"country": "DE"}
    assert controls.intl_control("SAP") == "INTL"          # not in the universe file -> FMP profile
    assert controls.intl_control("NOPE") is None           # no profile
    assert controls.industry_of("TSM") == "Semiconductors" and controls.industry_of("NVDA") is None


def test_spreads_cover_styles_and_intl():
    assert controls.SPREADS["SIZE"] == ("RSP", "SPY") and controls.SPREADS["INTL"] == ("VXUS", "SPY")
    assert set(controls.SPREADS) == {"VALUE", "SIZE", "MOM", "LOWVOL", "INTL"}
