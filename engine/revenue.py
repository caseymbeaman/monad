"""Revenue signal: what share of a company's revenue comes from a theme, from FMP data.

revenue_pct(ticker, theme_key) -> {"pct", "fiscal_year", "segments", "source"} or None

- Most themes: the company's latest annual FMP revenue-by-segment data. Segments whose NAME contains one of the
  theme's keywords (whole words, case-insensitive, so "AI" never matches inside "retail") count toward the
  theme; pct = matching segments / all positive segments. Same idea as the theme evidence (engine/evidence.py).
- Bank lending: net interest income / (net interest income + non-interest income) from the income statement
  (engine/evidence.nii_share), the same formula the theme's references use.
- Consumer discretionary: no reliable keywords, so always None.
- None when FMP has no segment data or no segment matches.

Revenue only feeds the final rating for stocks that are already business-linked (see engine/rating.py).
"""

from __future__ import annotations

import re
from functools import cache

from engine import evidence, fmp

THEME_KEYWORDS: dict[str, list[str] | None] = {
    "ai": ["data center", "data centre", "ai", "artificial intelligence", "accelerated computing"],
    "oil": ["crude", "crude oil", "oil and gas", "oil & gas", "upstream", "exploration and production", "oil",
            "petroleum"],
    "gold": ["gold", "silver", "precious metals", "precious metal"],
    "defense": ["defense", "defence", "government", "military", "national security", "aerospace"],
    "healthcare": ["pharmaceutical", "pharmaceuticals", "medical", "health", "healthcare", "health care",
                   "biopharma", "biopharmaceutical", "diagnostics", "life sciences", "pharmacy"],
    "metals": ["copper", "lithium"],
    "clean_energy": ["solar", "renewable", "renewables", "wind"],
    "cyber": ["security", "cybersecurity"],
    "consumer_disc": None,  # no reliable keywords
    "bank_lending": None,  # uses net interest income instead (see revenue_pct)
}


def _pattern(words: list[str]) -> re.Pattern:
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alts})(?![A-Za-z0-9])", re.IGNORECASE)


_PATTERNS = {k: _pattern(v) for k, v in THEME_KEYWORDS.items() if v}


def matching_segments(segment_names: list[str], theme_key: str) -> list[str]:
    pat = _PATTERNS.get(theme_key)
    return [s for s in segment_names if pat and pat.search(s)] if pat else []


@cache
def _latest_segments(ticker: str) -> tuple[int, tuple[tuple[str, float], ...]] | None:
    try:
        rows = fmp.revenue_product_segments(ticker)
    except fmp.FMPError:
        return None
    rows = [r for r in rows or [] if r.get("fiscalYear") is not None and r.get("data")]
    if not rows:
        return None
    r = max(rows, key=lambda r: int(r["fiscalYear"]))
    data = tuple((k, float(v)) for k, v in r["data"].items() if isinstance(v, (int, float)) and v > 0)
    return (int(r["fiscalYear"]), data) if data else None


def revenue_pct(ticker: str, theme_key: str) -> dict | None:
    if theme_key == "bank_lending":
        try:
            r = evidence.nii_share(ticker)
        except (ValueError, fmp.FMPError):
            return None
        return {"pct": r["evidence_pct"], "fiscal_year": r["fiscal_year"], "segments": [], "source": r["source"]}
    if not THEME_KEYWORDS.get(theme_key):
        return None
    latest = _latest_segments(ticker)
    if latest is None:
        return None
    fy, data = latest
    names = [k for k, _ in data]
    hits = matching_segments(names, theme_key)
    if not hits:
        return None
    total = sum(v for _, v in data)
    share = sum(v for k, v in data if k in hits)
    return {"pct": round(100 * share / total, 1), "fiscal_year": fy, "segments": hits,
            "source": f"FMP revenue-product-segmentation FY{fy}: {' + '.join(hits)} / all segments"}
