"""Way 2, "Build my ETF": theme preferences -> a basket of good, recognizable stocks, re-checked with Way 1.

    build({"ai": "want", "gold": "want", "oil": "avoid"}, region="all")  -> dict (JSON-ready)

Command line:
    python -m engine.builder --want ai --avoid oil
    python -m engine.builder --want ai,gold --region us --json
    python -m engine.builder --avoid oil,gold                  # no wants: biggest stocks that pass the avoids
    python -m engine.builder --want ai --all-names             # turn off "well-known names only"

Rules:
- Universe: data/exposure_table.parquet (every stock in data/universe.csv, already scored on every theme by
  python -m engine.build_table). Individual NYSE + NASDAQ stocks only. Region: all, us or intl.
- Ratings come from the final rating (engine/rating.py: business link + revenue share + regression), not the
  regression alone.
- "avoid" X (every stock must pass every avoid rule): the stock must be rated "Not exposed" on X, so High,
  Moderate, Business only (an X business with no confirmed exposure: the safety net) and Market-driven (moves
  with X's companies without being an X business) are all excluded.
- "want": several wants are COMBINED (OR). The ETF holds stocks from EACH wanted theme: the TOP_N slots are split
  across the wanted themes (15 slots, 2 wants -> 8 + 7). A stock picked for a theme must be rated High or
  Moderate for THAT theme (which means business-linked, backed by revenue or a price link). Each stock is labeled with the theme it was picked for; no duplicates.
- "dont_care": no rule for that theme.
- Well-known names only (ON by default): non-reference picks need a market cap of at least $20B. Tier 1
  references always qualify.
- Ranking within each wanted theme: Tier 1 references first, then a combined score = 50% percentile of the
  t-statistic (strength of the price link) + 50% percentile of market cap, with High before Moderate as a
  tiebreaker. Picks alternate across wanted themes. At most MAX_PER_INDUSTRY stocks per FMP industry in the ETF,
  except that a stock picked for a theme doesn't count when its industry is one of that theme's own industries
  (gold miners in a Gold pick, defense companies in an Aerospace & defense pick).
- No wants: the largest companies by market cap that pass every avoid rule.
- Never empty: if a wanted theme has fewer qualifiers than its slots, its market-cap floor is lowered in steps
  ($20B -> $10B -> $2B) for that theme only, and the output says so; leftover slots then go to the other wanted
  themes. If nothing qualifies at all, the output shows the funnel, names the rule that removed the most stocks
  and suggests a change.
- Equal weight, capped at 15% each; if there are too few names to reach 100% under the cap, the rest is cash.
- The final basket is re-checked from scratch with Way 1 (run_screen): stocks picked for a theme must be rated
  High/Moderate for it, and nothing may be High, Moderate, Business only or Market-driven on an avoided theme.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from engine import screen
from engine.build_table import load_table
from engine.rating import NOT_EXPOSED
from engine.regression import HIGH, MODERATE
from engine.theme_loader import load_all

ROOT = Path(__file__).resolve().parent.parent
CAP_PCT = 15.0
TOP_N = 15  # how many stocks go into the basket
MIN_HOLDINGS = 6
MAX_PER_INDUSTRY = 3
WELL_KNOWN_FLOORS = [20e9, 10e9, 2e9]  # market-cap floor for non-reference picks, lowered in steps if needed
WANT_OK = {HIGH, MODERATE}
AVOID_FAIL = {HIGH, MODERATE}
CHOICES = {"want": "want", "avoid": "avoid", "dont_care": "dont_care", "don't care": "dont_care",
           "dont care": "dont_care", "dontcare": "dont_care"}
REGIONS = {"all": "All regions", "us": "US only", "intl": "International only"}


class BuildError(ValueError):
    """The preferences couldn't be understood."""


