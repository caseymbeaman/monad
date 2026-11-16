"""Tests for engine/builder.py (Way 2). The exposure table and the Way 1 re-check are faked."""

import json

import pandas as pd
import pytest

from engine import builder, screen
from engine.rating import final_rating

H, M, L, LL, ND = "High", "Moderate", "Limited", "Limited (lower confidence)", "Not determined"
B = 1e9

THEMES = {k: {"key": k, "name": n, "references": {"High": [], "Moderate": []}, "direct_classification": [],
              "allowed_industries": inds}
          for k, n, inds in (("ai", "AI", []), ("oil", "Oil", ["Oil"]), ("gold", "Gold", ["Gold", "Silver"]))}

# ticker: (country, market cap $bn, industry, {theme: (tier, business_linked, t-stat, reference)})
_ = (L, False, 0.0, False)
ROWS = {
    # AI: references A1 (small), A2; big caps A3-A6; a small non-reference A7; a price-link-only A8; an oil-flagged A9
    "A1": ("US", 5, "Semis", {"ai": (H, True, 2.0, True), "oil": _, "gold": _}),
    "A2": ("US", 900, "Software", {"ai": (M, True, 1.0, True), "oil": _, "gold": _}),
    "A3": ("US", 800, "Semis", {"ai": (H, True, 6.0, False), "oil": (ND, False, 0.0, False), "gold": _}),
    "A4": ("TW", 600, "Semis", {"ai": (M, True, 5.0, False), "oil": _, "gold": _}),
    "A5": ("US", 300, "Semis", {"ai": (H, True, 4.0, False), "oil": _, "gold": _}),   # 4th semi: industry cap
    "A6": ("US", 50, "Hardware", {"ai": (M, True, 3.0, False), "oil": _, "gold": _}),
    "A7": ("US", 8, "Hardware", {"ai": (H, True, 9.0, False), "oil": _, "gold": _}),   # under $20B, not a reference
    "A8": ("US", 700, "Retail", {"ai": (H, False, 7.0, False), "oil": _, "gold": _}),  # no AI business
    "A9": ("US", 400, "Software", {"ai": (H, True, 8.0, False), "oil": (M, False, 1.0, False), "gold": _}),
    # Gold: one reference and two small miners
    "G1": ("CA", 100, "Gold", {"ai": _, "oil": _, "gold": (H, True, 5.0, True)}),
    "G2": ("US", 15, "Gold", {"ai": _, "oil": _, "gold": (H, True, 4.0, False)}),
    "G3": ("US", 12, "Silver", {"ai": _, "oil": _, "gold": (M, True, 3.0, False)}),
    # Oil: an oil company (business-linked, regression Not determined) and a flagged reference
    "O1": ("US", 500, "Oil", {"ai": _, "oil": (ND, True, 0.0, False), "gold": _}),
    "O2": ("US", 450, "Oil", {"ai": _, "oil": (H, True, 5.0, True), "gold": _}),
    # Plain big companies for avoid-only baskets
    "K1": ("US", 3000, "Phones", {"ai": _, "oil": _, "gold": _}),
    "K2": ("US", 2000, "Retail", {"ai": _, "oil": _, "gold": _}),
}


def table():
    rows = []
    for t, (c, cap, ind, d) in ROWS.items():
        for k, (tier, bl, ts, ref) in d.items():
            rows.append({"ticker": t, "theme": k, "tier": tier, "business_linked": bl, "country": c,
                         "final_rating": final_rating(bl, None, tier, ref),
                         "name": f"{t} Inc", "industry": ind, "market_cap": cap * B, "strength": ts / 10,
                         "strength_t": ts, "reference": ref, "method": "regression", "sentence": "x", "n_obs": 498,
                         "r_squared": 0.5, "p_threshold": 0.01, "controls_used": "SPY,TLT",
                         "High_sum": 0.4 if tier != ND else None, "High_se": 0.1, "High_p": 0.001, "High_upper": 0.56,
                         "High_eligible": True})
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(builder, "load_all", lambda: THEMES)
    monkeypatch.setattr(builder, "load_table", table)
    monkeypatch.setattr(screen, "load_theme", lambda k: THEMES[k])
    monkeypatch.setattr(screen, "industry_of", lambda t: None)
    monkeypatch.setattr(screen, "_screen_one", lambda t, th, s, e: {
        "ticker": t, "theme": th["name"], "tier": ROWS[t][3][th["key"]][0], "method": "fake", "sentence": "x"})
    monkeypatch.setattr(screen, "business_linked", lambda t, ind, th: ROWS[t][3][th["key"]][1])
    monkeypatch.setattr(screen, "revenue_for", lambda t, k: None)
    monkeypatch.setattr(screen, "_is_listed", lambda t, th: ROWS[t][3][th["key"]][3])


def tickers(out):
    return [h["ticker"] for h in out["holdings"] if h["ticker"] != "CASH"]


def by(out):
    return {h["ticker"]: h for h in out["holdings"]}


