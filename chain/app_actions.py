"""The dashboard's link to Phase 7: the same publish / launch / deposit / try-add steps as the command
line (chain/publish.py and chain/launch.py), callable from app.py.

Nothing new happens on-chain here; every action reuses Phase 7's own functions. What this adds:
- config(): what's set up and what's missing (RPC, factory address, keystore), in plain English.
- unlock(): opens the Foundry keystore with a password typed into the app. The unlocked wallet only
  lives in the app's memory for this session; the password and key are never saved or printed.
- publish_basket / launch_basket / deposit_dollars / try_adding: one call per dashboard button.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3

from chain import launch, publish
from chain.publish import PublishError

ROOT = Path(__file__).resolve().parent.parent
MONAD_CHAIN_ID = 10143
DEMO_EXTRA = ("XOM",)  # published alongside the fund so "Try adding XOM" has on-chain data


def config() -> dict:
    """What the on-chain steps need, whether each is in place, and the next step if not."""
    load_dotenv(ROOT / ".env")
    rpc = os.environ.get("MONAD_RPC_URL", "").strip()
    factory = os.environ.get("FACTORY_ADDRESS", "").strip()
    keystore = os.environ.get("DEPLOYER_KEYSTORE", "").strip() or "deployer"
    path = Path(keystore).expanduser()
    found = path.exists() or (publish.KEYSTORE_DIR / keystore).exists()
    missing = []
    if not rpc:
        missing.append("Set MONAD_RPC_URL in .env (Monad testnet: https://testnet-rpc.monad.xyz).")
    if not factory:
        missing.append("Deploy the contracts (contracts/script/Deploy.s.sol) and put FACTORY_ADDRESS in .env.")
    if not found:
        missing.append(f"Create the wallet keystore: cast wallet import {keystore} --interactive")
    return {"rpc": rpc, "factory": factory, "keystore": keystore, "keystore_found": found,
            "ready": not missing, "missing": missing}


def connect_readonly(cfg: dict | None = None) -> tuple[Web3, publish.Publisher]:
    """A connection that can read the contracts and rehearse calls, with no wallet."""
    cfg = cfg or config()
    w3 = Web3(Web3.HTTPProvider(cfg["rpc"]))
    return w3, publish.Publisher(w3, cfg["factory"], account=None, log=lambda _m: None, require_owner=False)


def unlock(password: str, cfg: dict | None = None):
    """(w3, wallet) from the keystore and a password typed in the app. Raises PublishError if wrong."""
    cfg = cfg or config()
    if not cfg["ready"]:
        raise PublishError(" ".join(cfg["missing"]))
    if not password:
        raise PublishError("Type the keystore password first.")
    w3 = Web3(Web3.HTTPProvider(cfg["rpc"]))
    if not w3.is_connected():
        raise PublishError("Can't reach the chain. Check MONAD_RPC_URL in .env.")
    return w3, publish.load_account(w3, cfg["keystore"], password)


def network_name(chain_id: int) -> str:
    return "Monad testnet" if chain_id == MONAD_CHAIN_ID else f"local test chain (id {chain_id})"


def explorer_links(fund: dict) -> dict:
    """Explorer links only make sense on Monad testnet; a local chain has no explorer."""
    if fund.get("chain_id") != MONAD_CHAIN_ID:
        return {}
    return {"fund": fund.get("explorer_url"), "tx": fund.get("tx_url")}


def publish_basket(build: dict, w3: Web3, account, cfg: dict | None = None, extra=DEMO_EXTRA,
                   log=lambda _m: None) -> dict:
    """Post the fund's stocks (plus the demo extras) to the oracle: list tokens, tiers, latest prices.

    Only the oracle's owner wallet can do this. Re-running only sends what changed (plus fresh prices).
    """
    cfg = cfg or config()
    results, window = publish.results_from_build(build, list(extra), None)
    rows = publish.exposure_rows(results, window)
    tickers = sorted(results)
    frames = publish.price_frames(tickers, None, 1)
    chain = publish.Publisher(w3, cfg["factory"], account, log, require_owner=True)
    chain.list_stocks(tickers)
    posted = chain.post_exposures(rows)
    for label, prices in frames:
        chain.post_prices(prices, label)
    return {"stocks": tickers, "tiers_posted": posted, "tiers_total": len(rows),
            "price_date": frames[-1][0] if frames else None, "oracle": chain.oracle.address,
            "network": network_name(w3.eth.chain_id)}


def plan_for(build: dict, name: str | None = None, symbol: str | None = None,
             want_min_pct: float = 60.0) -> dict:
    """The fund that would be launched (name, symbol, weights, mandate rules). Sends nothing."""
    return launch.plan_from_build(build, name or None, symbol or None, want_min_pct)


def launch_basket(build: dict, w3: Web3, account, name: str | None = None, symbol: str | None = None,
                  want_min_pct: float = 60.0, cfg: dict | None = None, log=lambda _m: None) -> dict:
    """Create the fund through the factory and save its details to results/fund_latest.json."""
    cfg = cfg or config()
    plan = plan_for(build, name, symbol, want_min_pct)
    chain = publish.Publisher(w3, cfg["factory"], account, log, require_owner=False)
    fund = launch.launch_fund(chain, plan)
    launch.FUND_FILE.parent.mkdir(exist_ok=True)
    launch.FUND_FILE.write_text(json.dumps(fund, indent=1))
    return {**fund, "network": network_name(fund["chain_id"])}


def deposit_dollars(fund_address: str, dollars: float, w3: Web3, account, cfg: dict | None = None,
                    log=lambda _m: None) -> dict:
    """Put test dollars into the fund; returns shares received and the fund's value."""
    cfg = cfg or config()
    chain = publish.Publisher(w3, cfg["factory"], account, log, require_owner=False)
    return launch.deposit(chain, fund_address, dollars)


def try_adding(fund_address: str, ticker: str, cfg: dict | None = None,
               weight_pct: float = 5.0) -> tuple[bool, str]:
    """Rehearse adding a stock (sends nothing). (allowed, the contract's own reason if rejected)."""
    _w3, chain = connect_readonly(cfg)
    return launch.try_add(chain, fund_address, ticker, weight_pct)
