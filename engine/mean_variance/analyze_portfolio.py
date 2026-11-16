"""Main entry point: evaluate one portfolio on the mean-variance chart.

The main app will call analyze_portfolio(...) when someone builds a portfolio.
It can also be run from the command line:

    python -m engine.mean_variance.analyze_portfolio AAPL=0.4 MSFT=0.35 XOM=0.25 --output chart.html

Steps:
1. Check the tickers and weights the user entered.
2. Pull up to 10 years of dividend-adjusted prices and the current 10-year
   Treasury yield from FMP.
3. Turn prices into annual expected returns and a risk model.
4. Find the minimum-variance portfolio, the efficient frontier and the
   tangency portfolio.
5. Draw the chart and summary table.
"""

import argparse
import datetime as dt
import math
import numbers
import sys
from dataclasses import dataclass

import pandas as pd

from . import chart_builder, data_fetcher, optimizer, return_calculator
from .errors import PortfolioInputError, PortfolioToolError

LOOKBACK_YEARS = 10
# Weights may add up to anywhere from 99% to 101%; they are then rescaled to 100%.
WEIGHT_SUM_TOLERANCE = 0.01


@dataclass
class PortfolioAnalysis:
    """Everything the tool works out, so the app can use any piece of it."""

    summary: pd.DataFrame          # return, volatility, sharpe, weights per marked portfolio
    frontier: pd.DataFrame         # points along the efficient frontier
    stocks: pd.DataFrame           # return and volatility of each stock on its own
    risk_free_rate: float
    window_mode: str
    windows: pd.DataFrame          # data period each stock was measured over
    figure: object                 # the plotly chart


def validate_weights(weights):
    """Check the portfolio and return it with clean tickers and weights summing to 1.

    Rules: at least two stocks, no blank or repeated tickers, weights are
    numbers, no negative weights (long-only), and they add up to 100% (+/- 1%).
    """
    if not isinstance(weights, dict) or not weights:
        raise PortfolioInputError(
            "Enter the portfolio as tickers and weights, e.g. {'AAPL': 0.5, 'MSFT': 0.5}."
        )

    cleaned = {}
    for raw_ticker, weight in weights.items():
        if not isinstance(raw_ticker, str) or not raw_ticker.strip():
            raise PortfolioInputError(f"'{raw_ticker}' is not a valid ticker.")
        ticker = raw_ticker.strip().upper()
        if ticker in cleaned:
            raise PortfolioInputError(f"{ticker} appears more than once.")
        if isinstance(weight, bool) or not isinstance(weight, numbers.Real):
            raise PortfolioInputError(f"The weight for {ticker} must be a number.")
        weight = float(weight)
        if not math.isfinite(weight):
            raise PortfolioInputError(f"The weight for {ticker} must be a finite number.")
        if weight < 0:
            raise PortfolioInputError(
                f"{ticker} has a negative weight. Short positions are not supported yet."
            )
        cleaned[ticker] = weight

    if len(cleaned) < 2:
        raise PortfolioInputError("Add at least two stocks; a frontier needs a choice to make.")

    total = sum(cleaned.values())
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise PortfolioInputError(
            f"Weights add up to {total:.1%}. They need to add up to 100%."
        )
    return {t: w / total for t, w in cleaned.items()}


def _last_complete_month_end(today):
    """The last day of the previous month, so a half-finished month is never used."""
    return today.replace(day=1) - dt.timedelta(days=1)


def _summary_table(portfolios, expected_returns, covariance, risk_free_rate):
    """Return, risk and Sharpe ratio for each named portfolio, plus its weights."""
    stats = {}
    for name, weights in portfolios.items():
        w = weights[expected_returns.index].to_numpy()
        ret = optimizer.portfolio_return(w, expected_returns)
        vol = optimizer.portfolio_volatility(w, covariance)
        stats[name] = {"return": ret, "volatility": vol,
                       "sharpe": optimizer.sharpe_ratio(ret, vol, risk_free_rate)}
    summary = pd.DataFrame.from_dict(stats, orient="index")
    summary["weights"] = pd.Series(portfolios, dtype=object)
    return summary