def prescreen() -> dict[str, dict[str, dict]]:
    """{ticker: {theme_key: result}} for the whole universe, in run_screen's result shape, from the exposure
    table. (chain/publish.py reads its results from here.)"""
    themes = load_all()
    out: dict[str, dict[str, dict]] = {}
    for r in load_table().to_dict("records"):
        th = themes[r["theme"]]
        groups = {}
        for g in ("High", "Moderate"):
            if r.get(f"{g}_sum") is not None and not pd.isna(r.get(f"{g}_sum")):
                groups[g] = {"names": [x["ticker"] for x in th["references"].get(g, [])],
                             "beta_sum": r[f"{g}_sum"], "se": r[f"{g}_se"], "p_one_sided": r[f"{g}_p"],
                             "upper_95": r[f"{g}_upper"], "eligible": bool(r[f"{g}_eligible"])}
        nan = lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else v
        out.setdefault(r["ticker"], {})[r["theme"]] = {
            "ticker": r["ticker"], "theme": th["name"], "tier": r["tier"], "method": r["method"],
            "sentence": r["sentence"], "groups": groups, "n_obs": nan(r.get("n_obs")),
            "r_squared": nan(r.get("r_squared")), "p_threshold": nan(r.get("p_threshold")),
            "controls": (r.get("controls_used") or "").split(",") if r["method"] == "regression" else [],
        }
    return out


def cap_and_rescale(points: dict[str, float], cap: float = CAP_PCT) -> tuple[dict[str, float], float]:
    """Weights proportional to points, none above `cap`, summing to 100. Returns (weights, cash %).

    Repeatedly pins anything over the cap at the cap and spreads the remainder over the rest in
    proportion to their points. If every holding ends up at the cap, the leftover is cash.
    """
    if not points:
        return {}, 100.0
    if any(p <= 0 for p in points.values()):
        raise ValueError("Points must be positive.")
    weights: dict[str, float] = {}
    free = dict(points)
    remaining = 100.0
    while free:
        total = sum(free.values())
        trial = {t: remaining * p / total for t, p in free.items()}
        over = {t for t, w in trial.items() if w > cap + 1e-12}
        if not over:
            weights.update(trial)
            remaining = 0.0
            break
        for t in over:
            weights[t] = cap
            remaining -= cap
            del free[t]
    return weights, max(remaining, 0.0)


def _validate(prefs: dict[str, str], themes: dict[str, dict], region: str) -> dict[str, str]:
    if region not in REGIONS:
        raise BuildError(f"Region must be one of: {', '.join(REGIONS)}")
    clean = {}
    for k, v in prefs.items():
        key, choice = k.strip().lower(), CHOICES.get(str(v).strip().lower())
        if key not in themes:
            raise BuildError(f"No theme called '{k}'. Available: {', '.join(sorted(themes))}")
        if choice is None:
            raise BuildError(f"'{k}': choose 'want', 'avoid' or 'dont_care', not '{v}'")
        clean[key] = choice
    if not any(v in ("want", "avoid") for v in clean.values()):
        raise BuildError("Choose at least one theme to want or avoid, e.g. --want ai --avoid oil")
    return clean


def split_slots(n: int, k: int) -> list[int]:
    """n slots over k themes as evenly as possible, extras to the first themes (15 over 2 -> [8, 7])."""
    base, rem = divmod(n, k)
    return [base + (1 if i < rem else 0) for i in range(k)]


def _fmt_cap(v: float) -> str:
    return f"${v / 1e9:,.0f}B" if v >= 1e9 else f"${v / 1e6:,.0f}M"


def _ranked(cands: list[str], k: str, ref, tier, tstat, mcap) -> list[str]:
    """Tier 1 references first, then 50% t-stat percentile + 50% market-cap percentile, High before Moderate."""
    if not cands:
        return []
    t = pd.Series({x: tstat.loc[x, k] for x in cands}, dtype=float).fillna(-99.0).rank(pct=True)
    m = pd.Series({x: mcap[x] for x in cands}, dtype=float).fillna(0.0).rank(pct=True)
    score = 0.5 * t + 0.5 * m
    return sorted(cands, key=lambda x: (not bool(ref.loc[x, k]), -score[x], tier.loc[x, k] != HIGH, x))


def theme_candidates(table: pd.DataFrame, k: str, n: int = TOP_N, well_known: bool = True) -> list[str]:
    """One theme's qualifying stocks in ranking order, with no avoids and no industry limit (used to pick the
    League's stock pool). Same tests and ranking as build(): High/Moderate + business-linked, well-known floor
    lowered in steps until at least n qualify."""
    tier = table.pivot(index="ticker", columns="theme", values="final_rating")
    tstat = table.pivot(index="ticker", columns="theme", values="strength_t")
    ref = table.pivot(index="ticker", columns="theme", values="reference").astype(bool)
    mcap = table.groupby("ticker")["market_cap"].first().reindex(tier.index).astype(float).fillna(0.0)
    fit = [x for x in tier.index if tier.loc[x, k] in WANT_OK]
    chosen = fit
    for floor in WELL_KNOWN_FLOORS if well_known else []:
        chosen = [x for x in fit if ref.loc[x, k] or mcap[x] >= floor]
        if len(chosen) >= n:
            break
    return _ranked(chosen, k, ref, tier, tstat, mcap)


