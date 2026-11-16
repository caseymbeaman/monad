"""Tests for the mean-variance tool's data fetcher. engine/fmp.py is replaced with a fake,
so these never call FMP (the FMP client itself is tested in tests/test_fmp.py)."""

import datetime as dt

import pytest

from engine import fmp
from engine.mean_variance import data_fetcher
from engine.mean_variance.errors import DataFetchError

PRICES = "historical-price-eod/dividend-adjusted"
START, END = dt.date(2016, 9, 30), dt.date(2026, 10, 31)


@pytest.fixture
def fake_fmp(monkeypatch):
    """Replace engine.fmp.get. Set .replies[endpoint] to a payload, a list of payloads, or an exception."""

    class Fake:
        def __init__(self):
            self.replies = {}
            self.calls = []

        def __call__(self, endpoint, params=None, use_cache=True):
            self.calls.append((endpoint, params))
            reply = self.replies[endpoint]
            if isinstance(reply, list) and reply and isinstance(reply[0], list):
                reply = reply.pop(0)  # one payload per call, in order
            if isinstance(reply, Exception):
                raise reply
            return reply

    fake = Fake()
    monkeypatch.setattr(data_fetcher.fmp, "get", fake)
    return fake


def _rows(pairs):
    return [{"date": d, "adjClose": p} for d, p in pairs]


# ---- going through the project's FMP client ----

def test_uses_project_fmp_client_with_plain_params(fake_fmp):
    fake_fmp.replies[PRICES] = _rows([("2020-01-02", 10.0)])
    data_fetcher.fetch_adjusted_prices(["OLD"], START, END)
    assert fake_fmp.calls == [(PRICES, {"symbol": "OLD", "from": "2016-09-30", "to": "2026-10-31"})]


@pytest.mark.parametrize("error, message", [
    (fmp.FMPPlanError("not on plan"), "plan doesn't include this data: not on plan"),
    (fmp.FMPError("gave up after 3 tries"), "Could not get data from FMP: gave up after 3 tries"),
])
def test_fmp_errors_become_clear_tool_errors(fake_fmp, error, message):
    fake_fmp.replies[PRICES] = error
    with pytest.raises(DataFetchError, match=message):
        data_fetcher.fetch_adjusted_prices(["X"], START, END)


# ---- prices ----

def test_prices_one_column_per_ticker_with_gap_for_young_stock(fake_fmp):
    fake_fmp.replies[PRICES] = [
        _rows([("2020-01-03", 11.0), ("2020-01-02", 10.0)]),
        _rows([("2020-01-03", 5.0)]),
    ]
    prices = data_fetcher.fetch_adjusted_prices(["OLD", "NEW"], START, END)
    assert list(prices.columns) == ["OLD", "NEW"]
    assert prices["OLD"].tolist() == [10.0, 11.0]  # sorted oldest first
    assert prices["NEW"].isna().tolist() == [True, False]


@pytest.mark.parametrize("payload", [[], {}, None])
def test_unknown_ticker(fake_fmp, payload):
    fake_fmp.replies[PRICES] = payload
    with pytest.raises(DataFetchError, match="No price data found for 'ZZZZ'"):
        data_fetcher.fetch_adjusted_prices(["ZZZZ"], START, END)


@pytest.mark.parametrize(
    "row", [{"date": "2020-01-02"}, {"date": "2020-01-02", "adjClose": "abc"}, {"adjClose": 10.0}],
)
def test_malformed_price_rows(fake_fmp, row):
    fake_fmp.replies[PRICES] = [row]
    with pytest.raises(DataFetchError, match="missing dates or prices"):
        data_fetcher.fetch_adjusted_prices(["X"], START, END)


@pytest.mark.parametrize("bad_price", [0.0, -5.0])
def test_zero_or_negative_prices_rejected(fake_fmp, bad_price):
    fake_fmp.replies[PRICES] = _rows([("2020-01-02", 10.0), ("2020-01-03", bad_price)])
    with pytest.raises(DataFetchError, match="zero or negative"):
        data_fetcher.fetch_adjusted_prices(["X"], START, END)


def test_very_large_prices_kept_exactly(fake_fmp):
    fake_fmp.replies[PRICES] = _rows([("2020-01-02", 1e12)])
    assert data_fetcher.fetch_adjusted_prices(["BIG"], START, END)["BIG"].iloc[0] == 1e12


# ---- 10-year Treasury yield ----

def test_yield_uses_most_recent_date_and_converts_to_decimal(fake_fmp):
    fake_fmp.replies["treasury-rates"] = [
        {"date": "2026-11-12", "year10": 5.10},
        {"date": "2026-11-13", "year10": 5.15},
        {"date": "2026-11-10", "year10": 4.90},
    ]
    rate = data_fetcher.fetch_ten_year_yield(today=dt.date(2026, 11, 15))
    assert rate == pytest.approx(0.0515)
    # keyed by today's date, so the cached yield refreshes once a day
    assert fake_fmp.calls == [("treasury-rates", {"from": "2026-11-01", "to": "2026-11-15"})]


def test_yield_defaults_to_today(fake_fmp):
    fake_fmp.replies["treasury-rates"] = [{"date": "2026-11-13", "year10": 5.0}]
    data_fetcher.fetch_ten_year_yield()
    assert fake_fmp.calls[0][1]["to"] == dt.date.today().isoformat()


def test_yield_skips_blank_readings(fake_fmp):
    fake_fmp.replies["treasury-rates"] = [
        {"date": "2026-11-13", "year10": None},
        {"date": "2026-11-12", "year10": 5.10},
        "junk",
        {"date": "2026-11-14", "year10": float("nan")},
    ]
    assert data_fetcher.fetch_ten_year_yield() == pytest.approx(0.051)


def test_zero_yield_is_allowed(fake_fmp):
    fake_fmp.replies["treasury-rates"] = [{"date": "2026-11-13", "year10": 0}]
    assert data_fetcher.fetch_ten_year_yield() == 0.0


@pytest.mark.parametrize("payload", [[], [{"date": "2026-11-13"}]])
def test_no_yield_found(fake_fmp, payload):
    fake_fmp.replies["treasury-rates"] = payload
    with pytest.raises(DataFetchError, match="No recent 10-year"):
        data_fetcher.fetch_ten_year_yield()


def test_yield_wrong_format(fake_fmp):
    fake_fmp.replies["treasury-rates"] = {"year10": 5}
    with pytest.raises(DataFetchError, match="unexpected format"):
        data_fetcher.fetch_ten_year_yield()
