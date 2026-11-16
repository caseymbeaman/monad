"""Monte Carlo risk simulation: what could a year in this portfolio look like?

    simulate({"NVDA": 30, "XOM": 20, "CASH": 50})  -> MonteCarloResult

How it works, in plain terms:
- Start from the last ~2 years of real daily returns for every holding and for SPY (the market).
- Build one simulated year (252 trading days) by picking random 5-day stretches of real history and
  stitching them together. Keeping 5 real days together preserves short streaks (a bad week tends to
  stay bad for a few days), which a day-by-day shuffle would erase. This is a "5-day block bootstrap".
- The portfolio and SPY are resampled on the SAME dates, so the simulation keeps how they moved together.
- Repeat 5,000 times with a fixed random seed, so the same portfolio always gives the same answer.
- Weights are held constant each day (daily rebalancing). Cash keeps its weight and is assumed to earn
  nothing, which slightly understates returns but never hides risk.

What comes out (all for a one-year horizon):
- Chance of losing more than 10%.
- 5% Value at Risk (VaR): in the worst 1-in-20 years, you lose at least this much.
- 5% Conditional VaR (CVaR): the AVERAGE loss across those worst 1-in-20 years.
- Median outcome, chance of beating SPY, and a fan chart of the range of outcomes.

This is not a forecast. It replays the past two years in random order; a future unlike those two years
(a crash bigger than anything in the window, say) is not covered.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from engine.data import DEFAULT_END, DEFAULT_START, DataError, get_returns

N_PATHS = 5_000
HORIZON_DAYS = 252          # one trading year
BLOCK_DAYS = 5              # one trading week
SEED = 20261115             # fixed: Monad Blitz Oregon date, so results are reproducible
BENCHMARK = "SPY"
CASH = "CASH"
LOSS_THRESHOLD = -0.10      # "lose more than 10%"
TAIL = 0.05                 # 5% VaR / CVaR
FAN_PERCENTILES = (5, 25, 50, 75, 95)
START_VALUE = 10_000        # charts and sentences talk about a $10,000 investment
FLAT = 0.005                # moves smaller than 0.5% are described as "break even" (they'd show as 0%)
FULL_WINDOW_DAYS = 450      # ~2 years is ~500 trading days; fewer shared days than this gets a warning


class SimulationError(ValueError):
    """The portfolio or the data can't be simulated. The message is safe to show to a user."""


@dataclass
class OutcomeStats:
    """Summary of 5,000 simulated one-year returns (decimals: -0.12 = -12%)."""
    median: float
    mean: float
    p_loss_over_10: float    # share of years with a loss worse than -10%
    var_5: float             # 5% Value at Risk, as a positive loss (0.20 = lose 20%)
    cvar_5: float            # average loss in the worst 5% of years, as a positive loss
    best_5: float            # 95th percentile return (a good year)


@dataclass
class MonteCarloResult:
    weights: dict[str, float]        # decimals summing to 1, cash included
    n_paths: int
    horizon_days: int
    block_days: int
    seed: int
    history_days: int
    history_start: str
    history_end: str
    portfolio: OutcomeStats
    benchmark: OutcomeStats
    p_beat_benchmark: float
    fan: dict                        # {"days": [...], "portfolio": {pct: [...]}, "benchmark": {pct: [...]}}
    sentences: list[str]
    history_note: str | None = None  # set when a young holding shortens the shared history

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------

def to_weights(holdings: dict[str, float]) -> dict[str, float]:
    """Percent holdings (any total) -> decimal weights summing to 1. Cash stays as its own line."""
    if not holdings:
        raise SimulationError("No holdings given.")
    clean: dict[str, float] = {}
    for ticker, w in holdings.items():
        t = str(ticker).strip().upper()
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not np.isfinite(w) or w <= 0:
            raise SimulationError(f"Weight for {t} must be a positive number.")
        if t in clean:
            raise SimulationError(f"{t} is listed twice; combine it into one weight.")
        clean[t] = float(w)
    total = sum(clean.values())
    return {t: w / total for t, w in clean.items()}


def portfolio_daily_returns(weights: dict[str, float], returns: pd.DataFrame) -> pd.Series:
    """Each day's portfolio return = sum of weight x that holding's return. Cash earns 0."""
    stocks = [t for t in weights if t != CASH]
    missing = [t for t in stocks if t not in returns.columns]
    if missing:
        raise SimulationError(f"No returns for: {', '.join(missing)}")
    w = pd.Series({t: weights[t] for t in stocks}, dtype=float)
    return returns[stocks].mul(w, axis=1).sum(axis=1) if stocks else pd.Series(0.0, index=returns.index)


# ---------------------------------------------------------------------------------------------
# The bootstrap
# ---------------------------------------------------------------------------------------------