def build(prefs: dict[str, str], region: str = "all", table: pd.DataFrame | None = None,
          well_known: bool = True) -> dict:
    themes = load_all()
    prefs = _validate(prefs, themes, region)
    t = load_table() if table is None else table
    want = [k for k, v in prefs.items() if v == "want"]
    avoid = [k for k, v in prefs.items() if v == "avoid"]
    dont_care = [k for k, v in prefs.items() if v == "dont_care"]

    tier = t.pivot(index="ticker", columns="theme", values="final_rating")  # the final rating
    reg_tier = t.pivot(index="ticker", columns="theme", values="tier")  # the regression tier, for display
    strength = t.pivot(index="ticker", columns="theme", values="strength")
    tstat = t.pivot(index="ticker", columns="theme", values="strength_t")
    ref = t.pivot(index="ticker", columns="theme", values="reference").astype(bool)
    info = t.groupby("ticker")[["name", "industry", "country", "market_cap"]].first().reindex(tier.index)
    mcap = info["market_cap"].astype(float).fillna(0.0)
    industry = info["industry"].fillna("")
    country = info["country"].fillna("")

    alive = pd.Series(True, index=tier.index)
    funnel = [{"step": "Universe (scored stocks)", "left": int(alive.sum())}]
    if region == "us":
        alive &= country.eq("US")
    elif region == "intl":
        alive &= ~country.isin(["US", ""])
    if region != "all":
        funnel.append({"step": f"Region: {REGIONS[region]}", "left": int(alive.sum())})
    for k in avoid:
        name = themes[k]["name"]
        alive &= ~tier[k].isin(AVOID_FAIL)
        funnel.append({"step": f"Avoid {name}: not rated High or Moderate", "left": int(alive.sum())})
        alive &= tier[k].ne("Business only")
        funnel.append({"step": f"Avoid {name}: not in the {name} business (Business only)", "left": int(alive.sum())})
        alive &= tier[k].eq(NOT_EXPOSED)
        funnel.append({"step": f"Avoid {name}: not market-driven", "left": int(alive.sum())})
    if dont_care:
        funnel.append({"step": "Don't care: " + ", ".join(themes[k]["name"] for k in dont_care) + " (no rule)",
                       "left": int(alive.sum())})
    base = list(alive[alive].index)
    notes: list[str] = []

    def qualifiers(cands: list[str], floor: float, k: str | None) -> list[str]:
        if not well_known:
            return cands
        return [x for x in cands if (k is not None and ref.loc[x, k]) or mcap[x] >= floor]

    # ---- candidates per wanted theme (or, with no wants, by market cap) ----
    lists: dict[str, list[str]] = {}
    slots: dict[str, int] = {}
    floors: dict[str, float | None] = {}
    if want:
        for k, n in zip(want, split_slots(TOP_N, len(want)), strict=True):
            name = themes[k]["name"]
            fit = [x for x in base if tier.loc[x, k] in WANT_OK]
            funnel.append({"step": f"Want {name}: rated High or Moderate", "left": len(fit)})
            chosen, used = [], None
            for floor in WELL_KNOWN_FLOORS if well_known else [0.0]:
                chosen, used = qualifiers(fit, floor, k), floor
                if len(chosen) >= n:
                    break
            if well_known:
                funnel.append({"step": f"Want {name}: well-known (reference or ≥ {_fmt_cap(used)})", "left": len(chosen)})
                if used < WELL_KNOWN_FLOORS[0]:
                    notes.append(f"{name}: only {len(qualifiers(fit, WELL_KNOWN_FLOORS[0], k))} stock(s) at ≥ "
                                 f"{_fmt_cap(WELL_KNOWN_FLOORS[0])}, so the floor was lowered to {_fmt_cap(used)} "
                                 f"for this theme.")
            lists[k], slots[k], floors[k] = _ranked(chosen, k, ref, tier, tstat, mcap), n, used if well_known else None
    else:
        chosen, used = base, None
        for floor in WELL_KNOWN_FLOORS if well_known else [0.0]:
            chosen, used = qualifiers(base, floor, None), floor
            if len(chosen) >= TOP_N:
                break
        if well_known:
            funnel.append({"step": f"Well-known (≥ {_fmt_cap(used)})", "left": len(chosen)})
            if used < WELL_KNOWN_FLOORS[0]:
                notes.append(f"Only {len(qualifiers(base, WELL_KNOWN_FLOORS[0], None))} stock(s) at ≥ "
                             f"{_fmt_cap(WELL_KNOWN_FLOORS[0])}; the floor was lowered to {_fmt_cap(used)}.")
        lists["_cap"] = sorted(chosen, key=lambda x: (-mcap[x], x))
        slots["_cap"], floors["_cap"] = TOP_N, used

    # ---- pick: alternate across themes, no duplicates, at most MAX_PER_INDUSTRY per industry ----
    picked_for: dict[str, str] = {}
    per_industry: dict[str, int] = {}
    pos = dict.fromkeys(lists, 0)
    capped = set()

    own = {k: set(themes[k].get("allowed_industries", [])) for k in want}

    def counts(x: str, k: str) -> bool:
        """Does this pick count toward the industry limit? Not when it's in the theme's own industry."""
        return not (k in own and industry[x] in own[k])

    def next_pick(k: str) -> str | None:
        lst = lists[k]
        while pos[k] < len(lst):
            x = lst[pos[k]]
            pos[k] += 1
            if x in picked_for:
                continue
            if counts(x, k) and per_industry.get(industry[x], 0) >= MAX_PER_INDUSTRY:
                capped.add(x)
                continue
            return x
        return None

    taken = dict.fromkeys(lists, 0)
    order = list(lists)
    progress = True
    while progress and len(picked_for) < TOP_N:
        progress = False
        for k in order:
            if taken[k] >= slots[k] or len(picked_for) >= TOP_N:
                continue
            x = next_pick(k)
            if x is None:
                continue
            picked_for[x] = k
            taken[k] += 1
            if counts(x, k):
                per_industry[industry[x]] = per_industry.get(industry[x], 0) + 1
            progress = True
    # leftover slots from themes that ran out -> the other wanted themes
    short = {k: slots[k] - taken[k] for k in order if taken[k] < slots[k]}
    if short and want:
        for k, missing in short.items():
            notes.append(f"{themes[k]['name']}: only {taken[k]} of {slots[k]} slots could be filled; "
                         f"{missing} slot(s) moved to the other wanted theme(s).")
        progress = True
        while progress and len(picked_for) < TOP_N:
            progress = False
            for k in order:
                if len(picked_for) >= TOP_N:
                    break
                x = next_pick(k)
                if x is not None:
                    picked_for[x], taken[k] = k, taken[k] + 1
                    if counts(x, k):
                        per_industry[industry[x]] = per_industry.get(industry[x], 0) + 1
                    progress = True
    if capped:
        notes.append(f"Industry limit: at most {MAX_PER_INDUSTRY} stocks per industry (a theme's own industries "
                     f"don't count), so {len(capped)} otherwise-qualifying stock(s) were skipped.")

    # in pick order: grouped by theme (the order of the wants), each theme's list in rank order
    rank_pos = {x: (order.index(picked_for[x]), lists[picked_for[x]].index(x)) for x in picked_for}
    picks = sorted(picked_for, key=lambda x: rank_pos[x])
    funnel.append({"step": "Basket", "left": len(picks)})

    weights, cash = cap_and_rescale(dict.fromkeys(picks, 1.0))  # equal weight
    warnings = list(notes)
    diagnosis = None
    if not picks:
        steps = [(funnel[i]["step"], funnel[i - 1]["left"] - funnel[i]["left"]) for i in range(1, len(funnel) - 1)]
        worst = max(steps, key=lambda s: s[1]) if steps else ("Universe", 0)
        diagnosis = {"rule": worst[0], "removed": worst[1], "suggestion": _suggest(worst[0], themes, prefs, region)}
        warnings.append(f"No stocks pass every rule. The rule that removed the most stocks: \"{worst[0]}\" "
                        f"({worst[1]} removed). Try: {diagnosis['suggestion']}")
    elif len(picks) < MIN_HOLDINGS:
        warnings.append(f"Only {len(picks)} holding(s) pass every rule (target is at least {MIN_HOLDINGS}). "
                        "The basket is small and concentrated.")
    if picks and cash > 1e-9:
        warnings.append(f"With {len(picks)} holding(s) and a {CAP_PCT:g}% cap, only {100 - cash:.0f}% can be "
                        f"invested; {cash:.0f}% is held as cash.")

    basket = {p: round(weights[p], 4) for p in picks}
    if picks and cash > 1e-9:  # no picks -> no basket at all, not 100% cash
        basket[screen.CASH] = round(cash, 4)
    nan = lambda v: None if pd.isna(v) else v

    def holding(p, wt):
        if p == screen.CASH:
            return {"ticker": p, "weight_pct": round(wt, 2)}
        k = picked_for[p]
        theme_name = themes[k]["name"] if k != "_cap" else None
        return {"ticker": p, "weight_pct": round(wt, 2), "name": info.loc[p, "name"], "industry": industry[p],
                "market_cap": float(mcap[p]), "picked_for": theme_name,
                "picked_tier": tier.loc[p, k] if k != "_cap" else None,
                "regression_tiers": {themes[w]["name"]: reg_tier.loc[p, w] for w in want + avoid},
                "want_tiers": {themes[w]["name"]: tier.loc[p, w] for w in want},
                "avoid_tiers": {themes[a]["name"]: tier.loc[p, a] for a in avoid},
                "strength": {themes[w]["name"]: nan(strength.loc[p, w]) for w in want},
                "t_stat": {themes[w]["name"]: nan(tstat.loc[p, w]) for w in want},
                "reference": {themes[w]["name"]: bool(ref.loc[p, w]) for w in want},
                # Kept for the dashboard and assistant (app.py, engine/assistant.py): all scored tiers + notes.
                "tiers": {themes[w]["name"]: tier.loc[p, w] for w in want + avoid},
                "labels": ([f"picked for {theme_name}"] if theme_name else []) +
                          [f"{themes[a]['name']}: regression " + ("lower confidence" if reg_tier.loc[p, a] == "Limited (lower confidence)"
                                                                  else "can't tell")
                           for a in avoid if reg_tier.loc[p, a] in ("Limited (lower confidence)", "Not determined")]}

    invested = 100.0 - (cash if picks else 100.0)
    theme_share = {themes[k]["name"]: round(sum(weights[p] for p in picks if picked_for[p] == k), 2) for k in want}
    return {
        "preferences": prefs, "region": region, "well_known_only": well_known, "universe_size": len(tier),
        "funnel": funnel, "survivors": len(base),
        "ranked_by": ("Tier 1 references first, then 50% t-statistic + 50% market-cap percentile (High before "
                      "Moderate); picks alternate across wanted themes" if want else "market cap (no want theme)"),
        "theme_share_pct": theme_share,  # weight picked for each wanted theme (useful for Want mandate minimums)
        "floors": {themes[k]["name"] if k != "_cap" else "all": v for k, v in floors.items()},
        "holdings": [holding(p, wt) for p, wt in basket.items()],
        "cash_pct": round(cash, 2) if picks else 0.0,
        "invested_pct": round(invested, 2) if picks else 0.0,
        "warnings": warnings,
        "diagnosis": diagnosis,
        "verification": _verify(basket, prefs, themes, {p: picked_for[p] for p in picks}) if picks else None,
    }


