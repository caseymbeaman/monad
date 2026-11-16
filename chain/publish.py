"""Publish the engine's results to Monad: list the test stocks, post each stock's tier per theme, post prices.

    python -m chain.publish                         # the latest built fund (results/build_latest.json)
    python -m chain.publish --extra XOM             # ...plus XOM, so the "try adding XOM" demo has data
    python -m chain.publish --report results/screen_latest.json    # a screened portfolio instead
    python -m chain.publish --dry-run               # show what would be posted; sends nothing
    python -m chain.publish --replay 20 --interval 3   # weekend demo: replay the last 20 trading days of
                                                       # real prices, one every 3 seconds, so NAV moves

What gets posted, per stock:
- its tier for each theme (High / Moderate / Limited / Limited (lower confidence) / Not determined)
- two fingerprints (hashes) so anyone can check the on-chain record matches the engine's output:
    baselineHash = which data the regression used (stock, theme, date window, number of days, regressors)
    statsHash    = what the regression found (tier, method, each group's sum / SE / p-value / upper bound)
  `hashes_for()` below recomputes both from a result, which is what the dashboard's audit trail uses.
- its latest price, in dollars with 8 decimals.
Only what changed is sent, so re-running is cheap.

Settings (in .env, never committed):
    MONAD_RPC_URL      e.g. https://testnet-rpc.monad.xyz
    FACTORY_ADDRESS    printed by contracts/script/Deploy.s.sol (the exchange and oracle are found from it)
    DEPLOYER_KEYSTORE  optional: name of the Foundry keystore holding the deployer wallet (default "deployer")
The keystore password is asked for when the script runs. It is never stored or printed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from web3 import Web3

from chain.abi import EXCHANGE_ABI, FACTORY_ABI, ORACLE_ABI

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD = ROOT / "results" / "build_latest.json"
KEYSTORE_DIR = Path.home() / ".foundry" / "keystores"
CASH = "CASH"
PRICE_DECIMALS = 8
BATCH = 40  # exposures per transaction
GAS_HEADROOM = 1.2  # send 20% more gas than estimated (see Publisher._send)
# Gas estimates run against the latest block's timestamp. If the previous post was in that block, the
# stored timestamp looks "unchanged" to the estimate (a cheap storage write) but changes when mined (a
# full write): exactly 2,800 gas more per item. Measured on anvil: 40 re-posted prices came up 112,000
# short. So batch posts add this much per item on top of the margin.
GAS_PER_TIMESTAMPED_ITEM = 3_000

# Must match the Tier enum in contracts/src/ExposureOracle.sol (0 = Unposted, never sent).
TIER_CODES = {
    "High": 1,
    "Moderate": 2,
    "Limited": 3,
    "Limited (lower confidence)": 4,
    "Not determined": 5,
}


class PublishError(RuntimeError):
    """Something about the inputs, settings or chain state stops us publishing. The message says what."""


# ---------------------------------------------------------------------------------------------
# Encoding: turning engine values into what the contracts store
# ---------------------------------------------------------------------------------------------

def to_bytes32(text: str) -> bytes:
    """'NVDA' -> 32 bytes, the same value Solidity gets from bytes32("NVDA")."""
    raw = text.encode("ascii", errors="strict") if text.isascii() else b""
    if not 0 < len(raw) <= 32:
        raise PublishError(f"'{text}' must be 1-32 plain ASCII characters to be used as an on-chain key")
    return raw.ljust(32, b"\0")


def price_to_chain(price) -> int:
    """187.42 -> 18742000000 (dollars with 8 decimals), rounded to the nearest unit, no float drift."""
    try:
        value = Decimal(str(price))
    except ArithmeticError:
        raise PublishError(f"price '{price}' isn't a number") from None
    if not value.is_finite() or value <= 0:
        raise PublishError(f"price '{price}' must be a positive number")
    return int((value * 10**PRICE_DECIMALS).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _canonical(obj) -> bytes:
    """One fixed way to write a record as text, so the same record always gives the same hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def hashes_for(ticker: str, theme_key: str, result: dict, window: dict) -> tuple[bytes, bytes]:
    """(baselineHash, statsHash) for one engine result. See the module docstring for what each covers."""
    groups = result.get("groups") or {}
    baseline = {
        "ticker": ticker,
        "theme": theme_key,
        "window_start": window.get("start"),
        "window_end": window.get("end"),
        "n_obs": result.get("n_obs"),
        "controls": result.get("controls") or [],
        "references": {g: s.get("names", []) for g, s in groups.items()},
    }
    stats = {
        "tier": result["tier"],
        "method": result.get("method"),
        "p_threshold": result.get("p_threshold"),
        "r_squared": result.get("r_squared"),
        "groups": {
            g: {k: s.get(k) for k in ("beta_sum", "se", "p_one_sided", "upper_95", "eligible")}
            for g, s in groups.items()
        },
    }
    return bytes(Web3.keccak(_canonical(baseline))), bytes(Web3.keccak(_canonical(stats)))