def evaluate(weights, prices, risk_free_rate, window_mode="shared"):
    """Run the analysis on prices already in hand (no internet needed).

    Split out from analyze_portfolio so it can be tested with made-up prices.
    """
    weights = validate_weights(weights)
    tickers = list(weights)
    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        raise PortfolioInputError(f"No prices supplied for: {', '.join(missing)}.")

    monthly = return_calculator.to_monthly_returns(prices[tickers])
    monthly = monthly.iloc[-LOOKBACK_YEARS * 12:]  # never more than 10 years
    inputs = return_calculator.estimate_inputs(monthly, window_mode)
    mu, cov = inputs.expected_returns[tickers], inputs.covariance.loc[tickers, tickers]

    user = pd.Series(weights)
    min_var = optimizer.min_variance_portfolio(cov)
    tangency = optimizer.tangency_portfolio(mu, cov, risk_free_rate)

    portfolios = {"Your portfolio": user, "Minimum-variance portfolio": min_var}
    if tangency is not None:
        portfolios["Tangency portfolio"] = tangency
    summary = _summary_table(portfolios, mu, cov, risk_free_rate)

    frontier = optimizer.efficient_frontier(mu, cov)
    stocks = pd.DataFrame({"return": mu, "volatility": pd.Series(
        {t: math.sqrt(cov.loc[t, t]) for t in tickers})})

    notes = [_window_note(inputs.windows, window_mode)]
    figure = chart_builder.build_chart(summary, frontier, stocks, risk_free_rate, notes)

    return PortfolioAnalysis(
        summary=summary,
        frontier=frontier,
        stocks=stocks,
        risk_free_rate=risk_free_rate,
        window_mode=window_mode,
        windows=inputs.windows,
        figure=figure,
    )


def _window_note(windows, window_mode):
    """One line for the chart describing which period the data covers."""
    if window_mode == "shared":
        first = windows.iloc[0]
        return (f"Data: {first['start']:%b %Y} to {first['end']:%b %Y} "
                f"({first['months']} months, all stocks)")
    parts = [f"{t} {row['months']}m" for t, row in windows.iterrows()]
    return "Data: each stock's own history, up to 10 years (" + ", ".join(parts) + ")"


def analyze_portfolio(weights, window_mode="shared", today=None, output_path=None):
    """Evaluate a portfolio using live FMP data.

    weights:     e.g. {"AAPL": 0.4, "MSFT": 0.35, "XOM": 0.25}
    window_mode: "shared" (all stocks over the same period) or
                 "max_available" (each stock uses its own history, up to 10 years)
    output_path: if given, the chart is saved there as an HTML file
    """
    weights = validate_weights(weights)
    if window_mode not in return_calculator.WINDOW_MODES:
        raise PortfolioInputError(
            f"window_mode must be one of {return_calculator.WINDOW_MODES}."
        )
    today = today or dt.date.today()
    end = _last_complete_month_end(today)
    # One extra month at the start gives a full 120 monthly returns.
    start = (pd.Timestamp(end) - pd.DateOffset(years=LOOKBACK_YEARS, months=1)).date()

    prices = data_fetcher.fetch_adjusted_prices(list(weights), start, end)
    risk_free_rate = data_fetcher.fetch_ten_year_yield(today)
    analysis = evaluate(weights, prices, risk_free_rate, window_mode)
    if output_path:
        analysis.figure.write_html(output_path, include_plotlyjs=True)
    return analysis


def _parse_cli_weights(pairs):
    weights = {}
    for pair in pairs:
        ticker, sep, value = pair.partition("=")
        if not sep:
            raise PortfolioInputError(f"'{pair}' should look like TICKER=WEIGHT, e.g. AAPL=0.4.")
        try:
            weights[ticker] = float(value)
        except ValueError as exc:
            raise PortfolioInputError(f"The weight in '{pair}' is not a number.") from exc
    return weights


def format_summary(summary):
    """The summary table as plain text for the command line."""
    lines = [f"{'Portfolio':<28}{'Return':>10}{'Risk':>10}{'Sharpe':>9}"]
    for name, row in summary.iterrows():
        sharpe = "n/a" if math.isnan(row["sharpe"]) else f"{row['sharpe']:.2f}"
        lines.append(f"{name:<28}{row['return']:>10.2%}{row['volatility']:>10.2%}{sharpe:>9}")
        lines.append("    " + ", ".join(f"{t} {w:.1%}" for t, w in row["weights"].items() if w > 0))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mean-variance analysis of a stock portfolio.")
    parser.add_argument("holdings", nargs="+", help="TICKER=WEIGHT pairs, e.g. AAPL=0.4 MSFT=0.6")
    parser.add_argument("--window", choices=return_calculator.WINDOW_MODES, default="shared",
                        help="how to handle stocks with less than 10 years of history")
    parser.add_argument("--output", default="mean_variance_chart.html",
                        help="where to save the chart (HTML)")
    args = parser.parse_args(argv)

    try:
        weights = _parse_cli_weights(args.holdings)
        analysis = analyze_portfolio(weights, args.window, output_path=args.output)
    except PortfolioToolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Risk-free rate (10-year Treasury): {analysis.risk_free_rate:.2%}")
    print(_window_note(analysis.windows, analysis.window_mode))
    print()
    print(format_summary(analysis.summary))
    print(f"\nChart saved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
