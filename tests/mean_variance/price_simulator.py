"""Made-up price data, so the mean-variance tests never need the internet."""

import numpy as np
import pandas as pd


def make_prices(tickers, years=10, drifts=None, vols=None, start_after=None, seed=0,
                end="2026-10-30"):
    """Daily business-day prices that follow a random walk.

    start_after: {ticker: date}; the stock has no prices before that date
    (simulates a recent IPO).
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end, periods=int(years * 252))
    drifts = drifts or {}
    vols = vols or {}
    data = {}
    for i, ticker in enumerate(tickers):
        mu = drifts.get(ticker, 0.08 + 0.03 * i) / 252
        sigma = vols.get(ticker, 0.15 + 0.05 * i) / np.sqrt(252)
        steps = rng.normal(mu, sigma, len(dates))
        series = pd.Series(100 * np.exp(np.cumsum(steps)), index=dates)
        if start_after and ticker in start_after:
            series[series.index < pd.Timestamp(start_after[ticker])] = np.nan
        data[ticker] = series
    return pd.DataFrame(data)