def exposure_rows(results: dict[str, dict[str, dict]], window: dict) -> list[dict]:
    """Flatten {ticker: {theme_key: result}} into one row per (stock, theme), ready to post."""
    rows = []
    for ticker in sorted(results):
        for theme_key in sorted(results[ticker]):
            result = results[ticker][theme_key]
            tier = result.get("tier")
            if tier not in TIER_CODES:
                raise PublishError(f"{ticker} / {theme_key}: unknown tier '{tier}'")
            baseline, stats = hashes_for(ticker, theme_key, result, window)
            rows.append({"ticker": ticker, "theme": theme_key, "tier": tier, "code": TIER_CODES[tier],
                         "baseline_hash": baseline, "stats_hash": stats})
    return rows


# ---------------------------------------------------------------------------------------------
# Inputs: where the results and prices come from
# ---------------------------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    if not path.exists():
        raise PublishError(f"{path} doesn't exist. Run the builder or the screen first.")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PublishError(f"{path} isn't valid JSON: {exc}") from None


def results_from_report(report: dict) -> tuple[dict[str, dict[str, dict]], dict]:
    """Pull {ticker: {theme_key: result}} and the date window out of a screen report (engine/screen.py)."""
    try:
        results = {h["ticker"]: h["results"] for h in report["holdings"] if h["ticker"] != CASH}
        window = report["window"]
    except (KeyError, TypeError):
        raise PublishError("That file doesn't look like a screen report (results/screen_latest.json).") from None
    if not results:
        raise PublishError("The screen report has no stocks in it (only cash).")
    return results, window


def results_from_build(build: dict, extra: list[str], themes: list[str] | None) -> tuple[dict, dict]:
    """Results for a built fund's stocks (plus any extras), taken from the builder's universe screen."""
    # Imported here so --report and --dry-run work without the engine's data.
    from engine import builder
    from engine.data import DEFAULT_END, DEFAULT_START

    try:
        tickers = [h["ticker"] for h in build["holdings"] if h["ticker"] != CASH]
        theme_keys = themes or list(build["preferences"])
    except (KeyError, TypeError):
        raise PublishError("That file doesn't look like a builder result (results/build_latest.json).") from None
    tickers = list(dict.fromkeys(tickers + [t.upper() for t in extra]))
    if not tickers:
        raise PublishError("The built fund has no stocks in it.")

    table = builder.prescreen()
    missing = [t for t in tickers if t not in table]
    if missing:
        raise PublishError(f"Not in the builder's universe, so there is no result to post: {', '.join(missing)}")
    unknown = [k for k in theme_keys if any(k not in table[t] for t in tickers)]
    if unknown:
        raise PublishError(f"No results for theme(s): {', '.join(unknown)}")
    results = {t: {k: table[t][k] for k in theme_keys} for t in tickers}
    return results, {"start": DEFAULT_START, "end": DEFAULT_END}


def price_frames(tickers: list[str], prices_file: Path | None, replay: int) -> list[tuple[str, dict[str, float]]]:
    """A list of (label, {ticker: price}) to post in order. Normally one frame: the latest close.

    With replay=N it is the last N trading days, oldest first. With a prices file it is that file's
    {ticker: price} as a single frame (handy for demos and tests without market data).
    """
    if prices_file:
        given = {k.upper(): v for k, v in _read_json(prices_file).items()}
        missing = [t for t in tickers if t not in given]
        if missing:
            raise PublishError(f"{prices_file} has no price for: {', '.join(missing)}")
        return [("prices file", {t: given[t] for t in tickers})]

    from engine.data import DataError, get_prices  # needs FMP / cached price data
    from engine.fmp import FMPError

    try:
        prices, _ = get_prices(tickers)
    except (DataError, FMPError, OSError) as exc:  # no data, no API key, no network: say so plainly
        raise PublishError(f"Couldn't load prices: {exc}") from None
    rows = prices.tail(max(replay, 1))
    return [(str(day)[:10], {t: float(row[t]) for t in tickers}) for day, row in rows.iterrows()]


# ---------------------------------------------------------------------------------------------
# The chain side
# ---------------------------------------------------------------------------------------------

def load_account(w3: Web3, keystore: str, password: str | None = None):
    """Unlock the deployer wallet from a Foundry keystore (created with `cast wallet import`)."""
    path = Path(keystore).expanduser()
    if not path.exists():
        path = KEYSTORE_DIR / keystore
    if not path.exists():
        raise PublishError(f"No keystore at '{keystore}' or {path}. Create one with: cast wallet import {keystore} --interactive")
    if password is None:
        password = getpass.getpass(f"Password for keystore '{path.name}': ")
    try:
        key = w3.eth.account.decrypt(json.loads(path.read_text()), password)
    except ValueError:
        raise PublishError("Wrong keystore password.") from None
    return w3.eth.account.from_key(key)


