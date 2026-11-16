"""Tests for chain/launch.py. The chain tests reuse the local test chain from tests/test_publish.py."""

import json
from argparse import Namespace

import pytest

from chain import launch, publish
from chain.abi import FUND_ABI
from chain.publish import PublishError
from tests.test_publish import (  # noqa: F401  (chain is a fixture)
    PRICES,
    REPORT,
    chain,
    needs_chain,
)

NAMES = {"ai": "AI", "oil": "Oil", "gold": "Gold"}
BUILD = {
    "preferences": {"oil": "avoid", "ai": "want"},
    "holdings": [{"ticker": "NVDA", "weight_pct": 80.0}, {"ticker": "CASH", "weight_pct": 20.0}],
}


def args(tmp_path, **overrides):
    build = tmp_path / "build.json"
    build.write_text(json.dumps(overrides.pop("build_data", BUILD)))
    base = {"build": str(build), "name": None, "symbol": None, "want_min_pct": 60.0, "deposit": None,
            "try_add": None, "dry_run": False, "keystore": "deployer"}
    return Namespace(**{**base, **overrides})


# ---------------------------------------------------------------------------------------------
# Turning a builder result into a launch plan
# ---------------------------------------------------------------------------------------------

def test_weights_to_bps_basic_and_cash_left_out():
    assert launch.weights_to_bps(BUILD["holdings"]) == {"NVDA": 8000}
    assert launch.weights_to_bps([{"ticker": "A", "weight_pct": 33.339}, {"ticker": "B", "weight_pct": "12.5"}]) == {
        "A": 3333, "B": 1250}


def test_weights_to_bps_trims_the_builders_rounding_excess():
    # The real AI ex-Oil basket: five at 14.29% and four at 7.14% add up to 100.01%.
    holdings = [{"ticker": f"H{i}", "weight_pct": 14.29} for i in range(5)]
    holdings += [{"ticker": f"M{i}", "weight_pct": 7.14} for i in range(4)]
    bps = launch.weights_to_bps(holdings)
    assert sum(bps.values()) == 10_000
    assert bps["H0"] == 1428 and bps["H1"] == 1429 and bps["M0"] == 714   # one unit off the largest only


@pytest.mark.parametrize("holdings, message", [
    ([{"ticker": "CASH", "weight_pct": 100}], "no stocks"),
    ([{"ticker": "A", "weight_pct": 0.001}], "too small"),
    ([{"ticker": "A", "weight_pct": 60}, {"ticker": "A", "weight_pct": 10}], "appears twice"),
    ([{"ticker": "A", "weight_pct": 60}, {"ticker": "B", "weight_pct": 50}], "more than 100%"),
])
def test_weights_to_bps_rejects_bad_baskets(holdings, message):
    with pytest.raises(PublishError, match=message):
        launch.weights_to_bps(holdings)


def test_mandate_rules():
    rules = launch.mandate_rules({"oil": "avoid", "ai": "want", "gold": "want"}, NAMES, 10_000, 60)
    assert [(r["theme"], r["kind"], r["min_bps"]) for r in rules] == [
        ("ai", launch.WANT, 6000), ("gold", launch.WANT, 6000), ("oil", launch.AVOID, 0)]
    assert rules[2]["label"] == "Oil"
    # A cash-heavy basket can't hold 60% in anything, so the minimum falls to what is invested.
    assert launch.mandate_rules({"ai": "want"}, NAMES, 4500, 60)[0]["min_bps"] == 4500


@pytest.mark.parametrize("prefs, pct, message", [
    ({}, 60, "no want/avoid preferences"),
    ({"silver": "want"}, 60, "No theme called 'silver'"),
    ({"ai": "maybe"}, 60, "must be 'want' or 'avoid'"),
    ({"ai": "want"}, 0, "--want-min-pct"),
    ({"ai": "want"}, 101, "--want-min-pct"),
])
def test_mandate_rules_reject_bad_input(prefs, pct, message):
    with pytest.raises(PublishError, match=message):
        launch.mandate_rules(prefs, NAMES, 10_000, pct)


def test_default_name_and_symbol():
    assert launch.default_name_and_symbol({"ai": "want", "oil": "avoid"}, NAMES) == ("AI ex-Oil Fund", "AIXO")
    assert launch.default_name_and_symbol({"ai": "want", "gold": "want"}, NAMES) == ("AI + Gold Fund", "AIGO")
    assert launch.default_name_and_symbol({"oil": "avoid"}, NAMES) == ("ex-Oil Fund", "XO")


def test_plan_from_build_and_text():
    plan = launch.plan_from_build(BUILD, None, None, 60)
    assert plan["name"] == "AI ex-Oil Fund" and plan["symbol"] == "AIXO"
    assert plan["weights_bps"] == {"NVDA": 8000} and plan["cash_bps"] == 2000
    text = launch.plan_text(plan)
    assert "Fund: AI ex-Oil Fund ($AIXO)" in text
    assert "NVDA    80.00%" in text and "CASH    20.00%" in text
    assert "Want AI: at least 60% of the fund in High or Moderate names" in text
    assert "Avoid Oil: every holding must be Limited or Limited (lower confidence)" in text

    assert launch.plan_from_build(BUILD, "My Fund", "mine", 60)["symbol"] == "MINE"
    with pytest.raises(PublishError, match="letters and digits only"):
        launch.plan_from_build(BUILD, None, "AI-XO", 60)
    with pytest.raises(PublishError, match="doesn't look like a builder result"):
        launch.plan_from_build({"holdings": []}, None, None, 60)


def test_revert_reason():
    assert launch.revert_reason(Exception("execution reverted: Mandate: Oil exposure too high")) == (
        "Mandate: Oil exposure too high")
    assert "without a reason" in launch.revert_reason(Exception("execution reverted: "))


