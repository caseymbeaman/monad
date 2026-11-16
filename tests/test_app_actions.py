"""Tests for chain/app_actions.py, the dashboard's link to Phase 7.

The end-to-end test runs the dashboard's whole on-chain flow on a local test chain (Foundry's anvil):
deploy -> unlock a password-protected keystore -> publish -> launch -> deposit -> try adding XOM.
It's skipped automatically if anvil or the compiled contracts aren't available (run `forge build`
in contracts/ first).
"""

import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from web3 import Web3

from chain import app_actions, launch, publish
from chain.publish import PublishError
from engine import builder
from engine.regression import HIGH, LIMITED, LIMITED_LOW, MODERATE

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "contracts" / "out"
needs_chain = pytest.mark.skipif(
    shutil.which("anvil") is None or not (OUT / "ThemeFundFactory.sol" / "ThemeFundFactory.json").exists(),
    reason="needs Foundry's anvil on PATH and `forge build` run in contracts/")


# ---- settings and small helpers ----

@pytest.fixture
def no_env(monkeypatch, tmp_path):
    monkeypatch.setattr(app_actions, "ROOT", tmp_path)  # no .env here
    for var in ("MONAD_RPC_URL", "FACTORY_ADDRESS", "DEPLOYER_KEYSTORE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(publish, "KEYSTORE_DIR", tmp_path / "keystores")
    return tmp_path


def test_config_lists_every_missing_step(no_env):
    cfg = app_actions.config()
    assert cfg["ready"] is False and cfg["keystore"] == "deployer"
    text = " ".join(cfg["missing"])
    assert "MONAD_RPC_URL" in text and "FACTORY_ADDRESS" in text and "cast wallet import deployer" in text


def test_config_ready_when_everything_is_set(no_env, monkeypatch):
    (no_env / "keystores").mkdir()
    (no_env / "keystores" / "demo").write_text("{}")
    monkeypatch.setenv("MONAD_RPC_URL", "http://127.0.0.1:8545")
    monkeypatch.setenv("FACTORY_ADDRESS", "0x" + "1" * 40)
    monkeypatch.setenv("DEPLOYER_KEYSTORE", "demo")
    cfg = app_actions.config()
    assert cfg["ready"] is True and cfg["missing"] == [] and cfg["keystore"] == "demo"


def test_unlock_refuses_when_not_ready_or_no_password(no_env):
    with pytest.raises(PublishError, match="MONAD_RPC_URL"):
        app_actions.unlock("pw")
    ready = {"ready": True, "missing": [], "rpc": "http://127.0.0.1:1", "keystore": "x"}
    with pytest.raises(PublishError, match="Type the keystore password"):
        app_actions.unlock("", ready)
    with pytest.raises(PublishError, match="Can't reach the chain"):
        app_actions.unlock("pw", ready)


def test_network_names_and_explorer_links():
    assert app_actions.network_name(10143) == "Monad testnet"
    assert app_actions.network_name(31337) == "local test chain (id 31337)"
    monad = {"chain_id": 10143, "explorer_url": "https://x/address/0xF", "tx_url": "https://x/tx/0x1"}
    assert app_actions.explorer_links(monad) == {"fund": "https://x/address/0xF", "tx": "https://x/tx/0x1"}
    assert app_actions.explorer_links({**monad, "chain_id": 31337}) == {}


# ---- the whole on-chain flow, on a local chain ----

def _basket_tickers(n=3):
    """Real stocks from the exposure table that fit 'want AI, avoid Oil', so the mandate can pass."""
    table = builder.prescreen()
    fits = [t for t, r in sorted(table.items())
            if r["ai"]["tier"] in (HIGH, MODERATE) and r["oil"]["tier"] in (LIMITED, LIMITED_LOW)]
    assert len(fits) >= n
    return fits[:n]


@pytest.fixture(scope="module")
def local_chain():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(["anvil", "--port", str(port), "--silent"])
    try:
        rpc = f"http://127.0.0.1:{port}"
        w3 = Web3(Web3.HTTPProvider(rpc))
        for _ in range(100):
            if w3.is_connected():
                break
            time.sleep(0.1)
        owner = w3.eth.account.create()
        w3.provider.make_request("anvil_setBalance", [owner.address, hex(10**20)])

        def deploy(name, *ctor):
            art = json.loads((OUT / f"{name}.sol" / f"{name}.json").read_text())
            contract = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
            tx = contract.constructor(*ctor).build_transaction(
                {"from": owner.address, "nonce": w3.eth.get_transaction_count(owner.address),
                 "chainId": w3.eth.chain_id})
            receipt = w3.eth.wait_for_transaction_receipt(
                w3.eth.send_raw_transaction(owner.sign_transaction(tx).raw_transaction))
            assert receipt.status == 1
            return receipt.contractAddress

        oracle = deploy("ExposureOracle")
        exchange = deploy("MockExchange", oracle)
        factory = deploy("ThemeFundFactory", exchange)
        yield {"rpc": rpc, "owner": owner, "factory": factory}
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@needs_chain
def test_dashboard_flow_end_to_end(local_chain, no_env, monkeypatch):
    # A password-protected keystore, like `cast wallet import` makes.
    keystore = no_env / "demo-keystore.json"
    keystore.write_text(json.dumps(local_chain["owner"].encrypt("correct horse")))
    monkeypatch.setenv("MONAD_RPC_URL", local_chain["rpc"])
    monkeypatch.setenv("FACTORY_ADDRESS", local_chain["factory"])
    monkeypatch.setenv("DEPLOYER_KEYSTORE", str(keystore))
    monkeypatch.setattr(launch, "FUND_FILE", no_env / "fund_latest.json")
    # Fixed prices instead of market data, so the test needs no internet.
    monkeypatch.setattr(publish, "price_frames",
                        lambda tickers, f, r: [("2026-11-13", {t: 100.0 for t in tickers})])

    cfg = app_actions.config()
    assert cfg["ready"], cfg["missing"]
    with pytest.raises(PublishError, match="Wrong keystore password"):
        app_actions.unlock("wrong", cfg)
    w3, account = app_actions.unlock("correct horse", cfg)
    assert account.address == local_chain["owner"].address

    tickers = _basket_tickers()
    build = {"preferences": {"ai": "want", "oil": "avoid"},
             "holdings": [{"ticker": t, "weight_pct": round(100 / len(tickers), 2)} for t in tickers]}

    published = app_actions.publish_basket(build, w3, account, cfg)
    assert set(published["stocks"]) == {*tickers, "XOM"}
    assert published["tiers_posted"] == published["tiers_total"] == 2 * (len(tickers) + 1)
    again = app_actions.publish_basket(build, w3, account, cfg)  # re-running only refreshes prices
    assert again["tiers_posted"] == 0

    fund = app_actions.launch_basket(build, w3, account, cfg=cfg)
    assert Web3.is_address(fund["address"]) and fund["name"] == "AI ex-Oil Fund" and fund["symbol"] == "AIXO"
    assert fund["network"].startswith("local test chain") and app_actions.explorer_links(fund) == {}
    assert json.loads(launch.FUND_FILE.read_text())["address"] == fund["address"]

    dep = app_actions.deposit_dollars(fund["address"], 1000, w3, account, cfg)
    assert dep["nav_usd"] == pytest.approx(1000, rel=0.01)
    assert dep["shares"] == pytest.approx(1000, rel=0.01)  # first deposit: 1 share = $1

    allowed, reason = app_actions.try_adding(fund["address"], "XOM", cfg)
    assert allowed is False and reason == "Mandate: Oil exposure too high"


@needs_chain
def test_launch_with_unpublished_stocks_says_what_to_do(local_chain, no_env, monkeypatch):
    keystore = no_env / "k.json"
    keystore.write_text(json.dumps(local_chain["owner"].encrypt("pw")))
    monkeypatch.setenv("MONAD_RPC_URL", local_chain["rpc"])
    monkeypatch.setenv("FACTORY_ADDRESS", local_chain["factory"])
    monkeypatch.setenv("DEPLOYER_KEYSTORE", str(keystore))
    w3, account = app_actions.unlock("pw")
    build = {"preferences": {"ai": "want"}, "holdings": [{"ticker": "ZZZQ", "weight_pct": 100.0}]}
    with pytest.raises(PublishError, match="Not on the exchange yet: ZZZQ"):
        app_actions.launch_basket(build, w3, account)


@needs_chain
def test_reposting_many_prices_back_to_back_has_enough_gas(local_chain):
    """Gas estimates come up 2,800 short per already-posted price (see GAS_PER_TIMESTAMPED_ITEM);
    40 prices re-posted right after each other used to fail with 'out of gas'."""
    w3 = Web3(Web3.HTTPProvider(local_chain["rpc"]))
    chain = publish.Publisher(w3, local_chain["factory"], local_chain["owner"], log=lambda _m: None)
    prices = {f"T{i}": 100.0 + i for i in range(40)}
    for bump in range(3):
        chain.post_prices({t: p + bump for t, p in prices.items()}, f"round {bump}")
    oracle_price, _ = chain.oracle.functions.priceOf(publish.to_bytes32("T39")).call()
    assert oracle_price == publish.price_to_chain(141.0)


@needs_chain
def test_an_approved_friend_can_publish_but_a_stranger_cannot(local_chain):
    w3 = Web3(Web3.HTTPProvider(local_chain["rpc"]))
    owner, friend, stranger = local_chain["owner"], w3.eth.account.create(), w3.eth.account.create()
    for acct in (friend, stranger):
        w3.provider.make_request("anvil_setBalance", [acct.address, hex(10**20)])
    as_owner = publish.Publisher(w3, local_chain["factory"], owner, log=lambda _m: None)
    as_owner.send(as_owner.oracle.functions.setPublisher(friend.address, True), "approve friend (oracle)")
    as_owner.send(as_owner.exchange.functions.setPublisher(friend.address, True), "approve friend (exchange)")

    with pytest.raises(PublishError, match="isn't allowed to publish to the oracle"):
        publish.Publisher(w3, local_chain["factory"], stranger)
    as_friend = publish.Publisher(w3, local_chain["factory"], friend, log=lambda _m: None)
    as_friend.list_stocks(["FRND"])
    as_friend.post_prices({"FRND": 42.0})
    price, _ = as_friend.oracle.functions.priceOf(publish.to_bytes32("FRND")).call()
    assert price == publish.price_to_chain(42.0)
