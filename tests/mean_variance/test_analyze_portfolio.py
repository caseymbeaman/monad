"""Tests for the main entry point: input checks, the full pipeline, and the command line."""

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from engine.mean_variance import analyze_portfolio as ap
from engine.mean_variance.errors import (
    DataFetchError,
    InsufficientDataError,
    PortfolioInputError,
)
from tests.mean_variance.price_simulator import make_prices

# ---- input checks ----

def test_valid_weights_cleaned_up():
    assert ap.validate_weights({" aapl ": 0.6, "msft": 0.4}) == {"AAPL": 0.6, "MSFT": 0.4}


def test_weights_within_tolerance_rescaled_to_100_percent():
    result = ap.validate_weights({"A": 0.5, "B": 0.495})
    assert sum(result.values()) == pytest.approx(1.0)
    assert result["A"] == pytest.approx(0.5 / 0.995)


def test_zero_weight_allowed():
    assert ap.validate_weights({"A": 1.0, "B": 0}) == {"A": 1.0, "B": 0.0}


def test_integer_weights_allowed():
    assert ap.validate_weights({"A": 1, "B": 0}) == {"A": 1.0, "B": 0.0}


@pytest.mark.parametrize(
    "weights, message",
    [
        (None, "Enter the portfolio"),
        ([("A", 1.0)], "Enter the portfolio"),
        ({}, "Enter the portfolio"),
        ({"A": 1.0}, "at least two stocks"),
        ({"": 0.5, "B": 0.5}, "not a valid ticker"),
        ({"  ": 0.5, "B": 0.5}, "not a valid ticker"),
        ({7: 0.5, "B": 0.5}, "not a valid ticker"),
        ({"aapl": 0.5, "AAPL": 0.5}, "AAPL appears more than once"),
        ({"A": "0.5", "B": 0.5}, "must be a number"),
        ({"A": True, "B": 0.0}, "must be a number"),
        ({"A": None, "B": 0.5}, "must be a number"),
        ({"A": float("nan"), "B": 0.5}, "finite"),
        ({"A": float("inf"), "B": 0.5}, "finite"),
        ({"A": 1.2, "B": -0.2}, "B has a negative weight"),
        ({"A": 0.5, "B": 0.4}, "add up to 90.0%"),
        ({"A": 0.6, "B": 0.6}, "add up to 120.0%"),
        ({"A": 0.0, "B": 0.0}, "add up to 0.0%"),
        ({"A": 1e12, "B": 1e12}, "need to add up to 100%"),
    ],
)
def test_bad_portfolios_give_clear_errors(weights, message):
    with pytest.raises(PortfolioInputError, match=message):
        ap.validate_weights(weights)


@pytest.mark.parametrize(
    "today, expected",
    [(dt.date(2026, 11, 15), dt.date(2026, 10, 31)),
     (dt.date(2026, 1, 5), dt.date(2025, 12, 31)),
     (dt.date(2024, 3, 1), dt.date(2024, 2, 29)),
     (dt.date(2026, 10, 31), dt.date(2026, 9, 30))],
)
def test_last_complete_month(today, expected):
    assert ap._last_complete_month_end(today) == expected


# ---- full pipeline on made-up prices ----

def test_evaluate_matches_independent_calculation(prices_three):
    weights = {"AAA": 0.5, "BBB": 0.3, "CCC": 0.2}
    rf = 0.04
    result = ap.evaluate(weights, prices_three, rf)

    # Independent check, written without the tool's own helpers
    month_end = prices_three.groupby(prices_three.index.to_period("M")).last()
    monthly = (month_end / month_end.shift(1) - 1).dropna().to_numpy()
    w = np.array([0.5, 0.3, 0.2])
    port = monthly @ w
    expected_return = port.mean() * 12
    expected_vol = port.std(ddof=1) * math.sqrt(12)

    mine = result.summary.loc["Your portfolio"]
    assert mine["return"] == pytest.approx(expected_return)
    assert mine["volatility"] == pytest.approx(expected_vol)
    assert mine["sharpe"] == pytest.approx((expected_return - rf) / expected_vol)

    assert list(result.summary.index) == ["Your portfolio", "Minimum-variance portfolio",
                                          "Tangency portfolio"]
    min_var = result.summary.loc["Minimum-variance portfolio"]
    tangency = result.summary.loc["Tangency portfolio"]
    assert min_var["volatility"] <= mine["volatility"] + 1e-9
    assert tangency["sharpe"] >= mine["sharpe"] - 1e-9
    assert result.figure is not None and result.window_mode == "shared"


def test_evaluate_caps_history_at_ten_years():
    prices = make_prices(["AAA", "BBB"], years=13)
    result = ap.evaluate({"AAA": 0.5, "BBB": 0.5}, prices, 0.04)
    assert set(result.windows["months"]) == {120}


