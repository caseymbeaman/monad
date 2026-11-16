"""Theme exposure regression: classifies one holding for one theme.

The method (from CLAUDE.md; don't change it without asking):
1. Regress the holding's daily return on the market controls (SPY, TLT, and VALUE = IWD minus IWF, the value-minus-growth swing)
   plus the daily returns of every High and Moderate reference company AND the theme's zero-exposure control
   company, using ordinary least squares. The control company never belongs to a High/Moderate group.
2. For each group (High, Moderate): add up that group's betas. Its standard error comes from the full
   covariance matrix, so it accounts for the reference companies moving together. One-sided test: is the
   sum above zero?
3. A group is "eligible" if its sum > 0.05 AND its one-sided p-value < 0.05 / (number of reference names,
   counting every High and Moderate reference plus the control company).
   The eligible group with the largest sum gives the tier.
4. If nothing is eligible:
   - Limited: every group's sum + 1.645 x SE is below 0.05 (we're confident it's small).
   - Limited (lower confidence): otherwise, if every group's sum is below 0.05.
   - Not determined: anything else. The data can't tell, which is NOT the same as zero.
A holding that is itself a reference, or on the theme's direct list, uses its listed tier with no regression.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

MIN_SUM = 0.05          # a group's beta sum must beat this to count as exposure
ALPHA = 0.05            # significance level before the Bonferroni split
Z_ONE_SIDED_95 = 1.645  # for the "confidently small" upper bound
GROUPS = ("High", "Moderate")

HIGH, MODERATE = "High", "Moderate"
LIMITED, LIMITED_LOW = "Limited", "Limited (lower confidence)"
NOT_DETERMINED = "Not determined"


@dataclass
class GroupStats:
    names: list[str]
    beta_sum: float
    se: float
    p_one_sided: float
    upper_95: float          # beta_sum + 1.645 x SE
    eligible: bool


@dataclass
class Result:
    ticker: str
    theme: str
    tier: str
    method: str              # "regression", "listed reference" or "direct classification"
    sentence: str
    groups: dict[str, GroupStats] = field(default_factory=dict)
    n_obs: int | None = None
    r_squared: float | None = None
    p_threshold: float | None = None
    controls: list[str] = field(default_factory=list)
    evidence: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["groups"] = {g: asdict(s) for g, s in self.groups.items()}
        return d


# ---------------------------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------------------------

def reference_names(theme: dict) -> dict[str, list[str]]:
    """{'High': [...], 'Moderate': [...]} of reference tickers (Tier 1 only)."""
    return {g: [r["ticker"] for r in theme["references"].get(g, [])] for g in GROUPS}


def regressors_needed(theme: dict, extra_control: str | None = None) -> list[str]:
    """Every price series a regression for this theme needs (besides the holding itself)."""
    refs = reference_names(theme)
    extra = [extra_control] if extra_control else []
    return list(theme["controls"]) + extra + refs[HIGH] + refs[MODERATE] + [theme["control"]["ticker"]]


def _listed(ticker: str, theme: dict):
    """If the holding is a reference or on the direct list, return its listed tier info."""
    for g in GROUPS:
        for r in theme["references"].get(g, []):
            if r["ticker"] == ticker:
                return g, "listed reference", f"{r['evidence_pct']}% {r['measures'].lower()}"
    for d in theme.get("direct_classification", []):
        if d["ticker"] == ticker:
            return d["tier"], "direct classification", d["reason"]
    return None


# ---------------------------------------------------------------------------------------------
# Decision rule (kept separate so it can be tested on its own)
# ---------------------------------------------------------------------------------------------

def decide_tier(groups: dict[str, GroupStats]) -> str:
    eligible = {g: s for g, s in groups.items() if s.eligible}
    if eligible:
        return max(eligible, key=lambda g: eligible[g].beta_sum)
    if all(s.upper_95 < MIN_SUM for s in groups.values()):
        return LIMITED
    if all(s.beta_sum < MIN_SUM for s in groups.values()):
        return LIMITED_LOW
    return NOT_DETERMINED


def sentence(ticker: str, theme_name: str, tier: str, method: str, evidence: str | None = None,
             plain: str | None = None) -> str:
    """One plain-English sentence. `plain` names the reference companies, e.g. "oil producers"."""
    peers = plain or f"{theme_name} companies"
    if method == "listed reference":
        return f"{ticker} is one of the {theme_name} reference companies ({evidence}), so it keeps its listed tier: {tier}."
    if method == "direct classification":
        return f"{ticker} is classified directly as {tier} for {theme_name}: {evidence}"
    return {
        HIGH: f"{ticker} moves strongly with {peers}, beyond what the overall market explains.",
        MODERATE: f"{ticker} moves partly with {peers}, beyond what the overall market explains.",
        LIMITED: f"{ticker} doesn't rise with this theme.",
        LIMITED_LOW: (f"{ticker} shows little sign of rising with {theme_name}, "
                      "but the data isn't precise enough to rule out a small link."),
        NOT_DETERMINED: (f"The data can't tell whether {ticker} is exposed to {theme_name}. "
                         "That is not the same as zero exposure."),
    }[tier]


# ---------------------------------------------------------------------------------------------
# The regression
# ---------------------------------------------------------------------------------------------

def group_stats(fit, names: list[str], n_refs: int) -> GroupStats:
    """Sum of a group's betas, its standard error from the full covariance matrix, one-sided p-value."""
    params = fit.params
    cov = fit.cov_params()
    w = pd.Series(0.0, index=params.index)
    w[names] = 1.0
    beta_sum = float(w @ params)
    se = float(np.sqrt(w @ cov @ w))
    t = beta_sum / se if se > 0 else np.inf
    p = float(stats.t.sf(t, fit.df_resid))  # one-sided: P(T > t)
    return GroupStats(names=list(names), beta_sum=beta_sum, se=se, p_one_sided=p,
                      upper_95=beta_sum + Z_ONE_SIDED_95 * se,
                      eligible=bool(beta_sum > MIN_SUM and p < ALPHA / n_refs))


