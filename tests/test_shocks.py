"""Tests for theme shocks, using made-up returns with known betas (no internet)."""

import numpy as np
import pandas as pd
import pytest

from engine import shocks
from engine.data import DataError
from engine.shocks import ShockError

THEME = {
    "key": "oil", "name": "Oil", "plain": "oil producers", "controls": ["SPY", "TLT", "VALUE"],
    "references": {"High": [{"ticker": "R1"}, {"ticker": "R2"}], "Moderate": [{"ticker": "R3"}, {"ticker": "R4"}]},
    "control": {"ticker": "CTL"}, "direct_classification": [],
}


def returns_table(n=500, seed=0):
    """Controls, four references and holdings with KNOWN theme betas.

    HOLD: beta 0.6 to the reference average. ZERO: beta 0. R1 is built independently of R2..R4,
    so measured against the OTHER references its beta should be about 0.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-11-15", periods=n)
    d = {"SPY": rng.normal(0, 0.01, n), "TLT": rng.normal(0, 0.008, n), "VALUE": rng.normal(0, 0.005, n)}
    common = rng.normal(0, 0.015, n)
    d["R1"] = rng.normal(0, 0.015, n) + 0.8 * d["SPY"]
    for r in ("R2", "R3", "R4"):
        d[r] = common + rng.normal(0, 0.005, n) + 0.8 * d["SPY"]
    basket = pd.DataFrame(d)[["R1", "R2", "R3", "R4"]].mean(axis=1).to_numpy()
    d["HOLD"] = 0.6 * basket + 1.1 * d["SPY"] + rng.normal(0, 0.004, n)
    d["ZERO"] = 1.0 * d["SPY"] + rng.normal(0, 0.01, n)
    d["CTL"] = rng.normal(0, 0.01, n)
    return pd.DataFrame(d, index=idx)


# ---- betas ----

def test_known_beta_recovered():
    beta, se, n = shocks.theme_beta("HOLD", THEME, returns_table())
    assert abs(beta - 0.6) < 3 * se and se < 0.05 and n == 500


def test_unrelated_stock_has_beta_near_zero():
    beta, se, _ = shocks.theme_beta("ZERO", THEME, returns_table())
    assert abs(beta) < 3 * se


def test_reference_is_measured_against_the_others_only():
    """R1 doesn't move with R2..R4. Leaving itself in the basket would fake a large beta."""
    beta, se, _ = shocks.theme_beta("R1", THEME, returns_table())
    assert abs(beta) < 3 * se


def test_beta_errors():
    one_ref = {**THEME, "references": {"High": [{"ticker": "R1"}], "Moderate": []}}
    with pytest.raises(ValueError, match="no other reference"):
        shocks.theme_beta("R1", one_ref, returns_table())
    with pytest.raises(ValueError, match="Missing returns for: NOPE"):
        shocks.theme_beta("NOPE", THEME, returns_table())
    with pytest.raises(ValueError, match="only 30 shared days"):
        shocks.theme_beta("HOLD", THEME, returns_table(30))


def test_sensitivities_cash_controls_and_failures():
    w = {"HOLD": 0.4, "SPY": 0.2, "NOPE": 0.1, "CASH": 0.3}
    s = shocks.sensitivities(w, THEME, returns_table())
    assert s["CASH"]["beta"] == 0 and s["SPY"]["beta"] == 0 and "market control" in s["SPY"]["note"]
    assert s["NOPE"]["beta"] is None and "Couldn't estimate" in s["NOPE"]["note"]
    assert s["HOLD"]["beta"] == pytest.approx(0.6, abs=0.1)


# ---- applying a shock ----

SENS = {"A": {"beta": 0.5, "se": 0.1, "note": ""}, "B": {"beta": -0.2, "se": 0.1, "note": ""},
        "CASH": {"beta": 0.0, "se": 0.0, "note": "Cash doesn't move."}}


def test_portfolio_move_is_weighted_sum_by_hand():
    res = shocks.apply_shock({"A": 0.5, "B": 0.3, "CASH": 0.2}, SENS, "oil", THEME, 0.30)
    # 0.5 x 0.5 x 30% + 0.3 x -0.2 x 30% = 7.5% - 1.8% = 5.7%
    assert res.portfolio_move == pytest.approx(0.057)
    assert res.covered_weight == pytest.approx(1.0)
    a = next(h for h in res.holdings if h.ticker == "A")
    assert a.move == pytest.approx(0.15) and a.contribution == pytest.approx(0.075)
    assert "oil producers rose 30% more than the overall market" in res.sentence
    assert "+5.7%" in res.sentence and shocks.LABEL in res.sentence
    assert "biggest effect comes from A (+7.5%)" in res.sentence
    assert res.label == "estimated sensitivity based on past co-movement"


def test_negative_shock_flips_the_move():
    res = shocks.apply_shock({"A": 0.5, "B": 0.3, "CASH": 0.2}, SENS, "oil", THEME, -0.30)
    assert res.portfolio_move == pytest.approx(-0.057)
    assert "fell 30%" in res.sentence and "-5.7%" in res.sentence


def test_missing_beta_is_reported_not_hidden():
    sens = {**SENS, "B": {"beta": None, "se": None, "note": "Couldn't estimate: no data"}}
    res = shocks.apply_shock({"A": 0.5, "B": 0.3, "CASH": 0.2}, sens, "oil", THEME, 0.30)
    assert res.covered_weight == pytest.approx(0.7)
    assert res.portfolio_move == pytest.approx(0.075)
    assert "B couldn't be estimated, so 30% of the portfolio is left out" in res.sentence


