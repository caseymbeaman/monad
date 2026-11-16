"""Tests for engine/business.py."""

from engine.business import business_linked, named_companies
from engine.theme_loader import load_all

THEME = {"references": {"High": [{"ticker": "PR"}], "Moderate": [{"ticker": "SHEL"}]},
         "direct_classification": [{"ticker": "OXY"}], "allowed_industries": ["Oil & Gas Integrated"]}


def test_industry_or_named_company():
    assert business_linked("XOM", "Oil & Gas Integrated", THEME)       # allowed industry
    assert business_linked("PR", "Something Else", THEME)              # reference
    assert business_linked("OXY", None, THEME)                         # Tier 2 name
    assert not business_linked("KO", "Beverages - Non-Alcoholic", THEME)
    assert not business_linked("KO", None, {**THEME, "allowed_industries": []})
    assert named_companies(THEME) == {"PR", "SHEL", "OXY"}


def test_every_theme_has_an_allowed_list():
    for t in load_all().values():
        assert t["allowed_industries"], t["key"]
