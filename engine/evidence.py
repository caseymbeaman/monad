"""Turn FMP filings data into a theme evidence percentage.

Two kinds of evidence, both read straight from FMP (never estimated):
- segment_share: what % of reported segment revenue comes from the named segments,
  e.g. NVDA "Data Center" / sum of all NVDA product segments.
- statement_ratio: one income-statement line divided by another,
  e.g. a bank's netInterestIncome / revenue.

Each result says the fiscal year and the exact FMP source, so a theme YAML can cite it.
"""

from __future__ import annotations

from engine import fmp


def _latest(rows: list[dict], fiscal_year: int | None):
    """Pick the requested fiscal year, or the most recent one."""
    rows = [r for r in rows if r.get("fiscalYear") is not None]
    if not rows:
        return None
    if fiscal_year is not None:
        rows = [r for r in rows if int(r["fiscalYear"]) == int(fiscal_year)]
        return rows[0] if rows else None
    return max(rows, key=lambda r: int(r["fiscalYear"]))


def segment_share(ticker: str, segments: list[str], fiscal_year: int | None = None) -> dict:
    """Share of segment revenue from the named segments (names matched case-insensitively).

    Denominator = sum of all positive reported product segments for that year.
    """
    row = _latest(fmp.revenue_product_segments(ticker), fiscal_year)
    if row is None:
        raise ValueError(f"{ticker}: no product-segment data from FMP for that year")
    data = {k: v for k, v in (row.get("data") or {}).items() if isinstance(v, (int, float)) and v > 0}
    wanted = {s.lower() for s in segments}
    matched = {k: v for k, v in data.items() if k.lower() in wanted}
    missing = wanted - {k.lower() for k in matched}
    if missing:
        raise ValueError(f"{ticker} FY{row['fiscalYear']}: segment(s) not found: {sorted(missing)}. Available: {sorted(data)}")
    total = sum(data.values())
    return {
        "ticker": ticker,
        "evidence_pct": round(100 * sum(matched.values()) / total, 1),
        "fiscal_year": int(row["fiscalYear"]),
        "source": f"FMP revenue-product-segmentation FY{row['fiscalYear']}: "
                  f"{' + '.join(sorted(matched))} / sum of all product segments",
        "segments": data,
    }


def statement_ratio(ticker: str, numerator: str, denominator: str = "revenue", fiscal_year: int | None = None) -> dict:
    """numerator / denominator from the FMP annual income statement."""
    row = _latest(fmp.income_statement(ticker), fiscal_year)
    if row is None:
        raise ValueError(f"{ticker}: no income-statement data from FMP for that year")
    num, den = row.get(numerator), row.get(denominator)
    if not isinstance(num, (int, float)) or not isinstance(den, (int, float)) or den <= 0:
        raise ValueError(f"{ticker} FY{row['fiscalYear']}: can't compute {numerator}/{denominator} ({num}/{den})")
    return {
        "ticker": ticker,
        "evidence_pct": round(100 * num / den, 1),
        "fiscal_year": int(row["fiscalYear"]),
        "source": f"FMP income-statement FY{row['fiscalYear']}: {numerator} / {denominator}",
    }


def show_segments(ticker: str) -> str:
    """Quick look at a company's latest segments with each one's share (for picking references)."""
    row = _latest(fmp.revenue_product_segments(ticker), None)
    if row is None:
        return f"{ticker}: no segment data"
    data = {k: v for k, v in (row.get("data") or {}).items() if isinstance(v, (int, float)) and v > 0}
    total = sum(data.values()) or 1
    parts = ", ".join(f"{k} {100 * v / total:.0f}%" for k, v in sorted(data.items(), key=lambda kv: -kv[1]))
    return f"{ticker} FY{row['fiscalYear']}: {parts}"


def nii_share(ticker: str, fiscal_year: int | None = None) -> dict:
    """Bank lending share: net interest income / (net interest income + non-interest income).

    FMP's income statement has no non-interest-income line. For banks, FMP's `revenue` is interest income
    plus non-interest income, so non-interest income = revenue - interestIncome.
    """
    row = _latest(fmp.income_statement(ticker), fiscal_year)
    if row is None:
        raise ValueError(f"{ticker}: no income-statement data from FMP for that year")
    nii, rev, ii = row.get("netInterestIncome"), row.get("revenue"), row.get("interestIncome")
    if not all(isinstance(v, (int, float)) for v in (nii, rev, ii)):
        raise ValueError(f"{ticker} FY{row['fiscalYear']}: missing netInterestIncome / revenue / interestIncome")
    non_ii = rev - ii
    if non_ii < 0 or nii + non_ii <= 0:
        raise ValueError(f"{ticker} FY{row['fiscalYear']}: can't compute NII share ({nii}, {rev}, {ii})")
    return {
        "ticker": ticker,
        "evidence_pct": round(100 * nii / (nii + non_ii), 1),
        "fiscal_year": int(row["fiscalYear"]),
        "source": (f"FMP income-statement FY{row['fiscalYear']}: netInterestIncome / (netInterestIncome + "
                   "(revenue - interestIncome))"),
    }
