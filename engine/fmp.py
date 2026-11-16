"""Financial Modeling Prep (FMP) client for the stable API.

What it does, in plain terms:
- Reads your FMP key from the .env file in the project folder (FMP_API_KEY=...).
- Sends a request to https://financialmodelingprep.com/stable/<endpoint>.
- Saves every successful answer as a JSON file in data/cache/fmp/, stamped with the time it was
  fetched. Asking the same question again reads the saved file instead of using up API calls.
  The saved files are also an audit trail: they show exactly what data the engine saw.

Safety: the key is never written to the cache, to logs, or into error messages.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://financialmodelingprep.com/stable"
CACHE_DIR = ROOT / "data" / "cache" / "fmp"
TIMEOUT_SECONDS = 30
MAX_RETRIES = 3


class FMPError(RuntimeError):
    """Something went wrong talking to FMP (bad answer, network trouble, etc.)."""


class FMPPlanError(FMPError):
    """FMP answered, but this endpoint or ticker isn't included in your subscription plan."""


def _api_key() -> str:
    """Load the key from .env. Raise a clear message (without the key) if it's missing."""
    load_dotenv(ROOT / ".env")
    key = os.environ.get("FMP_API_KEY", "").strip()
    if not key:
        raise FMPError("No FMP key found. Put FMP_API_KEY=your_key in the .env file in the project folder.")
    return key


def _clean_params(params: dict | None) -> dict:
    """Drop empty values and sort, so the same question always maps to the same cache file."""
    return {k: params[k] for k in sorted(params or {}) if params[k] is not None and k.lower() != "apikey"}


def cache_path(endpoint: str, params: dict | None = None) -> Path:
    """Where the answer to (endpoint, params) is saved. Readable name plus a short fingerprint."""
    clean = _clean_params(params)
    readable = "_".join([endpoint.strip("/").replace("/", "-")] + [f"{k}-{v}" for k, v in clean.items()])
    readable = "".join(c if c.isalnum() or c in "-_." else "-" for c in readable)[:120]
    digest = hashlib.sha256(json.dumps([endpoint, clean]).encode()).hexdigest()[:10]
    return CACHE_DIR / f"{readable}_{digest}.json"


def _plan_message(text: str) -> bool:
    """FMP signals 'not on your plan' in a few different ways; catch the common wordings."""
    t = text.lower()
    return any(w in t for w in ("premium", "subscription", "upgrade", "not available under", "exclusive", "restricted"))


def get(endpoint: str, params: dict | None = None, use_cache: bool = True):
    """Fetch one FMP stable endpoint and return the parsed JSON (usually a list of dicts).

    Example: get("profile", {"symbol": "NVDA"})
    Raises FMPPlanError if your plan doesn't cover it, FMPError for any other failure.
    """
    clean = _clean_params(params)
    path = cache_path(endpoint, clean)
    if use_cache and path.exists():
        return json.loads(path.read_text())["data"]

    url = f"{BASE_URL}/{endpoint.strip('/')}"
    last_problem = "unknown error"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params={**clean, "apikey": _api_key()}, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            # Don't include str(exc): it can contain the full URL, key included.
            last_problem = f"network error ({type(exc).__name__})"
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:  # rate limit or FMP server trouble: wait, retry
            last_problem = f"HTTP {resp.status_code}"
            time.sleep(2 ** attempt)
            continue

        body = resp.text[:300]
        if resp.status_code in (401, 403) and not _plan_message(body):
            raise FMPError(f"{endpoint}: FMP rejected the key (HTTP {resp.status_code}). Check FMP_API_KEY in .env.")
        if resp.status_code in (402, 403) or (resp.status_code >= 400 and _plan_message(body)):
            raise FMPPlanError(f"{endpoint}: not included in your FMP plan (HTTP {resp.status_code}).")
        if resp.status_code >= 400:
            raise FMPError(f"{endpoint}: HTTP {resp.status_code}: {body}")

        try:
            data = resp.json()
        except ValueError:
            # Some plan-restricted answers come back as plain text with HTTP 200.
            if _plan_message(body):
                raise FMPPlanError(f"{endpoint}: not included in your FMP plan.") from None
            raise FMPError(f"{endpoint}: FMP sent something that isn't JSON: {body[:120]}") from None

        if isinstance(data, dict) and ("Error Message" in data or "error" in data):
            msg = str(data.get("Error Message") or data.get("error"))
            if _plan_message(msg):
                raise FMPPlanError(f"{endpoint}: not included in your FMP plan: {msg[:150]}")
            raise FMPError(f"{endpoint}: {msg[:200]}")

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "endpoint": endpoint,
            "params": clean,  # the key is never in here
            "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "data": data,
        }
        path.write_text(json.dumps(record, indent=1))
        return data

    raise FMPError(f"{endpoint}: gave up after {MAX_RETRIES} tries ({last_problem}).")


# ---- Convenience wrappers for the endpoints this project uses ----

def profile(symbol: str):
    """Company basics: name, sector, industry, market cap, etc."""
    return get("profile", {"symbol": symbol})


def revenue_product_segments(symbol: str, period: str = "annual"):
    """Revenue broken down by product line, per fiscal year (used for theme evidence %)."""
    return get("revenue-product-segmentation", {"symbol": symbol, "period": period})


def income_statement(symbol: str, period: str = "annual", limit: int = 5):
    """Income statement lines (revenue, net interest income, etc.) for recent fiscal years."""
    return get("income-statement", {"symbol": symbol, "period": period, "limit": limit})


def company_screener(**filters):
    """List companies matching filters, e.g. company_screener(industry="Semiconductors", limit=10)."""
    return get("company-screener", filters)


def dividend_adjusted_prices(symbol: str, start: str, end: str):
    """Daily prices adjusted for dividends and splits, between start and end (YYYY-MM-DD)."""
    return get("historical-price-eod/dividend-adjusted", {"symbol": symbol, "from": start, "to": end})
