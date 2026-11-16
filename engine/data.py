"""Daily price data and returns.

get_returns(tickers, start, end) gives a table of simple daily returns, one column per ticker.

How it works, in plain terms:
- Prices are daily closes adjusted for dividends and splits, from FMP. If FMP has nothing for a
  ticker, it falls back to Yahoo Finance (yfinance), also adjusted for dividends and splits.
- Every download is cached on disk (FMP in data/cache/fmp/, Yahoo in data/cache/prices/), so the
  same request never hits the internet twice.
- Only dates where EVERY ticker has a price are kept (an "inner join"). Missing days are never
  filled in with the previous price; they're dropped.
- Simple return = today's price / yesterday's price - 1, computed after the join, so every
  ticker's return covers exactly the same days.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from engine import fmp

ROOT = Path(__file__).resolve().parent.parent
YF_CACHE_DIR = ROOT / "data" / "cache" / "prices"

# The project's fixed ~2-year window, so results are reproducible and the cache is reused.
DEFAULT_START = "2024-11-15"
DEFAULT_END = "2026-11-14"


class DataError(RuntimeError):
    """Prices couldn't be found or are unusable."""


def _from_fmp(ticker: str, start: str, end: str) -> pd.Series | None:
    try:
        rows = fmp.dividend_adjusted_prices(ticker, start, end)
    except fmp.FMPError:
        return None
    rows = [r for r in rows or [] if r.get("date") and isinstance(r.get("adjClose"), (int, float))]
    if not rows:
        return None
    s = pd.Series({pd.Timestamp(r["date"]): float(r["adjClose"]) for r in rows}, name=ticker)
    return s.sort_index()


def _from_yfinance(ticker: str, start: str, end: str) -> pd.Series | None:
    path = YF_CACHE_DIR / f"yf_{ticker}_{start}_{end}.csv"
    if path.exists():
        s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
        s.name = ticker
        return s
    try:
        import yfinance as yf

        # yfinance's end date is exclusive, so add a day. auto_adjust=True adjusts for dividends and splits.
        end_excl = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        df = yf.download(ticker, start=start, end=end_excl, auto_adjust=True, progress=False)
    except Exception:  # noqa: BLE001 - any Yahoo failure just means "no fallback data"
        return None
    if df is None or df.empty or "Close" not in df:
        return None
    close = df["Close"]
    if isinstance(close, pd.DataFrame):  # newer yfinance returns one column per ticker
        close = close.iloc[:, 0]
    s = close.dropna().astype(float)
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = ticker
    if s.empty:
        return None
    YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    s.to_csv(path)
    return s


def get_prices(tickers: list[str], start: str = DEFAULT_START, end: str = DEFAULT_END) -> tuple[pd.DataFrame, dict]:
    """Adjusted closes for each ticker on the dates they ALL share. Also returns where each came from."""
    tickers = list(dict.fromkeys(t.upper() for t in tickers))  # de-duplicate, keep order
    if not tickers:
        raise DataError("No tickers given.")
    series, sources, missing = [], {}, []
    for t in tickers:
        s = _from_fmp(t, start, end)
        src = "FMP dividend-adjusted"
        if s is None or s.empty:
            s, src = _from_yfinance(t, start, end), "yfinance auto-adjusted (FMP had no data)"
        if s is None or s.empty:
            missing.append(t)
            continue
        if (s <= 0).any():
            raise DataError(f"{t}: has zero or negative prices; can't compute returns.")
        series.append(s)
        sources[t] = src
    if missing:
        raise DataError(f"No price data from FMP or Yahoo for: {', '.join(missing)}")
    prices = pd.concat(series, axis=1, join="inner").sort_index()  # inner join: no filling gaps
    return prices, sources


# Built-in factor series that aren't single tickers. VALUE = value-minus-growth: the daily return of the
# large-cap value ETF (IWD) minus the large-cap growth ETF (IWF). It soaks up days when "value" stocks
# (banks, energy, defense, pharma) and "growth" stocks (tech) move in opposite directions, so that swing
# isn't mistaken for theme exposure.
from engine.controls import SPREADS as SYNTHETIC


def get_returns(tickers: list[str], start: str = DEFAULT_START, end: str = DEFAULT_END) -> pd.DataFrame:
    """Simple daily returns (decimal, e.g. 0.01 = +1%) on the dates all tickers share.

    Also understands the built-in series in SYNTHETIC (e.g. "VALUE").
    """
    wanted = list(dict.fromkeys(t.upper() for t in tickers))
    fetch = []
    for t in wanted:
        fetch += list(SYNTHETIC[t]) if t in SYNTHETIC else [t]
    prices, _ = get_prices(fetch, start, end)
    returns = prices.pct_change(fill_method=None).iloc[1:]
    if returns.isna().any().any():
        raise DataError("Unexpected gaps in returns after joining dates.")
    if len(returns) < 2:
        raise DataError(f"Only {len(returns)} shared trading days for {', '.join(prices.columns)}; need more history.")
    for name, (long, short) in SYNTHETIC.items():
        if name in wanted:
            returns[name] = returns[long] - returns[short]
    return returns[wanted]
