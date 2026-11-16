"""Price check: do the theme's reference companies actually trade like the theme?

For each theme:
"Beyond the market" means after controlling for SPY, the theme's style controls (VALUE, SIZE, MOM, LOWVOL
unless skipped by the 15% rule) and, for a non-US company, INTL (VXUS minus SPY).
- Each reference should move with its OWN group beyond the market: regress it on SPY, VALUE and the average
  return of the other members of its group. Pass = that coefficient is positive and significant
  (one-sided p < 0.05). If its group has no other members, the other group's average is used instead.
- Each reference should also move with the ground-truth ETF (if the theme has one) beyond SPY.
  For interest rates the ground truth is TLT with the sign flipped (banks should move opposite to bonds).
- The control should NOT: regressed on SPY plus the average of all references (and on the ground truth),
  it passes if the coefficient is not significantly positive.

Run:  python -m engine.price_check            (all themes)
      python -m engine.price_check ai oil     (just these)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import statsmodels.api as sm
from scipy import stats

from engine.controls import intl_control
from engine.data import get_returns
from engine.regression import GROUPS, reference_names
from engine.theme_loader import load_all, load_theme

P_PASS = 0.05


def _slope(y: pd.Series, x: pd.Series, ctrl: pd.DataFrame) -> tuple[float, float]:
    """Coefficient on x after the control columns, and its one-sided p-value for '> 0'."""
    X = sm.add_constant(pd.concat([ctrl, x.rename("x")], axis=1))
    fit = sm.OLS(y, X).fit()
    return float(fit.params["x"]), float(stats.t.sf(fit.tvalues["x"], fit.df_resid))


def _controls(theme: dict) -> list[str]:
    """SPY plus the theme's style controls (TLT is left out, as in the original price check)."""
    return ["SPY"] + [c for c in theme["controls"] if c not in ("SPY", "TLT")]


def check_theme(theme: dict, returns: pd.DataFrame | None = None) -> list[dict]:
    """Price check for one theme. `returns` can be passed in (it must hold every series needed)."""
    refs = reference_names(theme)
    gt, sign = theme.get("ground_truth"), theme.get("ground_truth_sign", 1)
    ctrl = theme["control"]["ticker"]
    base = _controls(theme)
    members = refs["High"] + refs["Moderate"] + [ctrl]
    sectors = {t: intl_control(t) for t in members}  # INTL for non-US references
    if returns is None:
        need = base + members + [s for s in sectors.values() if s] + ([gt] if gt else [])
        returns = get_returns(list(dict.fromkeys(need)))
    r = returns
    all_refs = refs["High"] + refs["Moderate"]
    rows = []

    def c(t):
        return r[base + ([sectors[t]] if sectors[t] else [])]

    for g in GROUPS:
        for t in refs[g]:
            peers = [p for p in refs[g] if p != t]
            basis = f"rest of {g}"
            if not peers:
                other = "Moderate" if g == "High" else "High"
                peers, basis = refs[other], f"{other} group (only one {g} name)"
            b, p = _slope(r[t], r[peers].mean(axis=1), c(t))
            row = {"theme": theme["key"], "ticker": t, "role": g, "group_basis": basis,
                   "group_beta": round(b, 3), "group_p": round(p, 4), "group_pass": b > 0 and p < P_PASS}
            if gt:
                bg, pg = _slope(r[t], sign * r[gt], c(t))
                row.update(gt_beta=round(bg, 3), gt_p=round(pg, 4), gt_pass=bg > 0 and pg < P_PASS)
            rows.append(row)

    b, p = _slope(r[ctrl], r[all_refs].mean(axis=1), c(ctrl))
    row = {"theme": theme["key"], "ticker": ctrl, "role": "Control", "group_basis": "all references",
           "group_beta": round(b, 3), "group_p": round(p, 4), "group_pass": not (b > 0 and p < P_PASS)}
    if gt:
        bg, pg = _slope(r[ctrl], sign * r[gt], c(ctrl))
        row.update(gt_beta=round(bg, 3), gt_p=round(pg, 4), gt_pass=not (bg > 0 and pg < P_PASS))
    rows.append(row)
    for row in rows:
        row["n_obs"] = len(r)
        row["pass"] = row["group_pass"] and row.get("gt_pass", True)
    return rows


def main(keys: list[str]) -> pd.DataFrame:
    themes = {k: load_theme(k) for k in keys} if keys else load_all()
    out = pd.DataFrame([row for t in themes.values() for row in check_theme(t)])
    with pd.option_context("display.width", 200, "display.max_rows", 500):
        print(out.to_string(index=False))
    if not keys:  # full run: keep a record
        results = Path(__file__).resolve().parent.parent / "results"
        results.mkdir(exist_ok=True)
        out.to_csv(results / "price_check.csv", index=False)
    fails = out[~out["pass"]]
    print(f"\n{len(out) - len(fails)}/{len(out)} pass.")
    for _, f in fails.iterrows():
        why = []
        if not f["group_pass"]:
            why.append(f"group beta {f['group_beta']} (p={f['group_p']})")
        if "gt_pass" in f and f["gt_pass"] is False:
            why.append(f"ground-truth beta {f['gt_beta']} (p={f['gt_p']})")
        print(f"FLAG {f['theme']}: {f['ticker']} ({f['role']}): {'; '.join(why)}")
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
