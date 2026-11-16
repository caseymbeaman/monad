"""Batch scoring must match run_screen exactly (1e-8): offline on simulated prices, and on real cached data."""

import numpy as np
import pandas as pd
import pytest

from engine import data, exposure, fmp, screen

TOL = 1e-8
STATS = ["High_sum", "High_se", "High_p", "High_upper", "Moderate_sum", "Moderate_se", "Moderate_p",
         "Moderate_upper", "r_squared"]


def compare(row: dict, res: dict):
    assert row["tier"] == res["tier"], (row["ticker"], row["tier"], res["tier"])
    if res["method"] != "regression":
        return
    assert row["n_obs"] == res["n_obs"]
    assert abs(row["r_squared"] - res["r_squared"]) < TOL
    for g, st in res["groups"].items():
        for key, name in (("sum", "beta_sum"), ("se", "se"), ("p", "p_one_sided"), ("upper", "upper_95")):
            assert abs(row[f"{g}_{key}"] - st[name]) < TOL, (row["ticker"], g, key, row[f"{g}_{key}"], st[name])


# ---------------- offline: simulated prices ----------------

DATES = pd.bdate_range("2024-11-15", "2026-11-13")
THEME = {
    "key": "sim", "name": "Sim", "plain": "sim companies", "controls": ["SPY", "TLT", "VALUE"],
    "references": {"High": [{"ticker": t, "evidence_pct": 80, "measures": "x"} for t in ("H1", "H2", "H3")],
                   "Moderate": [{"ticker": t, "evidence_pct": 20, "measures": "x"} for t in ("M1", "M2")]},
    "control": {"ticker": "CTRL"}, "direct_classification": [{"ticker": "D1", "tier": "Moderate", "reason": "x."}],
    "allowed_industries": ["Widgets"],
}


def simulated_prices():
    rng = np.random.default_rng(7)
    n = len(DATES)
    r = {k: rng.normal(0, 0.01, n) for k in ("SPY", "TLT", "IWD", "IWF", "VXUS", "F")}
    for t in ("H1", "H2", "H3"):
        r[t] = r["SPY"] + r["F"] + rng.normal(0, 0.01, n)
    for t in ("M1", "M2"):
        r[t] = r["SPY"] + 0.3 * r["F"] + rng.normal(0, 0.015, n)
    r["CTRL"] = r["SPY"] + rng.normal(0, 0.01, n)
    loads = np.linspace(-0.3, 0.9, 20)
    stocks = [f"S{i:02d}" for i in range(20)]
    for t, b in zip(stocks, loads, strict=True):
        r[t] = r["SPY"] + b * (r["H1"] + r["H2"] + r["H3"]) / 3 + rng.normal(0, 0.012, n)
    prices = {t: pd.Series(100 * np.cumprod(1 + v), index=DATES, name=t) for t, v in r.items() if t != "F"}
    prices["S00"] = prices["S00"].iloc[300:]  # short history (IPO-like)
    prices["S01"] = prices["S01"].iloc[420:]  # very short history
    prices["S02"] = prices["S02"].drop(DATES[200])  # one missing day
    return prices, stocks


@pytest.fixture
def sim(monkeypatch):
    prices, stocks = simulated_prices()
    monkeypatch.setattr(data, "_from_fmp", lambda t, s, e: prices.get(t))
    monkeypatch.setattr(data, "_from_yfinance", lambda t, s, e: None)
    monkeypatch.setattr(exposure, "revenue_pct", lambda t, k: None)  # no FMP calls for simulated tickers
    meta = {t: {"country": "US", "industry": "Widgets" if t == "S05" else "Other", "market_cap": 1e10} for t in stocks}
    meta["S03"]["country"] = "GB"  # a non-US stock gets the INTL control
    monkeypatch.setattr(screen, "intl_control", lambda t: "INTL" if meta.get(t, {}).get("country", "US") != "US" else None)
    return stocks, meta


