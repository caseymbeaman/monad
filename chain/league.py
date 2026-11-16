"""Fantasy Funds League: players build their own ETFs and race (testnet MON only, no real money).

    python -m chain.league deploy --network anvil           # League's OWN oracle + FundLeague
    python -m chain.league pool   --network anvil           # pick the ~60-stock pool, write page data (league/*.json)
    python -m chain.league open   --network anvil --entry-seconds 300 --stake 1
    python -m chain.league run    --network anvil           # waits for the deadline: lock -> start -> replay -> settle
    python -m chain.league status --network anvil
    python -m chain.league demo   --network anvil           # deploy + pool + open + run (rehearsals)

Separate deployment: the League deploys its own ExposureOracle (prices only) and FundLeague from its own operator
wallet and writes them to their OWN file, deployments/<network>-league.json (the main contracts live in
deployments/<network>.json, written by the main deploy). It never touches the main demo's contracts, so replaying old
prices can't change the dashboard or the "try adding XOM" demo.

Pool: the ~60 stocks that appear most across the engine's theme baskets (each theme's top picks first, so every
theme has enough stocks to build from), limited to stocks with a long enough price history.

Page data (shipped with league/index.html, no Python needed in the browser):
- league/pool.json     every pool stock with its name, industry, country and per-theme tier / business link /
                       t-statistic / reference flag (from data/exposure_table.parquet)
- league/presets.json  the engine builder's suggested basket, restricted to the pool, for common Want/Avoid combos

Replay (markets are closed, so it's replay only):
- league/replay_prices.json: real dividend-adjusted closes for the pool (engine price cache); its keccak256 hash is
  recorded on-chain in openRound, before anyone enters.
- Prices posted on-chain are normalized: $100 on the window's first day, $100 x close[d] / close[0] on day d.
  Returns are the real historical ones; only the price level is rescaled.
- The pool is the full universe (every stock in the exposure table with enough price history). On-chain it is just a
  Merkle root (merkle_root below; the page and the tests build the same tree), so opening a round costs the same
  for 666 stocks as for 10. Each entry sends a proof per stock.
- Prices are posted ONLY for the tickers some entry uses (the contract's deduplicated `used` list, read after
  entries close): $100 right before start, then one postPrices transaction per replayed day, every DAY_SECONDS,
  including the last day before settle. Pool stocks nobody picked never get a price.

Gas: every transaction asks for the estimate x 1.15 (Monad charges the gas limit, not the gas used).
Wallets: Anvil uses the node's own unlocked dev accounts (no keys). Monad testnet uses the League's own operator
wallet, a Foundry keystore (LEAGUE_KEYSTORE, default "league-operator" in ~/.foundry/keystores), never the main
deployer's wallet. Its password is read from LEAGUE_KEYSTORE_PASSWORD_FILE (default
~/.foundry/keystores/.league-operator.password) if that file exists, otherwise asked for. Keys are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from eth_abi import encode as abi_encode
from web3 import Web3

from chain.publish import KEYSTORE_DIR, load_account, price_to_chain, to_bytes32

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
DEPLOYMENTS = ROOT / "deployments"
PAGE = ROOT / "league"
REPLAY_FILE = PAGE / "replay_prices.json"
POOL_FILE = PAGE / "pool.json"
PRESETS_FILE = PAGE / "presets.json"
LIVE_FILE = PAGE / "live.json"
COST_FILE = PAGE / "cost_report.json"

RACE_DAYS = 20
DAY_SECONDS = 3
BASE_PRICE = 100.0
POOL_SIZE = 60
PER_THEME = 5  # each theme's top builder picks that are guaranteed a place in the pool
MIN_HISTORY_DAYS = 400
DEFAULT_PICKS = 5  # stocks in a suggested ETF
GAS_HEADROOM = 1.15
GAS_PER_PRICE = 2_800  # per-item margin for timestamped oracle writes (as in chain/publish.py)

NETWORKS = {
    "anvil": {"chainId": 31337, "rpc": "http://127.0.0.1:8545", "explorer": None, "currency": "ETH (Anvil test)"},
    "monad-testnet": {"chainId": 10143, "rpc": "https://testnet-rpc.monad.xyz",
                      "explorer": "https://testnet.monadexplorer.com", "currency": "MON"},
}
PHASES = ["None", "Open", "Locked", "Started", "Settled", "Cancelled"]


class LeagueError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------
# Chain access
# ---------------------------------------------------------------------------------------------

def artifact(name: str) -> dict:
    path = CONTRACTS / "out" / f"{name}.sol" / f"{name}.json"
    if not path.exists():
        subprocess.run([str(Path.home() / ".foundry" / "bin" / "forge"), "build"], cwd=CONTRACTS, check=True,
                       capture_output=True)
    return json.loads(path.read_text())


def _keystore_password() -> str | None:
    """The League keystore's password from its file (never printed), or None to ask for it."""
    p = Path(os.environ.get("LEAGUE_KEYSTORE_PASSWORD_FILE", KEYSTORE_DIR / ".league-operator.password")).expanduser()
    return p.read_text().strip() if p.exists() else None


