"""Launch the built fund on Monad as its own token, then (optionally) deposit and try a forbidden trade.

    python -m chain.launch                           # launch results/build_latest.json as a fund
    python -m chain.launch --dry-run                 # show the fund that would be launched; sends nothing
    python -m chain.launch --deposit 1000            # ...then put in 1,000 test dollars
    python -m chain.launch --try-add XOM             # ...then show the mandate rejecting XOM
    python -m chain.launch --name "AI ex-Oil Fund" --symbol AIXO --want-min-pct 60

Run `python -m chain.publish --extra XOM` first: a fund can only hold stocks whose tiers and prices are
already on the oracle, and the launch itself fails if the basket breaks the fund's own rules.

How the builder's result becomes the fund's mandate (the rules are fixed forever once launched):
- "avoid" theme -> Avoid rule: every holding must be Limited or Limited (lower confidence) for it.
- "want" theme  -> Want rule: at least --want-min-pct (default 60%) of the fund must be in High or
                   Moderate names for it. (If the basket holds less than that in stocks, the rest being
                   cash, the minimum is the invested share instead.)
Weights are converted from percent to basis points (14.29% -> 1429); cash is whatever is left over.

The fund's details are saved to results/fund_latest.json for the dashboard.
Settings and wallet: the same as chain/publish.py (.env + Foundry keystore).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.logs import DISCARD

from chain.abi import FUND_ABI, USDC_ABI
from chain.publish import (
    CASH,
    DEFAULT_BUILD,
    ROOT,
    Publisher,
    PublishError,
    _read_json,
    connect,
    to_bytes32,
)

FUND_FILE = ROOT / "results" / "fund_latest.json"
EXPLORER = "https://testnet.monadexplorer.com"
BPS = 10_000
USDC_UNIT = 10**6
WANT, AVOID = 0, 1  # must match RuleKind in contracts/src/ThemeFund.sol


# ---------------------------------------------------------------------------------------------
# Turning the builder's result into what the factory needs
# ---------------------------------------------------------------------------------------------

def weights_to_bps(holdings: list[dict]) -> dict[str, int]:
    """{ticker: basis points} for the stocks (cash left out). Never adds up to more than 10,000.

    The builder rounds each weight to 2 decimals, which can push the total to 100.01%. Any excess is
    trimmed one basis point at a time from the largest holdings.
    """
    bps = {}
    for h in holdings:
        if h["ticker"] == CASH:
            continue
        value = int((Decimal(str(h["weight_pct"])) * 100).to_integral_value(rounding=ROUND_DOWN))
        if value <= 0:
            raise PublishError(f"{h['ticker']}: weight {h['weight_pct']}% is too small to hold (minimum 0.01%)")
        if h["ticker"] in bps:
            raise PublishError(f"{h['ticker']} appears twice in the basket")
        bps[h["ticker"]] = value
    if not bps:
        raise PublishError("The built fund has no stocks in it.")
    excess = sum(bps.values()) - BPS
    if excess > len(bps):
        raise PublishError(f"Weights add up to {sum(bps.values()) / 100:.2f}%, which is more than 100%.")
    for ticker in sorted(bps, key=lambda t: (-bps[t], t))[:max(excess, 0)]:
        bps[ticker] -= 1
    return bps


def mandate_rules(prefs: dict[str, str], theme_names: dict[str, str], invested_bps: int, want_min_pct: float) -> list[dict]:
    """One rule per preference, in a fixed order (wants first, then avoids, each alphabetical)."""
    if not 0 < want_min_pct <= 100:
        raise PublishError("--want-min-pct must be above 0 and at most 100")
    rules = []
    for key in sorted(prefs, key=lambda k: (prefs[k] != "want", k)):
        if key not in theme_names:
            raise PublishError(f"No theme called '{key}' in themes/")
        if prefs[key] == "want":
            minimum = min(int(want_min_pct * 100), invested_bps)
            rules.append({"theme": key, "label": theme_names[key], "kind": WANT, "min_bps": minimum})
        elif prefs[key] == "avoid":
            rules.append({"theme": key, "label": theme_names[key], "kind": AVOID, "min_bps": 0})
        else:
            raise PublishError(f"'{key}': preference must be 'want' or 'avoid', not '{prefs[key]}'")
    if not rules:
        raise PublishError("The built fund has no want/avoid preferences, so there is no mandate to launch.")
    return rules


def default_name_and_symbol(prefs: dict[str, str], theme_names: dict[str, str]) -> tuple[str, str]:
    """{"ai": "want", "oil": "avoid"} -> ("AI ex-Oil Fund", "AIXO")."""
    wants = sorted(k for k, v in prefs.items() if v == "want")
    avoids = sorted(k for k, v in prefs.items() if v == "avoid")
    name = " + ".join(theme_names[k] for k in wants)
    if avoids:
        name = f"{name} ex-{'/'.join(theme_names[k] for k in avoids)}".strip()
    symbol = "".join(k[:2].upper() for k in wants) + ("X" + "".join(k[0].upper() for k in avoids) if avoids else "")
    return f"{name} Fund", symbol[:11]


def plan_from_build(build: dict, name: str | None, symbol: str | None, want_min_pct: float) -> dict:
    """Everything needed to launch, as plain data: name, symbol, weights and rules."""
    from engine.theme_loader import (
        load_all,  # reads the theme files only; no market data needed
    )

    try:
        prefs, holdings = build["preferences"], build["holdings"]
    except (KeyError, TypeError):
        raise PublishError("That file doesn't look like a builder result (results/build_latest.json).") from None
    theme_names = {k: t["name"] for k, t in load_all().items()}
    weights = weights_to_bps(holdings)
    rules = mandate_rules(prefs, theme_names, sum(weights.values()), want_min_pct)
    auto_name, auto_symbol = default_name_and_symbol(prefs, theme_names)
    plan = {"name": name or auto_name, "symbol": (symbol or auto_symbol).upper(), "weights_bps": weights,
            "cash_bps": BPS - sum(weights.values()), "rules": rules}
    if not plan["symbol"].isascii() or not plan["symbol"].isalnum():
        raise PublishError(f"Symbol '{plan['symbol']}' should be letters and digits only, e.g. AIXO")
    return plan


def plan_text(plan: dict) -> str:
    lines = [f"Fund: {plan['name']} (${plan['symbol']})", "Basket:"]
    lines += [f"  {t:6} {b / 100:6.2f}%" for t, b in plan["weights_bps"].items()]
    if plan["cash_bps"]:
        lines.append(f"  {'CASH':6} {plan['cash_bps'] / 100:6.2f}%")
    lines.append("Mandate (can never be changed):")
    for r in plan["rules"]:
        if r["kind"] == WANT:
            lines.append(f"  Want {r['label']}: at least {r['min_bps'] / 100:g}% of the fund in High or Moderate names")
        else:
            lines.append(f"  Avoid {r['label']}: every holding must be Limited or Limited (lower confidence)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# The chain side
# ---------------------------------------------------------------------------------------------

def revert_reason(exc: Exception) -> str:
    """The contract's own plain-English reason, e.g. 'Mandate: Oil exposure too high'."""
    text = str(getattr(exc, "message", None) or exc)
    return text.removeprefix("execution reverted: ").strip() or "the contract rejected it without a reason"