def block_indices(n_history: int, n_paths: int = N_PATHS, horizon: int = HORIZON_DAYS,
                  block: int = BLOCK_DAYS, seed: int = SEED) -> np.ndarray:
    """Which historical day each simulated day comes from: an (n_paths x horizon) array of row numbers.

    Each path is made of real consecutive `block`-day stretches, each starting at a random day where a
    full stretch fits. The last stretch is cut short so the path is exactly `horizon` days.
    """
    if n_history < block:
        raise SimulationError(f"Need at least {block} days of history; got {n_history}.")
    rng = np.random.default_rng(seed)
    n_blocks = -(-horizon // block)  # ceiling division
    starts = rng.integers(0, n_history - block + 1, size=(n_paths, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_paths, n_blocks * block)
    return idx[:, :horizon]


def growth_paths(daily: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Value of $1 along each simulated path, day by day (n_paths x (horizon + 1)), starting at 1."""
    growth = np.cumprod(1.0 + daily[idx], axis=1)
    return np.hstack([np.ones((idx.shape[0], 1)), growth])


def outcome_stats(year_returns: np.ndarray) -> OutcomeStats:
    """Summary numbers for a set of simulated one-year returns."""
    r = np.asarray(year_returns, dtype=float)
    if r.size == 0 or not np.all(np.isfinite(r)):
        raise SimulationError("Simulated returns are empty or invalid.")
    cutoff = float(np.quantile(r, TAIL))
    tail = r[r <= cutoff]
    return OutcomeStats(
        median=float(np.median(r)),
        mean=float(r.mean()),
        p_loss_over_10=float(np.mean(r < LOSS_THRESHOLD)),
        var_5=float(-cutoff),
        cvar_5=float(-tail.mean()),
        best_5=float(np.quantile(r, 1 - TAIL)),
    )


def _fan(paths: np.ndarray) -> dict[str, list[float]]:
    return {str(p): [round(float(v), 6) for v in np.percentile(paths, p, axis=0)] for p in FAN_PERCENTILES}


# ---------------------------------------------------------------------------------------------
# Plain-English sentences
# ---------------------------------------------------------------------------------------------

def _pct(x: float) -> str:
    return f"{abs(x) * 100:.0f}%"


def _money(x: float) -> str:
    return f"${x:,.0f}"


def sentences(port: OutcomeStats, bench: OutcomeStats, p_beat: float, n_paths: int,
              history_start: str, history_end: str, history_note: str | None = None) -> list[str]:
    med_word = "gain" if port.median >= 0 else "loss"
    if port.var_5 > FLAT:
        bad_year = (f"you'd lose at least {_pct(port.var_5)}, about {_money(START_VALUE * port.var_5)} "
                    f"on {_money(START_VALUE)}")
    elif port.var_5 < -FLAT:
        bad_year = f"you'd still gain at least {_pct(port.var_5)}"
    else:
        bad_year = "you'd roughly break even"
    if port.cvar_5 > FLAT:
        worst = f"a {_pct(port.cvar_5)} loss"
    elif port.cvar_5 < -FLAT:
        worst = f"a {_pct(port.cvar_5)} gain"
    else:
        worst = "roughly break-even"
    out = [
        (f"We replayed the market's real daily moves from {history_start} to {history_end} in random "
         f"5-day chunks to simulate {n_paths:,} possible years. This shows a range of outcomes, not a forecast."),
    ]
    if history_note:
        out.append(history_note)
    out += [
        (f"Typical year: a {_pct(port.median)} {med_word} (a {_money(START_VALUE)} investment ends near "
         f"{_money(START_VALUE * (1 + port.median))}). For SPY, the market, it's "
         f"{'+' if bench.median >= 0 else '-'}{_pct(bench.median)}."),
        (f"Chance of losing more than 10% in a year: {_pct(port.p_loss_over_10)} "
         f"(SPY: {_pct(bench.p_loss_over_10)})."),
        f"Bad year (5% VaR): in the worst 1 of every 20 simulated years {bad_year} (SPY: {_pct(bench.var_5)}).",
        f"Average of those worst years (5% CVaR): {worst} (SPY: {_pct(bench.cvar_5)}).",
        f"Your portfolio beat SPY in {_pct(p_beat)} of the simulated years.",
    ]
    return out


# ---------------------------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------------------------

def simulate_from_returns(weights: dict[str, float], returns: pd.DataFrame, n_paths: int = N_PATHS,
                          horizon: int = HORIZON_DAYS, block: int = BLOCK_DAYS,
                          seed: int = SEED, history_note: str | None = None) -> MonteCarloResult:
    """Run the simulation on returns already in hand (no internet needed; used by the tests)."""
    if BENCHMARK not in returns.columns:
        raise SimulationError(f"Returns must include the benchmark {BENCHMARK}.")
    if n_paths < 100:
        raise SimulationError("Use at least 100 paths for stable percentiles.")
    port_daily = portfolio_daily_returns(weights, returns).to_numpy()
    bench_daily = returns[BENCHMARK].to_numpy()
    idx = block_indices(len(returns), n_paths, horizon, block, seed)
    port_paths = growth_paths(port_daily, idx)      # same idx for both: same simulated dates
    bench_paths = growth_paths(bench_daily, idx)
    port_year = port_paths[:, -1] - 1
    bench_year = bench_paths[:, -1] - 1
    port_stats, bench_stats = outcome_stats(port_year), outcome_stats(bench_year)
    p_beat = float(np.mean(port_year > bench_year))
    start, end = f"{returns.index[0]:%b %Y}", f"{returns.index[-1]:%b %Y}"
    return MonteCarloResult(
        weights={t: round(w, 6) for t, w in weights.items()},
        n_paths=n_paths, horizon_days=horizon, block_days=block, seed=seed,
        history_days=len(returns), history_start=f"{returns.index[0]:%Y-%m-%d}",
        history_end=f"{returns.index[-1]:%Y-%m-%d}",
        portfolio=port_stats, benchmark=bench_stats, p_beat_benchmark=p_beat,
        fan={"days": list(range(horizon + 1)), "portfolio": _fan(port_paths), "benchmark": _fan(bench_paths)},
        sentences=sentences(port_stats, bench_stats, p_beat, n_paths, start, end, history_note),
        history_note=history_note,
    )


def simulate(holdings: dict[str, float], start: str = DEFAULT_START, end: str = DEFAULT_END,
             **kwargs) -> MonteCarloResult:
    """Simulate a portfolio given as percent weights, e.g. {"NVDA": 30, "XOM": 20, "CASH": 50}."""
    weights = to_weights(holdings)
    tickers = [t for t in weights if t != CASH]
    returns = get_returns(list(dict.fromkeys(tickers + [BENCHMARK])), start, end)
    note = shortened_history_note(tickers, returns, start, end)
    return simulate_from_returns(weights, returns, history_note=note, **kwargs)


def shortened_history_note(tickers: list[str], returns: pd.DataFrame, start: str, end: str) -> str | None:
    """A plain warning when a young holding cuts the shared history well below ~2 years, naming it.

    The simulation can only use days every holding traded, so one recent listing shortens the window for
    the whole fund. That window may be unusually good or bad, which the numbers would silently inherit.
    """
    if len(returns) >= FULL_WINDOW_DAYS or not tickers:
        return None
    starts = {}
    for t in tickers:
        try:
            starts[t] = get_returns([t], start, end).index[0]
        except DataError:
            continue
    window = f"{returns.index[0]:%b %Y} to {returns.index[-1]:%b %Y}"
    months = round(len(returns) / 21)
    if starts:
        young = max(starts, key=starts.get)
        cause = f"{young} only has prices from {starts[young]:%b %Y}"
    else:
        cause = "some holdings have short price histories"
    return (f"Heads-up: {cause}, so every simulated year is built from {window} alone (about {months} months), "
            "not the usual two years. These numbers reflect that period only; treat them with extra caution.")


# ---------------------------------------------------------------------------------------------
# Fan chart
# ---------------------------------------------------------------------------------------------

def fan_chart(result: MonteCarloResult, title: str = "Range of outcomes over one year"):
    """Plotly figure: shaded bands of simulated $10,000 values for the portfolio, SPY's median for comparison."""
    import plotly.graph_objects as go

    days = result.fan["days"]
    p, b = result.fan["portfolio"], result.fan["benchmark"]

    def dollars(series):
        return [START_VALUE * v for v in series]

    fig = go.Figure()
    bands = [("5", "95", "rgba(37, 99, 235, 0.15)", "Portfolio: 90% of outcomes"),
             ("25", "75", "rgba(37, 99, 235, 0.30)", "Portfolio: middle 50% of outcomes")]
    for low, high, color, name in bands:
        fig.add_trace(go.Scatter(x=days, y=dollars(p[high]), mode="lines", line={"width": 0},
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=days, y=dollars(p[low]), mode="lines", line={"width": 0}, fill="tonexty",
                                 fillcolor=color, name=name, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=days, y=dollars(p["50"]), mode="lines", name="Portfolio: typical path (median)",
                             line={"color": "#2563eb", "width": 3},
                             hovertemplate="Day %{x}: $%{y:,.0f}<extra>Portfolio median</extra>"))
    fig.add_trace(go.Scatter(x=days, y=dollars(b["50"]), mode="lines", name="SPY: typical path (median)",
                             line={"color": "#6b7280", "width": 2, "dash": "dash"},
                             hovertemplate="Day %{x}: $%{y:,.0f}<extra>SPY median</extra>"))
    fig.add_hline(y=START_VALUE * (1 + LOSS_THRESHOLD), line={"color": "#dc2626", "dash": "dot", "width": 1},
                  annotation_text="-10%", annotation_position="bottom right")
    fig.update_layout(
        title={"text": f"{title}<br><sup>{result.n_paths:,} simulated years from real "
                       f"{result.history_start} to {result.history_end} daily moves; not a forecast</sup>"},
        xaxis_title="Trading days from today", yaxis_title=f"Value of {_money(START_VALUE)}",
        yaxis_tickprefix="$", yaxis_tickformat=",.0f", template="plotly_white",
        legend={"orientation": "h", "y": -0.2}, height=520,
    )
    return fig
