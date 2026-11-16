"""Tests for chain/publish.py.

The first half needs nothing but Python. The second half runs the real contracts on a local test chain
(Foundry's `anvil`) and is skipped automatically if anvil or the compiled contracts aren't available
(run `forge build` in contracts/ first).
"""

import json
import shutil
import socket
import subprocess
import time
from argparse import Namespace
from pathlib import Path

import pytest
from web3 import Web3

from chain import publish
from chain.abi import EXCHANGE_ABI, FACTORY_ABI, FUND_ABI, ORACLE_ABI, USDC_ABI
from chain.publish import PublishError

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "contracts" / "out"
WINDOW = {"start": "2024-11-15", "end": "2026-11-14"}


def result(tier, method="regression", beta=0.5):
    """A cut-down engine result, shaped like engine/regression.py's Result.to_dict()."""
    return {
        "ticker": "X", "theme": "Name", "tier": tier, "method": method, "sentence": "…",
        "groups": {"High": {"names": ["A", "B"], "beta_sum": beta, "se": 0.1, "p_one_sided": 0.001,
                            "upper_95": beta + 0.1645, "eligible": True}},
        "n_obs": 500, "r_squared": 0.4, "p_threshold": 0.00625, "controls": ["SPY", "TLT"],
    }


RESULTS = {
    "NVDA": {"ai": result("High", "listed reference"), "oil": result("Limited", beta=-0.1)},
    "XOM": {"ai": result("Limited (lower confidence)", beta=0.01), "oil": result("High", beta=0.9)},
}
REPORT = {
    "window": WINDOW,
    "holdings": [
        {"ticker": "NVDA", "weight_pct": 50, "results": RESULTS["NVDA"]},
        {"ticker": "XOM", "weight_pct": 30, "results": RESULTS["XOM"]},
        {"ticker": "CASH", "weight_pct": 20, "results": "cash: kept at its weight, not scored"},
    ],
}
PRICES = {"NVDA": 187.42, "XOM": 109.05}


def args(**overrides):
    base = {"build": str(publish.DEFAULT_BUILD), "report": None, "extra": None, "themes": None,
            "prices_file": None, "replay": 1, "interval": 0.0, "dry_run": False, "keystore": "deployer"}
    return Namespace(**{**base, **overrides})


# ---------------------------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------------------------

def test_to_bytes32_matches_solidity():
    assert publish.to_bytes32("NVDA") == b"NVDA" + b"\0" * 28
    assert publish.to_bytes32("bank_lending")[:12] == b"bank_lending"
    assert len(publish.to_bytes32("A" * 32)) == 32


@pytest.mark.parametrize("bad", ["", "A" * 33, "NVDÄ"])
def test_to_bytes32_rejects_bad_keys(bad):
    with pytest.raises(PublishError):
        publish.to_bytes32(bad)


@pytest.mark.parametrize("price, expected", [
    (187.42, 18_742_000_000), ("109.05", 10_905_000_000), (0.1 + 0.2, 30_000_000), (1, 100_000_000),
    (0.000000015, 2), (1_000_000, 100_000_000_000_000),
])
def test_price_to_chain(price, expected):
    assert publish.price_to_chain(price) == expected


@pytest.mark.parametrize("bad", [0, -5, "abc", None, float("nan"), float("inf")])
def test_price_to_chain_rejects_bad_prices(bad):
    with pytest.raises(PublishError):
        publish.price_to_chain(bad)


def test_tier_codes_cover_the_five_tiers_in_contract_order():
    assert publish.TIER_CODES == {"High": 1, "Moderate": 2, "Limited": 3, "Limited (lower confidence)": 4,
                                  "Not determined": 5}


def test_hashes_are_stable_and_sensitive():
    base = publish.hashes_for("NVDA", "ai", result("High"), WINDOW)
    assert base == publish.hashes_for("NVDA", "ai", result("High"), WINDOW)       # same input, same hashes
    assert all(len(h) == 32 for h in base)

    other_stats = publish.hashes_for("NVDA", "ai", result("High", beta=0.51), WINDOW)
    assert other_stats[0] == base[0] and other_stats[1] != base[1]                # only the stats changed

    other_window = publish.hashes_for("NVDA", "ai", result("High"), {"start": "2024-11-16", "end": "2026-11-14"})
    assert other_window[0] != base[0] and other_window[1] == base[1]              # only the data changed

    assert publish.hashes_for("MSFT", "ai", result("High"), WINDOW)[0] != base[0]
    assert publish.hashes_for("NVDA", "oil", result("High"), WINDOW)[0] != base[0]

    reordered = dict(reversed(list(result("High").items())))                      # key order doesn't matter
    assert publish.hashes_for("NVDA", "ai", reordered, WINDOW) == base