def test_evaluate_both_window_modes_with_young_stock(prices_with_ipo):
    weights = {"AAA": 0.4, "BBB": 0.4, "NEW": 0.2}
    shared = ap.evaluate(weights, prices_with_ipo, 0.04, "shared")
    full = ap.evaluate(weights, prices_with_ipo, 0.04, "max_available")
    assert shared.windows.loc["AAA", "months"] == shared.windows.loc["NEW", "months"]
    assert full.windows.loc["AAA", "months"] > full.windows.loc["NEW", "months"]
    assert "each stock's own history" in full.figure.layout.title.text


def test_evaluate_without_tangency(prices_three):
    result = ap.evaluate({"AAA": 0.5, "BBB": 0.5, "CCC": 0.0}, prices_three, 5.0)
    assert "Tangency portfolio" not in result.summary.index
    assert "no tangency portfolio" in result.figure.layout.title.text


def test_evaluate_missing_prices(prices_three):
    with pytest.raises(PortfolioInputError, match="No prices supplied for: ZZZ"):
        ap.evaluate({"AAA": 0.5, "ZZZ": 0.5}, prices_three, 0.04)


def test_evaluate_not_enough_overlap():
    prices = make_prices(["AAA", "NEW"], start_after={"NEW": "2025-06-01"})
    with pytest.raises(InsufficientDataError, match="only share .* NEW has only 16 months of prices"):
        ap.evaluate({"AAA": 0.5, "NEW": 0.5}, prices, 0.04)


# ---- live entry point, with the internet replaced ----

@pytest.fixture
def fake_fmp(monkeypatch, prices_three):
    calls = {}

    def fake_prices(tickers, start, end):
        calls["prices"] = (tickers, start, end)
        return prices_three[tickers]

    def fake_yield(today=None):
        calls["yield"] = today
        return 0.0515

    monkeypatch.setattr(ap.data_fetcher, "fetch_adjusted_prices", fake_prices)
    monkeypatch.setattr(ap.data_fetcher, "fetch_ten_year_yield", fake_yield)
    return calls


def test_analyze_portfolio_requests_right_dates_and_saves_chart(fake_fmp, tmp_path):
    out = tmp_path / "chart.html"
    result = ap.analyze_portfolio({"aaa": 0.5, "BBB": 0.5},
                                  today=dt.date(2026, 11, 15), output_path=str(out))
    tickers, start, end = fake_fmp["prices"]
    assert tickers == ["AAA", "BBB"]
    assert end == dt.date(2026, 10, 31)
    assert start == dt.date(2016, 9, 30)
    assert result.risk_free_rate == 0.0515
    assert out.exists() and out.stat().st_size > 1000


def test_analyze_portfolio_without_saving(fake_fmp):
    result = ap.analyze_portfolio({"AAA": 0.5, "BBB": 0.5})
    assert result.summary is not None


def test_analyze_portfolio_rejects_bad_input_before_calling_fmp(fake_fmp):
    with pytest.raises(PortfolioInputError):
        ap.analyze_portfolio({"AAA": 0.5, "BBB": 0.5}, window_mode="weekly")
    with pytest.raises(PortfolioInputError):
        ap.analyze_portfolio({"AAA": 2.0, "BBB": 0.5})
    assert fake_fmp == {}


# ---- command line ----

def test_parse_cli_weights():
    assert ap._parse_cli_weights(["AAPL=0.4", "MSFT=.6"]) == {"AAPL": 0.4, "MSFT": 0.6}


@pytest.mark.parametrize("pair, message",
                         [("AAPL", "TICKER=WEIGHT"), ("AAPL=abc", "not a number")])
def test_parse_cli_bad_pairs(pair, message):
    with pytest.raises(PortfolioInputError, match=message):
        ap._parse_cli_weights([pair])


def test_format_summary_handles_missing_sharpe():
    summary = pd.DataFrame({"return": [0.1], "volatility": [0.0], "sharpe": [float("nan")]},
                           index=["Your portfolio"])
    summary["weights"] = pd.Series({"Your portfolio": pd.Series({"A": 1.0, "B": 0.0})},
                                   dtype=object)
    text = ap.format_summary(summary)
    assert "n/a" in text and "A 100.0%" in text and "B 0.0%" not in text


def test_cli_success(fake_fmp, tmp_path, capsys):
    out = tmp_path / "c.html"
    code = ap.main(["AAA=0.5", "BBB=0.5", "--window", "max_available", "--output", str(out)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "Risk-free rate (10-year Treasury): 5.15%" in printed
    assert "Tangency portfolio" in printed and out.exists()


def test_cli_error_is_a_message_not_a_crash(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise DataFetchError("FMP rate limit reached.")

    monkeypatch.setattr(ap, "analyze_portfolio", fail)
    code = ap.main(["AAA=0.5", "BBB=0.5"])
    assert code == 1
    assert capsys.readouterr().err.strip() == "Error: FMP rate limit reached."


def test_cli_rejects_unknown_window():
    with pytest.raises(SystemExit):
        ap.main(["AAA=0.5", "BBB=0.5", "--window", "weekly"])
