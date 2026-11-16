"""Finds the key portfolios on the risk/return chart. Long-only: no short selling.

- Minimum-variance portfolio: the mix of the stocks with the lowest possible risk.
- Efficient frontier: for each level of expected return, the mix with the
  lowest risk. Anything below this curve is leaving return on the table.
- Tangency portfolio: the mix with the best return per unit of risk above the
  risk-free rate (highest Sharpe ratio). The capital market line runs from the
  risk-free rate through this point.

"Risk" here means volatility: the annual standard deviation of returns.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .errors import OptimizationError

SOLVER_OPTIONS = {"ftol": 1e-12, "maxiter": 1000}
# How far a solver answer may miss a constraint (e.g. weights summing to 1)
# and still count as valid.
FEASIBILITY_TOLERANCE = 1e-6
# Weights this close to zero are rounded to zero (solver leftovers).
WEIGHT_CLEANUP_TOLERANCE = 1e-8


def portfolio_return(weights, expected_returns):
    """Expected annual return of a portfolio."""
    return float(np.dot(weights, expected_returns))


def portfolio_volatility(weights, covariance):
    """Annual volatility of a portfolio."""
    weights = np.asarray(weights, dtype=float)
    variance = float(weights @ np.asarray(covariance, dtype=float) @ weights)
    return float(np.sqrt(max(variance, 0.0)))


def sharpe_ratio(annual_return, volatility, risk_free_rate):
    """Excess return per unit of risk. Blank (NaN) if risk is zero."""
    if volatility <= 0:
        return float("nan")
    return (annual_return - risk_free_rate) / volatility


def _clean(weights):
    """Round tiny solver leftovers to zero and make the weights sum to exactly 1."""
    weights = np.where(np.abs(weights) < WEIGHT_CLEANUP_TOLERANCE, 0.0, weights)
    weights = np.clip(weights, 0.0, None)
    return weights / weights.sum()


def _is_feasible(result, constraints, lower_bound=0.0):
    """True if the solver's answer respects every constraint.

    The solver sometimes stops with a warning when it is already at the answer
    and cannot improve it any further at computer precision. Checking the
    constraints directly tells a usable answer from a real failure.
    """
    x = result.x
    if not np.all(np.isfinite(x)) or np.any(x < lower_bound - FEASIBILITY_TOLERANCE):
        return False
    return all(abs(c["fun"](x)) <= FEASIBILITY_TOLERANCE for c in constraints)


def _normalized(covariance):
    """Covariance rescaled so its average variance is 1.

    The solver decides it is done when improvements fall below a fixed size.
    With very small numbers (e.g. low-volatility assets) it would stop too
    early. Rescaling does not change the best weights, only the units.
    """
    cov = np.asarray(covariance, dtype=float)
    scale = float(np.mean(np.diag(cov)))
    return cov / scale if scale > 0 else cov


def _solve_min_variance(covariance, expected_returns=None, target_return=None,
                        start=None):
    """Lowest-risk long-only weights, optionally hitting a target return.

    start: optional starting guess (e.g. the previous point on the frontier).
    """
    cov = _normalized(covariance)
    n = cov.shape[0]
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    if target_return is not None:
        mu = np.asarray(expected_returns, dtype=float)
        constraints.append({"type": "eq", "fun": lambda w: w @ mu - target_return})

    result = minimize(
        lambda w: w @ cov @ w,
        x0=np.full(n, 1.0 / n) if start is None else np.asarray(start, dtype=float),
        jac=lambda w: 2.0 * cov @ w,
        bounds=[(0.0, 1.0)] * n,
        constraints=constraints,
        method="SLSQP",
        options=SOLVER_OPTIONS,
    )
    if not (result.success or _is_feasible(result, constraints)):
        raise OptimizationError(f"Could not find a minimum-risk portfolio: {result.message}")
    return _clean(result.x)


def min_variance_portfolio(covariance):
    """Weights of the lowest-risk long-only portfolio, as a Series by ticker."""
    return pd.Series(_solve_min_variance(covariance), index=covariance.columns)


def efficient_frontier(expected_returns, covariance, n_points=50):
    """Points along the efficient frontier, from the minimum-variance portfolio
    up to the highest-returning stock.

    Returns a table with columns: return, volatility, and one weight column per ticker.
    """
    if n_points < 2:
        raise ValueError("n_points must be at least 2.")
    tickers = list(covariance.columns)
    mu = expected_returns[tickers].to_numpy(dtype=float)

    min_var_weights = _solve_min_variance(covariance)
    low = portfolio_return(min_var_weights, mu)
    high = float(mu.max())  # long-only: best you can do is 100% in the top stock

    rows = []
    weights = min_var_weights
    for target in np.linspace(low, high, n_points):
        if target != low:
            # Start from the previous point: neighbours on the frontier have
            # similar weights, which makes the solver faster and more reliable.
            weights = _solve_min_variance(covariance, mu, target, start=weights)
        rows.append(
            {
                "return": portfolio_return(weights, mu),
                "volatility": portfolio_volatility(weights, covariance),
                **dict(zip(tickers, weights, strict=True)),
            }
        )
    return pd.DataFrame(rows)


def tangency_portfolio(expected_returns, covariance, risk_free_rate):
    """Weights of the highest-Sharpe long-only portfolio, or None if no stock
    is expected to beat the risk-free rate (then no capital market line exists).

    Method: maximizing the Sharpe ratio directly is awkward for solvers, so we
    use the standard equivalent problem: find the lowest-risk mix with one unit
    of excess return, then rescale those amounts to add up to 100%.
    """
    tickers = list(covariance.columns)
    mu = expected_returns[tickers].to_numpy(dtype=float)
    excess = mu - risk_free_rate
    if not (excess > 0).any():
        return None

    # Rescale both inputs so the solver works with numbers near 1 (see
    # _normalized). The final weights are rescaled to 100%, so units cancel out.
    cov = _normalized(covariance)
    excess = excess / excess.max()
    n = len(tickers)
    start = np.where(excess > 0, 1.0, 0.0)
    start = start / (start @ excess)  # a starting point that meets the constraint

    constraints = [{"type": "eq", "fun": lambda y: y @ excess - 1.0}]
    result = minimize(
        lambda y: y @ cov @ y,
        x0=start,
        jac=lambda y: 2.0 * cov @ y,
        bounds=[(0.0, None)] * n,
        constraints=constraints,
        method="SLSQP",
        options=SOLVER_OPTIONS,
    )
    if not (result.success or _is_feasible(result, constraints)) or result.x.sum() <= 0:
        raise OptimizationError(f"Could not find the tangency portfolio: {result.message}")
    return pd.Series(_clean(result.x), index=tickers)
