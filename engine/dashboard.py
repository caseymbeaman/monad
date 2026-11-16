"""Data helpers for the Streamlit dashboard (app.py). No Streamlit in here, so it's all testable.

- prefs_from_choices: the Want / Don't care / Avoid radio buttons -> builder preferences.
- tier_matrix + heatmap_figure: every holding x every theme, colored by tier.
- audit_rows + group_table: the full audit trail behind one tier (method, betas, p-values, thresholds).
- reshock: re-run a theme shock at a new size instantly, from betas already estimated.
- mandate_check: would adding a stock break the fund's rules? (Off-chain preview of the contract's
  check, used when no chain is set up, with the same wording, e.g. "Mandate: Oil exposure too high".)
- chain_facts: what the chat should know about the launched fund.
- Way 1 helpers: parse typed holdings, read a run_screen report, the per-theme fingerprint rows.
"""

from __future__ import annotations

import pandas as pd

from engine import shocks
from engine.regression import HIGH, LIMITED, LIMITED_LOW, MODERATE, NOT_DETERMINED

CHOICES = ("Want", "Don't care", "Avoid")
NOT_SCREENED = "Not screened"
TIER_ORDER = [HIGH, MODERATE, LIMITED, LIMITED_LOW, NOT_DETERMINED, NOT_SCREENED]
TIER_SHORT = {HIGH: "High", MODERATE: "Mod", LIMITED: "Ltd", LIMITED_LOW: "Ltd*",
              NOT_DETERMINED: "?", NOT_SCREENED: "-"}
# Strong blue = strong theme link, pale = little link, amber = the data can't tell.
TIER_COLOR = {HIGH: "#1e40af", MODERATE: "#60a5fa", LIMITED: "#e5e7eb", LIMITED_LOW: "#f3f4f6",
              NOT_DETERMINED: "#fbbf24", NOT_SCREENED: "#ffffff"}
TIER_MEANING = {
    HIGH: "moves strongly with the theme",
    MODERATE: "moves with the theme",
    LIMITED: "doesn't rise with this theme",
    LIMITED_LOW: "little sign of a link, but the data can't fully rule one out",
    NOT_DETERMINED: "the data can't tell (not the same as zero)",
    NOT_SCREENED: "not screened",
}
CASH = "CASH"


# ---------------------------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------------------------

def prefs_from_choices(choices: dict[str, str]) -> dict[str, str]:
    """{"ai": "Want", "oil": "Avoid", "gold": "Don't care"} -> {"ai": "want", "oil": "avoid"}."""
    bad = {k: v for k, v in choices.items() if v not in CHOICES}
    if bad:
        raise ValueError(f"Unknown choice(s): {bad}")
    return {k: v.lower() for k, v in choices.items() if v != "Don't care"}


def holdings_from_build(build: dict) -> dict[str, float]:
    """{ticker: weight %} from a builder result, cash included, zero weights dropped."""
    return {h["ticker"]: float(h["weight_pct"]) for h in build.get("holdings", []) if h["weight_pct"] > 0}


# ---------------------------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------------------------

def tier_matrix(table: dict[str, dict[str, dict]], tickers: list[str], themes: dict[str, dict]) -> pd.DataFrame:
    """Rows = holdings (cash skipped), columns = theme names, cells = tier text."""
    rows = {}
    for t in tickers:
        if t == CASH:
            continue
        results = table.get(t, {})
        rows[t] = {th["name"]: results.get(k, {}).get("tier", NOT_SCREENED) for k, th in themes.items()}
    return pd.DataFrame.from_dict(rows, orient="index", columns=[th["name"] for th in themes.values()])


