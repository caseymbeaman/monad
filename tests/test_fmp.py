"""Offline tests for engine/fmp.py. No real API calls: FMP's answers are faked."""

import json

import pytest
import requests

from engine import fmp

FAKE_KEY = "TESTKEY_should_never_appear_anywhere"


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Each test gets its own empty cache folder and a fake key; no sleeping on retries."""
    monkeypatch.setattr(fmp, "CACHE_DIR", tmp_path / "fmp")
    monkeypatch.setattr(fmp, "_api_key", lambda: FAKE_KEY)
    monkeypatch.setattr(fmp.time, "sleep", lambda s: None)


def fake_get(responses, calls):
    """Return a stand-in for requests.get that hands back the given responses in order."""
    def _get(url, params=None, timeout=None):
        calls.append((url, dict(params)))
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    return _get


def test_success_is_cached_and_key_not_saved(monkeypatch):
    calls = []
    monkeypatch.setattr(fmp.requests, "get", fake_get([FakeResponse(payload=[{"symbol": "NVDA"}])], calls))
    assert fmp.get("profile", {"symbol": "NVDA"}) == [{"symbol": "NVDA"}]
    # Second call comes from the cache: no new request.
    assert fmp.get("profile", {"symbol": "NVDA"}) == [{"symbol": "NVDA"}]
    assert len(calls) == 1
    assert calls[0][0] == "https://financialmodelingprep.com/stable/profile"
    saved = fmp.cache_path("profile", {"symbol": "NVDA"}).read_text()
    assert FAKE_KEY not in saved and "retrieved_at" in saved


def test_use_cache_false_refetches(monkeypatch):
    calls = []
    monkeypatch.setattr(fmp.requests, "get", fake_get([FakeResponse(payload=[1]), FakeResponse(payload=[2])], calls))
    assert fmp.get("profile", {"symbol": "X"}) == [1]
    assert fmp.get("profile", {"symbol": "X"}, use_cache=False) == [2]


def test_cache_path_ignores_param_order_and_none_and_apikey():
    a = fmp.cache_path("income-statement", {"symbol": "XOM", "limit": 5, "period": None})
    b = fmp.cache_path("income-statement", {"limit": 5, "symbol": "XOM", "apikey": "zzz"})
    assert a == b
    assert fmp.cache_path("profile", {"symbol": "XOM"}) != fmp.cache_path("profile", {"symbol": "NVDA"})


def test_cache_path_handles_slashes_in_endpoint():
    p = fmp.cache_path("historical-price-eod/dividend-adjusted", {"symbol": "NVDA"})
    assert "/" not in p.name and p.name.startswith("historical-price-eod-dividend-adjusted")


@pytest.mark.parametrize("resp", [
    FakeResponse(status=402, payload={"Error Message": "Premium endpoint"}),
    FakeResponse(status=403, payload={"Error Message": "Exclusive Endpoint: upgrade your subscription"}),
    FakeResponse(status=200, payload={"Error Message": "This endpoint is not available under your current subscription"}),
    FakeResponse(status=200, payload=None, text="Premium Query Parameter: upgrade your plan"),
])
def test_plan_restrictions_are_reported_as_plan_errors(monkeypatch, resp):
    monkeypatch.setattr(fmp.requests, "get", fake_get([resp], []))
    with pytest.raises(fmp.FMPPlanError):
        fmp.get("revenue-product-segmentation", {"symbol": "NVDA"})
    assert not list((fmp.CACHE_DIR).glob("*.json")) if fmp.CACHE_DIR.exists() else True  # errors aren't cached


def test_bad_key_message(monkeypatch):
    monkeypatch.setattr(fmp.requests, "get", fake_get([FakeResponse(status=401, payload={"Error Message": "Invalid API KEY"})], []))
    with pytest.raises(fmp.FMPError, match="rejected the key") as err:
        fmp.get("profile", {"symbol": "NVDA"})
    assert not isinstance(err.value, fmp.FMPPlanError)


def test_retries_on_rate_limit_then_succeeds(monkeypatch):
    calls = []
    seq = [FakeResponse(status=429, payload={}), FakeResponse(status=500, payload={}), FakeResponse(payload=[42])]
    monkeypatch.setattr(fmp.requests, "get", fake_get(seq, calls))
    assert fmp.get("profile", {"symbol": "NVDA"}) == [42]
    assert len(calls) == 3


def test_gives_up_after_retries_without_leaking_key(monkeypatch):
    boom = requests.ConnectionError(f"failed https://x/stable/profile?apikey={FAKE_KEY}")
    monkeypatch.setattr(fmp.requests, "get", fake_get([boom, boom, boom], []))
    with pytest.raises(fmp.FMPError) as err:
        fmp.get("profile", {"symbol": "NVDA"})
    assert FAKE_KEY not in str(err.value) and "gave up" in str(err.value)


def test_non_json_garbage(monkeypatch):
    monkeypatch.setattr(fmp.requests, "get", fake_get([FakeResponse(status=200, payload=None, text="<html>oops</html>")], []))
    with pytest.raises(fmp.FMPError, match="isn't JSON"):
        fmp.get("profile", {"symbol": "NVDA"})


def test_other_http_error(monkeypatch):
    monkeypatch.setattr(fmp.requests, "get", fake_get([FakeResponse(status=404, payload={"x": 1})], []))
    with pytest.raises(fmp.FMPError, match="HTTP 404"):
        fmp.get("nope", {})


def test_missing_key_message(monkeypatch, tmp_path):
    monkeypatch.undo()  # restore the real _api_key
    monkeypatch.setattr(fmp, "ROOT", tmp_path)  # a folder with no .env
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    with pytest.raises(fmp.FMPError, match="No FMP key"):
        fmp._api_key()
