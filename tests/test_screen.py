"""Tests for engine/screen.py. Themes and prices are faked so results are known in advance."""

import json

import numpy as np
import pandas as pd
import pytest

from engine import screen

N = 1500


def theme(key, name):
    return {
        "key": key, "name": name, "plain": f"{name} companies", "controls": ["SPY", "TLT"],
        "references": {
            "High": [{"ticker": f"{key.upper()}H{i}", "evidence_pct": 80, "measures": "share"} for i in (1, 2, 3)],
            "Moderate": [{"ticker": f"{key.upper()}M{i}", "evidence_pct": 20, "measures": "share"} for i in (1, 2)],
        },
        "control": {"ticker": "CTRL"},
        "direct_classification": [{"ticker": f"{key.upper()}DIRECT", "tier": "Moderate", "reason": "no number."}],
        "allowed_industries": ["Widgets"] if key == "t1" else [],
    }


THEMES = {"t1": theme("t1", "Alpha"), "t2": theme("t2", "Beta")}


def fake_returns():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"SPY": rng.normal(0, 0.01, N), "TLT": rng.normal(0, 0.008, N), "CTRL": rng.normal(0, 0.01, N)})
    for key in THEMES:
        f = rng.normal(0, 0.015, N)
        for i in (1, 2, 3):
            df[f"{key.upper()}H{i}"] = df["SPY"] + f + rng.normal(0, 0.01, N)
        for i in (1, 2):
            df[f"{key.upper()}M{i}"] = df["SPY"] + 0.3 * f + rng.normal(0, 0.012, N) + rng.normal(0, 0.01, N)
    df["ALPHAY"] = df["SPY"] + 0.8 * df[["T1H1", "T1H2", "T1H3"]].mean(axis=1) + rng.normal(0, 0.004, N)
    df["PLAIN"] = df["SPY"] + rng.normal(0, 0.002, N)
    return df


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    df = fake_returns()

    def get_returns(tickers, start, end):
        missing = [t for t in tickers if t not in df]
        if missing:
            raise screen.DataError(f"No price data from FMP or Yahoo for: {', '.join(missing)}")
        return df[tickers]

    monkeypatch.setattr(screen, "get_returns", get_returns)
    monkeypatch.setattr(screen, "load_theme", lambda k: THEMES[k] if k in THEMES else (_ for _ in ()).throw(ValueError(f"No theme called '{k}'")))
    monkeypatch.setattr(screen, "load_all", lambda: THEMES)
    monkeypatch.setattr(screen, "industry_of", lambda t: "Widgets" if t == "ALPHAY" else None)
    monkeypatch.setattr(screen, "revenue_for", lambda t, k: None)  # no FMP calls for fake tickers


def test_tiers_cash_and_fingerprint():
    rep = screen.run_screen({"ALPHAY": 30, "T2H1": 20, "CASH": 50})
    by = {h["ticker"]: h for h in rep["holdings"]}
    assert by["ALPHAY"]["results"]["t1"]["tier"] == "High"
    assert by["ALPHAY"]["results"]["t2"]["tier"] == "Limited"
    assert by["T2H1"]["results"]["t2"]["method"] == "listed reference"
    assert by["CASH"]["results"].startswith("cash")
    fp = rep["fingerprint"]
    assert fp["t1"]["high_moderate_pct"] == 30 and fp["t2"]["high_moderate_pct"] == 20
    assert fp["t1"]["business_linked_pct"] == 30 and fp["t1"]["price_only_pct"] == 0  # ALPHAY is in a Widgets business
    assert fp["t2"]["business_linked_pct"] == 20  # T2H1 is a named reference
    assert by["ALPHAY"]["results"]["t1"]["business_linked"] is True
    assert fp["t1"]["cash_pct"] == 50
    assert sum(fp["t1"]["by_tier_pct"].values()) + fp["t1"]["cash_pct"] == pytest.approx(100)
    assert "Alpha exposure: 30% of your portfolio (ALPHAY)" in fp["t1"]["sentence"]
    assert by["ALPHAY"]["results"]["t1"]["final_rating"] == "High"
    json.dumps(rep)  # must be JSON-serializable