class Chain:
    """Sends transactions as one wallet and records what each one cost."""

    def __init__(self, network: str, log=print, rpc: str | None = None, keystore: str | None = None,
                 address: str | None = None, account=None):
        if network not in NETWORKS:
            raise LeagueError(f"Unknown network '{network}'. Use one of: {', '.join(NETWORKS)}")
        self.network, self.log = network, log
        cfg = NETWORKS[network]
        self.rpc = rpc or (os.environ.get("MONAD_RPC_URL") if network == "monad-testnet" else None) or cfg["rpc"]
        self.w3 = Web3(Web3.HTTPProvider(self.rpc, request_kwargs={"timeout": 60}))
        if not self.w3.is_connected():
            raise LeagueError(f"Can't reach {network} at {self.rpc}." + (" Start it with: anvil" if network == "anvil" else ""))
        if self.w3.eth.chain_id != cfg["chainId"]:
            raise LeagueError(f"{self.rpc} is chain {self.w3.eth.chain_id}, expected {cfg['chainId']} for {network}.")
        if account is not None:
            self.account, self.address = account, account.address
        elif network == "anvil":
            self.account, self.address = None, address or self.w3.eth.accounts[0]  # unlocked dev account
        else:
            self.account = load_account(self.w3, keystore or os.environ.get("LEAGUE_KEYSTORE", "league-operator"),
                                        _keystore_password())
            self.address = self.account.address
        self.costs: list[dict] = []
        self.phase = "setup"

    def contract(self, name: str, address: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=artifact(name)["abi"])

    def finish(self, tx: dict, label: str, extra_gas: int = 0):
        tx["from"] = self.address
        tx["chainId"] = self.w3.eth.chain_id
        tx["nonce"] = self.w3.eth.get_transaction_count(self.address, "pending")
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:  # plain transfers (top-ups) don't get fees filled in
            tx["gasPrice"] = self.w3.eth.gas_price
        tx["gas"] = int(self.w3.eth.estimate_gas(tx) * GAS_HEADROOM) + extra_gas
        if self.account is None:
            h = self.w3.eth.send_transaction(tx)
        else:
            h = self.w3.eth.send_raw_transaction(self.account.sign_transaction(tx).raw_transaction)
        r = self.w3.eth.wait_for_transaction_receipt(h, timeout=180)
        if r.status != 1:
            raise LeagueError(f"{label} failed on-chain (tx {Web3.to_hex(h)}).")
        self.costs.append({"phase": self.phase, "label": label, "gas_used": r.gasUsed, "gas_limit": tx["gas"],
                           "gas_price": r.effectiveGasPrice})
        return r

    def send(self, call, label: str, value: int = 0, extra_gas: int = 0):
        tx = call.build_transaction({"from": self.address, "value": value, "nonce": 0, "gas": 0})
        tx.pop("gas"), tx.pop("nonce")
        return self.finish(tx, label, extra_gas)

    def deploy(self, name: str, *args) -> str:
        a = artifact(name)
        c = self.w3.eth.contract(abi=a["abi"], bytecode=a["bytecode"]["object"])
        tx = c.constructor(*args).build_transaction({"from": self.address, "nonce": 0, "gas": 0})
        tx.pop("gas"), tx.pop("nonce")
        r = self.finish(tx, f"deployed {name}")
        self.log(f"  deployed {name} at {r.contractAddress}")
        return r.contractAddress

    def mine_until(self, block: int):
        while self.w3.eth.block_number <= block:
            if self.network == "anvil":
                self.w3.provider.make_request("evm_mine", [])
            else:
                time.sleep(0.5)

    def wait_until_time(self, ts: int):
        while True:
            now = self.w3.eth.get_block("latest").timestamp
            if now >= ts:
                return
            if self.network == "anvil" and time.time() >= ts:
                self.w3.provider.make_request("evm_mine", [])
            time.sleep(min(1.0, max(0.1, ts - now)))


