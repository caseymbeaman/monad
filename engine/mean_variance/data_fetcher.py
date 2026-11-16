"""Pulls data from Financial Modeling Prep (FMP) through the project's FMP client (engine/fmp.py).

Two things come from FMP:
1. Daily closing prices adjusted for dividends and splits, so returns include
   dividends paid, not just price changes.
2. The current 10-year Treasury yield, used as the risk-free rate.

Going through engine/fmp.py means the key is read from the project's .env file and never
appears in a URL, log or error, and every answer is cached in data/cache/fmp/. The Treasury
request is keyed by today's date, so the yield refreshes once a day and is reused within the day.
"""

import datetime as dt
import math

import pandas as pd

from engine import fmp

from .errors import DataFetchError

# How far back to look for the latest Treasury reading (covers long weekends).
TREASURY_LOOKBACK_DAYS = 14


def _get(endpoint, params):
    """One cached FMP call; FMP problems become this tool's DataFetchError."""
    try:
        return fmp.get(endpoint, params)
    except fmp.FMPPlanError as exc:
        raise DataFetchError(f"Your FMP plan doesn't include this data: {exc}") from exc
    except fmp.FMPError as exc:
        raise DataFetchError(f"Could not get data from FMP: {exc}") from exc


def fetch_adjusted_prices(tickers, start, end):
    """Daily dividend-adjusted closing prices, one column per ticker.

    Dates where a stock did not trade yet (e.g. before its IPO) are left blank,
    so the next step can see how much history each stock really has.
    """
    columns = {}
    for ticker in tickers:
        rows = _get(
            "historical-price-eod/dividend-adjusted",
            {"symbol": ticker, "from": start.isoformat(), "to": end.isoformat()},
        )
        if not isinstance(rows, list) or not rows:
            raise DataFetchError(
                f"No price data found for '{ticker}'. Check the ticker symbol."
            )
        try:
            series = pd.Series(
                {pd.Timestamp(row["date"]): float(row["adjClose"]) for row in rows}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DataFetchError(
                f"Price data for '{ticker}' was missing dates or prices."
            ) from exc
        if (series <= 0).any():
            raise DataFetchError(f"Price data for '{ticker}' contains zero or negative prices.")
        columns[ticker] = series.sort_index()

    return pd.DataFrame(columns).sort_index()


def fetch_ten_year_yield(today=None):
    """Latest 10-year Treasury yield as a decimal (5.15% is returned as 0.0515)."""
    today = today or dt.date.today()
    rows = _get(
        "treasury-rates",
        {
            "from": (today - dt.timedelta(days=TREASURY_LOOKBACK_DAYS)).isoformat(),
            "to": today.isoformat(),
        },
    )
    if not isinstance(rows, list):
        raise DataFetchError("FMP sent back Treasury data in an unexpected format.")

    readings = []
    for row in rows:
        value = row.get("year10") if isinstance(row, dict) else None
        if isinstance(value, (int, float)) and math.isfinite(value) and "date" in row:
            readings.append((row["date"], float(value)))
    if not readings:
        raise DataFetchError("No recent 10-year Treasury yield found on FMP.")

    _, latest_percent = max(readings)  # most recent date wins
    return latest_percent / 100.0
