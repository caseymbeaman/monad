"""Business check: does a stock actually do business in a theme?

business_linked = the stock's FMP industry is in the theme's allowed_industries list,
                  OR the stock is one of the theme's named companies (a Tier 1 reference or a Tier 2 name).
Way 2 uses it as a second key for "want": a price link alone isn't enough.
"""

from __future__ import annotations


def named_companies(theme: dict) -> set[str]:
    refs = {r["ticker"] for g in ("High", "Moderate") for r in theme["references"].get(g, [])}
    return refs | {d["ticker"] for d in theme.get("direct_classification", [])}


def business_linked(ticker: str, industry: str | None, theme: dict) -> bool:
    return ticker in named_companies(theme) or (industry or "") in set(theme.get("allowed_industries", []))