# ---------------------------------------------------------------------------------------------
# deployments/<network>-league.json (the League's own file; never the main deployments/<network>.json)
# ---------------------------------------------------------------------------------------------

def deployment_file(network: str) -> Path:
    return DEPLOYMENTS / f"{network}-league.json"


def read_deployment(network: str) -> dict:
    p = deployment_file(network)
    return json.loads(p.read_text()) if p.exists() else {}


def write_league_section(network: str, league: dict) -> None:
    DEPLOYMENTS.mkdir(exist_ok=True)
    data = read_deployment(network)
    cfg = NETWORKS[network]
    data.setdefault("network", network)
    data.setdefault("chainId", cfg["chainId"])
    data.setdefault("rpc", cfg["rpc"])
    if cfg["explorer"]:
        data.setdefault("explorer", cfg["explorer"])
    data["league"] = league
    deployment_file(network).write_text(json.dumps(data, indent=2) + "\n")


def league_section(network: str) -> dict:
    lg = read_deployment(network).get("league")
    if not lg:
        raise LeagueError(f"No League deployment in deployments/{network}-league.json. "
                          f"Run: python -m chain.league deploy --network {network}")
    return lg


# ---------------------------------------------------------------------------------------------
# Pool, page data and replay file
# ---------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------
# Merkle tree of the pool (must match FundLeague._inPool, contracts/test/FundLeague.t.sol and league/index.html)
# leaf = keccak256(32-byte ticker); a pair is hashed in sorted order; an odd node at the end of a level moves up.
# ---------------------------------------------------------------------------------------------

def _merkle_up(level: list[bytes]) -> list[bytes]:
    out = []
    for i in range(0, len(level), 2):
        if i + 1 == len(level):
            out.append(level[i])
        else:
            a, b = sorted((level[i], level[i + 1]))
            out.append(Web3.keccak(a + b))
    return out


def merkle_root(tickers: list[str]) -> bytes:
    level = [Web3.keccak(to_bytes32(t)) for t in tickers]
    while len(level) > 1:
        level = _merkle_up(level)
    return level[0]


def merkle_proof(tickers: list[str], ticker: str) -> list[bytes]:
    idx = tickers.index(ticker)
    level = [Web3.keccak(to_bytes32(t)) for t in tickers]
    proof = []
    while len(level) > 1:
        sib = idx ^ 1
        if sib < len(level):
            proof.append(level[sib])
        level, idx = _merkle_up(level), idx // 2
    return proof