def heatmap_figure(matrix: pd.DataFrame, weights: dict[str, float] | None = None):
    """Plotly heatmap of a tier matrix: one color per tier, short tier label in each cell."""
    import plotly.graph_objects as go

    codes = matrix.map(lambda tier: TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER) - 1)
    n = len(TIER_ORDER)
    scale = []
    for i, tier in enumerate(TIER_ORDER):  # discrete colors: each code gets a flat band
        scale += [[i / n, TIER_COLOR[tier]], [(i + 1) / n, TIER_COLOR[tier]]]
    labels = [f"{t} ({weights[t]:.1f}%)" if weights and t in weights else t for t in matrix.index]
    hover = matrix.map(lambda tier: TIER_MEANING.get(tier, tier))
    fig = go.Figure(go.Heatmap(
        z=codes.to_numpy(), x=list(matrix.columns), y=labels, zmin=0, zmax=n, colorscale=scale,
        showscale=False, text=matrix.map(lambda tier: TIER_SHORT.get(tier, tier)).to_numpy(),
        texttemplate="%{text}", customdata=hover.to_numpy(), xgap=2, ygap=2,
        hovertemplate="<b>%{y}</b> / %{x}<br>%{customdata}<extra></extra>",
    ))
    fig.update_layout(height=max(260, 34 * len(matrix) + 120), template="plotly_white",
                      margin={"t": 30, "l": 10, "r": 10, "b": 10},
                      xaxis={"side": "top", "tickangle": -30}, yaxis={"autorange": "reversed"})
    return fig


# ---------------------------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------------------------

def audit_rows(result: dict) -> list[tuple[str, str]]:
    """(label, value) lines explaining how one tier was decided."""
    rows = [("Tier", result.get("tier", NOT_SCREENED)), ("In plain English", result.get("sentence", "")),
            ("Method", result.get("method", ""))]
    if result.get("evidence"):
        rows.append(("Evidence", str(result["evidence"])))
    if result.get("n_obs"):
        rows.append(("Trading days used", str(result["n_obs"])))
    if result.get("r_squared") is not None:
        rows.append(("Share of daily moves explained (R²)", f"{result['r_squared']:.2f}"))
    if result.get("controls"):
        rows.append(("Market and style controls", ", ".join(result["controls"])))
    if result.get("sector_control"):
        rows.append(("Sector control", result["sector_control"]))
    if result.get("p_threshold") is not None:
        rows.append(("Significance threshold (one-sided p)", f"{result['p_threshold']:.4f}"))
    etf = result.get("etf_check")
    if etf:
        rows.append(("Theme ETF check", (f"beta {etf.get('beta'):+.3f} on {etf.get('etf')}, "
                                         f"p = {etf.get('p'):.4f}: {'pass' if etf.get('pass') else 'no'}")))
    if result.get("error"):
        rows.append(("Problem", result["error"]))
    return rows


