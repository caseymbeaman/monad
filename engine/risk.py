"""Phase 6: the risk report for a portfolio. Monte Carlo + theme shocks + mean-variance check.

    run_risk({"NVDA": 30, "XOM": 20, "CASH": 50}, shocks={"oil": 0.30})  -> (report dict, figures dict)

Command line:
    python -m engine.risk NVDA:30 XOM:20 CASH:50                 (shocks every theme +30%)
    python -m engine.risk NVDA:30 XOM:20 CASH:50 --shock oil=30 --shock ai=-20
    python -m engine.risk --from-build                           (the basket in results/build_latest.json)
    python -m engine.risk --from-build --no-frontier --json

Saves results/risk_latest.json (the full report) and two charts: results/risk_fan_chart.html and
results/risk_frontier.html.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine import monte_carlo, shocks
from engine.data import DEFAULT_END, DEFAULT_START, DataError
from engine.frontier_view import frontier_view
from engine.screen import InputError, parse_holdings
from engine.theme_loader import load_all

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHOCK = 0.30


def parse_shocks(items: list[str] | None, theme_keys: list[str]) -> dict[str, float]:
    """["oil=30", "ai=-20"] -> {"oil": 0.30, "ai": -0.20}."""
    out: dict[str, float] = {}
    for item in items or []:
        key, sep, size = item.partition("=")
        key = key.strip().lower()
        if not sep or not key:
            raise InputError(f"'{item}' should look like THEME=PERCENT, e.g. oil=30")
        if key not in theme_keys:
            raise InputError(f"No theme called '{key}'. Available: {', '.join(sorted(theme_keys))}")
        try:
            value = float(size) / 100
        except ValueError:
            raise InputError(f"'{item}': '{size}' isn't a number") from None
        if not abs(value) <= shocks.MAX_SHOCK:  # also rejects nan
            raise InputError(f"'{item}': shocks must be between -100 and 100 percent")
        out[key] = value
    return out


def run_risk(holdings: dict[str, float], shock_sizes: dict[str, float] | None = None,
             include_frontier: bool = True, start: str = DEFAULT_START, end: str = DEFAULT_END):
    """Full risk report. `holdings` are percent weights (cash as "CASH"); shocks default to +30% per theme."""
    weights = monte_carlo.to_weights(holdings)
    mc = monte_carlo.simulate(holdings, start, end)
    theme_keys = list(load_all())
    sizes = shock_sizes if shock_sizes else {k: DEFAULT_SHOCK for k in theme_keys}
    shock_results = [shocks.shock_portfolio(weights, k, s, start, end).to_dict() for k, s in sizes.items()]
    figures = {"fan_chart": monte_carlo.fan_chart(mc)}
    frontier = None
    if include_frontier:
        pct = {t: w * 100 for t, w in weights.items()}
        frontier, figures["frontier"] = frontier_view(pct)
    report = {
        "holdings_pct": {t: round(w * 100, 4) for t, w in weights.items()},
        "monte_carlo": mc.to_dict(),
        "shocks": shock_results,
        "frontier": frontier,
        "summary": summary_sentences(mc, shock_results),
    }
    return report, figures


def summary_sentences(mc: monte_carlo.MonteCarloResult, shock_results: list[dict]) -> list[str]:
    """The three or four sentences a non-expert most needs."""
    p, b = mc.portfolio, mc.benchmark
    out = [mc.history_note] if mc.history_note else []
    out.append(f"Chance of losing more than 10% in a year: {p.p_loss_over_10 * 100:.0f}% "
               f"(SPY: {b.p_loss_over_10 * 100:.0f}%).")
    out.append(next(s for s in mc.sentences if s.startswith("Bad year (5% VaR)")))
    if shock_results:
        biggest = max(shock_results, key=lambda s: abs(s["portfolio_move"]))
        out.append(f"Most sensitive theme: {biggest['theme_name']}. {biggest['sentence']}")
    out.append(f"Typical year: {'+' if p.median >= 0 else '-'}{abs(p.median) * 100:.0f}%; this is a range "
               "of outcomes from the past two years, not a forecast.")
    return out


def summary_text(report: dict) -> str:
    mc = report["monte_carlo"]
    lines = ["Portfolio: " + ", ".join(f"{t} {w:.1f}%" for t, w in report["holdings_pct"].items()), "",
             f"MONTE CARLO ({mc['n_paths']:,} simulated years, {mc['block_days']}-day blocks, seed {mc['seed']})"]
    lines += [f"  {s}" for s in mc["sentences"]]
    lines += ["", "THEME SHOCKS (estimated sensitivity based on past co-movement)"]
    for s in sorted(report["shocks"], key=lambda s: -abs(s["portfolio_move"])):
        lines.append(f"  {s['theme_name'][:44]:<46}{s['shock'] * 100:+4.0f}%  ->  portfolio "
                     f"{s['portfolio_move'] * 100:+.1f}%")
    lines += [""] + [f"  {s['sentence']}" for s in report["shocks"]]
    if report["frontier"] is not None:
        lines += ["", "MEAN-VARIANCE CHECK"] + [f"  {s}" for s in report["frontier"]["sentences"]]
    lines += ["", "IN SHORT"] + [f"  {s}" for s in report["summary"]]
    return "\n".join(lines)


def _holdings_from_build(path: Path) -> dict[str, float]:
    if not path.exists():
        raise InputError(f"{path.name} not found. Run 'python -m engine.builder --want ...' first.")
    build = json.loads(path.read_text())
    holdings = {h["ticker"]: float(h["weight_pct"]) for h in build.get("holdings", []) if h["weight_pct"] > 0}
    if not holdings:
        raise InputError("The latest build has no holdings.")
    return holdings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine.risk", description="Risk report for a portfolio.")
    ap.add_argument("holdings", nargs="*", help="TICKER:WEIGHT pairs, e.g. NVDA:30 XOM:20 CASH:50")
    ap.add_argument("--from-build", action="store_true", help="use the basket in results/build_latest.json")
    ap.add_argument("--shock", action="append", help="THEME=PERCENT, e.g. oil=30 (default: every theme +30)")
    ap.add_argument("--no-frontier", action="store_true", help="skip the mean-variance check")
    ap.add_argument("--json", action="store_true", help="print the full JSON")
    args = ap.parse_args(argv)
    try:
        if args.from_build and args.holdings:
            raise InputError("Give holdings OR --from-build, not both.")
        holdings = (_holdings_from_build(ROOT / "results" / "build_latest.json") if args.from_build
                    else parse_holdings(args.holdings))
        sizes = parse_shocks(args.shock, list(load_all()))
        report, figures = run_risk(holdings, sizes, include_frontier=not args.no_frontier)
    except (InputError, DataError, monte_carlo.SimulationError, shocks.ShockError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "risk_latest.json").write_text(json.dumps(report, indent=1))
    for name, fig in figures.items():
        if fig is not None:
            file = "risk_fan_chart.html" if name == "fan_chart" else "risk_frontier.html"
            fig.write_html(out_dir / file, include_plotlyjs="cdn")
    print(json.dumps(report, indent=1) if args.json else summary_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
