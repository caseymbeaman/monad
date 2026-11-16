"""Compare three versions of the method on the same tests (writes results/method_comparison.json).

    A  = market + VALUE (the previous method; AI and Cyber without VALUE by hand, no sector control)
    A* = A with VALUE kept or skipped by the objective 15% rule (VALUE skipped for AI only)
    B = A + style controls SIZE, MOM, LOWVOL, all chosen by the objective 15% skip rule
    (Version C, B + sector controls, was tested and rejected; the sector code has since been deleted.)

Run:  python -m engine.method_comparison
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from engine import regression_check as rc
from engine.price_check import check_theme
from engine.theme_loader import load_all
from engine.universe import load_universe

ROOT = Path(__file__).resolve().parent.parent


def variant(themes: dict, v: str) -> dict:
    out = {}
    for k, th in themes.items():
        t = dict(th)
        if v == "A":
            t["controls"] = ["SPY", "TLT"] if k in ("ai", "cyber") else ["SPY", "TLT", "VALUE"]
        elif v == "A*":  # A, but VALUE kept/skipped by the objective 15% rule instead of by hand
            t["controls"] = ["SPY", "TLT"] + ([] if "VALUE" in th.get("style_skips", {}) else ["VALUE"])
        out[k] = t
    return out


def sanity_v(themes, r):
    return {t: {k: rc.cls(t, th, r).tier for k, th in themes.items()} for t in rc.SANITY}


def nd_share(themes, r, univ):
    tiers = [rc.cls(t, th, r).tier for t in univ if t in r.columns for th in themes.values()]
    return 100 * sum(x == "Not determined" for x in tiers) / len(tiers), len(tiers)


def main():
    base = load_all()
    univ = [r['ticker'] for r in load_universe()]
    r, dropped = rc.big_frame(base)
    out = {"dropped": dropped, "n_days": len(r)}
    for v in ("A", "A*", "B"):
        rc.RNG = __import__("numpy").random.default_rng(2026)  # same random draws for every version
        th = variant(base, v)
        loo = rc.leave_one_out(th, r)
        pc = pd.DataFrame([row for t in th.values() for row in check_theme(t, r)])
        gt = rc.ground_truth(th, r, univ)
        nd, n = nd_share(th, r, univ)
        out[v] = {
            "fp": rc.false_positives(th, r, univ),
            "sanity": sanity_v(th, r),
            "loo_hm_pct": 100 * loo["loo_tier"].isin(["High", "Moderate"]).mean(),
            "loo_exact_pct": 100 * (loo["loo_tier"] == loo["listed"]).mean(),
            "gt": gt, "gt_median": float(pd.Series([g["spearman"] for g in gt]).median()),
            "nd_pct": nd, "nd_n": n,
            "price_check": f"{int(pc['pass'].sum())}/{len(pc)}",
            "price_fails": [f"{a}:{b}" for a, b in pc.loc[~pc["pass"], ["theme", "ticker"]].values],
            "math": rc.math_check(th, r), "known": rc.known_answers(th, r),
        }
        o = out[v]
        print(f"{v}: FP real {o['fp']['real_pct']:.1f}% (noise {o['fp']['noise_pct']:.1f}%) | LOO {o['loo_hm_pct']:.1f}% "
              f"(exact {o['loo_exact_pct']:.1f}%) | ETF median {o['gt_median']:.2f} | ND {nd:.1f}% | price {o['price_check']}")
    (ROOT / "results" / "method_comparison.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
