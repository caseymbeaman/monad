"""Download ~2 years of daily dividend-adjusted prices for the whole universe (resumable).

Run:  python -m engine.fetch_prices          (safe to stop and re-run; finished tickers are skipped)

Covers data/universe.csv plus every series the regressions need (market and style ETFs, theme references,
control companies, ground-truth ETFs). Each ticker is one FMP request (FMP's bulk end-of-day file is one
snapshot per date and isn't dividend-adjusted across the whole history, so it can't be used here), cached
in data/cache/fmp/ like every other FMP call; Yahoo is the fallback.
Progress is written to data/cache/prices_progress.json after every ticker.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from engine import data, fmp
from engine.controls import SPREADS
from engine.theme_loader import load_all
from engine.universe import load_universe

ROOT = Path(__file__).resolve().parent.parent
PROGRESS = ROOT / "data" / "cache" / "prices_progress.json"
PAUSE_SECONDS = 0.25  # stays well under FMP's per-minute limit


def tickers_needed() -> list[str]:
    names = [r["ticker"] for r in load_universe()]
    names += ["SPY", "TLT"] + [leg for legs in SPREADS.values() for leg in legs]
    for th in load_all().values():
        names += [r["ticker"] for g in ("High", "Moderate") for r in th["references"].get(g, [])]
        names += [th["control"]["ticker"]] + ([th["ground_truth"]] if th.get("ground_truth") else [])
        names += [d["ticker"] for d in th.get("direct_classification", [])]
    return list(dict.fromkeys(names))


def _load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text())
    return {"done": {}, "failed": {}}


def main():
    todo = tickers_needed()
    prog = _load_progress()
    start = time.time()
    for i, t in enumerate(todo, 1):
        if t in prog["done"]:
            continue
        cached = fmp.cache_path("historical-price-eod/dividend-adjusted",
                                {"symbol": t, "from": data.DEFAULT_START, "to": data.DEFAULT_END}).exists()
        s = data._from_fmp(t, data.DEFAULT_START, data.DEFAULT_END)
        src = "FMP"
        if s is None or s.empty:
            s, src = data._from_yfinance(t, data.DEFAULT_START, data.DEFAULT_END), "yfinance"
        if s is None or s.empty:
            prog["failed"][t] = "no data from FMP or Yahoo"
        else:
            prog["done"][t] = {"source": src, "days": len(s), "first": str(s.index[0].date()), "last": str(s.index[-1].date())}
            prog["failed"].pop(t, None)
        prog["updated"] = datetime.now().isoformat(timespec="seconds")
        PROGRESS.write_text(json.dumps(prog, indent=1))
        if i % 25 == 0 or i == len(todo):
            print(f"[{i}/{len(todo)}] done {len(prog['done'])}, failed {len(prog['failed'])}, "
                  f"{time.time() - start:.0f}s elapsed", flush=True)
        if not cached:
            time.sleep(PAUSE_SECONDS)
    print(f"Finished: {len(prog['done'])} with prices, {len(prog['failed'])} failed: {sorted(prog['failed'])}", flush=True)


if __name__ == "__main__":
    main()