def _stock_addresses(chain: Publisher, tickers: list[str]) -> dict[str, str]:
    addresses = {t: chain.exchange.functions.stockOf(to_bytes32(t)).call() for t in tickers}
    missing = [t for t, a in addresses.items() if int(a, 16) == 0]
    if missing:
        raise PublishError(f"Not on the exchange yet: {', '.join(missing)}. Run `python -m chain.publish` first.")
    return addresses


def launch_fund(chain: Publisher, plan: dict) -> dict:
    """Create the fund through the factory. Returns its address, transaction and details."""
    stocks = _stock_addresses(chain, list(plan["weights_bps"]))
    create = chain.factory.functions.createFund(
        plan["name"],
        plan["symbol"],
        [stocks[t] for t in plan["weights_bps"]],
        list(plan["weights_bps"].values()),
        [(to_bytes32(r["theme"]), r["label"], r["kind"], r["min_bps"]) for r in plan["rules"]],
    )
    try:  # rehearse first, so a broken mandate gives its plain reason instead of a failed transaction
        create.call({"from": chain.account.address})
    except ContractLogicError as exc:
        raise PublishError(f"The fund can't be launched: {revert_reason(exc)}") from None

    tx_hash = chain.send(create, f"launched {plan['name']} (${plan['symbol']})")
    receipt = chain.w3.eth.get_transaction_receipt(tx_hash)
    # The receipt also holds the new fund's own events; keep only the factory's FundCreated.
    fund = chain.factory.events.FundCreated().process_receipt(receipt, errors=DISCARD)[0]["args"]["fund"]
    return {**plan, "address": fund, "tx": tx_hash, "chain_id": chain.w3.eth.chain_id,
            "manager": chain.account.address, "stocks": stocks,
            "explorer_url": f"{EXPLORER}/address/{fund}", "tx_url": f"{EXPLORER}/tx/{tx_hash}"}