def test_tiny_moves_skip_the_biggest_effect_line():
    sens = {"A": {"beta": 0.001, "se": 0.1, "note": ""}}
    res = shocks.apply_shock({"A": 1.0}, sens, "oil", THEME, 0.30)
    assert "biggest effect" not in res.sentence


def test_theme_without_plain_name():
    theme = {k: v for k, v in THEME.items() if k != "plain"}
    res = shocks.apply_shock({"A": 1.0}, SENS, "oil", theme, 0.10)
    assert "If Oil stocks rose 10%" in res.sentence


@pytest.mark.parametrize("bad, message", [(1.5, "between -100% and \\+100%"), (-2, "between"),
                                          (float("nan"), "must be a number"), (True, "must be a number"),
                                          ("0.3", "must be a number")])
def test_bad_shock_sizes(bad, message):
    with pytest.raises(ShockError, match=message):
        shocks.apply_shock({"A": 1.0}, SENS, "oil", THEME, bad)


def test_end_to_end_on_made_up_returns():
    res = shocks.shock_from_returns({"HOLD": 0.5, "ZERO": 0.3, "CASH": 0.2}, "oil", THEME, 0.30, returns_table())
    # HOLD beta ~0.6 -> ~0.5 x 0.6 x 30% = ~9%; ZERO ~0.
    assert res.portfolio_move == pytest.approx(0.09, abs=0.02)
    assert res.to_dict()["holdings"][0]["ticker"] == "HOLD"


# ---- fetching data ----

def test_shock_portfolio_fetches_everything_once(monkeypatch):
    seen = []

    def fake(tickers, start, end):
        seen.append(tickers)
        return returns_table()

    monkeypatch.setattr(shocks, "get_returns", fake)
    monkeypatch.setattr(shocks, "load_theme", lambda key: THEME)
    res = shocks.shock_portfolio({"HOLD": 0.7, "CASH": 0.3}, "oil", 0.3)
    assert seen == [["HOLD", "SPY", "TLT", "VALUE", "R1", "R2", "R3", "R4"]]
    assert res.portfolio_move == pytest.approx(0.7 * 0.6 * 0.3, abs=0.02)


def test_one_holding_without_data_doesnt_sink_the_rest(monkeypatch):
    table = returns_table()

    def fake(tickers, start, end):
        if "NEW" in tickers:
            raise DataError("No price data from FMP or Yahoo for: NEW")
        return table[[t for t in tickers]]

    monkeypatch.setattr(shocks, "get_returns", fake)
    monkeypatch.setattr(shocks, "load_theme", lambda key: THEME)
    res = shocks.shock_portfolio({"HOLD": 0.5, "NEW": 0.5}, "oil", 0.3)
    new = next(h for h in res.holdings if h.ticker == "NEW")
    assert new.beta is None and res.covered_weight == pytest.approx(0.5)
    assert next(h for h in res.holdings if h.ticker == "HOLD").beta == pytest.approx(0.6, abs=0.1)


def test_reference_data_failure_is_a_clear_error(monkeypatch):
    def fake(tickers, start, end):
        raise DataError("FMP is down")

    monkeypatch.setattr(shocks, "get_returns", fake)
    monkeypatch.setattr(shocks, "load_theme", lambda key: THEME)
    with pytest.raises(ShockError, match="Couldn't load the Oil reference data"):
        shocks.shock_portfolio({"HOLD": 1.0}, "oil", 0.3)


@pytest.fixture(autouse=True)
def _no_country_lookups(monkeypatch):
    """Fake tickers like HOLD must never trigger a real FMP country lookup."""
    monkeypatch.setattr(shocks, "intl_control", lambda t: None)


# ---- international control (non-US holdings get INTL = VXUS - SPY, like the classification) ----

def test_intl_control_is_used_for_non_us_holdings(monkeypatch):
    """HOLD here is a non-US stock that moves with the non-US market swing, not the theme. Without the INTL
    control the theme basket would soak some of that up; with it, the theme beta is the true 0.3."""
    table = returns_table()
    rng = np.random.default_rng(9)
    table["INTL"] = rng.normal(0, 0.01, len(table)) + 0.5 * table[["R2", "R3", "R4"]].mean(axis=1)
    basket = table[["R1", "R2", "R3", "R4"]].mean(axis=1)
    table["HOLD"] = 0.3 * basket + 1.0 * table["INTL"] + 1.1 * table["SPY"] + rng.normal(0, 0.003, len(table))
    seen = []

    def fake_get(tickers, start, end):
        seen.append(tickers)
        return table

    monkeypatch.setattr(shocks, "get_returns", fake_get)
    monkeypatch.setattr(shocks, "load_theme", lambda key: THEME)
    monkeypatch.setattr(shocks, "intl_control", lambda t: "INTL" if t == "HOLD" else None)
    res = shocks.shock_portfolio({"HOLD": 1.0}, "oil", 0.3)
    assert "INTL" in seen[0]
    assert res.holdings[0].beta == pytest.approx(0.3, abs=0.05)
    without = shocks.theme_beta("HOLD", THEME, table)[0]
    assert without > 0.5  # leaving the INTL control out would overstate the theme beta


def test_no_intl_control_for_us_holdings(monkeypatch):
    seen = []

    def fake_get(tickers, start, end):
        seen.append(tickers)
        return returns_table()

    monkeypatch.setattr(shocks, "get_returns", fake_get)
    monkeypatch.setattr(shocks, "load_theme", lambda key: THEME)
    monkeypatch.setattr(shocks, "intl_control", lambda t: None)
    shocks.shock_portfolio({"HOLD": 1.0}, "oil", 0.3)
    assert "INTL" not in seen[0]