def test_batch_matches_run_screen_on_simulated_prices(sim):
    stocks, meta = sim
    tickers = stocks + ["H2", "D1", "CTRL"]
    rows = {r["ticker"]: r for r in exposure.score_theme(THEME, tickers, meta, exposure.PriceStore())}
    paths = {t: rows[t]["path"] for t in tickers}
    assert [t for t in stocks if paths[t] == "single"] == ["S00", "S01", "S02"]  # short, short, one missing day
    assert paths["S03"] == "batch"  # the non-US stock is scored in its own batch (with INTL)
    assert paths["H2"] == paths["D1"] == "listed" and paths["CTRL"] == "single"
    assert sum(p == "batch" for p in paths.values()) == 17
    for t in tickers:
        compare(rows[t], screen._screen_one(t, THEME, exposure.START, exposure.END))
    assert rows["S00"]["n_obs"] < rows["S10"]["n_obs"] and rows["S01"]["n_obs"] < rows["S00"]["n_obs"]
    assert rows["S03"]["controls_used"].endswith("INTL")
    assert rows["S05"]["business_linked"] and not rows["S06"]["business_linked"] and rows["H2"]["business_linked"]
    assert {rows[t]["tier"] for t in stocks} >= {"High", "Limited"}  # the test covers more than one tier


def test_batch_ols_matches_statsmodels_directly():
    import statsmodels.api as sm
    rng = np.random.default_rng(1)
    X = pd.DataFrame(rng.normal(size=(300, 4)), columns=["a", "b", "c", "d"])
    Y = pd.DataFrame({f"y{i}": X @ rng.normal(size=4) + rng.normal(size=300) for i in range(5)})
    out = exposure.batch_ols(Y, X, {"G": ["b", "c"]}, n_names=3)
    for c in Y:
        fit = sm.OLS(Y[c], sm.add_constant(X)).fit()
        w = np.array([0, 0, 1, 1, 0.0])
        assert abs(out.loc[c, "G_sum"] - fit.params[["b", "c"]].sum()) < TOL
        assert abs(out.loc[c, "G_se"] - np.sqrt(w @ fit.cov_params().values @ w)) < TOL
        assert abs(out.loc[c, "r_squared"] - fit.rsquared) < TOL


# ---------------- real cached data (skipped if prices aren't downloaded) ----------------

REAL = ["AAPL", "MSFT", "JNJ", "XOM", "KO", "JPM", "PG", "UNH", "HD", "CAT", "BA", "NEE", "LIN", "AMD", "ORCL",
        "TSM", "SAP", "SHOP"]


def _short_history(n=2):
    """Universe stocks whose cached history is clearly shorter than the window."""
    from engine.universe import load_universe
    out = []
    for r in load_universe():
        path = fmp.cache_path("historical-price-eod/dividend-adjusted",
                              {"symbol": r["ticker"], "from": data.DEFAULT_START, "to": data.DEFAULT_END})
        if path.exists():
            s = data._from_fmp(r["ticker"], data.DEFAULT_START, data.DEFAULT_END)
            if s is not None and 150 < len(s) < 450:
                out.append(r["ticker"])
        if len(out) == n:
            break
    return out


@pytest.mark.skipif(not (fmp.CACHE_DIR.exists() and (exposure.data.ROOT / "data" / "universe.csv").exists()),
                    reason="needs downloaded prices and data/universe.csv")
def test_batch_matches_run_screen_on_real_data():
    from engine.theme_loader import load_all
    from engine.universe import load_universe
    short = _short_history()
    assert len(short) >= 2, "need at least 2 short-history stocks in the cache"
    tickers = REAL + short
    assert len(tickers) == 20
    meta = {r["ticker"]: r for r in load_universe()}
    store = exposure.PriceStore()
    paths = []
    for theme in load_all().values():
        for row in exposure.score_theme(theme, tickers, meta, store):
            compare(row, screen._screen_one(row["ticker"], theme, exposure.START, exposure.END))
            paths.append(row["path"])
    assert "batch" in paths and "single" in paths