def test_weights_rescaled_when_not_100():
    rep = screen.run_screen({"ALPHAY": 1, "PLAIN": 3}, ["t1"])
    assert rep["weights_rescaled_to_100"] is True
    assert [h["weight_pct"] for h in rep["holdings"]] == [25, 75]
    assert rep["fingerprint"]["t1"]["high_moderate_pct"] == 25


def test_all_cash_portfolio():
    rep = screen.run_screen({"CASH": 100}, ["t1"])
    assert rep["fingerprint"]["t1"]["high_moderate_pct"] == 0
    assert rep["fingerprint"]["t1"]["sentence"].startswith("Alpha exposure: none of your portfolio is rated High or Moderate")


def test_unknown_ticker_is_not_determined_with_reason():
    rep = screen.run_screen({"NOPE": 50, "ALPHAY": 50}, ["t1"])
    r = rep["holdings"][0]["results"]["t1"]
    assert r["tier"] == "Not determined" and r["method"] == "not screened" and "NOPE" in r["error"]
    assert "the data can't tell" in rep["fingerprint"]["t1"]["sentence"]


def test_market_control_as_holding_is_not_screened():
    r = screen.run_screen({"SPY": 100}, ["t1"])["holdings"][0]["results"]["t1"]
    assert r["method"] == "not screened" and "market controls" in r["sentence"]


def test_direct_listed_needs_no_prices():
    r = screen.run_screen({"T1DIRECT": 100}, ["t1"])["holdings"][0]["results"]["t1"]
    assert (r["tier"], r["method"]) == ("Moderate", "direct classification")


@pytest.mark.parametrize("items, msg", [
    ([], "No holdings"), (["NVDA30"], "TICKER:WEIGHT"), ([":30"], "TICKER:WEIGHT"),
    (["NVDA:abc"], "isn't a number"), (["NVDA:-5"], "positive"), (["NVDA:0"], "positive"),
    (["NVDA:nan"], "positive"), (["NVDA:inf"], "positive"), (["NVDA:10", "nvda:20"], "twice"),
])
def test_parse_errors(items, msg):
    with pytest.raises(screen.InputError, match=msg):
        screen.parse_holdings(items)


def test_parse_ok_and_lowercase():
    assert screen.parse_holdings(["nvda:30", "Cash:70"]) == {"NVDA": 30.0, "CASH": 70.0}


def test_run_screen_bad_inputs():
    with pytest.raises(screen.InputError):
        screen.run_screen({})
    with pytest.raises(screen.InputError, match="positive"):
        screen.run_screen({"A": -1})
    with pytest.raises(screen.InputError, match="No theme"):
        screen.run_screen({"ALPHAY": 100}, ["nope"])


def test_cli_summary_json_and_errors(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "ROOT", tmp_path)
    assert screen.main(["ALPHAY:30", "CASH:70", "--themes", "t1"]) == 0
    out = capsys.readouterr().out
    assert "Portfolio fingerprint" in out and "ALPHAY (30%)" in out and "cash: kept" in out
    assert "Exposure %" in out and "Market-driven %" in out and "business linked: yes" in out
    assert json.loads((tmp_path / "results" / "screen_latest.json").read_text())["cash_pct"] == 70
    assert screen.main(["ALPHAY:1", "PLAIN:1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["weights_rescaled_to_100"] is True
    assert screen.main(["NVDA30"]) == 2
    assert "Error:" in capsys.readouterr().err


def test_price_co_movement_only_is_reported_separately(monkeypatch):
    monkeypatch.setattr(screen, "industry_of", lambda t: None)  # ALPHAY moves with t1 but isn't in its business
    fp = screen.run_screen({"ALPHAY": 30, "CASH": 70}, ["t1"])["fingerprint"]["t1"]
    assert (fp["business_linked_pct"], fp["price_only_pct"], fp["high_moderate_pct"]) == (0, 30, 0)
    assert "Caution, market-driven: 30% (ALPHAY)" in fp["sentence"]
    assert fp["market_driven_pct"] == 30 and fp["exposure_pct"] == 0
