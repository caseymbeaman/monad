"""Tests for the dashboard's data helpers (engine/dashboard.py)."""

import pytest

from engine import dashboard, shocks
from engine.regression import HIGH, LIMITED, LIMITED_LOW, MODERATE, NOT_DETERMINED

THEMES = {"ai": {"name": "AI", "plain": "AI companies"}, "oil": {"name": "Oil", "plain": "oil producers"}}


def test_prefs_from_choices():
    assert dashboard.prefs_from_choices({"ai": "Want", "oil": "Avoid", "gold": "Don't care"}) == {
        "ai": "want", "oil": "avoid"}
    assert dashboard.prefs_from_choices({"ai": "Don't care"}) == {}
    with pytest.raises(ValueError, match="Unknown choice"):
        dashboard.prefs_from_choices({"ai": "Maybe"})


def test_holdings_from_build_drops_zero_weights():
    build = {"holdings": [{"ticker": "A", "weight_pct": 60}, {"ticker": "B", "weight_pct": 0},
                          {"ticker": "CASH", "weight_pct": 40}]}
    assert dashboard.holdings_from_build(build) == {"A": 60.0, "CASH": 40.0}
    assert dashboard.holdings_from_build({}) == {}


TABLE = {"NVDA": {"ai": {"tier": HIGH}, "oil": {"tier": LIMITED_LOW}},
         "XOM": {"ai": {"tier": NOT_DETERMINED}, "oil": {"tier": MODERATE}}}


def test_tier_matrix_skips_cash_and_marks_gaps():
    m = dashboard.tier_matrix(TABLE, ["NVDA", "XOM", "NEW", "CASH"], THEMES)
    assert list(m.columns) == ["AI", "Oil"] and list(m.index) == ["NVDA", "XOM", "NEW"]
    assert m.loc["NVDA", "AI"] == HIGH and m.loc["NEW", "Oil"] == dashboard.NOT_SCREENED


def test_heatmap_codes_labels_and_hover():
    m = dashboard.tier_matrix(TABLE, ["NVDA", "XOM"], THEMES)
    fig = dashboard.heatmap_figure(m, {"NVDA": 60.0, "XOM": 40.0})
    hm = fig.data[0]
    assert hm.z.tolist() == [[0, 3], [4, 1]]
    assert hm.text.tolist() == [["High", "Ltd*"], ["?", "Mod"]]
    assert list(hm.y) == ["NVDA (60.0%)", "XOM (40.0%)"]
    assert "can't tell" in hm.customdata[1][0]
    assert dashboard.heatmap_figure(m).data[0].y == ("NVDA", "XOM")


REGRESSION = {
    "tier": MODERATE, "sentence": "XOM moves with Oil.", "method": "regression", "n_obs": 499, "r_squared": 0.61,
    "controls": ["SPY", "TLT"], "sector_control": "SEC_XLE", "p_threshold": 0.00625, "evidence": "FMP FY2025",
    "etf_check": {"etf": "USO", "beta": 0.21, "p": 0.0001, "pass": True}, "error": None,
    "groups": {"High": {"names": ["FANG", "COP"], "beta_sum": 0.42, "se": 0.1, "p_one_sided": 0.00001,
                        "upper_95": 0.5845, "eligible": True},
               "Moderate": {"names": ["CVX"], "beta_sum": 0.02, "se": 0.05, "p_one_sided": 0.34,
                            "upper_95": 0.10225, "eligible": False}},
}


def test_audit_rows_explain_the_decision():
    rows = dict(dashboard.audit_rows(REGRESSION))
    assert rows["Tier"] == MODERATE and rows["Trading days used"] == "499"
    assert rows["Share of daily moves explained (R²)"] == "0.61"
    assert rows["Sector control"] == "SEC_XLE" and rows["Evidence"] == "FMP FY2025"
    assert rows["Significance threshold (one-sided p)"] == "0.0063"
    assert rows["Theme ETF check"] == "beta +0.210 on USO, p = 0.0001: pass"


def test_audit_rows_minimal_and_failed_screen():
    rows = dict(dashboard.audit_rows({"tier": NOT_DETERMINED, "method": "not screened", "error": "no data"}))
    assert rows["Problem"] == "no data" and "Trading days used" not in rows
    assert dict(dashboard.audit_rows({}))["Tier"] == dashboard.NOT_SCREENED


def test_group_table():
    df = dashboard.group_table(REGRESSION)
    assert df["Group"].tolist() == ["High", "Moderate"] and df["Eligible"].tolist() == ["yes", "no"]
    assert df.loc[0, "Reference companies"] == "FANG, COP" and df.loc[1, "Upper bound (95%)"] == 0.102
    assert dashboard.group_table({"tier": HIGH}) is None


