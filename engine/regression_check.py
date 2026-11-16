"""Regression check: how well is the exposure method working? Tests and reports only; changes nothing.

Run:  python -m engine.regression_check     -> results/regression_check.md (+ printed summary)

1. Math check      3 holdings re-done by hand (statsmodels OLS + own covariance algebra) vs the engine.
2. Known answers   simulated holdings built from the High group, the Moderate group, or the market only.
3. False positives references swapped for (a) pure noise and (b) random real tickers from other sectors.
4. Leave-one-out   each Tier 1 reference classified with itself removed from the regressors.
5. Ground truth    Spearman rank correlation of the method's score vs the direct beta on the theme ETF.
6. Sanity table    familiar names across all themes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from engine import fmp
from engine.controls import SPREADS, intl_control
from engine.data import get_returns
from engine.regression import ALPHA, MIN_SUM, Z_ONE_SIDED_95, classify, reference_names
from engine.theme_loader import load_all
from engine.universe import load_universe

ROOT = Path(__file__).resolve().parent.parent
RNG = np.random.default_rng(2026)
REAL: set[str] = set()  # real tickers (synthetic test series never get the INTL control)


def cls(ticker, theme, df):
    """classify() with the INTL control for non-US holdings."""
    sc = intl_control(ticker) if ticker in REAL else None
    if sc and sc not in df.columns:
        sc = None
    return classify(ticker, theme, df, sc)
N_SIM = 100
NOISE = 0.015  # daily idiosyncratic noise for simulated holdings (1.5%, typical for a single stock)


def big_frame(themes):
    """One table of returns for the universe, controls, ETFs (drops names with short history)."""
    names = [r['ticker'] for r in load_universe()] + ["SPY", "TLT", "IWD", "IWF"] + [t["ground_truth"] for t in themes.values() if t.get("ground_truth")]
    names += [t["control"]["ticker"] for t in themes.values()]
    names += [leg for legs in SPREADS.values() for leg in legs]
    names += SANITY  # SMH is an ETF, so it isn't in the universe; the checks still use it as a test holding
    names = list(dict.fromkeys(names))
    keep = []
    for n in names:
        try:
            if len(get_returns([n])) >= 480:
                keep.append(n)
        except Exception:  # noqa: BLE001, S110 - a missing ticker just isn't used
            pass
    r = get_returns(keep + list(SPREADS))
    REAL.update(keep)
    return r, sorted(set(names) - set(keep))


# ---------------- 1. Math check ----------------

def by_hand(y, X, groups, n_names):
    fit = sm.OLS(y, sm.add_constant(X)).fit()
    V = fit.cov_params().values
    out = {}
    for g, names in groups.items():
        w = np.array([1.0 if c in names else 0.0 for c in fit.params.index])
        s = float(w @ fit.params.values)
        se = float(np.sqrt(w @ V @ w))
        p = float(1 - stats.t.cdf(s / se, fit.df_resid))
        out[g] = (s, se, p, s + Z_ONE_SIDED_95 * se, s > MIN_SUM and p < ALPHA / n_names)
    elig = {g: v for g, v in out.items() if v[4]}
    if elig:
        tier = max(elig, key=lambda g: elig[g][0])
    elif all(v[3] < MIN_SUM for v in out.values()):
        tier = "Limited"
    elif all(v[0] < MIN_SUM for v in out.values()):
        tier = "Limited (lower confidence)"
    else:
        tier = "Not determined"
    return out, tier


def math_check(themes, r):
    rows = []
    for ticker, key in (("SMH", "ai"), ("XOM", "oil"), ("JNJ", "healthcare")):
        th = themes[key]
        refs = reference_names(th)
        res = cls(ticker, th, r)
        ctrls = res.controls
        cols = ctrls + refs["High"] + refs["Moderate"] + [th["control"]["ticker"]]
        hand, tier = by_hand(r[ticker], r[cols], {g: refs[g] for g in refs if refs[g]}, len(cols) - len(ctrls))
        diff = max(max(abs(hand[g][0] - res.groups[g].beta_sum), abs(hand[g][1] - res.groups[g].se),
                       abs(hand[g][2] - res.groups[g].p_one_sided)) for g in hand)
        rows.append({"holding": ticker, "theme": th["name"], "engine_tier": res.tier, "hand_tier": tier,
                     "max_abs_diff": diff, "match": tier == res.tier and diff < 1e-9})
    return rows


# ---------------- 2. Known answers ----------------

def known_answers(themes, r):
    out = []
    for key in ("ai", "oil"):
        th = themes[key]
        refs = reference_names(th)
        cases = {"High-group holding (true High sum 0.6)": ("High", 0.6, refs["High"]),
                 "Moderate-group holding (true Moderate sum 0.4)": ("Moderate", 0.4, refs["Moderate"]),
                 "Market-only holding": (None, 0.0, [])}
        for label, (want, b, names) in cases.items():
            hits = limited = 0
            for _ in range(N_SIM):
                y = r["SPY"] + (b * r[names].mean(axis=1) if names else 0) + RNG.normal(0, NOISE, len(r))
                df = r.assign(SIMX=y)
                tier = cls("SIMX", th, df).tier
                if want:
                    hits += tier == want
                else:
                    hits += tier not in ("High", "Moderate")
                    limited += tier in ("Limited", "Limited (lower confidence)")
            row = {"theme": th["name"], "case": label, "correct_pct": hits}
            if not want:
                row["limited_pct"] = limited
            out.append(row)
    return out


# ---------------- 3. False positives ----------------

def _sector(t):
    try:
        return (fmp.profile(t) or [{}])[0].get("sector") or "?"
    except fmp.FMPError:
        return "?"


def false_positives(themes, r, univ):
    template = themes["oil"]  # uses SPY, TLT, VALUE
    stocks = [t for t in univ if t in r.columns]
    sectors = {t: _sector(t) for t in stocks}
    noise_hits = noise_n = real_hits = real_n = 0
    for _ in range(50):
        # (a) pure noise references, same volatility as a typical stock
        fake = pd.DataFrame(RNG.normal(0, r[stocks].std().median(), (len(r), 8)), index=r.index,
                            columns=[f"N{i}" for i in range(8)])
        df = pd.concat([r, fake], axis=1)
        th = {**template, "references": {"High": [{"ticker": f"N{i}"} for i in range(4)],
                                         "Moderate": [{"ticker": f"N{i}"} for i in range(4, 7)]},
              "control": {"ticker": "N7"}, "direct_classification": []}
        for h in RNG.choice(stocks, 20, replace=False):
            noise_n += 1
            noise_hits += cls(h, th, df).tier in ("High", "Moderate")
        # (b) random real tickers; holdings only from sectors none of the references are in
        pick = list(RNG.choice(stocks, 8, replace=False))
        used = {sectors[p] for p in pick}
        th = {**template, "references": {"High": [{"ticker": p} for p in pick[:4]],
                                         "Moderate": [{"ticker": p} for p in pick[4:7]]},
              "control": {"ticker": pick[7]}, "direct_classification": []}
        pool = [s for s in stocks if s not in pick and sectors[s] not in used]
        for h in RNG.choice(pool, min(20, len(pool)), replace=False) if pool else []:
            real_n += 1
            real_hits += cls(h, th, r).tier in ("High", "Moderate")
    return {"noise_pct": 100 * noise_hits / noise_n, "noise_n": noise_n,
            "real_pct": 100 * real_hits / real_n, "real_n": real_n}


# ---------------- 4. Leave-one-out ----------------

def _without(th, ticker):
    refs = {g: [x for x in th["references"].get(g, []) if x["ticker"] != ticker] for g in ("High", "Moderate")}
    return {**th, "references": refs, "direct_classification": []}


def leave_one_out(themes, r):
    rows = []
    for th in themes.values():
        for g in ("High", "Moderate"):
            for ref in th["references"].get(g, []):
                t = ref["ticker"]
                if t not in r.columns:
                    continue
                res = cls(t, _without(th, t), r)
                rows.append({"theme": th["name"], "ticker": t, "listed": g, "loo_tier": res.tier})
    return pd.DataFrame(rows)


# ---------------- 5. Ground truth ----------------

def ground_truth(themes, r, univ):
    rows = []
    for th in themes.values():
        gt = th.get("ground_truth")
        if not gt or gt not in r.columns:
            continue
        sign = th.get("ground_truth_sign", 1)
        scores, betas = [], []
        for t in univ:
            if t not in r.columns or t == gt or t in th["controls"]:
                continue
            res = cls(t, _without(th, t), r)  # references scored with themselves left out
            scores.append(max(g.beta_sum for g in res.groups.values()))
            fit = sm.OLS(r[t], sm.add_constant(pd.DataFrame({"SPY": r["SPY"], "ETF": sign * r[gt]}))).fit()
            betas.append(fit.params["ETF"])
        rho, p = stats.spearmanr(scores, betas)
        rows.append({"theme": th["name"], "etf": gt, "n": len(scores), "spearman": rho, "p": p})
    return rows


# ---------------- 6. Sanity table ----------------

SANITY = ["SMH", "NVDA", "XOM", "COP", "JNJ", "LMT", "NEM", "KO", "AAPL"]
SHORT = {"High": "High", "Moderate": "Mod", "Limited": "Lim", "Limited (lower confidence)": "Lim-low",
         "Not determined": "ND"}


def sanity(themes, r):
    """Tiers for familiar names across all themes, computed fresh (SMH isn't in the stock universe)."""
    return {t: {k: cls(t, th, r).tier for k, th in themes.items()} for t in SANITY if t in r.columns}


def main():
    themes = load_all()
    univ = [r['ticker'] for r in load_universe()]
    r, dropped = big_frame(themes)
    print(f"frame: {len(r)} days x {r.shape[1]} series; dropped (short history/missing): {dropped}")
    results = {
        "math": math_check(themes, r),
        "known": known_answers(themes, r),
        "fp": false_positives(themes, r, univ),
        "loo": leave_one_out(themes, r),
        "gt": ground_truth(themes, r, univ),
        "sanity": sanity(themes, r),
        "n_days": len(r), "dropped": dropped,
    }
    out = ROOT / "results" / "regression_check_raw.json"
    out.write_text(json.dumps({k: (v.to_dict("records") if isinstance(v, pd.DataFrame) else v) for k, v in results.items()},
                              indent=1, default=float))
    print(json.dumps({k: (v.to_dict("records") if isinstance(v, pd.DataFrame) else v) for k, v in results.items()
                      if k != "loo"}, indent=1, default=float))
    loo = results["loo"]
    print("LOO High/Moderate %:", round(100 * loo["loo_tier"].isin(["High", "Moderate"]).mean(), 1),
          "exact %:", round(100 * (loo["loo_tier"] == loo["listed"]).mean(), 1))
    print(loo.to_string(index=False))


if __name__ == "__main__":
    main()
