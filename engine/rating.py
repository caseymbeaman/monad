"""Final rating: combines the business link, the revenue share and the regression (a layer on top; the
regression itself is unchanged).

    High           business-linked AND (revenue >= 40% OR regression High)
    Moderate       business-linked AND (revenue 5-40% OR regression High/Moderate)
    Business only  business-linked, but regression Limited / Limited (lower confidence) / Not determined and revenue
                   missing or under 5%
    Market-driven  regression High/Moderate but NOT business-linked (a caution: the price moves with the theme's
                   companies, but it isn't in the theme's business)
    Not exposed    none of the above

Tier 1 references and Tier 2 names keep their listed tier (High or Moderate).
"""

from __future__ import annotations

HIGH, MODERATE = "High", "Moderate"
BUSINESS_ONLY, MARKET_DRIVEN, NOT_EXPOSED = "Business only", "Market-driven", "Not exposed"
RATINGS = [HIGH, MODERATE, BUSINESS_ONLY, MARKET_DRIVEN, NOT_EXPOSED]
EXPOSED = {HIGH, MODERATE}


def final_rating(business_linked: bool, revenue_pct: float | None, regression_tier: str,
                 listed: bool = False) -> str:
    """`listed` = a Tier 1 reference or Tier 2 name for this theme: its listed tier is kept."""
    if listed and regression_tier in EXPOSED:
        return regression_tier
    reg_hm = regression_tier in EXPOSED
    rev = revenue_pct if revenue_pct is not None else None
    if business_linked:
        if (rev is not None and rev >= 40) or regression_tier == HIGH:
            return HIGH
        if (rev is not None and rev >= 5) or reg_hm:
            return MODERATE
        return BUSINESS_ONLY
    return MARKET_DRIVEN if reg_hm else NOT_EXPOSED


def rating_sentence(ticker: str, rating: str, theme_name: str, plain: str | None = None,
                    revenue_pct: float | None = None) -> str:
    peers = plain or f"{theme_name} companies"
    rev = f" About {revenue_pct:.0f}% of its revenue is {theme_name}." if revenue_pct is not None and revenue_pct >= 5 else ""
    return {
        HIGH: f"{ticker} is strongly exposed to {theme_name}: it's in the business and moves with {peers}.{rev}",
        MODERATE: f"{ticker} is partly exposed to {theme_name}: it's in the business.{rev}",
        BUSINESS_ONLY: f"{ticker} is in a {theme_name} business, but its price doesn't clearly move with {peers}.",
        MARKET_DRIVEN: f"Caution: {ticker}'s price moves with {peers}, but it isn't a {theme_name} business.",
        NOT_EXPOSED: f"{ticker} isn't exposed to {theme_name}.",
    }[rating]