def test_dry_run_and_errors_from_the_command_line(tmp_path, capsys, monkeypatch):
    a = args(tmp_path)
    assert launch.main(["--build", a.build, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "AIXO" in out and "Dry run: nothing was sent." in out

    monkeypatch.delenv("MONAD_RPC_URL", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    assert launch.main(["--build", a.build]) == 2
    assert "MONAD_RPC_URL isn't set" in capsys.readouterr().err
    assert launch.main(["--build", str(tmp_path / "missing.json")]) == 2
    assert "doesn't exist" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------
# With the real contracts on a local chain (anvil)
# ---------------------------------------------------------------------------------------------

@pytest.fixture
def published(chain, tmp_path, monkeypatch):  # noqa: F811
    """The local chain with NVDA and XOM listed, priced and tiered, as chain/publish.py leaves it."""
    report, prices = tmp_path / "screen.json", tmp_path / "prices.json"
    report.write_text(json.dumps(REPORT))
    prices.write_text(json.dumps(PRICES))
    monkeypatch.setenv("FACTORY_ADDRESS", chain["factory"])
    monkeypatch.setattr(launch, "FUND_FILE", tmp_path / "fund_latest.json")
    pub_args = Namespace(build=str(publish.DEFAULT_BUILD), report=str(report), extra=None, themes=None,
                         prices_file=str(prices), replay=1, interval=0.0, dry_run=False, keystore="deployer")
    publish.run(pub_args, log=lambda *_: None, account=chain["owner"], w3=chain["w3"])
    return chain


@needs_chain
def test_launch_deposit_and_rejection_end_to_end(published, tmp_path):
    w3, owner, logs = published["w3"], published["owner"], []
    a = args(tmp_path, deposit=1000.0, try_add="xom")

    assert launch.run(a, log=logs.append, account=owner, w3=w3) == 0
    text = "\n".join(logs)

    saved = json.loads((tmp_path / "fund_latest.json").read_text())
    fund = w3.eth.contract(address=saved["address"], abi=FUND_ABI)
    assert fund.functions.symbol().call() == "AIXO"
    assert fund.functions.name().call() == "AI ex-Oil Fund"
    assert fund.functions.manager().call() == owner.address
    assert saved["explorer_url"].endswith(saved["address"])
    assert saved["weights_bps"] == {"NVDA": 8000} and saved["chain_id"] == w3.eth.chain_id

    # $1,000 in: 1,000 shares at $1, and the fund is worth $1,000 (80% NVDA, 20% cash).
    assert fund.functions.balanceOf(owner.address).call() == 1000 * 10**18
    assert abs(fund.functions.nav().call() - 1000 * 10**6) <= 10
    assert "You now hold 1,000.00 $AIXO" in text

    # The demo moment: XOM is High for oil, so the Avoid-Oil mandate refuses it. Nothing was traded.
    assert "Adding XOM is REJECTED by the fund: Mandate: Oil exposure too high" in text
    assert len(fund.functions.basket().call()[0]) == 1

    # A second deposit reuses the wallet's test dollars and mints at NAV.
    chain_helper = publish.Publisher(w3, published["factory"], owner, lambda *_: None, require_owner=False)
    second = launch.deposit(chain_helper, saved["address"], 250)
    assert abs(second["shares"] - 250) < 1e-6 and abs(second["nav_usd"] - 1250) < 1e-3

    # try_add on its own, and for a stock the mandate allows at a small weight... there is none here,
    # so check the allowed path with a fund that has no Avoid rule.
    assert launch.try_add(chain_helper, saved["address"], "XOM") == (False, "Mandate: Oil exposure too high")
    free = launch.launch_fund(chain_helper, launch.plan_from_build(
        {"preferences": {"ai": "want"}, "holdings": BUILD["holdings"]}, "AI Fund", "AIF", 60))
    assert launch.try_add(chain_helper, free["address"], "XOM", 5) == (True, "")
    assert launch.try_add(chain_helper, free["address"], "XOM", 50) == (False, "Mandate: AI exposure too low")


@needs_chain
def test_launch_refuses_a_basket_that_breaks_its_own_mandate(published, tmp_path):
    bad = {"preferences": {"ai": "want", "oil": "avoid"},
           "holdings": [{"ticker": "NVDA", "weight_pct": 70}, {"ticker": "XOM", "weight_pct": 30}]}
    with pytest.raises(PublishError, match="can't be launched: Mandate: Oil exposure too high"):
        launch.run(args(tmp_path, build_data=bad), log=lambda *_: None, account=published["owner"], w3=published["w3"])
    assert not (tmp_path / "fund_latest.json").exists()


@needs_chain
def test_launch_needs_published_stocks_and_sane_deposits(published, tmp_path):
    w3, owner = published["w3"], published["owner"]
    unlisted = {"preferences": {"ai": "want"}, "holdings": [{"ticker": "JNJ", "weight_pct": 100}]}
    with pytest.raises(PublishError, match="Not on the exchange yet: JNJ"):
        launch.run(args(tmp_path, build_data=unlisted), log=lambda *_: None, account=owner, w3=w3)

    chain_helper = publish.Publisher(w3, published["factory"], owner, lambda *_: None, require_owner=False)
    fund = launch.launch_fund(chain_helper, launch.plan_from_build(BUILD, None, "AIX2", 60))
    with pytest.raises(PublishError, match="at least \\$1"):
        launch.deposit(chain_helper, fund["address"], 0.5)
    with pytest.raises(PublishError, match="Not on the exchange yet: JNJ"):
        launch.try_add(chain_helper, fund["address"], "JNJ")