def test_reshock_scales_linearly_and_rewrites_the_sentence():
    sens = {"A": {"beta": 0.5, "se": 0.1, "note": ""}, "CASH": {"beta": 0.0, "se": 0.0, "note": ""}}
    theme = {"name": "Oil", "plain": "oil producers"}
    base = shocks.apply_shock({"A": 0.6, "CASH": 0.4}, sens, "oil", theme, 0.30).to_dict()
    down = dashboard.reshock(base, theme, -0.20)
    assert down.portfolio_move == pytest.approx(-0.20 / 0.30 * base["portfolio_move"])
    assert "fell 20%" in down.sentence and down.shock == -0.20


@pytest.mark.parametrize("tiers, allowed, fragment", [
    ({"ai": HIGH, "oil": LIMITED}, True, None),
    ({"ai": MODERATE, "oil": LIMITED_LOW}, True, None),
    ({"ai": HIGH, "oil": MODERATE}, False, "Mandate: Oil exposure too high (XOM is Moderate for Oil)."),
    ({"ai": HIGH, "oil": NOT_DETERMINED}, False, "Mandate: Oil exposure can't be ruled out"),
    ({"ai": LIMITED, "oil": LIMITED}, False, "Mandate: not enough AI exposure (XOM is Limited for AI)."),
    ({}, False, "not enough AI exposure (XOM is Not screened"),
])
def test_mandate_check(tiers, allowed, fragment):
    ok, reasons = dashboard.mandate_check("XOM", {"ai": "want", "oil": "avoid"}, tiers, THEMES)
    assert ok is allowed
    if fragment:
        assert any(fragment in r for r in reasons)
    else:
        assert reasons == []


def test_chain_facts_before_and_after_launch():
    assert dashboard.chain_facts()["launched"] is False
    fund = {"network": "Monad testnet", "name": "AI ex-Oil Fund", "symbol": "AIXO", "address": "0xF",
            "rules": [{"kind": 0, "label": "AI"}, {"kind": 1, "label": "Oil"}]}
    facts = dashboard.chain_facts(fund, {"shares": 1000.0, "nav_usd": 1000.0, "nav_per_share_usd": 1.0})
    assert facts["launched"] and facts["mandate"] == ["Want AI", "Avoid Oil"]
    assert facts["last_deposit"] == {"shares": 1000.0, "fund_value_usd": 1000.0, "value_per_share_usd": 1.0}
    assert "last_deposit" not in dashboard.chain_facts(fund)


def test_parse_holdings_text():
    assert dashboard.parse_holdings_text("nvda:30, XOM:20\ncash:50") == {"NVDA": 30.0, "XOM": 20.0, "CASH": 50.0}
    with pytest.raises(ValueError, match="TICKER:WEIGHT"):
        dashboard.parse_holdings_text("NVDA")
    with pytest.raises(ValueError, match="No holdings"):
        dashboard.parse_holdings_text("  ")


REPORT = {
    "holdings": [{"ticker": "NVDA", "weight_pct": 60.0, "results": {"ai": {"tier": HIGH}, "oil": {
                  "tier": NOT_DETERMINED, "error": "no data"}}},
                 {"ticker": "CASH", "weight_pct": 40.0, "results": "cash: kept at its weight, not scored"}],
    "fingerprint": {"ai": {"name": "AI", "high_moderate_pct": 60.0, "by_tier_pct": {NOT_DETERMINED: 0.0},
                           "sentence": "60% AI."},
                    "oil": {"name": "Oil", "high_moderate_pct": 0.0, "by_tier_pct": {NOT_DETERMINED: 60.0},
                            "sentence": "No oil."}},
}


def test_way_1_report_helpers():
    assert dashboard.results_from_screen(REPORT) == {"NVDA": REPORT["holdings"][0]["results"]}
    assert dashboard.holdings_from_screen(REPORT) == {"NVDA": 60.0, "CASH": 40.0}
    rows = dashboard.fingerprint_rows(REPORT)
    assert [r["Theme"] for r in rows] == ["AI", "Oil"]  # most exposed first
    assert rows[1]["The data can't tell"] == "60%" and rows[0]["In plain English"] == "60% AI."
    assert dashboard.screen_errors(REPORT) == ["NVDA: no data"]


def test_funnel_rows():
    build = {"funnel": [{"step": "Universe", "left": 650}, {"step": "Want AI", "left": 40}]}
    assert dashboard.funnel_rows(build) == [{"Step": "Universe", "Stocks left": 650},
                                            {"Step": "Want AI", "Stocks left": 40}]
    assert dashboard.funnel_rows({}) == []
