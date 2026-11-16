"""Tests for turning prices into expected returns and a risk model."""

import numpy as np
import pandas as pd
import pytest

from engine.mean_variance import return_calculator as rc
from engine.mean_variance.errors import InsufficientDataError, PortfolioInputError


def test_monthly_returns_match_hand_calculation():
    dates = pd.to_datetime(["2020-01-15", "2020-01-31", "2020-02-28", "2020-03-31"])
    prices = pd.DataFrame({"X": [90.0, 100.0, 110.0, 99.0]}, index=dates)
    returns = rc.to_monthly_returns(prices)
    # Jan month-end 100 -> Feb 110 = +10%; Feb 110 -> Mar 99 = -10%
    assert returns["X"].tolist() == pytest.approx([0.10, -0.10])
    assert [d.month for d in returns.index] == [2, 3]


def test_month_before_ipo_stays_blank():
    dates = pd.to_datetime(["2020-01-31", "2020-02-28", "2020-03-31"])
    prices = pd.DataFrame({"OLD": [10.0, 11.0, 12.1], "NEW": [np.nan, 50.0, 55.0]},
                          index=dates)
    returns = rc.to_monthly_returns(prices)
    assert np.isnan(returns["NEW"].iloc[0])
    assert returns["NEW"].iloc[1] == pytest.approx(0.10)


def test_monthly_returns_unaffected_by_price_scale():
    dates = pd.to_datetime(["2020-01-31", "2020-02-28", "2020-03-31"])
    small = pd.DataFrame({"X": [1.0, 1.2, 0.9]}, index=dates)
    big = small * 1e9
    pd.testing.assert_frame_equal(rc.to_monthly_returns(small), rc.to_monthly_returns(big))


def test_no_prices():
    with pytest.raises(InsufficientDataError, match="No price data"):
        rc.to_monthly_returns(pd.DataFrame())


def test_shared_mode_matches_independent_numpy_calculation(prices_three):
    monthly = rc.to_monthly_returns(prices_three)
    result = rc.estimate_inputs(monthly, "shared")

    raw = monthly.dropna().to_numpy()
    expected_mean = raw.mean(axis=0) * 12
    expected_cov = np.cov(raw, rowvar=False, ddof=1) * 12
    assert result.expected_returns.to_numpy() == pytest.approx(expected_mean)
    assert result.covariance.to_numpy() == pytest.approx(expected_cov)
    assert set(result.windows["months"]) == {len(raw)}


def test_shared_mode_uses_only_overlap(prices_with_ipo):
    monthly = rc.to_monthly_returns(prices_with_ipo)
    result = rc.estimate_inputs(monthly, "shared")
    new_months = monthly["NEW"].notna().sum()
    assert result.windows.loc["AAA", "months"] == new_months
    assert result.windows.loc["AAA", "start"] == result.windows.loc["NEW", "start"]


def test_max_available_uses_each_stocks_own_history(prices_with_ipo):
    monthly = rc.to_monthly_returns(prices_with_ipo)
    result = rc.estimate_inputs(monthly, "max_available")

    aaa_all = monthly["AAA"].dropna()
    assert result.windows.loc["AAA", "months"] == len(aaa_all)
    assert result.windows.loc["NEW", "months"] == monthly["NEW"].notna().sum()
    assert result.expected_returns["AAA"] == pytest.approx(aaa_all.mean() * 12)
    assert result.covariance.loc["AAA", "AAA"] == pytest.approx(aaa_all.var() * 12)

    # Off-diagonal = vol_a * vol_b * correlation over the shared months
    shared = monthly.dropna()
    corr = shared["AAA"].corr(shared["NEW"])
    vol_a = aaa_all.std() * np.sqrt(12)
    vol_n = monthly["NEW"].dropna().std() * np.sqrt(12)
    assert result.covariance.loc["AAA", "NEW"] == pytest.approx(vol_a * vol_n * corr)


def test_max_available_risk_model_is_valid(prices_with_ipo):
    """A valid covariance matrix never implies negative risk (no negative eigenvalues)."""
    monthly = rc.to_monthly_returns(prices_with_ipo)
    cov = rc.estimate_inputs(monthly, "max_available").covariance.to_numpy()
    assert np.allclose(cov, cov.T)
    assert np.linalg.eigvalsh(cov).min() > -1e-12


def test_both_modes_agree_when_all_stocks_have_full_history(prices_three):
    monthly = rc.to_monthly_returns(prices_three)
    shared = rc.estimate_inputs(monthly, "shared")
    full = rc.estimate_inputs(monthly, "max_available")
    pd.testing.assert_series_equal(shared.expected_returns, full.expected_returns)
    np.testing.assert_allclose(shared.covariance, full.covariance)


def test_too_little_shared_history(prices_three):
    monthly = rc.to_monthly_returns(prices_three).iloc[-(rc.MIN_SHARED_MONTHS - 1):]
    with pytest.raises(InsufficientDataError, match="only share 23 months"):
        rc.estimate_inputs(monthly)


def test_exactly_minimum_history_is_accepted(prices_three):
    monthly = rc.to_monthly_returns(prices_three).iloc[-rc.MIN_SHARED_MONTHS:]
    assert len(rc.estimate_inputs(monthly).windows) == 3


@pytest.mark.parametrize("mode", ["", "Shared", "all", None])
def test_unknown_window_mode(prices_three, mode):
    monthly = rc.to_monthly_returns(prices_three)
    with pytest.raises(PortfolioInputError, match="window_mode"):
        rc.estimate_inputs(monthly, mode)


@pytest.mark.parametrize("mode", ["shared", "max_available"])
def test_stock_with_flat_price_rejected(prices_three, mode):
    prices = prices_three.copy()
    prices["CCC"] = 50.0
    monthly = rc.to_monthly_returns(prices)
    with pytest.raises(InsufficientDataError, match="CCC showed no price movement"):
        rc.estimate_inputs(monthly, mode)