def _suggest(rule: str, themes: dict, prefs: dict, region: str) -> str:
    for k, v in prefs.items():
        name = themes[k]["name"]
        if v == "avoid" and rule.startswith(f"Avoid {name}"):
            return f"switch Avoid {name} to Don't care."
        if v == "want" and rule.startswith(f"Want {name}"):
            return (f"switch Want {name} to Don't care, or turn off \"Well-known names only\"."
                    if "well-known" in rule else f"switch Want {name} to Don't care, or pick another theme.")
    if rule.startswith("Region"):
        return "choose All regions."
    return "loosen one of your rules."


def _verify(basket: dict[str, float], prefs: dict[str, str], themes: dict[str, dict], picked_for: dict) -> dict:
    """Re-check the final basket from scratch with Way 1: each wanted theme's picks must show as business-linked
    High/Moderate for that theme, and nothing may be High/Moderate on an avoided theme."""
    keys = [k for k, v in prefs.items() if v != "dont_care"]
    report = screen.run_screen(basket, keys)
    checks = {}
    for k in keys:
        f = report["fingerprint"][k]
        if prefs[k] == "want":
            need = sum(w for p, w in basket.items() if picked_for.get(p) == k)
            ok = f["exposure_pct"] >= need - 0.01
            goal = f"the {need:.0f}% picked for it is rated High/Moderate"
        else:
            ok = f["exposure_pct"] + f["business_only_pct"] + f["market_driven_pct"] < 0.01
            goal = "0% High, Moderate, Business only or Market-driven"
        checks[k] = {"theme": themes[k]["name"], "choice": prefs[k], "goal": goal, "pass": ok,
                     "high_moderate_pct": f["high_moderate_pct"], "exposure_pct": f["exposure_pct"],
                     "by_tier_pct": f["by_tier_pct"], "sentence": f["sentence"]}
    return {"all_pass": all(c["pass"] for c in checks.values()), "checks": checks}


