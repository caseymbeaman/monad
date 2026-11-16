"""Backup entries for the Fantasy Funds League, from test wallets (testnet MON only, no real money).

Use this if live entries from phones fail during the demo.

    python -m chain.league_bets enter --network anvil               # 4 sample ETFs from 4 test wallets
    python -m chain.league_bets enter --network anvil --count 3
    python -m chain.league_bets claim --network anvil
    python -m chain.league_bets show  --network anvil

Sample ETFs come from league/presets.json (the engine builder's suggestions, restricted to the pool), each with a
different theme and slightly different weights, so they don't tie.

Wallets:
- Anvil: the node's own unlocked dev accounts 1..9 (no keys anywhere).
- Monad testnet: throwaway test wallets created on first use and saved in data/cache/league_wallets.json
  (gitignored; testnet only). The League operator wallet tops each one up with the stake + 0.05 MON for gas.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3

from chain.league import (
    NETWORKS,
    PRESETS_FILE,
    Chain,
    LeagueError,
    league_section,
    merkle_proof,
)
from chain.publish import to_bytes32

ROOT = Path(__file__).resolve().parent.parent
WALLETS = ROOT / "data" / "cache" / "league_wallets.json"
TOPUP_WAIT_S = 6
GAS_BUFFER_MON = 0.25  # stake + gas; Monad checks balance against gas limit x max fee (about 2x the gas price); an entry is ~0.59M gas

# The sample ETFs: (name, preset key, weights tilt). Weights are in basis points and add up to 10,000.
SAMPLES = [
    ("AI Rocket", "ai:want,oil:avoid", [3000, 2500, 2000, 1500, 1000]),
    ("Gold Rush", "gold:want", [2500, 2500, 2000, 1500, 1500]),
    ("Pill Power", "healthcare:want", [2200, 2200, 2000, 1800, 1800]),
    ("Top Gun", "defense:want", [3000, 2000, 2000, 1500, 1500]),
    ("Sun & Wind", "clean_energy:want,oil:avoid", [2000, 2000, 2000, 2000, 2000]),
]


def wallets(chain: Chain, n: int) -> list[Chain]:
    """n player wallets, each as its own Chain so it signs (or, on Anvil, sends) for itself."""
    if chain.network == "anvil":
        accts = chain.w3.eth.accounts[1:1 + n]
        if len(accts) < n:
            raise LeagueError(f"Anvil only has {len(accts)} spare dev accounts.")
        return [Chain(chain.network, rpc=chain.rpc, address=a, log=chain.log) for a in accts]
    WALLETS.parent.mkdir(parents=True, exist_ok=True)
    keys = json.loads(WALLETS.read_text()) if WALLETS.exists() else []
    while len(keys) < n:
        keys.append(Account.create().key.hex())
    WALLETS.write_text(json.dumps(keys))
    WALLETS.chmod(0o600)
    return [Chain(chain.network, rpc=chain.rpc, account=Account.from_key(k), log=chain.log) for k in keys[:n]]


def sample_etfs(count: int) -> list[dict]:
    presets = {p["key"]: p for p in json.loads(PRESETS_FILE.read_text())["presets"]}
    out = []
    for name, key, tilt in SAMPLES[:count]:
        p = presets.get(key)
        if not p or len(p["picks"]) < 3:
            raise LeagueError(f"No usable preset '{key}' in league/presets.json. Run: python -m chain.league pool")
        picks = p["picks"][:len(tilt)]
        w = tilt[:len(picks)]
        w[0] += 10_000 - sum(w)
        out.append({"name": name, "tickers": picks, "weights_bps": w, "preset": key})
    return out


def enter(chain: Chain, count: int, round_id: int | None = None, log=print) -> list[dict]:
    lg = league_section(chain.network)
    rid = round_id or lg["currentRound"]
    stake = int(lg["entryStake"])
    out = []
    for player, etf in zip(wallets(chain, count), sample_etfs(count), strict=True):
        if chain.network != "anvil":  # top the test wallet up from the operator
            need = stake + Web3.to_wei(GAS_BUFFER_MON, "ether") - chain.w3.eth.get_balance(player.address)
            if need > 0:
                chain.finish({"to": player.address, "value": need}, f"top up {player.address[:8]}")
                time.sleep(TOPUP_WAIT_S)  # Monad checks balances a few blocks behind; let the top-up show first
        league = player.contract("FundLeague", lg["fundLeague"])
        player.phase = "player entry"
        proofs = [merkle_proof(lg["pool"], t) for t in etf["tickers"]]  # one Merkle proof per stock
        try:
            league.functions.enter(rid, etf["name"], [to_bytes32(t) for t in etf["tickers"]],
                                   etf["weights_bps"], proofs).call({"from": player.address, "value": stake})
        except Exception as e:  # noqa: BLE001 - re-runs skip wallets that already entered
            if "already entered" in str(e):
                log(f"  {player.address[:8]}… already entered, skipped")
                continue
        player.send(league.functions.enter(rid, etf["name"], [to_bytes32(t) for t in etf["tickers"]], etf["weights_bps"],
                                           proofs),
                    f"enter {etf['name']}", value=stake)
        log(f"  {player.address[:8]}… entered '{etf['name']}': " +
            ", ".join(f"{t} {w / 100:g}%" for t, w in zip(etf["tickers"], etf["weights_bps"], strict=True)))
        out.append({"address": player.address, **etf, "costs": player.costs})
    return out


def claim(chain: Chain, round_id: int | None = None, log=print) -> list[dict]:
    lg = league_section(chain.network)
    rid = round_id or lg["currentRound"]
    stake = int(lg["entryStake"])
    n = 9 if chain.network == "anvil" else len(json.loads(WALLETS.read_text())) if WALLETS.exists() else 0
    out = []
    for player in wallets(chain, n):
        league = player.contract("FundLeague", lg["fundLeague"])
        if league.functions.entryOf(rid, player.address).call() == 0:
            continue
        amount = league.functions.claimable(rid, player.address).call()
        if amount > 0:
            player.phase = "player claim"
            player.send(league.functions.claim(rid), "claim")
        log(f"  {player.address[:8]}…: staked {stake / 1e18:g}, paid out {amount / 1e18:g} ({(amount - stake) / 1e18:+g})")
        out.append({"address": player.address, "staked": stake / 1e18, "paid": amount / 1e18, "costs": player.costs})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m chain.league_bets", description="Backup League entries from test wallets.")
    ap.add_argument("command", choices=["enter", "claim", "show"])
    ap.add_argument("--network", default="anvil", choices=list(NETWORKS))
    ap.add_argument("--rpc")
    ap.add_argument("--keystore", help="League operator keystore (Monad testnet: tops up the test wallets)")
    ap.add_argument("--round", type=int)
    ap.add_argument("--count", type=int, default=4, help="how many sample ETFs to enter (1-5)")
    args = ap.parse_args(argv)
    try:
        chain = Chain(args.network, rpc=args.rpc, keystore=args.keystore)
        if args.command in ("enter", "claim"):
            done = enter(chain, max(1, min(args.count, len(SAMPLES))), args.round) if args.command == "enter" \
                else claim(chain, args.round)
            txs = [c for d in done for c in d["costs"]]
            if txs:
                print(f"  per player tx: gas used ~{sum(c['gas_used'] for c in txs) // len(txs):,}, "
                      f"gas limit ~{sum(c['gas_limit'] for c in txs) // len(txs):,} (estimate x 1.15)")
        else:
            for e in sample_etfs(len(SAMPLES)):
                print(f"  {e['name']:<12} {e['preset']:<28} " + ", ".join(e["tickers"]))
    except LeagueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
