"""Portfolio screen: every holding's tier for every theme, plus the portfolio's theme fingerprint.

    run_screen({"NVDA": 30, "XOM": 20, "CASH": 50}, ["ai", "oil"])  -> dict (JSON-ready)

Command line:
    python -m engine.screen NVDA:30 XOM:20 CASH:50              (all themes, plain summary)
    python -m engine.screen NVDA:30 XOM:20 CASH:50 --themes ai,oil
    python -m engine.screen NVDA:30 XOM:20 CASH:50 --json       (print the full JSON)
The full JSON is also saved to results/screen_latest.json.

Rules (from CLAUDE.md):
- Cash keeps its weight but isn't scored.
- Fingerprint for each theme = % of the whole portfolio (cash included) held in High or Moderate stocks.
- Weights are percentages of the portfolio. If they don't add up to 100 they're rescaled to 100, and the
  output says so.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from engine.business import business_linked
from engine.controls import industry_of, intl_control
from engine.data import DEFAULT_END, DEFAULT_START, DataError, get_returns
from engine.rating import (
    BUSINESS_ONLY,
    MARKET_DRIVEN,
    NOT_EXPOSED,
    RATINGS,
    final_rating,
    rating_sentence,
)
from engine.rating import HIGH as R_HIGH
from engine.rating import MODERATE as R_MODERATE
from engine.regression import (
    HIGH,
    LIMITED,
    LIMITED_LOW,
    MODERATE,
    NOT_DETERMINED,
    classify,
    regressors_needed,
)
from engine.revenue import revenue_pct as revenue_for
from engine.theme_loader import load_all, load_theme

ROOT = Path(__file__).resolve().parent.parent
CASH = "CASH"
TIERS = [HIGH, MODERATE, LIMITED, LIMITED_LOW, NOT_DETERMINED]


class InputError(ValueError):
    """The holdings or theme list couldn't be understood."""


def parse_holdings(items: list[str]) -> dict[str, float]:
    """Turn ["NVDA:30", "cash:50"] into {"NVDA": 30.0, "CASH": 50.0}, with clear errors."""
    if not items:
        raise InputError("No holdings given. Example: NVDA:30 XOM:20 CASH:50")
    holdings: dict[str, float] = {}
    for item in items:
        ticker, sep, weight = item.partition(":")
        ticker = ticker.strip().upper()
        if not sep or not ticker:
            raise InputError(f"'{item}' should look like TICKER:WEIGHT, e.g. NVDA:30")
        try:
            w = float(weight)
        except ValueError:
            raise InputError(f"'{item}': weight '{weight}' isn't a number") from None
        if not (w > 0 and math.isfinite(w)):  # also rejects nan and infinity
            raise InputError(f"'{item}': weight must be a positive number")
        if ticker in holdings:
            raise InputError(f"{ticker} is listed twice; combine it into one weight")
        holdings[ticker] = w
    return holdings


def _normalize(holdings: dict[str, float]) -> tuple[dict[str, float], bool]:
    if not holdings:
        raise InputError("No holdings given.")
    bad = [t for t, w in holdings.items() if not isinstance(w, (int, float)) or not w > 0]
    if bad:
        raise InputError(f"Weights must be positive numbers: {', '.join(bad)}")
    total = sum(holdings.values())
    rescaled = abs(total - 100) > 1e-6
    return {t.upper(): 100 * w / total for t, w in holdings.items()}, rescaled


def _screen_one(ticker: str, theme: dict, start: str, end: str) -> dict:
    """Classify one holding for one theme; any data problem becomes 'Not determined' with the reason."""
    try:
        sc = None if _is_listed(ticker, theme) else intl_control(ticker)
        needed = [] if _is_listed(ticker, theme) else regressors_needed(theme, sc)
        returns = get_returns([ticker] + needed, start, end) if needed else None
        out = classify(ticker, theme, returns, sc).to_dict()
        out["extra_control"] = sc
        return out
    except (DataError, ValueError) as exc:
        return {"ticker": ticker, "theme": theme["name"], "tier": NOT_DETERMINED, "method": "not screened",
                "sentence": f"{ticker} couldn't be screened for {theme['name']}: {exc}", "error": str(exc)}