class Publisher:
    """Talks to the deployed contracts. Finds the exchange and oracle from the factory address."""

    def __init__(self, w3: Web3, factory_address: str, account=None, log=print, require_owner: bool = True):
        """require_owner=True (publishing) needs the owner or an approved publisher; False is for actions
        anyone may take (launching a fund, depositing)."""
        self.w3, self.account, self.log = w3, account, log
        if not w3.is_connected():
            raise PublishError("Can't reach the chain. Check MONAD_RPC_URL in .env.")
        if not Web3.is_address(factory_address):
            raise PublishError("FACTORY_ADDRESS in .env isn't a valid address.")
        factory_address = Web3.to_checksum_address(factory_address)
        if len(w3.eth.get_code(factory_address)) == 0:
            raise PublishError(f"Nothing is deployed at FACTORY_ADDRESS {factory_address} on this network.")
        self.factory = factory = w3.eth.contract(address=factory_address, abi=FACTORY_ABI)
        self.exchange = w3.eth.contract(address=factory.functions.exchange().call(), abi=EXCHANGE_ABI)
        self.oracle = w3.eth.contract(address=self.exchange.functions.oracle().call(), abi=ORACLE_ABI)
        if account is not None:
            # Publishing needs the owner or a wallet the owner approved as a publisher on BOTH contracts.
            for name, contract in (("oracle", self.oracle), ("exchange", self.exchange)) if require_owner else ():
                if not contract.functions.canPublish(account.address).call():
                    owner = contract.functions.owner().call()
                    raise PublishError(f"This wallet ({account.address}) isn't allowed to publish to the {name}. "
                                       f"Ask its owner ({owner}) to approve it as a publisher.")
            self._nonce = w3.eth.get_transaction_count(account.address, "pending")

    def send(self, call, label: str, extra_gas: int = 0) -> str:
        """Sign and send one transaction, wait for it, and return its hash."""
        return self._send(call, label, extra_gas)

    def _send(self, call, label: str, extra_gas: int = 0) -> str:
        if self.account is None:
            raise PublishError("No wallet loaded, so nothing can be sent.")
        tx = call.build_transaction({"from": self.account.address, "nonce": self._nonce, "chainId": self.w3.eth.chain_id})
        # Gas estimates can be short (see GAS_PER_TIMESTAMPED_ITEM), and sending with zero headroom then
        # fails with "out of gas" and no reason. A 20% margin is standard, plus any per-item extra.
        tx["gas"] = int(tx["gas"] * GAS_HEADROOM) + extra_gas
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        self._nonce += 1
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status != 1:
            raise PublishError(f"{label} failed on-chain (tx {Web3.to_hex(tx_hash)}).")
        self.log(f"  {label}  tx {Web3.to_hex(tx_hash)}")
        return Web3.to_hex(tx_hash)

    def list_stocks(self, tickers: list[str]) -> dict[str, str]:
        """Make sure every ticker has a test token on the exchange. Returns {ticker: token address}."""
        addresses = {}
        for t in tickers:
            address = self.exchange.functions.stockOf(to_bytes32(t)).call()
            if int(address, 16) == 0:
                self._send(self.exchange.functions.listStock(f"Mock {t}", t), f"listed {t}")
                address = self.exchange.functions.stockOf(to_bytes32(t)).call()
            addresses[t] = address
        return addresses

    def pending_exposures(self, rows: list[dict]) -> list[dict]:
        """The rows whose tier or hashes differ from what the oracle already holds."""
        out = []
        for r in rows:
            tier, baseline, stats, _ = self.oracle.functions.exposureOf(to_bytes32(r["ticker"]), to_bytes32(r["theme"])).call()
            if (tier, bytes(baseline), bytes(stats)) != (r["code"], r["baseline_hash"], r["stats_hash"]):
                out.append(r)
        return out

    def post_exposures(self, rows: list[dict]) -> int:
        """Post only the rows that changed, in batches. Returns how many were posted."""
        todo = self.pending_exposures(rows)
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            self._send(
                self.oracle.functions.postExposures(
                    [to_bytes32(r["ticker"]) for r in chunk],
                    [to_bytes32(r["theme"]) for r in chunk],
                    [r["code"] for r in chunk],
                    [r["baseline_hash"] for r in chunk],
                    [r["stats_hash"] for r in chunk],
                ),
                f"posted {len(chunk)} tier(s)",
                extra_gas=GAS_PER_TIMESTAMPED_ITEM * len(chunk),
            )
        return len(todo)

    def post_prices(self, prices: dict[str, float], label: str = "") -> None:
        """Post every price in one transaction (always sent: it also refreshes the 7-day freshness clock)."""
        tickers = sorted(prices)
        self._send(
            self.oracle.functions.postPrices([to_bytes32(t) for t in tickers], [price_to_chain(prices[t]) for t in tickers]),
            f"posted {len(tickers)} price(s){' for ' + label if label else ''}",
            extra_gas=GAS_PER_TIMESTAMPED_ITEM * len(tickers),
        )