def summary_text(out: dict) -> str:
    prefs = ", ".join(f"{'dont care' if v == 'dont_care' else v} {k}" for k, v in out["preferences"].items())
    head = (f"Preferences: {prefs}   Region: {REGIONS[out['region']]}   "
            f"Well-known names only: {'on' if out['well_known_only'] else 'off'}")
    lines = [head, "", "Funnel:"]
    lines += [f"  {f['left']:5}  {f['step']}" for f in out["funnel"]]
    lines.append("")
    if not out["holdings"]:
        lines.append("No basket: nothing passes every rule.")
    else:
        n = sum(1 for h in out["holdings"] if h["ticker"] != screen.CASH)
        lines.append(f"Basket ({n} holdings; ranked by {out['ranked_by']}):")
        lines.append(f"  {'Ticker':6} {'Weight':>6}  {'Company':28} {'Industry':30} {'Mkt cap':>8}  {'Picked for':24} Rating")
        for h in out["holdings"]:
            if h["ticker"] == screen.CASH:
                lines.append(f"  {'CASH':6} {h['weight_pct']:5.2f}%")
                continue
            lines.append(f"  {h['ticker']:6} {h['weight_pct']:5.2f}%  {str(h['name'])[:28]:28} {str(h['industry'])[:30]:30} "
                         f"{_fmt_cap(h['market_cap']):>8}  {str(h['picked_for'] or '-')[:24]:24} {h['picked_tier'] or '-'}"
                         + (f" | avoid: {', '.join(f'{k} {v}' for k, v in h['avoid_tiers'].items())}" if h["avoid_tiers"] else ""))
    lines += [f"NOTE: {w}" for w in out["warnings"]]
    v = out["verification"]
    if v:
        lines += ["", "Re-check with Way 1:"]
        for c in v["checks"].values():
            lines.append(f"  {'PASS' if c['pass'] else 'FAIL'}  {c['choice']} {c['theme']}: {c['goal']}.")
        lines.append("All goals met." if v["all_pass"] else "Some goals NOT met; see above.")
    return "\n".join(lines)


