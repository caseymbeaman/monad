"""Tests for the frontier math, checked against textbook formulas worked out separately."""

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import OptimizeResult

from engine.mean_variance import optimizer as opt
from engine.mean_variance.errors import OptimizationError

TICKERS = ["A", "B", "C"]
MU = pd.Series([0.08, 0.12, 0.15], index=TICKERS)
VOLS = np.array([0.15, 0.20, 0.30])
CORR = np.array([[1.0, 0.3, 0.2], [0.3, 1.0, 0.4], [0.2, 0.4, 1.0]])
COV = pd.DataFrame(np.outer(VOLS, VOLS) * CORR, index=TICKERS, columns=TICKERS)


def _two_asset_cov(vol1, vol2, corr):
    cov12 = vol1 * vol2 * corr
    return pd.DataFrame([[vol1**2, cov12], [cov12, vol2**2]], index=["X", "Y"],
                        columns=["X", "Y"])


# ---- basic stats ----

def test_portfolio_return_and_volatility_by_hand():
    cov = _two_asset_cov(0.10, 0.20, 0.5)
    w = np.array([0.5, 0.5])
    assert opt.portfolio_return(w, [0.06, 0.10]) == pytest.approx(0.08)
    # variance = .25*.01 + .25*.04 + 2*.25*(.10*.20*.5) = .0025 + .01 + .005 = .0175
    assert opt.portfolio_volatility(w, cov) == pytest.approx(np.sqrt(0.0175))


def test_sharpe_ratio():
    assert opt.sharpe_ratio(0.12, 0.20, 0.04) == pytest.approx(0.4)
    assert np.isnan(opt.sharpe_ratio(0.12, 0.0, 0.04))


def test_zero_weights_give_zero_return_and_risk():
    assert opt.portfolio_return([0, 0, 0], MU) == 0.0
    assert opt.portfolio_volatility([0, 0, 0], COV) == 0.0


# ---- minimum-variance portfolio ----

@pytest.mark.parametrize("vol1, vol2, corr", [(0.10, 0.20, 0.3), (0.25, 0.15, -0.5),
                                               (0.20, 0.20, 0.0)])
def test_two_asset_min_variance_matches_formula(vol1, vol2, corr):
    cov = _two_asset_cov(vol1, vol2, corr)
    s11, s22, s12 = cov.iloc[0, 0], cov.iloc[1, 1], cov.iloc[0, 1]
    expected_x = (s22 - s12) / (s11 + s22 - 2 * s12)
    weights = opt.min_variance_portfolio(cov)
    assert weights["X"] == pytest.approx(expected_x, abs=1e-6)
    assert weights.sum() == pytest.approx(1.0)


def test_min_variance_long_only_corner():
    """Formula says short Y (high correlation, Y much riskier); long-only answer is 100% X."""
    cov = _two_asset_cov(0.10, 0.40, 0.9)
    weights = opt.min_variance_portfolio(cov)
    assert weights["X"] == pytest.approx(1.0)
    assert weights["Y"] == 0.0


def test_min_variance_beats_random_portfolios():
    rng = np.random.default_rng(0)
    best = opt.portfolio_volatility(opt.min_variance_portfolio(COV), COV)
    for w in rng.dirichlet(np.ones(3), size=5000):
        assert opt.portfolio_volatility(w, COV) >= best - 1e-9


# ---- tangency portfolio ----

def test_tangency_matches_closed_form_when_no_shorts_needed():
    rf = 0.03
    raw = np.linalg.solve(COV.to_numpy(), (MU - rf).to_numpy())
    assert (raw > 0).all()  # so the long-only answer equals the textbook one
    expected = raw / raw.sum()
    weights = opt.tangency_portfolio(MU, COV, rf)
    np.testing.assert_allclose(weights.to_numpy(), expected, atol=1e-6)


def test_tangency_has_the_best_sharpe_ratio():
    rf = 0.03
    t = opt.tangency_portfolio(MU, COV, rf)
    best = opt.sharpe_ratio(opt.portfolio_return(t, MU), opt.portfolio_volatility(t, COV), rf)
    for _, row in opt.efficient_frontier(MU, COV).iterrows():
        assert opt.sharpe_ratio(row["return"], row["volatility"], rf) <= best + 1e-9
    rng = np.random.default_rng(1)
    for w in rng.dirichlet(np.ones(3), size=5000):
        s = opt.sharpe_ratio(opt.portfolio_return(w, MU), opt.portfolio_volatility(w, COV), rf)
        assert s <= best + 1e-9


