"""Theme shocks: "if Oil jumps 30%, what happens to my portfolio?"

    shock_portfolio({"NVDA": 30, "XOM": 20, "CASH": 50}, "oil", 0.30)  -> ShockResult

How it works, in plain terms:
- Each theme has reference companies (e.g. Oil: FANG, CHRD, COP, EOG, CVX, ...). Their average daily
  return is the theme's "basket".
- For each holding, a regression measures how much it moved with that basket over the last ~2 years,
  after removing the same controls the classification uses (SPY, TLT, the theme's style controls, and
  the INTL control for a non-US holding).
  That slope is the holding's beta to the theme: beta 0.5 means "when the theme's basket rose 1% more
  than the market explained, this stock tended to rise 0.5%".
- A shock of +30% means: the theme's basket rises 30% while the market controls stay flat. Each holding
  moves beta x 30%; the portfolio moves by the weighted sum. Cash doesn't move.
- If a holding is itself one of the theme's references, it's left out of the basket for its own
  regression, so it isn't measured against itself.
- A holding that is a market control (SPY, TLT) is held flat by definition, so it moves 0.

This is an ESTIMATED SENSITIVITY BASED ON PAST CO-MOVEMENT, not a prediction. Real shocks rarely leave
the market flat, and relationships change.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm

from engine.controls import intl_control
from engine.data import DEFAULT_END, DEFAULT_START, DataError, get_returns
from engine.theme_loader import load_theme

CASH = "CASH"
LABEL = "estimated sensitivity based on past co-movement"
MIN_DAYS = 60            # fewer shared days than this and the beta is too noisy to report
MAX_SHOCK = 1.0          # shocks are limited to -100% .. +100%


class ShockError(ValueError):
    """The shock request can't be run. The message is safe to show to a user."""


@dataclass
class HoldingShock:
    ticker: str
    weight: float            # decimal share of the whole portfolio
    beta: float | None       # sensitivity to the theme basket (None if it couldn't be estimated)
    se: float | None         # standard error of beta
    move: float | None       # this holding's estimated move under the shock (decimal)
    contribution: float      # weight x move: its effect on the portfolio (decimal)
    note: str = ""


@dataclass
class ShockResult:
    theme: str               # theme key, e.g. "oil"
    theme_name: str
    shock: float             # decimal, e.g. 0.30
    portfolio_move: float    # decimal
    covered_weight: float    # share of the portfolio with a usable beta (cash counts as covered)
    holdings: list[HoldingShock] = field(default_factory=list)
    sentence: str = ""
    label: str = LABEL

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------------------------
# Sensitivities
# ---------------------------------------------------------------------------------------------

def reference_tickers(theme: dict) -> list[str]:
    return [r["ticker"] for g in ("High", "Moderate") for r in theme["references"].get(g, [])]


def theme_beta(ticker: str, theme: dict, returns: pd.DataFrame,
               sector: str | None = None) -> tuple[float, float, int]:
    """(beta, standard error, days used) of one holding to the theme's equal-weighted reference basket.

    `sector` is the holding's extra control column ("INTL" for a non-US stock), if any.
    """
    ticker = ticker.upper()
    refs = [t for t in reference_tickers(theme) if t != ticker]  # never measure a stock against itself
    if not refs:
        raise ValueError(f"{theme['name']} has no other reference companies to compare {ticker} with.")
    controls = list(theme["controls"]) + ([sector] if sector else [])
    needed = [ticker] + controls + refs
    missing = [c for c in needed if c not in returns.columns]
    if missing:
        raise ValueError(f"Missing returns for: {', '.join(missing)}")
    data = returns[needed].dropna()
    if len(data) < MIN_DAYS:
        raise ValueError(f"only {len(data)} shared days of data (need {MIN_DAYS}).")
    x = data[controls].copy()
    x["THEME"] = data[refs].mean(axis=1)
    fit = sm.OLS(data[ticker], sm.add_constant(x)).fit()
    return float(fit.params["THEME"]), float(fit.bse["THEME"]), int(fit.nobs)


def sensitivities(weights: dict[str, float], theme: dict, returns: pd.DataFrame,
                  sectors: dict[str, str | None] | None = None) -> dict[str, dict]:
    """Beta to the theme for every holding. Problems become a note, not a crash.

    `sectors` maps each holding to its sector-control column (or None), as the classification does.
    """
    sectors = sectors or {}
    out = {}
    for ticker in weights:
        if ticker == CASH:
            out[ticker] = {"beta": 0.0, "se": 0.0, "note": "Cash doesn't move."}
        elif ticker in theme["controls"]:
            out[ticker] = {"beta": 0.0, "se": 0.0,
                           "note": f"{ticker} is a market control, held flat in the shock."}
        else:
            try:
                beta, se, n = theme_beta(ticker, theme, returns, sectors.get(ticker))
                out[ticker] = {"beta": beta, "se": se, "note": f"{n} days of data"}
            except ValueError as exc:
                out[ticker] = {"beta": None, "se": None, "note": f"Couldn't estimate: {exc}"}
    return out