def _split(values: list[str] | None) -> list[str]:
    return [x.strip() for v in values or [] for x in v.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine.builder", description="Build a theme basket (Way 2).")
    ap.add_argument("--want", action="append", help="theme key(s) to want, e.g. ai or ai,gold")
    ap.add_argument("--avoid", action="append", help="theme key(s) to avoid, e.g. oil")
    ap.add_argument("--dont-care", action="append", help="theme key(s) with no rule (optional, for the record)")
    ap.add_argument("--region", default="all", choices=list(REGIONS), help="all (default), us or intl")
    ap.add_argument("--all-names", action="store_true", help="turn off 'well-known names only' (the $20B floor)")
    ap.add_argument("--json", action="store_true", help="print the full JSON")
    args = ap.parse_args(argv)
    want, avoid, dc = _split(args.want), _split(args.avoid), _split(args.dont_care)
    try:
        clash = (set(want) & set(avoid)) | (set(dc) & (set(want) | set(avoid)))
        if clash:
            raise BuildError(f"Each theme gets one choice; listed twice: {', '.join(sorted(clash))}")
        prefs = {**dict.fromkeys(dc, "dont_care"), **dict.fromkeys(want, "want"), **dict.fromkeys(avoid, "avoid")}
        out = build(prefs, region=args.region, well_known=not args.all_names)
    except (BuildError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "build_latest.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str) if args.json else summary_text(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
