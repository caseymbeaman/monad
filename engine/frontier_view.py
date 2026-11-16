"""Mean-variance check: where does the fund sit against the best mixes of its own stocks?

    frontier_view({"ARM": 14.3, "GOOGL": 14.3, ..., "CASH": 0})  -> (dict, plotly figure or None)

This is a CHECK ONLY. The fund's weights come from the theme rules (engine/builder.py); this view never
changes them. It answers: "Given these same stocks, how does the fund's risk/return trade-off compare
with the lowest-risk mix and the best risk-adjusted (tangency) mix?"

How it works, in plain terms:
- Uses engine/mean_variance (efficient frontier, capital market line, minimum-variance and tangency
  portfolios, long-only).
- Data: up to 10 years of MONTHLY dividend-adjusted returns from FMP (through engine/fmp.py, so
  cached like everything else), and the current 10-year Treasury
  yield as the risk-free rate. That's a longer, different window from the 2 years of daily data used for
  classification and the Monte Carlo, and it's labeled as such.
- Each stock uses its own history (up to 10 years); how stocks move together comes from the period they
  all share. Cash is left out of the chart and reported separately.
- Past averages are noisy; the chart shows how this mix did, not what it will do.
"""

from __future__ import annotations

from engine.mean_variance.analyze_portfolio import analyze_portfolio
from engine.mean_variance.errors import PortfolioToolError

CASH = "CASH"
WINDOW_MODE = "max_available"


def _invested_weights(holdings: dict[str, float]) -> tuple[dict[str, float], float]:
    """Non-cash holdings rescaled to add up to 1, and the cash share of the whole portfolio (decimal)."""
    total = sum(holdings.values())
    if total <= 0:
        raise ValueError("Weights must add up to more than zero.")
    cash = holdings.get(CASH, 0.0) / total
    stocks = {t: w for t, w in holdings.items() if t != CASH}
    invested = sum(stocks.values())
    return ({t: w / invested for t, w in stocks.items()} if invested > 0 else {}), cash


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def sentences(summary, cash: float) -> list[str]:
    mine = summary.loc["Your portfolio"]
    low = summary.loc["Minimum-variance portfolio"]
    out = [(f"Using up to 10 years of monthly data, the invested part of your fund earned about "
           f"{_pct(mine['return'])} a year with {_pct(mine['volatility'])} yearly swings (risk), "
           f"a Sharpe ratio of {mine['sharpe']:.2f} (return above Treasuries per unit of risk).")]
    out.append(f"The lowest-risk mix of these same stocks had {_pct(low['volatility'])} risk, "
               f"vs {_pct(mine['volatility'])} for yours.")
    if "Tangency portfolio" in summary.index:
        best = summary.loc["Tangency portfolio"]
        share = mine["sharpe"] / best["sharpe"] if best["sharpe"] > 0 else float("nan")
        out.append(f"The best risk-adjusted mix of these stocks had a Sharpe ratio of {best['sharpe']:.2f}; "
                   f"yours gets {share * 100:.0f}% of the way there.")
    else:
        out.append("None of these stocks beat the 10-year Treasury yield, so there's no best risk-adjusted mix.")
    if cash > 1e-9:
        out.append(f"Your fund also holds {_pct(cash)} cash, which isn't shown in this chart.")
    out.append("This is a check only: the fund's weights come from your theme choices, not from this chart.")
    return out


def frontier_view(holdings: dict[str, float], today=None):
    """Return (JSON-ready dict, plotly figure or None). Never raises for data problems: they're reported."""
    invested, cash = _invested_weights({t.upper(): float(w) for t, w in holdings.items()})
    if len(invested) < 2:
        return ({"available": False, "cash_pct": round(cash * 100, 2),
                 "sentences": [("The mean-variance check needs at least two stocks, so it's skipped "
                               "for this portfolio.")]}, None)
    try:
        analysis = analyze_portfolio(invested, window_mode=WINDOW_MODE, today=today)
    except PortfolioToolError as exc:
        return ({"available": False, "cash_pct": round(cash * 100, 2),
                 "sentences": [f"The mean-variance check couldn't run: {exc}"]}, None)
    summary = analysis.summary
    table = {
        name: {"return": round(float(row["return"]), 6), "volatility": round(float(row["volatility"]), 6),
               "sharpe": round(float(row["sharpe"]), 4),
               "weights": {t: round(float(w), 4) for t, w in row["weights"].items() if w > 0}}
        for name, row in summary.iterrows()
    }
    windows = {t: {"start": str(r["start"]), "end": str(r["end"]), "months": int(r["months"])}
               for t, r in analysis.windows.iterrows()}
    report = {
        "available": True,
        "risk_free_rate": round(analysis.risk_free_rate, 6),
        "window_mode": analysis.window_mode,
        "data_windows": windows,
        "cash_pct": round(cash * 100, 2),
        "portfolios": table,
        "sentences": sentences(summary, cash),
    }
    return report, analysis.figure