def deposit(chain: Publisher, fund_address: str, dollars: float) -> dict:
    """Put `dollars` of test money into the fund (tops up from the faucet if the wallet is short)."""
    amount = int(Decimal(str(dollars)) * USDC_UNIT)
    if amount < USDC_UNIT:
        raise PublishError("Deposit at least $1.")
    fund = chain.w3.eth.contract(address=Web3.to_checksum_address(fund_address), abi=FUND_ABI)
    usdc = chain.w3.eth.contract(address=chain.exchange.functions.usdc().call(), abi=USDC_ABI)
    me = chain.account.address

    for _ in range(100):  # the faucet gives $10,000 a call
        if usdc.functions.balanceOf(me).call() >= amount:
            break
        chain.send(usdc.functions.faucet(), "took $10,000 from the test-dollar faucet")
    else:
        raise PublishError("That deposit is more than the faucet can supply ($1,000,000).")
    if usdc.functions.allowance(me, fund.address).call() < amount:
        chain.send(usdc.functions.approve(fund.address, amount), "approved the fund to take the deposit")
    try:
        fund.functions.deposit(amount).call({"from": me})
    except ContractLogicError as exc:
        raise PublishError(f"The deposit was refused: {revert_reason(exc)}") from None
    before = fund.functions.balanceOf(me).call()
    tx_hash = chain.send(fund.functions.deposit(amount), f"deposited ${dollars:,.2f}")
    shares = fund.functions.balanceOf(me).call() - before
    return {"tx": tx_hash, "shares": shares / 10**18, "nav_usd": fund.functions.nav().call() / USDC_UNIT,
            "nav_per_share_usd": fund.functions.navPerShare().call() / USDC_UNIT}


def try_add(chain: Publisher, fund_address: str, ticker: str, weight_pct: float = 5.0) -> tuple[bool, str]:
    """Rehearse adding a stock to the fund WITHOUT sending anything. Returns (allowed, reason)."""
    fund = chain.w3.eth.contract(address=Web3.to_checksum_address(fund_address), abi=FUND_ABI)
    stock = _stock_addresses(chain, [ticker.upper()])[ticker.upper()]
    try:
        fund.functions.addHolding(stock, int(weight_pct * 100)).call({"from": fund.functions.manager().call()})
    except ContractLogicError as exc:
        return False, revert_reason(exc)
    return True, ""


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------

def run(args, log=print, account=None, w3: Web3 | None = None) -> int:
    plan = plan_from_build(_read_json(Path(args.build)), args.name, args.symbol, args.want_min_pct)
    log(plan_text(plan))
    if args.dry_run:
        log("Dry run: nothing was sent.")
        return 0

    chain = connect(args.keystore, log, account, w3, require_owner=False)
    fund = launch_fund(chain, plan)
    log(f"Fund token: {fund['address']}")
    log(f"Explorer:   {fund['explorer_url']}")
    FUND_FILE.parent.mkdir(exist_ok=True)
    FUND_FILE.write_text(json.dumps(fund, indent=1))

    if args.deposit:
        d = deposit(chain, fund["address"], args.deposit)
        log(f"You now hold {d['shares']:,.2f} ${plan['symbol']}. The fund is worth ${d['nav_usd']:,.2f} "
            f"(${d['nav_per_share_usd']:.4f} a share).")
    if args.try_add:
        allowed, reason = try_add(chain, fund["address"], args.try_add)
        if allowed:
            log(f"Adding {args.try_add.upper()} would be allowed: it doesn't break the mandate.")
        else:
            log(f"Adding {args.try_add.upper()} is REJECTED by the fund: {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m chain.launch", description="Launch the built fund on Monad.")
    ap.add_argument("--build", default=str(DEFAULT_BUILD), help="builder result (default: results/build_latest.json)")
    ap.add_argument("--name", help='fund name (default: made from the themes, e.g. "AI ex-Oil Fund")')
    ap.add_argument("--symbol", help="token symbol (default: made from the themes, e.g. AIXO)")
    ap.add_argument("--want-min-pct", type=float, default=60.0,
                    help="minimum %% of the fund in High/Moderate names for each wanted theme (default 60)")
    ap.add_argument("--deposit", type=float, help="after launching, deposit this many test dollars")
    ap.add_argument("--try-add", help="after launching, show whether the mandate would allow adding this ticker")
    ap.add_argument("--dry-run", action="store_true", help="show the fund that would be launched; send nothing")
    ap.add_argument("--keystore", default=os.environ.get("DEPLOYER_KEYSTORE", "deployer"),
                    help="Foundry keystore name or path (default: DEPLOYER_KEYSTORE or 'deployer')")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        return run(args)
    except PublishError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
