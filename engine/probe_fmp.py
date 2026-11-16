"""Check which FMP endpoints work on your plan.

Run:  python -m engine.probe_fmp
Calls each endpoint this project needs for NVDA and XOM and prints a plain summary.
Answers are cached in data/cache/fmp/, so running it again is free. The key is never printed.
"""

from datetime import date, timedelta

from engine import fmp


def _describe(name, data):
    """One short line saying what came back."""
    if not data:
        return "worked, but returned no data"
    rows = data if isinstance(data, list) else [data]
    first = rows[0] if isinstance(rows[0], dict) else {}
    if name == "profile":
        return f"{first.get('companyName')} | sector {first.get('sector')} | industry {first.get('industry')}"
    if name == "revenue-product-segmentation":
        seg = first.get("data") or {}
        return f"{len(rows)} fiscal years; latest FY{first.get('fiscalYear')}: {', '.join(list(seg)[:4])}"
    if name == "income-statement":
        years = [str(r.get("fiscalYear") or r.get("date", "")[:4]) for r in rows]
        return f"{len(rows)} years ({', '.join(years)}); revenue {first.get('revenue'):,}"
    if name == "company-screener":
        return f"{len(rows)} companies, e.g. {', '.join(r.get('symbol', '?') for r in rows[:5])}"
    if name == "dividend-adjusted prices":
        dates = sorted(r.get("date") for r in rows)
        cols = sorted(k for k in first if k not in ("symbol", "date"))
        return f"{len(rows)} trading days, {dates[0]} to {dates[-1]}; columns: {', '.join(cols)}"
    return f"{len(rows)} rows"


def main():
    end = date.today()
    start = end - timedelta(days=730)
    results = []
    for sym in ("NVDA", "XOM"):
        industry = None
        checks = [
            ("profile", lambda s=sym: fmp.profile(s)),
            ("revenue-product-segmentation", lambda s=sym: fmp.revenue_product_segments(s)),
            ("income-statement", lambda s=sym: fmp.income_statement(s)),
            # Reads `industry` when called, i.e. after the profile check above has set it.
            ("company-screener", lambda: fmp.company_screener(industry=industry, limit=10)),  # noqa: B023
            ("dividend-adjusted prices", lambda s=sym: fmp.dividend_adjusted_prices(s, start.isoformat(), end.isoformat())),
        ]
        for name, call in checks:
            try:
                data = call()
                status, detail = "OK", _describe(name, data)
                if name == "profile" and data:
                    industry = data[0].get("industry")  # screener test uses the same industry
            except fmp.FMPPlanError as e:
                status, detail = "NOT ON PLAN", str(e)
            except fmp.FMPError as e:
                status, detail = "ERROR", str(e)
            results.append((sym, name, status, detail))
            print(f"{sym:5} {name:30} {status:12} {detail}")
    return results


if __name__ == "__main__":
    main()
