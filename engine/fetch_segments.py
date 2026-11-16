"""Download FMP revenue-by-segment data for the whole universe (resumable; every answer is cached).

Run:  python -m engine.fetch_segments

Used by engine/revenue.py to work out each stock's theme share of revenue. Re-running skips stocks already cached.
"""

from __future__ import annotations

import time

from engine import fmp
from engine.universe import load_universe

PAUSE_SECONDS = 0.25


def main():
    tickers = [r["ticker"] for r in load_universe()]
    done = failed = 0
    start = time.time()
    for i, t in enumerate(tickers, 1):
        cached = fmp.cache_path("revenue-product-segmentation", {"symbol": t, "period": "annual"}).exists()
        try:
            fmp.revenue_product_segments(t)
            done += 1
        except fmp.FMPError:
            failed += 1
        if not cached:
            time.sleep(PAUSE_SECONDS)
        if i % 50 == 0 or i == len(tickers):
            print(f"[{i}/{len(tickers)}] ok {done}, failed {failed}, {time.time() - start:.0f}s", flush=True)


if __name__ == "__main__":
    main()