def _is_listed(ticker: str, theme: dict) -> bool:
    listed = {r["ticker"] for g in ("High", "Moderate") for r in theme["references"].get(g, [])}
    listed |= {d["ticker"] for d in theme.get("direct_classification", [])}
    return ticker in listed


def add_rating(result: dict, ticker: str, industry: str | None, theme: dict) -> dict:
    """Add the business link, revenue share and final rating to one regression result (in place)."""
    linked = business_linked(ticker, industry, theme)
    rev = revenue_for(ticker, theme["key"]) if linked else None
    listed = _is_listed(ticker, theme)
    rating = final_rating(linked, rev["pct"] if rev else None, result["tier"], listed)
    result.update({"business_linked": linked, "revenue_pct": rev["pct"] if rev else None,
                   "revenue_source": rev["source"] if rev else None, "regression_tier": result["tier"],
                   "final_rating": rating,
                   "rating_sentence": rating_sentence(ticker, rating, theme["name"], theme.get("plain"),
                                                      rev["pct"] if rev else None)})
    return result


def _rating_of(r: dict) -> str:
    """The final rating; results made before it existed fall back to the regression tier and business link."""
    if r.get("final_rating"):
        return r["final_rating"]
    if r["tier"] in (HIGH, MODERATE):
        return r["tier"] if r.get("business_linked", True) else MARKET_DRIVEN
    return NOT_EXPOSED


def fingerprint(holdings: dict[str, float], results: dict[str, dict[str, dict]], themes: dict[str, dict]) -> dict:
    """Per theme, from the final rating:

    - exposure_pct (the headline): weight in stocks rated High or Moderate (business-linked, with revenue or a
      price link backing it). Also given as high_moderate_pct and business_linked_pct, for older readers.
    - business_only_pct: in the theme's business, but neither revenue nor prices confirm much exposure.
    - market_driven_pct (a caution): prices move with the theme's companies, but not a theme business.
      Also given as price_only_pct.
    - by_tier_pct: weight per REGRESSION tier (unchanged).
    """
    out = {}
    cash = holdings.get(CASH, 0.0)
    for key, theme in themes.items():
        by_tier = dict.fromkeys(TIERS, 0.0)
        groups = {r: [] for r in RATINGS}
        for ticker, w in holdings.items():
            if ticker == CASH:
                continue
            r = results[ticker][key]
            by_tier[r["tier"]] += w
            groups[_rating_of(r)].append(ticker)
        pct = {g: sum(holdings[t] for t in names) for g, names in groups.items()}
        exposed = groups[R_HIGH] + groups[R_MODERATE]
        e_pct = pct[R_HIGH] + pct[R_MODERATE]
        name = theme["name"]
        if exposed:
            text = f"{name} exposure: {e_pct:.0f}% of your portfolio ({', '.join(exposed)})."
        else:
            text = f"{name} exposure: none of your portfolio is rated High or Moderate."
        if groups[BUSINESS_ONLY]:
            text += (f" Business only: {pct[BUSINESS_ONLY]:.0f}% ({', '.join(groups[BUSINESS_ONLY])}) is in a {name} "
                     f"business, but its price doesn't clearly move with the theme.")
        if by_tier[NOT_DETERMINED]:
            text += f" For {by_tier[NOT_DETERMINED]:.0f}% the data can't tell (regression Not determined)."
        if groups[MARKET_DRIVEN]:
            text += (f" Caution, market-driven: {pct[MARKET_DRIVEN]:.0f}% ({', '.join(groups[MARKET_DRIVEN])}) moves "
                     f"with {theme.get('plain') or name + ' companies'}, but isn't a {name} business.")
        out[key] = {"name": name, "exposure_pct": round(e_pct, 2), "high_moderate_pct": round(e_pct, 2),
                    "business_linked_pct": round(e_pct, 2),
                    "business_only_pct": round(pct[BUSINESS_ONLY], 2),
                    "market_driven_pct": round(pct[MARKET_DRIVEN], 2), "price_only_pct": round(pct[MARKET_DRIVEN], 2),
                    "by_rating_pct": {g: round(v, 2) for g, v in pct.items()},
                    "by_tier_pct": {t: round(v, 2) for t, v in by_tier.items()},
                    "cash_pct": round(cash, 2), "sentence": text}
    return out


