"""Tests for engine/regression.py using simulated data with known answers."""

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from engine import regression as reg

N_DAYS = 2000


def make_theme(controls=("SPY", "TLT")):
    return {
        "key": "test", "name": "Test", "controls": list(controls), "ground_truth": None,
        "references": {
            "High": [{"ticker": t, "evidence_pct": 80, "measures": "Theme share of revenue"} for t in ("H1", "H2", "H3")],
            "Moderate": [{"ticker": t, "evidence_pct": 20, "measures": "Theme share of revenue"} for t in ("M1", "M2")],
        },
        "control": {"ticker": "CTRL"},
        "direct_classification": [{"ticker": "D1", "tier": "Moderate", "reason": "no disclosed number."}],
    }


def simulate(seed=0, n=N_DAYS):
    """Market + bonds + a theme factor. High refs load heavily on the theme, Moderate refs lightly,
    and each Moderate name also has its own sub-theme factor so the two groups aren't identical."""
    rng = np.random.default_rng(seed)
    spy = rng.normal(0, 0.01, n)
    tlt = rng.normal(0, 0.008, n)
    theme = rng.normal(0, 0.015, n)
    sub = rng.normal(0, 0.012, n)
    df = pd.DataFrame({"SPY": spy, "TLT": tlt})
    for t in ("H1", "H2", "H3"):
        df[t] = spy + 1.0 * theme + rng.normal(0, 0.01, n)
    for t in ("M1", "M2"):
        df[t] = spy + 0.3 * theme + sub + rng.normal(0, 0.01, n)
    df["CTRL"] = spy + rng.normal(0, 0.01, n)  # zero-exposure control company
    return df, rng


def test_strong_high_exposure_is_high():
    df, rng = simulate()
    df["X"] = df["SPY"] + 0.8 * df[["H1", "H2", "H3"]].mean(axis=1) + rng.normal(0, 0.005, N_DAYS)
    res = reg.classify("X", make_theme(), df)
    assert res.tier == reg.HIGH and res.method == "regression"
    assert res.groups["High"].beta_sum == pytest.approx(0.8, abs=0.1)
    assert res.groups["High"].eligible


def test_moderate_only_exposure_is_moderate():
    df, rng = simulate(1)
    df["X"] = df["SPY"] + 0.5 * df[["M1", "M2"]].mean(axis=1) + rng.normal(0, 0.005, N_DAYS)
    res = reg.classify("X", make_theme(), df)
    assert res.tier == reg.MODERATE
    assert res.groups["Moderate"].beta_sum == pytest.approx(0.5, abs=0.1)


def test_market_only_with_lots_of_data_is_limited():
    df, rng = simulate(2)
    df["X"] = 1.1 * df["SPY"] + rng.normal(0, 0.002, N_DAYS)
    res = reg.classify("X", make_theme(), df)
    assert res.tier == reg.LIMITED
    assert all(g.upper_95 < 0.05 for g in res.groups.values())
    assert res.sentence == "X doesn't rise with this theme."


def test_noisy_short_history_is_not_determined():
    df, rng = simulate(3, n=60)
    df["X"] = df["SPY"] + 0.3 * df[["H1", "H2", "H3"]].mean(axis=1) + rng.normal(0, 0.08, 60)
    res = reg.classify("X", make_theme(), df)
    assert res.tier == reg.NOT_DETERMINED
    assert "not the same as zero" in res.sentence


def test_negative_exposure_is_never_high_or_moderate():
    df, rng = simulate(4)
    df["X"] = df["SPY"] - 0.8 * df[["H1", "H2", "H3"]].mean(axis=1) + rng.normal(0, 0.005, N_DAYS)
    res = reg.classify("X", make_theme(), df)
    assert res.tier == reg.LIMITED  # no Inverse tier: confidently not rising with the theme


def test_group_se_matches_full_covariance_by_hand():
    df, rng = simulate(5)
    df["X"] = df["SPY"] + 0.4 * df["H1"] + rng.normal(0, 0.01, N_DAYS)
    res = reg.classify("X", make_theme(), df)
    cols = ["SPY", "TLT", "H1", "H2", "H3", "M1", "M2", "CTRL"]
    fit = sm.OLS(df["X"], sm.add_constant(df[cols])).fit()
    w = np.array([0, 0, 0, 1, 1, 1, 0, 0, 0], dtype=float)  # const, SPY, TLT, H1..H3, M1, M2, CTRL
    se = np.sqrt(w @ fit.cov_params().values @ w)
    assert res.groups["High"].se == pytest.approx(se, rel=1e-9)
    assert res.groups["High"].beta_sum == pytest.approx(fit.params[["H1", "H2", "H3"]].sum(), rel=1e-9)
    assert res.p_threshold == pytest.approx(0.05 / 6)  # 5 references + the control company
    assert "CTRL" in fit.params.index
    assert res.n_obs == N_DAYS


def test_rates_style_theme_drops_tlt():
    df, rng = simulate(6)
    df["X"] = df["SPY"] + rng.normal(0, 0.01, N_DAYS)
    res = reg.classify("X", make_theme(controls=("SPY",)), df.drop(columns=["TLT"]))
    assert res.controls == ["SPY"]


