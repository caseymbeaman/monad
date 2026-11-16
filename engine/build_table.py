"""Build the exposure table: every universe stock scored on every theme.

Run:  python -m engine.build_table        -> data/exposure_table.parquet

Uses engine/exposure.py (batch scoring that matches run_screen exactly). Prices must already be downloaded
(python -m engine.fetch_prices); anything missing is fetched on the fly.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from engine.exposure import PriceStore, score_theme
from engine.theme_loader import load_all
from engine.universe import load_universe

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "data" / "exposure_table.parquet"


def build_table() -> tuple[pd.DataFrame, float]:
    t0 = time.time()
    uni = load_universe()
    meta = {r["ticker"]: r for r in uni}
    tickers = [r["ticker"] for r in uni]
    store = PriceStore()
    rows = []
    for key, theme in load_all().items():
        t1 = time.time()
        rows += score_theme(theme, tickers, meta, store)
        print(f"  {key:14} scored in {time.time() - t1:5.1f}s", flush=True)
    df = pd.DataFrame(rows)
    return df, time.time() - t0


def load_table() -> pd.DataFrame:
    if not TABLE.exists():
        raise FileNotFoundError("data/exposure_table.parquet is missing. Run: python -m engine.build_table")
    return pd.read_parquet(TABLE)


def main():
    df, secs = build_table()
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(TABLE, index=False)
    paths = df["path"].value_counts().to_dict()
    print(f"Wrote {len(df)} rows ({df['ticker'].nunique()} stocks x {df['theme'].nunique()} themes) in {secs:.1f}s. "
          f"Paths: {paths}")


if __name__ == "__main__":
    main()