def equal_weights(n: int) -> list[int]:
    """n weights in basis points adding up to exactly 10,000 (any remainder goes to the first ones)."""
    base, rem = divmod(10_000, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def build_pool() -> tuple[list[str], dict, list]:
    """Pick the pool and write league/pool.json + league/presets.json. Returns (pool, pool_data, presets)."""
    from engine import builder
    from engine.build_table import load_table
    from engine.data import get_prices
    from engine.theme_loader import load_all

    themes = load_all()
    table = load_table()
    keys = list(themes)

    def history_ok(t):
        try:
            return len(get_prices([t])[0]) >= MIN_HISTORY_DAYS + 1
        except Exception:  # noqa: BLE001 - no prices -> not in the pool
            return False

    # The pool is the whole universe: every stock with enough price history for a race window, biggest first.
    caps = table.groupby("ticker")["market_cap"].first().astype(float).fillna(0.0)
    pool = [t for t in sorted(caps.index, key=lambda x: (-caps[x], x)) if history_ok(t)]
    rows = table[table["ticker"].isin(pool)]
    info = rows.groupby("ticker")[["name", "industry", "country", "market_cap"]].first()
    stocks = []
    for t in pool:
        r = rows[rows["ticker"] == t].set_index("theme")
        stocks.append({"ticker": t, "name": info.loc[t, "name"], "industry": info.loc[t, "industry"],
                       "country": info.loc[t, "country"], "market_cap": float(info.loc[t, "market_cap"] or 0),
                       "themes": {k: {"tier": r.loc[k, "tier"], "rating": r.loc[k, "final_rating"],
                                      "revenue_pct": None if r.loc[k, "revenue_pct"] != r.loc[k, "revenue_pct"]
                                      else r.loc[k, "revenue_pct"],
                                      "linked": bool(r.loc[k, "business_linked"]),
                                      "t": None if r.loc[k, "strength_t"] != r.loc[k, "strength_t"] else round(float(r.loc[k, "strength_t"]), 2),
                                      "ref": bool(r.loc[k, "reference"])} for k in keys}})
    pool_data = {"about": "Stock pool for the Fantasy Funds League (the full universe), with each stock's engine "
                          "result per theme.",
                 "themes": [{"key": k, "name": themes[k]["name"],
                             "industries": themes[k].get("allowed_industries", [])} for k in keys],
                 "rules": {"min_stocks": 3, "max_stocks": 8, "min_weight_pct": 5, "default_picks": DEFAULT_PICKS,
                           "well_known_floors": builder.WELL_KNOWN_FLOORS, "max_per_industry": builder.MAX_PER_INDUSTRY},
                 "stocks": stocks}
    PAGE.mkdir(exist_ok=True)
    POOL_FILE.write_text(json.dumps(pool_data, indent=1))

    combos = [{k: "want"} for k in keys]
    combos += [{k: "want", "oil": "avoid"} for k in keys if k != "oil"]
    combos += [{k: "want", "ai": "avoid"} for k in keys if k != "ai"]
    pool_table = table[table["ticker"].isin(pool)]
    combos += [{k: "want", j: "want"} for i, k in enumerate(keys) for j in keys[i + 1:]]  # two wants
    presets = []
    saved_top = builder.TOP_N
    try:
        for prefs in combos:
            out = {}
            for n in (DEFAULT_PICKS, 8):  # the page's default ETF size and its maximum
                builder.TOP_N = n
                b = builder.build(prefs, table=pool_table)
                out[n] = [(h["ticker"], h.get("picked_for")) for h in b["holdings"] if h["ticker"] != "CASH"]
            picks = [t for t, _ in out[DEFAULT_PICKS]]
            presets.append({"key": ",".join(f"{k}:{v}" for k, v in sorted(prefs.items())), "preferences": prefs,
                            "picks": picks, "picked_for": [f for _, f in out[DEFAULT_PICKS]],
                            "ranked": [t for t, _ in out[8]], "ranked_for": [f for _, f in out[8]],
                            "weights_bps": equal_weights(len(picks)) if len(picks) >= 3 else []})
    finally:
        builder.TOP_N = saved_top
    PRESETS_FILE.write_text(json.dumps({"about": "Engine builder suggestions restricted to the League pool.",
                                        "presets": presets}, indent=1))
    return pool, pool_data, presets


def write_replay_file(tickers: list[str]) -> tuple[bytes, int, dict]:
    from engine.data import get_prices

    prices, _ = get_prices(tickers)
    data = {"about": "Fantasy Funds League replay prices: dividend-adjusted daily closes (FMP, via the engine cache). "
                     "On-chain prices are normalized to $100 on the window's first day.",
            "race_days": RACE_DAYS, "day_seconds": DAY_SECONDS, "base_price": BASE_PRICE,
            "dates": [d.date().isoformat() for d in prices.index], "tickers": list(prices.columns),
            "closes": [[round(float(x), 6) for x in row] for row in prices.values]}
    raw = json.dumps(data, separators=(",", ":")).encode()
    REPLAY_FILE.write_bytes(raw)
    windows = len(data["dates"]) - RACE_DAYS
    if windows < 1:
        raise LeagueError("Not enough shared price history for a race window.")
    return Web3.keccak(raw), windows, data


def write_live(state: dict):
    PAGE.mkdir(exist_ok=True)
    LIVE_FILE.write_text(json.dumps({**state, "updated": int(time.time())}))


# ---------------------------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------------------------

def deploy(chain: Chain, reuse_oracle: bool = False) -> dict:
    """Deploy the League's own oracle + FundLeague. reuse_oracle: keep the League oracle already in the deployment
    file and deploy only a new FundLeague (the previous FundLeague address is kept as previousFundLeague)."""
    chain.phase = "deploy"
    old = league_section(chain.network) if reuse_oracle else {}
    if reuse_oracle and not old.get("oracle"):
        raise LeagueError("No League oracle in the deployment file to reuse. Run deploy without --reuse-oracle.")
    chain.log("Deploying the League's own contracts (separate from the main demo):")
    oracle = old["oracle"] if reuse_oracle else chain.deploy("ExposureOracle")
    if reuse_oracle:
        chain.log(f"  reusing the League's ExposureOracle at {oracle}")
    league = chain.deploy("FundLeague", oracle)
    lg = {"oracle": oracle, "fundLeague": league, "operator": chain.address,
          "deployedAt": datetime.now(UTC).isoformat(timespec="seconds")}
    if old.get("fundLeague"):
        lg["previousFundLeague"] = old["fundLeague"]
    write_league_section(chain.network, lg)
    return lg


def make_pool(chain: Chain) -> dict:
    lg = league_section(chain.network)
    pool, _, presets = build_pool()
    lg["pool"] = pool
    write_league_section(chain.network, lg)
    chain.log(f"Pool: {len(pool)} stocks. {len(presets)} preset suggestions written to league/presets.json.")
    return lg


def post_prices(chain: Chain, oracle, prices: dict[str, float], label: str):
    ts = sorted(prices)
    chain.send(oracle.functions.postPrices([to_bytes32(t) for t in ts], [price_to_chain(prices[t]) for t in ts]),
               f"posted {len(ts)} prices: {label}", extra_gas=GAS_PER_PRICE * len(ts))


def open_round(chain: Chain, entry_seconds: int, stake_mon: float, prepared: tuple | None = None,
               deadline: int | None = None, duration: int | None = None, extra: dict | None = None,
               side: bool = False) -> int:
    """Open a round. prepared = (data_hash, windows, data) from another replay source (demo day, weekly);
    deadline / duration override entry_seconds and the replay length (weekly matchups); extra is saved in the
    deployment file's league section (e.g. the week's lock and end times for the page)."""
    lg = league_section(chain.network)
    if not lg.get("pool"):
        raise LeagueError("No pool yet. Run: python -m chain.league pool")
    chain.phase = "open"
    data_hash, windows, data = prepared or write_replay_file(lg["pool"])
    league = chain.contract("FundLeague", lg["fundLeague"])
    # No prices at open: only the tickers entries actually use get prices, right before start (see run_round).
    root = merkle_root(data["tickers"])
    now = chain.w3.eth.get_block("latest").timestamp
    deadline = deadline or max(now, int(time.time())) + entry_seconds
    stake = Web3.to_wei(stake_mon, "ether")
    r = chain.send(league.functions.openRound(root, len(data["tickers"]), stake, deadline,
                                              duration or RACE_DAYS * DAY_SECONDS, data_hash, windows), "opened round")
    round_id = league.events.RoundOpened().process_receipt(r)[0]["args"]["roundId"]
    if side:  # a side round (the weekly matchup): leave the main round's settings in the deployment file alone
        return round_id
    lg.update({"currentRound": round_id, "currentDeadline": deadline, "entryStake": str(stake), "pool": data["tickers"],
               "poolRoot": Web3.to_hex(root),
               "replay": {"file": "league/replay_prices.json", "dataHash": Web3.to_hex(data_hash), "windows": windows,
                          "raceDays": RACE_DAYS, "daySeconds": DAY_SECONDS, "firstDate": data["dates"][0],
                          "lastDate": data["dates"][-1], "mode": data.get("mode", "replay"),
                          "windowStride": data.get("window_stride", 1),
                          "chosenDay": data.get("chosen_day")}})  # set when the organiser picked the day
    lg.pop("weekly", None)
    lg.update(extra or {})
    write_league_section(chain.network, lg)
    write_live({"round": round_id, "phase": "entries", "deadline": deadline})
    chain.log(f"Round {round_id} open: entry {stake_mon} {NETWORKS[chain.network]['currency']}, entries close in "
              f"{deadline - int(time.time())}s. Pool: {len(data['tickers'])} stocks (Merkle root). Replay hash {Web3.to_hex(data_hash)}, {windows} windows "
              f"({data['dates'][0]} to {data['dates'][-1]}).")
    return round_id


def expected_window(block_hash: bytes, round_id: int, data_hash: bytes, windows: int) -> int:
    seed = Web3.keccak(abi_encode(["bytes32", "uint256", "bytes32"], [block_hash, round_id, data_hash]))
    return int.from_bytes(seed, "big") % windows


def run_round(chain: Chain, round_id: int | None = None) -> dict:
    """lock -> start -> replay (one price batch per day for the used tickers) -> settle. Waits for the deadline."""
    lg = league_section(chain.network)
    round_id = round_id or lg["currentRound"]
    league = chain.contract("FundLeague", lg["fundLeague"])
    oracle = chain.contract("ExposureOracle", lg["oracle"])
    info = league.functions.getRound(round_id).call()  # RoundInfo tuple
    raw = REPLAY_FILE.read_bytes()
    if Web3.keccak(raw) != bytes(info[8]):
        raise LeagueError("league/replay_prices.json doesn't match the hash recorded when the round opened.")
    replay = json.loads(raw)
    deadline = info[2]

    chain.phase = "lock+start"
    chain.log(f"Waiting for entries to close ({datetime.fromtimestamp(deadline, UTC):%H:%M:%S} UTC) ...")
    chain.wait_until_time(deadline)
    r = chain.send(league.functions.lock(round_id), "lock")
    if league.events.Cancelled().process_receipt(r):
        chain.log("Fewer than 2 entries: round cancelled, everyone can claim their stake back.")
        write_live({"round": round_id, "phase": "cancelled"})
        return results(chain, round_id)
    target = league.events.Locked().process_receipt(r)[0]["args"]["targetBlock"]
    write_live({"round": round_id, "phase": "locked", "targetBlock": target})
    used = [bytes(t).rstrip(b"\0").decode() for t in league.functions.getRound(round_id).call()[0]]
    chain.log(f"{len(used)} distinct stocks used by entries (of {len(replay['tickers'])} in the pool): "
              "only these get prices.")
    post_prices(chain, oracle, dict.fromkeys(used, BASE_PRICE), "race start ($100 each)")
    chain.mine_until(target)
    r = chain.send(league.functions.start(round_id), "start")
    w = league.events.Started().process_receipt(r)[0]["args"]["windowIndex"]
    check = expected_window(chain.w3.eth.get_block(target).hash, round_id, bytes(info[8]), info[6])
    stride = replay.get("window_stride", 1)  # demo day: each window is its own block of rows
    rows = [w * stride + d for d in range(RACE_DAYS + 1)]
    dates = [replay["dates"][r] for r in rows]
    chain.log(f"Window {w} of {info[6]} picked by block {target}'s hash (recomputed off-chain: {check}): "
              f"{dates[0]} to {dates[-1]}")

    chain.phase = "replay"
    closes, col = replay["closes"], {t: i for i, t in enumerate(replay["tickers"])}
    for d in range(1, RACE_DAYS + 1):
        t0 = time.time()
        post_prices(chain, oracle, {t: BASE_PRICE * closes[rows[d]][col[t]] / closes[rows[0]][col[t]] for t in used},
                    f"day {d}/{RACE_DAYS} ({dates[d]})")
        scores = league.functions.liveScores(round_id).call()
        write_live({"round": round_id, "phase": "racing", "day": d, "days": RACE_DAYS, "date": dates[d], "window": w,
                    "firstDate": dates[0], "lastDate": dates[-1], "returns": [s / 1e18 for s in scores]})
        time.sleep(max(0.0, DAY_SECONDS - (time.time() - t0)))

    chain.phase = "settle"
    started = league.functions.getRound(round_id).call()[4]
    chain.wait_until_time(started + info[3])
    chain.send(league.functions.settle(round_id), "settle")
    return results(chain, round_id)


def results(chain: Chain, round_id: int, live: bool | None = None) -> dict:
    lg = league_section(chain.network)
    league = chain.contract("FundLeague", lg["fundLeague"])
    info = league.functions.getRound(round_id).call()
    phase = PHASES[info[10]]
    live_round = live if live is not None else lg.get("replay", {}).get("mode") == "live-weekly"  # weekly matchups use live prices, no replay file
    replay = {} if live_round else json.loads(REPLAY_FILE.read_bytes())
    w = info[7]
    live = list(league.functions.liveScores(round_id).call()) if phase in ("Started", "Settled") else []
    entries = []
    for i in range(info[11]):
        owner, name, tickers, weights, score = league.functions.getEntry(round_id, i).call()
        ret = (score if phase == "Settled" else (live[i] if live else None))
        entries.append({"index": i, "owner": owner, "name": name,
                        "stocks": [(bytes(t).rstrip(b"\0").decode(), wt / 100) for t, wt in zip(tickers, weights, strict=True)],
                        "return_pct": ret / 1e16 if ret is not None else None,
                        "winner": phase == "Settled" and score == info[13]})
    stride = replay.get("window_stride", 1)
    live_mode = live_round
    out = {"round": round_id, "phase": phase, "window": w,
           "dates": ([replay["dates"][w * stride], replay["dates"][w * stride + RACE_DAYS]]
                     if phase in ("Started", "Settled") and not live_mode else None),
           "pot": info[14] / 1e18, "stake": info[1] / 1e18, "winners": info[12], "entries": entries}
    if phase == "Settled" and out["dates"]:
        write_live({"round": round_id, "phase": "settled", "window": w, "firstDate": out["dates"][0],
                    "lastDate": out["dates"][1], "returns": [e["return_pct"] / 100 for e in entries]})
    return out


def print_results(r: dict, log=print):
    log(f"\nRound {r['round']} ({r['phase']}), pot {r['pot']:.4f}, stake {r['stake']:.4f}")
    if r["dates"]:
        log(f"Window {r['window']}: {r['dates'][0]} to {r['dates'][1]}")
    for e in sorted(r["entries"], key=lambda e: -(e["return_pct"] if e["return_pct"] is not None else -1e9)):
        ret = f"{e['return_pct']:+7.2f}%" if e["return_pct"] is not None else "    -   "
        stocks = ", ".join(f"{t} {w:g}%" for t, w in e["stocks"])
        log(f"  {'WINNER ' if e['winner'] else '       '}{ret}  {e['name']:<20} {e['owner'][:8]}…  {stocks}")


def cost_report(chain: Chain, extra: dict | None = None) -> dict:
    price = testnet_gas_price()
    by_phase: dict[str, dict] = {}
    for c in chain.costs:
        p = by_phase.setdefault(c["phase"], {"txs": 0, "gas_used": 0, "gas_limit": 0})
        p["txs"] += 1
        p["gas_used"] += c["gas_used"]
        p["gas_limit"] += c["gas_limit"]
    rep = {"by_phase": by_phase, "txs": len(chain.costs), "gas_used": sum(p["gas_used"] for p in by_phase.values()),
           "gas_limit": sum(p["gas_limit"] for p in by_phase.values()),
           "testnet_gas_price_gwei": price / 1e9 if price else None, "headroom": GAS_HEADROOM, **(extra or {})}
    if price:
        rep["mon_at_testnet_price"] = rep["gas_limit"] * price / 1e18  # Monad charges the gas limit
    COST_FILE.write_text(json.dumps(rep, indent=1))
    return rep


def testnet_gas_price() -> int | None:
    try:
        return int(Web3(Web3.HTTPProvider(NETWORKS["monad-testnet"]["rpc"], request_kwargs={"timeout": 15})).eth.gas_price)
    except Exception:  # noqa: BLE001 - only used for an estimate
        return None


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m chain.league", description="Fantasy Funds League (testnet only).")
    ap.add_argument("command", choices=["deploy", "pool", "open", "run", "status", "demo", "weekly", "demo-day", "always-on"])
    ap.add_argument("--network", default="anvil", choices=list(NETWORKS))
    ap.add_argument("--rpc", help="override the RPC URL")
    ap.add_argument("--keystore", help=f"League operator keystore (Monad testnet), default league-operator in {KEYSTORE_DIR}")
    ap.add_argument("--round", type=int, help="round id (default: the latest)")
    ap.add_argument("--entry-seconds", type=int, default=300, help="how long entries stay open")
    ap.add_argument("--stake", type=float, default=1.0, help="entry stake in MON (default 1)")
    ap.add_argument("--reuse-oracle", action="store_true", help="deploy: only a new FundLeague, keep the League oracle")
    ap.add_argument("--lock", default="Mon 06:30 PT", help="weekly: entries lock (e.g. 'Mon 06:30 PT', or '+1m')")
    ap.add_argument("--end", default="Fri 13:00 PT", help="weekly: matchup ends (e.g. 'Fri 13:00 PT', or '+5m')")
    ap.add_argument("--every", type=int, default=300, help="weekly: seconds between live price updates")
    ap.add_argument("--weeks", type=int, help="weekly: stop after this many matchups (default: keep going)")
    ap.add_argument("--simulate-prices", action="store_true", help="weekly (tests): random-walk prices, not live FMP")
    ap.add_argument("--data", default="simulated", help="always-on: price data (simulated)")
    ap.add_argument("--rounds", type=int, help="always-on (tests): stop after opening this many rounds")
    ap.add_argument("--day", help="demo-day / always-on: race this real trading day (YYYY-MM-DD) instead of a random "
                                  "one. The day is then public, not a secret")
    ap.add_argument("--ignore-market-hours", action="store_true", help="weekly (tests): post prices around the clock")
    args = ap.parse_args(argv)
    if args.day and args.command not in ("demo-day", "always-on"):
        ap.error("--day only works with demo-day and always-on")
    try:
        chain = Chain(args.network, rpc=args.rpc, keystore=args.keystore)
        if args.command in ("deploy", "demo"):
            deploy(chain, reuse_oracle=args.reuse_oracle)
        if args.command in ("pool", "demo"):
            make_pool(chain)
        if args.command in ("open", "demo"):
            open_round(chain, args.entry_seconds, args.stake)
        if args.command == "demo":
            chain.log("Enter ETFs now (league page, or: python -m chain.league_bets enter ...). Running the round ...")
        if args.command in ("run", "demo"):
            print_results(run_round(chain, args.round))
        if args.command == "weekly":
            from chain.league_live import weekly
            weekly(chain, args.lock, args.end, args.stake, every=args.every, simulate=args.simulate_prices,
                   ignore_market_hours=args.ignore_market_hours, weeks=args.weeks)
        if args.command == "demo-day":
            from chain.league_live import demo_day, run_demo_day
            demo_day(chain, args.entry_seconds, args.stake, day=args.day)
            run_demo_day(chain)
        if args.command == "always-on":
            from chain.league_live import always_on
            always_on(chain, args.entry_seconds, args.stake, data=args.data, max_rounds=args.rounds, day=args.day)
        if args.command == "status":
            print_results(results(chain, args.round or league_section(args.network).get("currentRound", 1)))
        if chain.costs:
            rep = cost_report(chain)
            chain.log(f"\n{rep['txs']} transactions, {rep['gas_used']:,} gas used ({rep['gas_limit']:,} gas limit).")
    except LeagueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