def group_table(result: dict) -> pd.DataFrame | None:
    """One row per reference group: beta sum, SE, p-value, 95% upper bound, eligible."""
    groups = result.get("groups") or {}
    if not groups:
        return None
    rows = []
    for name, g in groups.items():
        rows.append({"Group": name, "Reference companies": ", ".join(g.get("names", [])),
                     "Beta sum": round(g["beta_sum"], 3), "Std. error": round(g["se"], 3),
                     "One-sided p": round(g["p_one_sided"], 4), "Upper bound (95%)": round(g["upper_95"], 3),
                     "Eligible": "yes" if g.get("eligible") else "no"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# Shocks
# ---------------------------------------------------------------------------------------------

def reshock(shock_result: dict, theme: dict, size: float) -> shocks.ShockResult:
    """The same shock at a new size (decimal), reusing the betas already estimated. Instant."""
    weights = {h["ticker"]: h["weight"] for h in shock_result["holdings"]}
    sens = {h["ticker"]: {"beta": h["beta"], "se": h["se"], "note": h["note"]} for h in shock_result["holdings"]}
    return shocks.apply_shock(weights, sens, shock_result["theme"], theme, size)


# ---------------------------------------------------------------------------------------------
# Mandate preview and chain status
# ---------------------------------------------------------------------------------------------

WANT_OK = {HIGH, MODERATE}
AVOID_OK = {LIMITED, LIMITED_LOW}


def mandate_check(ticker: str, prefs: dict[str, str], tiers: dict[str, str], themes: dict[str, dict]):
    """(allowed, reasons) for adding `ticker` to a fund with these preferences.

    `tiers` = {theme_key: tier} for the ticker. Same rules as the builder: a "want" theme needs High
    or Moderate; an "avoid" theme needs Limited or Limited (lower confidence).
    """
    reasons = []
    for key, choice in prefs.items():
        name = themes[key]["name"]
        tier = tiers.get(key, NOT_SCREENED)
        if choice == "avoid":
            if tier in WANT_OK:
                reasons.append(f"Mandate: {name} exposure too high ({ticker} is {tier} for {name}).")
            elif tier not in AVOID_OK:
                reasons.append(f"Mandate: {name} exposure can't be ruled out ({ticker}: {tier}).")
        elif tier not in WANT_OK:
            reasons.append(f"Mandate: not enough {name} exposure ({ticker} is {tier} for {name}).")
    return (not reasons), reasons


def chain_facts(fund: dict | None = None, deposit: dict | None = None) -> dict:
    """What the chat (and the page) should know about the on-chain fund."""
    if not fund:
        return {"launched": False,
                "note": "This fund isn't launched on-chain yet. Launch it from the 'Launch on Monad' tab."}
    out = {"launched": True, "network": fund.get("network"), "name": fund.get("name"),
           "symbol": fund.get("symbol"), "address": fund.get("address"),
           "mandate": [("Want " if r["kind"] == 0 else "Avoid ") + r["label"] for r in fund.get("rules", [])]}
    if deposit:
        out["last_deposit"] = {"shares": deposit.get("shares"), "fund_value_usd": deposit.get("nav_usd"),
                               "value_per_share_usd": deposit.get("nav_per_share_usd")}
    return out


# ---------------------------------------------------------------------------------------------
# Way 1 ("Check my portfolio") and the builder's funnel
# ---------------------------------------------------------------------------------------------

def parse_holdings_text(text: str) -> dict[str, float]:
    """"NVDA:30, XOM:20 cash:50" (spaces, commas or new lines) -> {"NVDA": 30.0, "XOM": 20.0, "CASH": 50.0}."""
    from engine.screen import parse_holdings

    items = [x for x in text.replace(",", " ").split() if x.strip()]
    return parse_holdings(items)


def results_from_screen(report: dict) -> dict[str, dict[str, dict]]:
    """{ticker: {theme_key: result}} from a run_screen report (cash left out)."""
    return {h["ticker"]: h["results"] for h in report.get("holdings", []) if h["ticker"] != CASH}


def holdings_from_screen(report: dict) -> dict[str, float]:
    return {h["ticker"]: float(h["weight_pct"]) for h in report.get("holdings", []) if h["weight_pct"] > 0}


def fingerprint_rows(report: dict) -> list[dict]:
    """One row per theme: share of the portfolio in High or Moderate stocks, and the plain sentence."""
    rows = [{"Theme": f["name"], "High or Moderate": f"{f['high_moderate_pct']:.0f}%",
             "The data can't tell": f"{f['by_tier_pct'].get(NOT_DETERMINED, 0):.0f}%",
             "In plain English": f["sentence"], "_sort": f["high_moderate_pct"]}
            for f in report.get("fingerprint", {}).values()]
    rows.sort(key=lambda r: -r["_sort"])
    return [{k: v for k, v in r.items() if k != "_sort"} for r in rows]


def screen_errors(report: dict) -> list[str]:
    """Stocks that couldn't be screened for some theme, with the reason (first one per stock)."""
    out = []
    for ticker, results in results_from_screen(report).items():
        for r in results.values():
            if r.get("error"):
                out.append(f"{ticker}: {r['error']}")
                break
    return out


def funnel_rows(build: dict) -> list[dict]:
    """The builder's funnel: how many stocks are left after each rule."""
    return [{"Step": f["step"], "Stocks left": f["left"]} for f in build.get("funnel", [])]