def test_split_slots():
    assert builder.split_slots(15, 2) == [8, 7]
    assert builder.split_slots(15, 3) == [5, 5, 5]
    assert builder.split_slots(5, 2) == [3, 2]


def test_want_ai_avoid_oil_quality_ranking_and_industry_cap(monkeypatch):
    monkeypatch.setattr(builder, "TOP_N", 5)  # 6 AI stocks qualify at $20B, so the floor isn't lowered
    out = builder.build({"ai": "want", "oil": "avoid"})
    t = tickers(out)
    assert set(t[:2]) == {"A1", "A2"}  # references first (A1 even though small); by combined score among them
    assert "A7" not in t  # under $20B and not a reference: not well-known
    assert "A8" not in t  # no AI business
    assert "A9" not in t  # flagged Moderate on oil
    assert "A5" not in t  # A1, A3, A4 already fill the 3 "Semis" slots
    assert set(t) == {"A1", "A2", "A3", "A4", "A6"}
    assert all(h["picked_for"] == "AI" for h in out["holdings"] if h["ticker"] != "CASH")
    assert by(out)["A3"]["avoid_tiers"] == {"Oil": "Not exposed"}
    assert by(out)["A3"]["regression_tiers"]["Oil"] == ND
    assert any("Industry limit" in w for w in out["warnings"])
    assert out["verification"]["all_pass"]


def test_combined_score_is_half_t_stat_half_market_cap(monkeypatch):
    monkeypatch.setattr(builder, "TOP_N", 5)
    out = builder.build({"ai": "want", "oil": "avoid"})
    # non-reference AI qualifiers: A3 (t 6, $800B), A4 (t 5, $600B), A5 (t 4), A6 (t 3, $50B) -> A3 then A4 first
    assert tickers(out)[2:4] == ["A3", "A4"]


def test_well_known_off_lets_small_caps_in():
    out = builder.build({"ai": "want", "oil": "avoid"}, well_known=False)
    assert "A7" in tickers(out) and out["well_known_only"] is False


def test_multiple_wants_are_combined_with_split_slots(monkeypatch):
    monkeypatch.setattr(builder, "TOP_N", 4)
    out = builder.build({"ai": "want", "gold": "want"})
    picked = {h["ticker"]: h["picked_for"] for h in out["holdings"] if h["ticker"] != "CASH"}
    assert sum(v == "AI" for v in picked.values()) == 2 and sum(v == "Gold" for v in picked.values()) == 2
    assert picked["A1"] == "AI" and picked["G1"] == "Gold"  # references first in each theme
    assert out["theme_share_pct"] == {"AI": pytest.approx(30), "Gold": pytest.approx(30)}
    assert out["verification"]["all_pass"]


def test_floor_is_lowered_for_one_theme_only_and_said(monkeypatch):
    monkeypatch.setattr(builder, "TOP_N", 6)
    out = builder.build({"ai": "want", "gold": "want"})  # 3 + 3: Gold has only G1 at >= $20B
    gold = {h["ticker"] for h in out["holdings"] if h.get("picked_for") == "Gold"}
    assert gold == {"G1", "G2", "G3"}
    assert out["floors"]["Gold"] == 10e9 and out["floors"]["AI"] == 20e9
    assert any(w.startswith("Gold: only 1 stock(s) at ≥ $20B") for w in out["warnings"])


def test_leftover_slots_move_to_the_other_wanted_theme(monkeypatch):
    monkeypatch.setattr(builder, "TOP_N", 10)
    out = builder.build({"gold": "want", "ai": "want"})  # 5 + 5, but Gold has only 3 stocks
    gold = [h for h in out["holdings"] if h.get("picked_for") == "Gold"]
    ai = [h for h in out["holdings"] if h.get("picked_for") == "AI"]
    assert len(gold) == 3 and len(ai) > 5
    assert any("Gold: only 3 of 5 slots" in w for w in out["warnings"])


def test_avoids_exclude_flagged_and_business_linked_and_no_wants_ranks_by_market_cap():
    out = builder.build({"oil": "avoid"})
    t = tickers(out)
    assert "O1" not in t  # an oil company, even though its regression is Not determined
    assert "O2" not in t and "A9" not in t  # flagged on oil
    assert t[:2] == ["K1", "K2"]  # biggest companies first
    assert out["ranked_by"] == "market cap (no want theme)"


def test_never_empty_names_the_blocking_rule_and_suggests_a_change():
    out = builder.build({"oil": "want"}, region="intl")
    assert out["holdings"] == [] and out["verification"] is None
    assert out["diagnosis"]["rule"] == "Region: International only"
    assert out["diagnosis"]["suggestion"] == "choose All regions."
    assert "Try: choose All regions." in out["warnings"][-1]