# ---------------------------------------------------------------------------------------------
# Applying a shock
# ---------------------------------------------------------------------------------------------

def _signed_pct(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}{abs(x) * 100:.1f}%"


def apply_shock(weights: dict[str, float], sens: dict[str, dict], theme_key: str, theme: dict,
                shock: float) -> ShockResult:
    """Combine weights and betas into the portfolio's estimated move under a theme shock."""
    if not isinstance(shock, (int, float)) or isinstance(shock, bool) or not np.isfinite(shock):
        raise ShockError("The shock size must be a number.")
    if abs(shock) > MAX_SHOCK:
        raise ShockError("Shocks are limited to between -100% and +100%.")
    rows, total, covered = [], 0.0, 0.0
    for ticker, w in weights.items():
        s = sens[ticker]
        if s["beta"] is None:
            rows.append(HoldingShock(ticker, w, None, None, None, 0.0, s["note"]))
            continue
        move = s["beta"] * shock
        rows.append(HoldingShock(ticker, w, s["beta"], s["se"], move, w * move, s["note"]))
        total += w * move
        covered += w
    plain = theme.get("plain") or f"{theme['name']} stocks"
    direction = "rose" if shock >= 0 else "fell"
    sentence = (f"If {plain} {direction} {abs(shock) * 100:.0f}% more than the overall market, your portfolio "
                f"would move about {_signed_pct(total)} ({LABEL}).")
    movers = sorted((r for r in rows if r.move is not None and r.ticker != CASH),
                    key=lambda r: -abs(r.contribution))
    if movers and abs(movers[0].contribution) >= 0.0005:
        top = movers[0]
        sentence += f" The biggest effect comes from {top.ticker} ({_signed_pct(top.contribution)})."
    if covered < 1 - 1e-9:
        gaps = ", ".join(r.ticker for r in rows if r.beta is None)
        sentence += f" {gaps} couldn't be estimated, so {(1 - covered) * 100:.0f}% of the portfolio is left out."
    return ShockResult(theme_key, theme["name"], float(shock), float(total), float(covered), rows, sentence)


def shock_from_returns(weights: dict[str, float], theme_key: str, theme: dict, shock: float,
                       returns: pd.DataFrame, sectors: dict[str, str | None] | None = None) -> ShockResult:
    """Run one shock on returns already in hand (no internet needed; used by the tests)."""
    return apply_shock(weights, sensitivities(weights, theme, returns, sectors), theme_key, theme, shock)


def shock_portfolio(weights: dict[str, float], theme_key: str, shock: float,
                    start: str = DEFAULT_START, end: str = DEFAULT_END) -> ShockResult:
    """Estimated portfolio move if a theme's reference basket moves by `shock` (decimal, e.g. 0.30).

    `weights` are decimals summing to 1 (cash included as "CASH").
    """
    theme = load_theme(theme_key)
    tickers = [t for t in weights if t != CASH]
    sectors = {t: intl_control(t) for t in tickers if t not in theme["controls"]}  # INTL for non-US
    extra = [s for s in sectors.values() if s]
    needed = list(dict.fromkeys(tickers + list(theme["controls"]) + extra + reference_tickers(theme)))
    try:
        returns = get_returns(needed, start, end)
    except DataError as exc:
        # One stock with too little history shouldn't sink everyone; retry without the stocks' joint join.
        returns = _returns_per_holding(tickers, theme, extra, start, end, exc)
    return shock_from_returns(weights, theme_key, theme, shock, returns, sectors)


def _returns_per_holding(tickers: list[str], theme: dict, extra: list[str], start: str, end: str,
                        first_error: Exception):
    """Fallback: fetch the theme's regressors once, then add each holding that has data on its own."""
    base_cols = list(dict.fromkeys(list(theme["controls"]) + extra + reference_tickers(theme)))
    try:
        base = get_returns(base_cols, start, end)
    except DataError:
        raise ShockError(f"Couldn't load the {theme['name']} reference data: {first_error}") from first_error
    for t in tickers:
        if t in base.columns:
            continue
        try:
            base = base.join(get_returns([t], start, end)[[t]], how="left")
        except DataError:
            continue  # that holding gets "Couldn't estimate" with a missing-returns note
    return base