def test_reference_and_direct_use_listed_tier_without_regression():
    df, _ = simulate(7)
    r = reg.classify("H2", make_theme(), df)
    assert (r.tier, r.method, r.groups) == ("High", "listed reference", {})
    assert "80% theme share of revenue" in r.sentence
    d = reg.classify("d1", make_theme(), df)  # lower-case input is accepted
    assert (d.tier, d.method) == ("Moderate", "direct classification")


def test_missing_columns_and_short_data_raise_clear_errors():
    df, _ = simulate(8, n=30)  # 8 regressors need 38+ days
    with pytest.raises(ValueError, match="Missing returns for: X"):
        reg.classify("X", make_theme(), df)
    df["X"] = df["SPY"]
    with pytest.raises(ValueError, match="need more"):
        reg.classify("X", make_theme(), df)


def test_holding_that_is_a_control_raises():
    df, _ = simulate(9)
    with pytest.raises(ValueError, match="market controls"):
        reg.classify("SPY", make_theme(), df)


def gs(beta_sum, se, eligible):
    return reg.GroupStats(names=[], beta_sum=beta_sum, se=se, p_one_sided=0.0,
                          upper_95=beta_sum + 1.645 * se, eligible=eligible)


@pytest.mark.parametrize("groups, expected", [
    ({"High": gs(0.6, 0.1, True), "Moderate": gs(0.9, 0.1, True)}, "Moderate"),   # largest eligible wins
    ({"High": gs(0.6, 0.1, True), "Moderate": gs(0.2, 0.1, True)}, "High"),
    ({"High": gs(0.9, 0.5, False), "Moderate": gs(0.3, 0.1, True)}, "Moderate"),  # big but not eligible
    ({"High": gs(0.0, 0.01, False), "Moderate": gs(-0.1, 0.02, False)}, "Limited"),
    ({"High": gs(0.0, 0.1, False), "Moderate": gs(0.01, 0.01, False)}, "Limited (lower confidence)"),
    ({"High": gs(0.049, 0.0, False), "Moderate": gs(0.0, 0.0, False)}, "Limited"),  # just under the bar
    ({"High": gs(0.05, 0.0, False), "Moderate": gs(0.0, 0.0, False)}, "Not determined"),  # exactly 0.05 isn't < 0.05
    ({"High": gs(0.3, 0.2, False), "Moderate": gs(0.0, 0.01, False)}, "Not determined"),
])
def test_decision_rule(groups, expected):
    assert reg.decide_tier(groups) == expected


def test_eligibility_uses_bonferroni_threshold():
    df, rng = simulate(10)
    df["X"] = df["SPY"] + 0.3 * df[["H1", "H2", "H3"]].mean(axis=1) + rng.normal(0, 0.01, N_DAYS)
    fit = sm.OLS(df["X"], sm.add_constant(df[["SPY", "TLT", "H1", "H2", "H3", "M1", "M2", "CTRL"]])).fit()
    g = reg.group_stats(fit, ["H1", "H2", "H3"], n_refs=6)
    assert g.eligible == (g.beta_sum > 0.05 and g.p_one_sided < 0.05 / 6)


def test_control_company_is_a_regressor_but_never_in_a_group():
    df, rng = simulate(11)
    df["X"] = df["SPY"] + 0.8 * df["CTRL"] + rng.normal(0, 0.005, N_DAYS)  # moves only with the control
    res = reg.classify("X", make_theme(), df)
    assert all("CTRL" not in g.names for g in res.groups.values())
    assert res.tier == reg.LIMITED  # the control's co-movement is absorbed, not counted as theme exposure


def test_holding_that_is_the_control_company_is_left_off_the_right_hand_side():
    df, _ = simulate(12)
    res = reg.classify("CTRL", make_theme(), df)
    assert res.method == "regression" and res.p_threshold == pytest.approx(0.05 / 5)


def test_plain_phrase_is_used_in_sentences():
    df, rng = simulate(13)
    df["X"] = df["SPY"] + 0.8 * df[["H1", "H2", "H3"]].mean(axis=1) + rng.normal(0, 0.005, N_DAYS)
    theme = make_theme() | {"plain": "banks that earn mostly from lending"}
    assert reg.classify("X", theme, df).sentence == (
        "X moves strongly with banks that earn mostly from lending, beyond what the overall market explains.")


def test_extra_control_is_a_control_not_a_reference():
    df, rng = simulate(14)
    df["SEC"] = rng.normal(0, 0.01, N_DAYS)
    df["X"] = df["SPY"] + 0.9 * df["SEC"] + rng.normal(0, 0.004, N_DAYS)
    res = reg.classify("X", make_theme(), df, extra_control="SEC")
    assert res.controls == ["SPY", "TLT", "SEC"]
    assert res.p_threshold == pytest.approx(0.05 / 6)  # still 5 references + the control company
    assert res.tier == reg.LIMITED  # co-movement with the extra control is absorbed, not theme exposure