def connect(keystore: str, log=print, account=None, w3: Web3 | None = None, require_owner: bool = True) -> Publisher:
    """Connect to the chain and contracts named in .env and unlock the wallet (asks for its password)."""
    rpc, factory = os.environ.get("MONAD_RPC_URL"), os.environ.get("FACTORY_ADDRESS")
    if w3 is None:
        if not rpc:
            raise PublishError("MONAD_RPC_URL isn't set in .env.")
        w3 = Web3(Web3.HTTPProvider(rpc))
    if not factory:
        raise PublishError("FACTORY_ADDRESS isn't set in .env. Deploy first (contracts/script/Deploy.s.sol).")
    if account is None:
        account = load_account(w3, keystore)
    return Publisher(w3, factory, account, log, require_owner)


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------

def _plain_summary(rows: list[dict], frames: list[tuple[str, dict]]) -> str:
    lines = ["Tiers to publish:"]
    for r in rows:
        lines.append(f"  {r['ticker']:6} {r['theme']:14} {r['tier']}")
    label, prices = frames[-1]
    lines.append(f"Prices ({label}):")
    lines += [f"  {t:6} ${Decimal(str(p)):,.2f}" for t, p in sorted(prices.items())]
    if len(frames) > 1:
        lines.append(f"Replay: {len(frames)} trading days, {frames[0][0]} to {frames[-1][0]}.")
    return "\n".join(lines)


def run(args, log=print, account=None, w3: Web3 | None = None) -> int:
    themes = [t.strip() for t in args.themes.split(",") if t.strip()] if args.themes else None
    extra = [t.strip().upper() for t in (args.extra or "").split(",") if t.strip()]

    if args.report:
        results, window = results_from_report(_read_json(Path(args.report)))
        if extra:
            raise PublishError("--extra only works with a built fund, not with --report. Add the stock to the screen instead.")
        if themes:
            results = {t: {k: v for k, v in r.items() if k in themes} for t, r in results.items()}
    else:
        results, window = results_from_build(_read_json(Path(args.build)), extra, themes)

    rows = exposure_rows(results, window)
    if not rows:
        raise PublishError("Nothing to publish: no results for the chosen themes.")
    tickers = sorted(results)
    frames = price_frames(tickers, Path(args.prices_file) if args.prices_file else None, args.replay)
    for _, prices in frames:
        for p in prices.values():
            price_to_chain(p)  # fail early on a bad price, before anything is sent

    log(_plain_summary(rows, frames))
    if args.dry_run:
        log("Dry run: nothing was sent.")
        return 0

    publisher = connect(args.keystore, log, account, w3)
    w3 = publisher.w3
    log(f"Publishing as {publisher.account.address} to oracle {publisher.oracle.address} (chain {w3.eth.chain_id})")
    publisher.list_stocks(tickers)
    posted = publisher.post_exposures(rows)
    if posted == 0:
        log("  tiers already up to date")
    for i, (label, prices) in enumerate(frames):
        if i:
            time.sleep(args.interval)
        publisher.post_prices(prices, label)
    log("Done.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m chain.publish", description="Publish engine results to the oracle.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--build", default=str(DEFAULT_BUILD), help="builder result to publish (default: results/build_latest.json)")
    src.add_argument("--report", help="publish a screen report instead, e.g. results/screen_latest.json")
    ap.add_argument("--extra", help="extra tickers to publish with a built fund, e.g. XOM (for the rejection demo)")
    ap.add_argument("--themes", help="comma-separated theme keys (default: the fund's own themes, or all in a report)")
    ap.add_argument("--prices-file", help='JSON file of {"TICKER": price} to use instead of market data')
    ap.add_argument("--replay", type=int, default=1, help="post the last N trading days of prices in order (default 1)")
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between replayed days (default 3)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be posted; send nothing")
    ap.add_argument("--keystore", default=os.environ.get("DEPLOYER_KEYSTORE", "deployer"),
                    help="Foundry keystore name or path (default: DEPLOYER_KEYSTORE or 'deployer')")
    args = ap.parse_args(argv)
    if args.replay < 1 or args.interval < 0:
        ap.error("--replay must be at least 1 and --interval can't be negative")
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        return run(args)
    except PublishError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