def classify(ticker: str, theme: dict, returns: pd.DataFrame, extra_control: str | None = None) -> Result:
    """Classify one holding for one theme. `returns` must contain the holding and every regressor.

    `extra_control` (e.g. "INTL" for a non-US stock) adds one more control for this holding only.
    Like all controls, it is never in a group and never counts in the Bonferroni denominator.
    """
    ticker = ticker.upper()
    name = theme["name"]
    plain = theme.get("plain")

    listed = _listed(ticker, theme)
    if listed:
        tier, method, evidence = listed
        return Result(ticker, name, tier, method, sentence(ticker, name, tier, method, evidence, plain), evidence=evidence)

    controls = list(theme["controls"]) + ([extra_control] if extra_control else [])
    if ticker in controls:
        raise ValueError(f"{ticker} is one of the market controls for {name}; its exposure beyond itself can't be measured.")

    refs = reference_names(theme)
    control_co = theme["control"]["ticker"]
    # The control company is a regressor too (never in a group). If the holding IS the control, it can't
    # also be on the right-hand side, so it's left out of that one regression.
    extra = [control_co] if control_co != ticker else []
    regressors = controls + refs[HIGH] + refs[MODERATE] + extra
    needed = [ticker] + regressors
    missing = [c for c in needed if c not in returns.columns]
    if missing:
        raise ValueError(f"Missing returns for: {', '.join(missing)}")
    data = returns[needed].dropna()
    n_refs = len(refs[HIGH]) + len(refs[MODERATE]) + len(extra)  # Bonferroni count includes the control
    if len(data) < len(regressors) + 30:
        raise ValueError(f"{ticker}: only {len(data)} days of shared data for {len(regressors)} regressors; need more.")

    fit = sm.OLS(data[ticker], sm.add_constant(data[regressors])).fit()
    groups = {g: group_stats(fit, refs[g], n_refs) for g in GROUPS if refs[g]}
    tier = decide_tier(groups)
    return Result(ticker, name, tier, "regression", sentence(ticker, name, tier, "regression", plain=plain),
                  groups=groups, n_obs=int(fit.nobs), r_squared=float(fit.rsquared),
                  p_threshold=ALPHA / n_refs, controls=controls)