def test_hashes_handle_listed_stocks_with_no_regression():
    listed = {"ticker": "NVDA", "theme": "AI", "tier": "High", "method": "listed reference", "groups": {},
              "n_obs": None, "r_squared": None, "p_threshold": None, "controls": []}
    assert all(len(h) == 32 for h in publish.hashes_for("NVDA", "ai", listed, WINDOW))


def test_exposure_rows():
    rows = publish.exposure_rows(RESULTS, WINDOW)
    assert [(r["ticker"], r["theme"], r["code"]) for r in rows] == [
        ("NVDA", "ai", 1), ("NVDA", "oil", 3), ("XOM", "ai", 4), ("XOM", "oil", 1)]


def test_exposure_rows_reject_unknown_tier():
    with pytest.raises(PublishError, match="unknown tier 'Inverse'"):
        publish.exposure_rows({"NVDA": {"ai": {"tier": "Inverse"}}}, WINDOW)


# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------

def test_results_from_report_skips_cash():
    results, window = publish.results_from_report(REPORT)
    assert sorted(results) == ["NVDA", "XOM"] and window == WINDOW


@pytest.mark.parametrize("bad", [{}, {"holdings": "x", "window": WINDOW}, {"window": WINDOW, "holdings": [
    {"ticker": "CASH", "results": "cash"}]}])
def test_results_from_report_rejects_other_files(bad):
    with pytest.raises(PublishError):
        publish.results_from_report(bad)


def test_results_from_build(monkeypatch):
    from engine import builder
    table = {**RESULTS, "JNJ": {"ai": result("Limited"), "oil": result("Limited"), "gold": result("Limited")}}
    monkeypatch.setattr(builder, "prescreen", lambda: table)
    build = {"preferences": {"ai": "want", "oil": "avoid"},
             "holdings": [{"ticker": "NVDA"}, {"ticker": "CASH"}]}

    results, window = publish.results_from_build(build, ["xom"], None)
    assert sorted(results) == ["NVDA", "XOM"]
    assert sorted(results["NVDA"]) == ["ai", "oil"]
    assert set(window) == {"start", "end"}

    results, _ = publish.results_from_build(build, [], ["oil"])
    assert results == {"NVDA": {"oil": RESULTS["NVDA"]["oil"]}}

    with pytest.raises(PublishError, match="Not in the builder's universe.*ZZZZ"):
        publish.results_from_build(build, ["ZZZZ"], None)
    with pytest.raises(PublishError, match="No results for theme"):
        publish.results_from_build(build, [], ["gold"])
    with pytest.raises(PublishError, match="doesn't look like a builder result"):
        publish.results_from_build({"holdings": []}, [], None)
    with pytest.raises(PublishError, match="no stocks"):
        publish.results_from_build({"preferences": {}, "holdings": [{"ticker": "CASH"}]}, [], None)


def test_price_frames_from_file(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"nvda": 187.42, "XOM": 109.05, "OTHER": 1}))
    assert publish.price_frames(["NVDA", "XOM"], f, 1) == [("prices file", PRICES)]
    with pytest.raises(PublishError, match="no price for: JNJ"):
        publish.price_frames(["NVDA", "JNJ"], f, 1)


def test_price_frames_latest_and_replay(monkeypatch):
    import pandas as pd

    from engine import data
    frame = pd.DataFrame({"NVDA": [100.0, 110.0, 120.0], "XOM": [50.0, 51.0, 52.0]},
                         index=pd.to_datetime(["2026-11-11", "2026-11-12", "2026-11-13"]))
    monkeypatch.setattr(data, "get_prices", lambda tickers: (frame[tickers], {}))

    assert publish.price_frames(["NVDA", "XOM"], None, 1) == [("2026-11-13", {"NVDA": 120.0, "XOM": 52.0})]
    replay = publish.price_frames(["NVDA"], None, 2)
    assert replay == [("2026-11-12", {"NVDA": 110.0}), ("2026-11-13", {"NVDA": 120.0})]
    assert len(publish.price_frames(["NVDA"], None, 10)) == 3  # asks for more days than exist

    def boom(tickers):
        raise data.DataError("No price data from FMP or Yahoo for: NVDA")
    monkeypatch.setattr(data, "get_prices", boom)
    with pytest.raises(PublishError, match="Couldn't load prices"):
        publish.price_frames(["NVDA"], None, 1)


