"""Tests for engine/evidence.py (FMP faked) and engine/theme_loader.py (temp theme files)."""

import pytest
import yaml

from engine import evidence, fmp, theme_loader

SEGMENTS = [
    {"fiscalYear": 2024, "data": {"Oil": 50, "Gas": 50}},
    {"fiscalYear": 2025, "data": {"Oil": 60, "Gas": 30, "Chemicals": 10, "Eliminations": -5, "Note": "n/a"}},
]
INCOME = [{"fiscalYear": "2025", "revenue": 200, "netInterestIncome": 110, "interestIncome": 160},
          {"fiscalYear": "2024", "revenue": 0}]


@pytest.fixture(autouse=True)
def fake_fmp(monkeypatch):
    monkeypatch.setattr(fmp, "revenue_product_segments", lambda t: [] if t == "NONE" else SEGMENTS)
    monkeypatch.setattr(fmp, "income_statement", lambda t: [] if t == "NONE" else INCOME)


def test_segment_share_latest_year_ignores_negatives_and_text():
    r = evidence.segment_share("X", ["oil"])  # case-insensitive
    assert r["evidence_pct"] == 60.0 and r["fiscal_year"] == 2025  # 60 / (60+30+10)
    assert "Oil / sum of all product segments" in r["source"]


def test_segment_share_specific_year_and_multiple_segments():
    assert evidence.segment_share("X", ["Oil", "Gas"], fiscal_year=2024)["evidence_pct"] == 100.0


def test_segment_share_errors():
    with pytest.raises(ValueError, match="not found"):
        evidence.segment_share("X", ["Coal"])
    with pytest.raises(ValueError, match="no product-segment data"):
        evidence.segment_share("NONE", ["Oil"])
    with pytest.raises(ValueError, match="no product-segment data"):
        evidence.segment_share("X", ["Oil"], fiscal_year=1999)


def test_statement_ratio_and_errors():
    r = evidence.statement_ratio("BANK", "netInterestIncome")
    assert (r["evidence_pct"], r["fiscal_year"]) == (55.0, 2025)
    with pytest.raises(ValueError, match="can't compute"):
        evidence.statement_ratio("BANK", "netInterestIncome", fiscal_year=2024)  # revenue 0
    with pytest.raises(ValueError, match="no income-statement"):
        evidence.statement_ratio("NONE", "netInterestIncome")


def test_show_segments():
    assert evidence.show_segments("X") == "X FY2025: Oil 60%, Gas 30%, Chemicals 10%"
    assert evidence.show_segments("NONE") == "NONE: no segment data"


def write_theme(tmp_path, key, **overrides):
    t = {"key": key, "name": key.title(), "controls": ["SPY", "TLT"], "ground_truth": "ETF",
         "references": {"High": [{"ticker": "A"}], "Moderate": [{"ticker": "B"}]},
         "control": {"ticker": "C"}, "direct_classification": []}
    t.update(overrides)
    (tmp_path / f"{key}.yaml").write_text(yaml.safe_dump(t))


def test_theme_loader(tmp_path, monkeypatch):
    monkeypatch.setattr(theme_loader, "THEMES_DIR", tmp_path)
    write_theme(tmp_path, "good")
    assert theme_loader.load_theme("good")["name"] == "Good"
    assert list(theme_loader.load_all()) == ["good"]
    with pytest.raises(ValueError, match="Available: good"):
        theme_loader.load_theme("missing")
    write_theme(tmp_path, "gt_is_ref", ground_truth="A")
    with pytest.raises(ValueError, match="must never be a reference"):
        theme_loader.load_theme("gt_is_ref")
    (tmp_path / "broken.yaml").write_text(yaml.safe_dump({"key": "broken"}))
    with pytest.raises(ValueError, match="missing: name"):
        theme_loader.load_theme("broken")


def test_real_theme_files_are_valid():
    themes = theme_loader.load_all()
    assert len(themes) == 10
    for t in themes.values():
        refs = [r["ticker"] for g in ("High", "Moderate") for r in t["references"][g]]
        assert t["controls"][:2] == ["SPY", "TLT"]
        for style in ("VALUE", "SIZE", "MOM", "LOWVOL"):  # each style control is either used or skipped (with %)
            assert (style in t["controls"]) != (style in t["style_skips"])
        assert "use_sector_control" not in t and "sector_skips" not in t  # sector control deleted
        assert t["control"]["ticker"] not in refs
        assert 3 <= len(t["references"]["High"]) <= 5
        assert 0 <= len(t["references"]["Moderate"]) <= 4
        assert "plain" in t


def test_nii_share():
    r = evidence.nii_share("BANK")  # NII 110 / (110 + (200 - 160)) = 73.3%
    assert (r["evidence_pct"], r["fiscal_year"]) == (73.3, 2025)
    with pytest.raises(ValueError, match="missing"):
        evidence.nii_share("BANK", fiscal_year=2024)
    with pytest.raises(ValueError, match="no income-statement"):
        evidence.nii_share("NONE")