def test_diagnosis_for_an_avoid_rule(monkeypatch):
    rows = {"X1": ("US", 50, "Oil", {"ai": _, "oil": (ND, True, 0.0, False), "gold": (H, True, 3.0, False)})}
    monkeypatch.setattr(builder, "load_table", lambda: pd.DataFrame(
        [{"ticker": "X1", "theme": k, "tier": v[0], "business_linked": v[1], "country": "US", "name": "X1",
          "final_rating": final_rating(v[1], None, v[0], v[3]),
          "industry": "Oil", "market_cap": 50e9, "strength": 0.1, "strength_t": v[2], "reference": v[3]}
         for k, v in rows["X1"][3].items()]))
    out = builder.build({"gold": "want", "oil": "avoid"})
    assert out["holdings"] == []
    assert out["diagnosis"]["suggestion"] == "switch Avoid Oil to Don't care."


def test_region_filter():
    us = builder.build({"ai": "want", "oil": "avoid"}, region="us")
    assert "A4" not in tickers(us) and us["funnel"][1] == {"step": "Region: US only", "left": 14}


def test_dont_care_adds_no_rule_but_is_listed():
    a = builder.build({"ai": "want", "oil": "avoid"})
    b = builder.build({"ai": "want", "oil": "avoid", "gold": "dont care"})
    assert tickers(a) == tickers(b)
    assert any(f["step"] == "Don't care: Gold (no rule)" for f in b["funnel"])


def test_holdings_keep_fields_for_the_dashboard():
    h = builder.build({"ai": "want", "oil": "avoid"})["holdings"][0]
    for k in ("ticker", "weight_pct", "name", "industry", "market_cap", "picked_for", "picked_tier", "tiers", "labels",
              "want_tiers", "avoid_tiers", "t_stat", "reference"):
        assert k in h
    assert h["labels"][0] == "picked for AI"


def test_theme_candidates_has_no_industry_limit():
    t = builder.theme_candidates(table(), "ai", n=5)
    assert set(t[:2]) == {"A1", "A2"} and "A5" in t and "A8" not in t


def test_prescreen_keeps_run_screen_shape_for_chain_publish():
    r = builder.prescreen()["A1"]["ai"]
    assert r["tier"] == H and r["controls"] == ["SPY", "TLT"] and r["n_obs"] == 498
    assert r["groups"]["High"]["eligible"] is True


def test_cap_and_rescale_math():
    weights, cash = builder.cap_and_rescale({"a": 10, "b": 1, "c": 1, "d": 1, "e": 1, "f": 1, "g": 1, "h": 1})
    assert weights["a"] == pytest.approx(15) and cash == 0
    assert builder.cap_and_rescale({}) == ({}, 100.0)
    with pytest.raises(ValueError):
        builder.cap_and_rescale({"a": 0})


@pytest.mark.parametrize("prefs, region, msg", [
    ({}, "all", "at least one"), ({"gold": "dont_care"}, "all", "at least one"),
    ({"nope": "want"}, "all", "No theme called"), ({"ai": "love"}, "all", "'want', 'avoid' or 'dont_care'"),
    ({"ai": "want"}, "mars", "Region must be"),
])
def test_bad_preferences(prefs, region, msg):
    with pytest.raises(builder.BuildError, match=msg):
        builder.build(prefs, region=region)


def test_cli(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    assert builder.main(["--want", "ai", "--avoid", "oil"]) == 0
    out = capsys.readouterr().out
    assert "Funnel:" in out and "Picked for" in out and "All goals met." in out
    saved = json.loads((tmp_path / "results" / "build_latest.json").read_text())
    assert saved["preferences"] == {"ai": "want", "oil": "avoid"} and "points" not in saved["holdings"][0]
    assert builder.main(["--want", "ai", "--all-names", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["well_known_only"] is False
    assert builder.main(["--want", "ai", "--avoid", "ai"]) == 2
    assert builder.main([]) == 2


def test_floor_is_lowered_when_a_theme_has_too_few_well_known_names():
    out = builder.build({"ai": "want", "oil": "avoid"})  # 15 slots, only 6 AI stocks at >= $20B
    assert "A7" in tickers(out)
    assert any(w.startswith("AI: only 6 stock(s) at ≥ $20B") for w in out["warnings"])


def test_avoid_excludes_business_only_and_market_driven():
    out = builder.build({"oil": "avoid"})
    t = tickers(out)
    assert "O1" not in t  # an oil business whose regression can't tell: Business only -> excluded (safety net)
    assert "A9" not in t  # moves with oil, not an oil business: Market-driven -> excluded
    assert "A3" in t  # not exposed to oil at all


def test_own_theme_industry_does_not_count_toward_the_limit(monkeypatch):
    extra = {f"G{i}": ("US", 30 + i, "Gold", {"ai": _, "oil": _, "gold": (H, True, 2.0 + i / 10, False)}) for i in range(4, 9)}
    for t, row in extra.items():
        monkeypatch.setitem(ROWS, t, row)
    monkeypatch.setattr(builder, "TOP_N", 6)
    out = builder.build({"gold": "want"})
    gold_industry = [h for h in out["holdings"] if h.get("industry") == "Gold"]
    assert len(gold_industry) > 3  # gold miners in a Gold pick aren't limited to 3