def test_tangency_ignores_stocks_below_risk_free_rate():
    mu = pd.Series([0.02, 0.12, 0.15], index=TICKERS)
    weights = opt.tangency_portfolio(mu, COV, 0.05)
    assert weights["A"] == 0.0
    assert weights.sum() == pytest.approx(1.0)


@pytest.mark.parametrize("rf", [0.15, 0.20, 1.0])
def test_no_tangency_when_nothing_beats_risk_free_rate(rf):
    assert opt.tangency_portfolio(MU, COV, rf) is None


# ---- efficient frontier ----

def test_frontier_shape():
    frontier = opt.efficient_frontier(MU, COV, n_points=30)
    assert len(frontier) == 30
    min_var = opt.min_variance_portfolio(COV)
    assert frontier["return"].iloc[0] == pytest.approx(opt.portfolio_return(min_var, MU))
    assert frontier["return"].iloc[-1] == pytest.approx(MU.max())
    assert frontier["return"].is_monotonic_increasing
    assert (frontier["volatility"].diff().dropna() > -1e-9).all()  # risk rises with return
    weights = frontier[TICKERS]
    assert (weights >= 0).all().all()
    np.testing.assert_allclose(weights.sum(axis=1), 1.0)


def test_no_random_portfolio_beats_the_frontier():
    """Independent check: no mix of the stocks has less risk than the frontier
    at the same expected return."""
    frontier = opt.efficient_frontier(MU, COV, n_points=200)
    rng = np.random.default_rng(2)
    for w in rng.dirichlet(np.ones(3), size=5000):
        ret = opt.portfolio_return(w, MU)
        if ret < frontier["return"].iloc[0]:
            continue  # below the minimum-variance point: not on the efficient side
        frontier_vol = np.interp(ret, frontier["return"], frontier["volatility"])
        # Small allowance for straight-line interpolation between frontier points
        assert opt.portfolio_volatility(w, COV) >= frontier_vol - 2e-4


def test_frontier_too_few_points():
    with pytest.raises(ValueError, match="at least 2"):
        opt.efficient_frontier(MU, COV, n_points=1)


def test_frontier_when_all_stocks_have_same_return():
    mu = pd.Series([0.10, 0.10, 0.10], index=TICKERS)
    frontier = opt.efficient_frontier(mu, COV, n_points=5)
    assert frontier["return"].tolist() == pytest.approx([0.10] * 5)


def test_very_large_and_very_small_numbers():
    """Scaling risk and return by the same factor scales the answer, not the weights."""
    small = opt.min_variance_portfolio(COV * 1e-4)
    normal = opt.min_variance_portfolio(COV)
    np.testing.assert_allclose(small, normal, atol=1e-5)
    big = opt.tangency_portfolio(MU * 100, COV * 1e4, 3.0)
    np.testing.assert_allclose(big, opt.tangency_portfolio(MU, COV, 0.03), atol=1e-5)


# ---- solver failures ----

def _failed_result(*args, **kwargs):
    return OptimizeResult(x=np.array([np.nan, np.nan, np.nan]), success=False,
                          message="forced failure")


def test_min_variance_solver_failure_reported(monkeypatch):
    monkeypatch.setattr(opt, "minimize", _failed_result)
    with pytest.raises(OptimizationError, match="minimum-risk portfolio: forced failure"):
        opt.min_variance_portfolio(COV)


def test_tangency_solver_failure_reported(monkeypatch):
    monkeypatch.setattr(opt, "minimize", _failed_result)
    with pytest.raises(OptimizationError, match="tangency portfolio: forced failure"):
        opt.tangency_portfolio(MU, COV, 0.03)


def test_solver_warning_accepted_when_answer_is_valid(monkeypatch):
    """The solver can flag a warning at an answer that is actually fine."""
    def warn_but_valid(fun, x0, **kwargs):
        return OptimizeResult(x=np.array([0.2, 0.3, 0.5]), success=False,
                              message="Positive directional derivative for linesearch")

    monkeypatch.setattr(opt, "minimize", warn_but_valid)
    weights = opt.min_variance_portfolio(COV)
    np.testing.assert_allclose(weights, [0.2, 0.3, 0.5])


def test_feasibility_check_rejects_bad_answers():
    sums_to_one = [{"fun": lambda w: np.sum(w) - 1.0}]
    assert opt._is_feasible(OptimizeResult(x=np.array([0.5, 0.5])), sums_to_one)
    assert not opt._is_feasible(OptimizeResult(x=np.array([0.5, 0.6])), sums_to_one)
    assert not opt._is_feasible(OptimizeResult(x=np.array([1.5, -0.5])), sums_to_one)
    assert not opt._is_feasible(OptimizeResult(x=np.array([np.nan, 1.0])), sums_to_one)
