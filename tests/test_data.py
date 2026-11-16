"""Offline tests for engine/data.py (FMP and Yahoo are faked)."""

import pandas as pd
import pytest

from engine import data, fmp

REAL_FROM_YF = data._from_yfinance


def fake_fmp(prices_by_ticker):
    def _prices(ticker, start, end):
        if ticker not in prices_by_ticker:
            raise fmp.FMPError("no data")
        # FMP returns newest first
        return [{"date": d, "adjClose": p} for d, p in sorted(prices_by_ticker[ticker].items(), reverse=True)]
    return _prices


@pytest.fixture(autouse=True)
def no_yahoo(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "YF_CACHE_DIR", tmp_path / "prices")
    monkeypatch.setattr(data, "_from_yfinance", lambda t, s, e: None)


def test_simple_returns_and_inner_join_no_fill(monkeypatch):
    monkeypatch.setattr(fmp, "dividend_adjusted_prices", fake_fmp({
        "AAA": {"2025-01-02": 100.0, "2025-01-03": 110.0, "2025-01-06": 99.0, "2025-01-07": 99.0},
        "BBB": {"2025-01-02": 50.0, "2025-01-03": 50.0, "2025-01-07": 55.0},  # missing 01-06
    }))
    r = data.get_returns(["AAA", "BBB"], "2025-01-01", "2025-01-31")
    assert list(r.index.strftime("%Y-%m-%d")) == ["2025-01-03", "2025-01-07"]
    assert r.loc["2025-01-03", "AAA"] == pytest.approx(0.10)
    # 01-06 is dropped (not filled): AAA's 01-07 return is measured from 01-03 to 01-07.
    assert r.loc["2025-01-07", "AAA"] == pytest.approx(99 / 110 - 1)
    assert r.loc["2025-01-07", "BBB"] == pytest.approx(0.10)


def test_duplicate_and_lowercase_tickers(monkeypatch):
    monkeypatch.setattr(fmp, "dividend_adjusted_prices", fake_fmp({
        "AAA": {"2025-01-02": 1.0, "2025-01-03": 2.0, "2025-01-06": 3.0}}))
    r = data.get_returns(["aaa", "AAA"], "2025-01-01", "2025-01-31")
    assert list(r.columns) == ["AAA"] and len(r) == 2


def test_missing_ticker_is_named(monkeypatch):
    monkeypatch.setattr(fmp, "dividend_adjusted_prices", fake_fmp({"AAA": {"2025-01-02": 1.0, "2025-01-03": 2.0}}))
    with pytest.raises(data.DataError, match="ZZZZ"):
        data.get_returns(["AAA", "ZZZZ"], "2025-01-01", "2025-01-31")


def test_empty_list_and_bad_prices(monkeypatch):
    with pytest.raises(data.DataError, match="No tickers"):
        data.get_returns([])
    monkeypatch.setattr(fmp, "dividend_adjusted_prices", fake_fmp({"AAA": {"2025-01-02": 0.0, "2025-01-03": 2.0}}))
    with pytest.raises(data.DataError, match="zero or negative"):
        data.get_returns(["AAA"], "2025-01-01", "2025-01-31")


def test_too_little_history(monkeypatch):
    monkeypatch.setattr(fmp, "dividend_adjusted_prices", fake_fmp({"AAA": {"2025-01-02": 1.0, "2025-01-03": 2.0}}))
    with pytest.raises(data.DataError, match="shared trading days"):
        data.get_returns(["AAA"], "2025-01-01", "2025-01-31")


def test_falls_back_to_yahoo_when_fmp_has_nothing(monkeypatch):
    monkeypatch.setattr(fmp, "dividend_adjusted_prices", fake_fmp({}))
    yahoo = pd.Series([10.0, 11.0, 12.1], index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]), name="AAA")
    monkeypatch.setattr(data, "_from_yfinance", lambda t, s, e: yahoo)
    _, sources = data.get_prices(["AAA"], "2025-01-01", "2025-01-31")
    assert sources["AAA"].startswith("yfinance")
    assert data.get_returns(["AAA"], "2025-01-01", "2025-01-31")["AAA"].tolist() == pytest.approx([0.1, 0.1])


def test_yahoo_download_is_cached(monkeypatch, tmp_path):
    """The real _from_yfinance: downloads once, then reads the cached CSV."""
    import sys
    import types

    monkeypatch.setattr(data, "_from_yfinance", REAL_FROM_YF)
    calls = []

    def download(ticker, start, end, auto_adjust, progress):
        calls.append((ticker, start, end, auto_adjust))
        idx = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
        return pd.DataFrame({("Close", ticker): [10.0, 11.0, 12.1]}, index=idx)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=download))
    s1 = data._from_yfinance("AAA", "2025-01-01", "2025-01-31")
    s2 = data._from_yfinance("AAA", "2025-01-01", "2025-01-31")
    assert calls == [("AAA", "2025-01-01", "2025-02-01", True)]  # end made inclusive; adjusted prices
    assert s1.tolist() == s2.tolist() == [10.0, 11.0, 12.1]


def test_yahoo_failure_or_empty_means_no_data(monkeypatch):
    import sys
    import types

    monkeypatch.setattr(data, "_from_yfinance", REAL_FROM_YF)

    def boom(*a, **k):
        raise RuntimeError("yahoo down")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=boom))
    assert data._from_yfinance("AAA", "2025-01-01", "2025-01-31") is None
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=lambda *a, **k: pd.DataFrame()))
    assert data._from_yfinance("BBB", "2025-01-01", "2025-01-31") is None


def test_fmp_rows_without_prices_count_as_no_data(monkeypatch):
    monkeypatch.setattr(fmp, "dividend_adjusted_prices", lambda t, s, e: [{"date": "2025-01-02"}])
    assert data._from_fmp("AAA", "2025-01-01", "2025-01-31") is None


def test_value_factor_is_iwd_minus_iwf(monkeypatch):
    monkeypatch.setattr(fmp, "dividend_adjusted_prices", fake_fmp({
        "IWD": {"2025-01-02": 100.0, "2025-01-03": 102.0, "2025-01-06": 102.0},
        "IWF": {"2025-01-02": 100.0, "2025-01-03": 101.0, "2025-01-06": 103.02},
        "AAA": {"2025-01-02": 10.0, "2025-01-03": 11.0, "2025-01-06": 11.0},
    }))
    r = data.get_returns(["AAA", "value"], "2025-01-01", "2025-01-31")
    assert list(r.columns) == ["AAA", "VALUE"]  # IWD/IWF only used to build VALUE
    assert r["VALUE"].tolist() == pytest.approx([0.02 - 0.01, 0.0 - 0.02])