def run_screen(holdings: dict[str, float], themes: list[str] | None = None,
               start: str = DEFAULT_START, end: str = DEFAULT_END) -> dict:
    """Screen a portfolio. holdings = {ticker: weight %}; themes = theme keys (default: all)."""
    weights, rescaled = _normalize(holdings)
    try:
        theme_defs = {k: load_theme(k) for k in themes} if themes else load_all()
    except ValueError as exc:
        raise InputError(str(exc)) from None
    results: dict[str, dict[str, dict]] = {}
    for ticker in weights:
        if ticker == CASH:
            continue
        results[ticker] = {key: _screen_one(ticker, th, start, end) for key, th in theme_defs.items()}
        industry = industry_of(ticker)
        for key, th in theme_defs.items():
            add_rating(results[ticker][key], ticker, industry, th)
    return {
        "window": {"start": start, "end": end},
        "weights_rescaled_to_100": rescaled,
        "cash_pct": round(weights.get(CASH, 0.0), 2),
        "holdings": [
            {"ticker": t, "weight_pct": round(w, 2),
             "results": "cash: kept at its weight, not scored" if t == CASH else results[t]}
            for t, w in weights.items()
        ],
        "fingerprint": fingerprint(weights, results, theme_defs),
    }


def summary_text(report: dict) -> str:
    """Plain-English summary for the command line."""
    lines = [f"Window: {report['window']['start']} to {report['window']['end']}"]
    if report["weights_rescaled_to_100"]:
        lines.append("Note: weights didn't add to 100, so they were rescaled.")
    lines.append("")
    keys = list(report["fingerprint"])
    width = max(len(report["fingerprint"][k]["name"]) for k in keys)
    for h in report["holdings"]:
        lines.append(f"{h['ticker']} ({h['weight_pct']:g}%)")
        if h["ticker"] == CASH:
            lines.append("  cash: kept at its weight, not scored")
            continue
        for k in keys:
            r = h["results"][k]
            bl = "yes" if r.get("business_linked") else "no"
            lines.append(f"  {report['fingerprint'][k]['name']:<{width}}  {r.get('final_rating', '-'):<14} "
                         f"(regression {r['tier']}, business linked: {bl}"
                         + (f", revenue {r['revenue_pct']:.0f}%" if r.get("revenue_pct") is not None else "") + ")")
    lines += ["", "Portfolio fingerprint:",
              f"  {'Theme':<{width}}  Exposure %  Business only %  Market-driven %"]
    for k in keys:
        f = report["fingerprint"][k]
        lines.append(f"  {f['name']:<{width}}  {f['exposure_pct']:9.1f}%  {f['business_only_pct']:14.1f}%  "
                     f"{f['market_driven_pct']:14.1f}%")
    lines += ["", "Exposure = High or Moderate: in the theme's business, backed by revenue or a price link (the headline).",
              "Business only = in the business, but neither revenue nor prices confirm much exposure.",
              "Market-driven = the price moves with the theme's companies, but it isn't a theme business (caution).", ""]
    for k in keys:
        lines.append(f"  {report['fingerprint'][k]['sentence']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine.screen", description="Screen a portfolio for theme exposure.")
    ap.add_argument("holdings", nargs="*", help="TICKER:WEIGHT pairs, e.g. NVDA:30 XOM:20 CASH:50")
    ap.add_argument("--themes", help="comma-separated theme keys (default: all), e.g. ai,oil")
    ap.add_argument("--json", action="store_true", help="print the full JSON instead of the summary")
    args = ap.parse_args(argv)
    try:
        holdings = parse_holdings(args.holdings)
        themes = [t.strip() for t in args.themes.split(",") if t.strip()] if args.themes else None
        report = run_screen(holdings, themes)
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "screen_latest.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1) if args.json else summary_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
