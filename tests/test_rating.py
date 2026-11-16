"""Tests for engine/rating.py and engine/revenue.py (FMP faked)."""

import pytest

from engine import evidence, fmp, rating, revenue
from engine.rating import (
    BUSINESS_ONLY,
    HIGH,
    MARKET_DRIVEN,
    MODERATE,
    NOT_EXPOSED,
    final_rating,
)

L, LL, ND = "Limited", "Limited (lower confidence)", "Not determined"


@pytest.mark.parametrize("linked, rev, reg, listed, expected", [
    (True, 45.0, L, False, HIGH),          # revenue >= 40
    (True, None, HIGH, False, HIGH),       # regression High
    (True, 20.0, ND, False, MODERATE),     # revenue 5-40
    (True, None, MODERATE, False, MODERATE),
    (True, 3.0, HIGH, False, HIGH),        # regression High wins over small revenue
    (True, 3.0, LL, False, BUSINESS_ONLY), # revenue under 5, regression not H/M
    (True, None, ND, False, BUSINESS_ONLY),
    (False, 80.0, HIGH, False, MARKET_DRIVEN),  # revenue is ignored without a business link
    (False, None, MODERATE, False, MARKET_DRIVEN),
    (False, None, L, False, NOT_EXPOSED),
    (True, None, MODERATE, True, MODERATE),  # listed (reference / Tier 2) keeps its tier
    (True, 90.0, MODERATE, True, MODERATE),
])
def test_final_rating(linked, rev, reg, listed, expected):
    assert final_rating(linked, rev, reg, listed) == expected


def test_rating_sentences():
    assert rating.rating_sentence("XOM", MARKET_DRIVEN, "Oil", "oil producers") == \
        "Caution: XOM's price moves with oil producers, but it isn't a Oil business."
    assert "About 60% of its revenue is Oil." in rating.rating_sentence("COP", HIGH, "Oil", None, 60.0)


def test_whole_word_matching():
    assert revenue.matching_segments(["AI Infrastructure", "Retail", "Detail Services", "Data Center"], "ai") == \
        ["AI Infrastructure", "Data Center"]
    assert revenue.matching_segments(["Oil Products", "Boiler Services", "Upstream"], "oil") == ["Oil Products", "Upstream"]
    assert revenue.matching_segments(["Anything"], "consumer_disc") == []


def test_revenue_pct_from_segments(monkeypatch):
    revenue._latest_segments.cache_clear()
    monkeypatch.setattr(fmp, "revenue_product_segments", lambda t: [
        {"fiscalYear": 2024, "data": {"Data Center": 10, "Gaming": 90}},
        {"fiscalYear": 2025, "data": {"Data Center": 80, "Gaming": 15, "Automotive": 5}}])
    r = revenue.revenue_pct("X", "ai")
    assert (r["pct"], r["fiscal_year"], r["segments"]) == (80.0, 2025, ["Data Center"])
    assert revenue.revenue_pct("X", "gold") is None  # no matching segment
    assert revenue.revenue_pct("X", "consumer_disc") is None


def test_revenue_pct_banks_use_nii(monkeypatch):
    monkeypatch.setattr(evidence, "nii_share", lambda t: {"evidence_pct": 72.0, "fiscal_year": 2025, "source": "nii"})
    assert revenue.revenue_pct("BANK", "bank_lending")["pct"] == 72.0
    def boom(t):
        raise ValueError("no data")
    monkeypatch.setattr(evidence, "nii_share", boom)
    assert revenue.revenue_pct("BANK", "bank_lending") is None


def test_no_segment_data(monkeypatch):
    revenue._latest_segments.cache_clear()
    monkeypatch.setattr(fmp, "revenue_product_segments", lambda t: [])
    assert revenue.revenue_pct("Y", "ai") is None
