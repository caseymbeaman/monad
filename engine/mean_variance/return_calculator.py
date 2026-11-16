"""Turns daily prices into the two inputs mean-variance analysis needs.

1. Expected return of each stock: its average monthly return, scaled to a year.
2. Covariance matrix: how much each stock moves, and how the stocks move
   together, also scaled to a year.

Two ways to handle stocks with different amounts of history:

- "shared": every stock is measured over the same period, the stretch where all
  of them have data. Simple and consistent, but one young stock shortens the
  window for everyone.
- "max_available": each stock's average return and volatility use all of its
  own history (up to the 10-year window). How the stocks move together
  (correlation) still comes from the shared period. Building the covariance as
  volatility x correlation x volatility guarantees the result is a valid risk
  model; mixing windows any other way can produce impossible numbers such as
  negative risk.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .errors import InsufficientDataError, PortfolioInputError

MONTHS_PER_YEAR = 12
# Fewer shared months than this and the correlation estimates are too noisy.
MIN_SHARED_MONTHS = 24
WINDOW_MODES = ("shared", "max_available")


@dataclass
class EstimatedInputs:
    """Annual expected returns and covariance, plus the window each stock used."""

    expected_returns: pd.Series
    covariance: pd.DataFrame
    windows: pd.DataFrame  # one row per ticker: start, end, months


def to_monthly_returns(prices):
    """Month-end to month-end percentage returns.

    A month is blank for a stock that had not started trading yet.
    """
    if prices.empty:
        raise InsufficientDataError("No price data to work with.")
    month_end_prices = prices.resample("ME").last()
    returns = month_end_prices.pct_change(fill_method=None)
    return returns.iloc[1:]  # the first month has no prior month to compare to


def _window_table(returns_by_ticker):
    rows = {}
    for ticker, series in returns_by_ticker.items():
        rows[ticker] = {
            "start": series.index.min().date(),
            "end": series.index.max().date(),
            "months": len(series),
        }
    return pd.DataFrame(rows).T[["start", "end", "months"]]


def _shortest_history(monthly_returns):
    """Name the stock that limits the shared window, e.g. 'CRWV has only 19 months of prices.'"""
    counts = monthly_returns.notna().sum()
    ticker = counts.idxmin()
    return f"{ticker} has only {int(counts[ticker])} months of prices."


def estimate_inputs(monthly_returns, window_mode="shared"):
    """Annual expected returns and covariance matrix from monthly returns."""
    if window_mode not in WINDOW_MODES:
        raise PortfolioInputError(
            f"window_mode must be one of {WINDOW_MODES}, got '{window_mode}'."
        )

    shared = monthly_returns.dropna(how="any")
    if len(shared) < MIN_SHARED_MONTHS:
        raise InsufficientDataError(
            f"The stocks only share {len(shared)} months of history; at least "
            f"{MIN_SHARED_MONTHS} are needed for a reliable estimate. "
            f"{_shortest_history(monthly_returns)}"
        )

    if window_mode == "shared":
        per_ticker = {ticker: shared[ticker] for ticker in shared.columns}
        expected = shared.mean() * MONTHS_PER_YEAR
        covariance = shared.cov() * MONTHS_PER_YEAR
    else:
        per_ticker = {
            ticker: monthly_returns[ticker].dropna() for ticker in monthly_returns.columns
        }
        expected = pd.Series(
            {t: s.mean() * MONTHS_PER_YEAR for t, s in per_ticker.items()}
        )
        volatility = pd.Series(
            {t: s.std() * np.sqrt(MONTHS_PER_YEAR) for t, s in per_ticker.items()}
        )
        correlation = shared.corr()
        covariance = correlation.mul(volatility, axis=0).mul(volatility, axis=1)

    # A stock with a constant price has zero risk (and an undefined
    # correlation), which breaks the math downstream.
    flat = [
        t
        for t in covariance.columns
        if not covariance.loc[t, t] > 0 or covariance[t].isna().any()
    ]
    if flat:
        raise InsufficientDataError(
            f"{', '.join(flat)} showed no price movement, so its risk cannot be measured."
        )

    return EstimatedInputs(
        expected_returns=expected,
        covariance=covariance,
        windows=_window_table(per_ticker),
    )