def test_read_json_errors(tmp_path):
    with pytest.raises(PublishError, match="doesn't exist"):
        publish._read_json(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(PublishError, match="isn't valid JSON"):
        publish._read_json(bad)


# ---------------------------------------------------------------------------------------------
# Command line, without a chain
# ---------------------------------------------------------------------------------------------

@pytest.fixture
def files(tmp_path):
    report, prices = tmp_path / "screen.json", tmp_path / "prices.json"
    report.write_text(json.dumps(REPORT))
    prices.write_text(json.dumps(PRICES))
    return report, prices


def test_dry_run_prints_plan_and_sends_nothing(files, capsys):
    report, prices = files
    code = publish.main(["--report", str(report), "--prices-file", str(prices), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "XOM    oil            High" in out
    assert "NVDA   $187.42" in out
    assert "Dry run: nothing was sent." in out


def test_themes_filter(files, capsys):
    report, prices = files
    publish.main(["--report", str(report), "--prices-file", str(prices), "--dry-run", "--themes", "oil"])
    out = capsys.readouterr().out
    assert "oil" in out and " ai " not in out


def test_clear_errors_from_the_command_line(files, capsys, monkeypatch):
    report, prices = files
    monkeypatch.delenv("MONAD_RPC_URL", raising=False)
    monkeypatch.delenv("FACTORY_ADDRESS", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    base = ["--report", str(report), "--prices-file", str(prices)]

    assert publish.main(base) == 2
    assert "MONAD_RPC_URL isn't set" in capsys.readouterr().err

    monkeypatch.setenv("MONAD_RPC_URL", "http://127.0.0.1:9")
    assert publish.main(base) == 2
    assert "FACTORY_ADDRESS isn't set" in capsys.readouterr().err

    assert publish.main(base + ["--extra", "JNJ", "--dry-run"]) == 2
    assert "--extra only works with a built fund" in capsys.readouterr().err

    assert publish.main(base + ["--themes", "gold", "--dry-run"]) == 2
    assert "Nothing to publish" in capsys.readouterr().err

    assert publish.main(["--report", str(report.with_name("missing.json")), "--dry-run"]) == 2
    assert "doesn't exist" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        publish.main(base + ["--replay", "0"])


def test_bad_price_stops_before_anything_is_sent(files, capsys):
    report, prices = files
    prices.write_text(json.dumps({"NVDA": 187.42, "XOM": -1}))
    assert publish.main(["--report", str(report), "--prices-file", str(prices), "--dry-run"]) == 2
    assert "must be a positive number" in capsys.readouterr().err


def test_keystore_loading(tmp_path):
    w3 = Web3()
    acct = w3.eth.account.create()
    path = tmp_path / "deployer"
    path.write_text(json.dumps(w3.eth.account.encrypt(acct.key, "correct horse", kdf="pbkdf2", iterations=1000)))

    assert publish.load_account(w3, str(path), "correct horse").address == acct.address
    with pytest.raises(PublishError, match="Wrong keystore password"):
        publish.load_account(w3, str(path), "wrong")
    with pytest.raises(PublishError, match="No keystore"):
        publish.load_account(w3, str(tmp_path / "missing"), "x")


# ---------------------------------------------------------------------------------------------
# With the real contracts on a local chain (anvil)
# ---------------------------------------------------------------------------------------------

def _artifact(name):
    return json.loads((OUT / f"{name}.sol" / f"{name}.json").read_text())


needs_chain = pytest.mark.skipif(
    shutil.which("anvil") is None or not (OUT / "ThemeFundFactory.sol").exists(),
    reason="needs Foundry's anvil on PATH and `forge build` run in contracts/",
)


@pytest.fixture(scope="module")
def chain():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(["anvil", "--port", str(port), "--silent"])
    try:
        w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}"))
        for _ in range(100):
            if w3.is_connected():
                break
            time.sleep(0.1)
        else:
            pytest.fail("anvil didn't start")
        owner = w3.eth.account.create()  # a throwaway wallet, funded by the test chain
        w3.provider.make_request("anvil_setBalance", [owner.address, hex(10**20)])

        def deploy(name, *ctor):
            art = _artifact(name)
            contract = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
            tx = contract.constructor(*ctor).build_transaction(
                {"from": owner.address, "nonce": w3.eth.get_transaction_count(owner.address), "chainId": w3.eth.chain_id})
            receipt = w3.eth.wait_for_transaction_receipt(
                w3.eth.send_raw_transaction(owner.sign_transaction(tx).raw_transaction))
            assert receipt.status == 1
            return receipt.contractAddress

        oracle = deploy("ExposureOracle")
        exchange = deploy("MockExchange", oracle)
        factory = deploy("ThemeFundFactory", exchange)
        yield {"w3": w3, "owner": owner, "oracle": oracle, "exchange": exchange, "factory": factory}
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@needs_chain
def test_hand_written_abis_match_the_compiled_contracts():
    def signature(f):
        if f["type"] == "event":
            return ("event", f["name"], tuple((i["type"], i["indexed"]) for i in f["inputs"]))
        return (f["name"], tuple(i["type"] for i in f["inputs"]), tuple(o["type"] for o in f["outputs"]),
                f["stateMutability"])

    pairs = (("ExposureOracle", ORACLE_ABI), ("MockExchange", EXCHANGE_ABI), ("ThemeFundFactory", FACTORY_ABI),
             ("ThemeFund", FUND_ABI), ("MockUSDC", USDC_ABI))
    for name, abi in pairs:
        compiled = {signature(f) for f in _artifact(name)["abi"] if f["type"] in ("function", "event")}
        for f in abi:
            assert signature(f) in compiled, f"{name}.{f['name']} in chain/abi.py doesn't match the contract"


@needs_chain
def test_publish_end_to_end(chain, files, monkeypatch):
    report, prices = files
    monkeypatch.setenv("FACTORY_ADDRESS", chain["factory"])
    w3, logs = chain["w3"], []
    a = args(report=str(report), prices_file=str(prices))

    assert publish.run(a, log=logs.append, account=chain["owner"], w3=w3) == 0

    oracle = w3.eth.contract(address=chain["oracle"], abi=ORACLE_ABI)
    exchange = w3.eth.contract(address=chain["exchange"], abi=EXCHANGE_ABI)
    key = publish.to_bytes32

    # Both stocks now have a test token, a price and their tiers.
    assert len(exchange.functions.allStocks().call()) == 2
    assert int(exchange.functions.stockOf(key("XOM")).call(), 16) != 0
    price, stamp = oracle.functions.priceOf(key("NVDA")).call()
    assert price == 18_742_000_000 and stamp > 0
    assert oracle.functions.tierOf(key("XOM"), key("oil")).call() == 1      # High
    assert oracle.functions.tierOf(key("NVDA"), key("oil")).call() == 3     # Limited
    assert oracle.functions.tierOf(key("XOM"), key("ai")).call() == 4       # Limited (lower confidence)
    assert oracle.functions.tierOf(key("NVDA"), key("gold")).call() == 0    # never posted

    # The on-chain hashes are exactly what hashes_for() gives: this is the audit trail.
    _, baseline, stats, _ = oracle.functions.exposureOf(key("XOM"), key("oil")).call()
    assert (bytes(baseline), bytes(stats)) == publish.hashes_for("XOM", "oil", RESULTS["XOM"]["oil"], WINDOW)

    # Running it again lists nothing new and re-posts no tiers, only fresh prices.
    logs.clear()
    assert publish.run(a, log=logs.append, account=chain["owner"], w3=w3) == 0
    text = "\n".join(logs)
    assert "tiers already up to date" in text and "listed" not in text and "posted 2 price(s)" in text

    # A changed result is picked up and only that row is re-posted.
    changed = json.loads(report.read_text())
    changed["holdings"][1]["results"]["oil"]["tier"] = "Moderate"
    report.write_text(json.dumps(changed))
    logs.clear()
    publish.run(a, log=logs.append, account=chain["owner"], w3=w3)
    assert "posted 1 tier(s)" in "\n".join(logs)
    assert oracle.functions.tierOf(key("XOM"), key("oil")).call() == 2      # Moderate


@needs_chain
def test_publisher_guards(chain):
    w3 = chain["w3"]
    stranger = w3.eth.account.create()
    with pytest.raises(PublishError, match="isn.t allowed to publish to the oracle"):
        publish.Publisher(w3, chain["factory"], stranger)
    with pytest.raises(PublishError, match="isn't a valid address"):
        publish.Publisher(w3, "0x123", chain["owner"])
    with pytest.raises(PublishError, match="Nothing is deployed"):
        publish.Publisher(w3, stranger.address, chain["owner"])
    with pytest.raises(PublishError, match="No wallet loaded"):
        publish.Publisher(w3, chain["factory"]).post_prices(PRICES)
    with pytest.raises(PublishError, match="Can't reach the chain"):
        publish.Publisher(Web3(Web3.HTTPProvider("http://127.0.0.1:9")), chain["factory"])
