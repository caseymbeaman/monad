"""Click-through tests for the Streamlit dashboard (app.py) with fake engine and chain results
(no internet, no chain)."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from chain import app_actions
from engine import assistant, builder, monte_carlo, risk, screen, shocks
from engine.regression import HIGH, LIMITED, LIMITED_LOW, MODERATE
from engine.theme_loader import load_all

THEMES = load_all()
APP = str(Path(__file__).resolve().parent.parent / "app.py")
SEEN = {}


def fake_build(prefs, region="all"):
    SEEN["build"] = (prefs, region)
    return {
        "preferences": prefs, "region": region, "universe_size": 650,
        "funnel": [{"step": "Universe (scored stocks)", "left": 650},
                   {"step": "Want AI: High or Moderate", "left": 40}],
        "holdings": [{"ticker": "AAA", "weight_pct": 60.0, "tiers": {"AI": HIGH}, "labels": []},
                     {"ticker": "BBB", "weight_pct": 40.0, "tiers": {"AI": MODERATE},
                      "labels": ["Oil: lower confidence"]}],
        "cash_pct": 0.0, "warnings": ["Only 2 holdings."],
        "verification": {"all_pass": False, "checks": {
            "ai": {"theme": "AI", "choice": "want", "goal": "g", "pass": True, "sentence": "100% is AI."},
            "oil": {"theme": "Oil", "choice": "avoid", "goal": "g", "pass": False, "sentence": "Some oil."}}},
    }


def _result(tier):
    return {"tier": tier, "sentence": f"It is {tier}.", "method": "regression", "n_obs": 499, "r_squared": 0.4,
            "controls": ["SPY"], "p_threshold": 0.01,
            "groups": {"High": {"names": ["R1"], "beta_sum": 0.01, "se": 0.02, "p_one_sided": 0.3,
                                "upper_95": 0.04, "eligible": False}}}


def fake_table():
    table = {t: {k: _result(LIMITED) for k in THEMES} for t in ("AAA", "BBB")}
    table["AAA"]["ai"] = _result(HIGH)
    table["BBB"]["ai"] = _result(MODERATE)
    return table


def fake_screen(holdings, themes=None):
    total = sum(holdings.values())
    weights = {t.upper(): 100 * w / total for t, w in holdings.items()}
    results = {t: {k: {**_result(HIGH if (t, k) == ("NVDA", "ai") else LIMITED), "theme": th["name"]}
                   for k, th in THEMES.items()} for t in weights if t != "CASH"}
    results["NVDA"]["gold"] = {"tier": "Not determined", "theme": "Gold & precious metals",
                               "error": "no data", "sentence": "couldn't be screened"}
    report = {"window": {"start": "2024-11-15", "end": "2026-11-14"},
              "weights_rescaled_to_100": abs(total - 100) > 1e-6, "cash_pct": weights.get("CASH", 0.0),
              "holdings": [{"ticker": t, "weight_pct": w,
                            "results": "cash: kept at its weight, not scored" if t == "CASH" else results[t]}
                           for t, w in weights.items()]}
    report["fingerprint"] = screen.fingerprint(weights, results, THEMES)
    return report


def fake_risk(holdings):
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-11-15", periods=300)
    stocks = [t for t in holdings if t != "CASH"]
    r = pd.DataFrame({"SPY": rng.normal(0.0004, 0.01, 300),
                      **{t: rng.normal(0.0005, 0.02, 300) for t in stocks}}, index=idx)
    weights = monte_carlo.to_weights(holdings)
    mc = monte_carlo.simulate_from_returns(weights, r, n_paths=200)
    sens = {t: {"beta": 0.4 if i == 0 else -0.1, "se": 0.1, "note": ""} for i, t in enumerate(weights)}
    shock_list = [shocks.apply_shock(weights, sens, k, th, 0.30).to_dict() for k, th in THEMES.items()]
    report = {"holdings_pct": holdings, "monte_carlo": mc.to_dict(), "shocks": shock_list,
              "frontier": {"available": True, "sentences": ["Mean-variance sentence."]}, "summary": ["Short."]}
    return report, {"fan_chart": monte_carlo.fan_chart(mc), "frontier": None}


NOT_READY = {"rpc": "", "factory": "", "keystore": "deployer", "keystore_found": False, "ready": False,
             "missing": ["Set MONAD_RPC_URL in .env.", "Put FACTORY_ADDRESS in .env."]}
READY = {"rpc": "http://chain", "factory": "0xF", "keystore": "deployer", "keystore_found": True, "ready": True,
         "missing": []}


@pytest.fixture
def app(monkeypatch):
    st.cache_data.clear()
    st.cache_resource.clear()
    SEEN.clear()
    monkeypatch.setattr(builder, "build", fake_build)
    monkeypatch.setattr(builder, "prescreen", fake_table)
    monkeypatch.setattr(screen, "run_screen", fake_screen)
    monkeypatch.setattr(risk, "run_risk", fake_risk)
    monkeypatch.setattr(assistant, "company_info", lambda tickers: {t: {"name": f"{t} Corp"} for t in tickers})
    monkeypatch.setattr(screen, "_screen_one", lambda t, th, s, e: {"tier": MODERATE if th["key"] == "oil"
                                                                    else LIMITED_LOW})
    monkeypatch.setattr(app_actions, "config", lambda: NOT_READY)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def build_ai_oil(at, region="all"):
    at.radio(key="choice_ai").set_value("Want")
    at.radio(key="choice_oil").set_value("Avoid")
    at.selectbox(key="region").set_value(region)
    at.button(key="build_button").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def check_portfolio(at, text="NVDA:30 XOM:20 CASH:50"):
    at.radio(key="mode").set_value("Check my portfolio")
    at.run()
    at.text_area(key="holdings_text").set_value(text)
    at.button(key="check_button").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]


# ---- start page ----

def test_start_page_offers_two_ways_in(app):
    assert not app.exception
    assert app.title[0].value == "Theme Funds"
    assert app.radio(key="mode").options == ["Build my ETF", "Check my portfolio"]
    assert any("Two ways in" in m.value for m in app.markdown)


# ---- Way 2: Build my ETF ----

def test_build_needs_at_least_one_choice(app):
    app.button(key="build_button").click()
    app.run()
    assert "Pick at least one theme" in app.sidebar.warning[0].value


def test_build_view_with_region_funnel_and_recheck(app):
    build_ai_oil(app, region="us")
    assert SEEN["build"] == ({"ai": "want", "oil": "avoid"}, "us")
    assert [t.label for t in app.tabs] == ["Your ETF", "Risk", "Ask about your fund", "Launch on Monad"]
    assert any("region: US only" in c.value for c in app.caption)
    funnel = app.dataframe[0].value
    assert list(funnel.columns) == ["Step", "Stocks left"] and funnel["Stocks left"].tolist() == [650, 40]
    assert any("Want AI" in s.value for s in app.success)
    assert any("Avoid Oil" in e.value for e in app.error)  # a failing re-check shows red
    assert any("Only 2 holdings" in w.value for w in app.warning)
    labels = [m.label for m in app.metric]
    assert "Chance of losing >10%" in labels and "Beat SPY" in labels


def test_shock_slider_changes_the_answer(app):
    build_ai_oil(app)
    app.selectbox(key="shock_theme").set_value("AI")
    app.select_slider(key="shock_size").set_value(30)
    app.run()
    up = next(m for m in app.metric if m.label.startswith("Estimated portfolio move"))
    app.select_slider(key="shock_size").set_value(-30)
    app.run()
    down = next(m for m in app.metric if m.label.startswith("Estimated portfolio move"))
    assert up.value.startswith("+") and down.value.startswith("-") and up.value[1:] == down.value[1:]


def test_audit_trail_for_any_cell(app):
    build_ai_oil(app)
    app.selectbox(key="audit_ticker").set_value("BBB")
    app.selectbox(key="audit_theme").set_value("AI")
    app.run()
    assert not app.exception
    assert any("Eligible" in df.value.columns.tolist() for df in app.dataframe)


def test_builder_error_and_empty_basket(app, monkeypatch):
    def fail(prefs, region="all"):
        raise builder.BuildError("No theme called 'x'")

    monkeypatch.setattr(builder, "build", fail)
    build_ai_oil(app)
    assert "No theme called" in app.sidebar.error[0].value

    st.cache_data.clear()
    monkeypatch.setattr(builder, "build", lambda prefs, region="all": {**fake_build(prefs, region), "holdings": [],
                                                                         "warnings": ["Nothing passes."]})
    build_ai_oil(app)
    assert any("No stock passes" in e.value for e in app.error)
    assert any("at least one stock to see its risk" in i.value for i in app.info)


def test_risk_failure_is_a_message(app, monkeypatch):
    def fail(holdings):
        raise monte_carlo.SimulationError("Need at least 5 days of history; got 3.")

    monkeypatch.setattr(risk, "run_risk", fail)
    build_ai_oil(app)
    assert any("risk report couldn't run" in e.value for e in app.error)


# ---- Way 1: Check my portfolio ----

def test_check_my_portfolio(app):
    check_portfolio(app, "nvda:30, XOM:20 CASH:40")  # adds to 90: rescaled
    assert [t.label for t in app.tabs] == ["Your portfolio", "Risk", "Ask about your fund", "Launch on Monad"]
    assert any("rescaled" in c.value for c in app.caption)
    fp = app.dataframe[0].value
    assert fp.iloc[0]["Theme"] == "AI" and fp.iloc[0]["High or Moderate"] == "33%"
    assert any("Couldn't fully score NVDA: no data" in w.value for w in app.warning)
    assert any("needs a fund from 'Build my ETF'" in i.value for i in app.info)  # launch tab


def test_check_bad_input_is_a_message(app):
    app.radio(key="mode").set_value("Check my portfolio")
    app.run()
    app.text_area(key="holdings_text").set_value("NVDA")
    app.button(key="check_button").click()
    app.run()
    assert "TICKER:WEIGHT" in app.sidebar.error[0].value


def test_chat_works_for_a_checked_portfolio(app, monkeypatch):
    seen = {}

    def fake_ask(question, facts, history):
        seen["facts"] = facts
        yield "You hold NVDA and XOM."

    monkeypatch.setattr(assistant, "ask", fake_ask)
    check_portfolio(app)
    app.chat_input[0].set_value("What do I hold?").run()
    assert seen["facts"]["mode"].startswith("Check my portfolio")
    assert seen["facts"]["holdings"][0]["name"] == "NVDA Corp" and seen["facts"]["theme_exposure"]


# ---- chat for a built fund ----

def test_chat_streams_an_answer(app, monkeypatch):
    seen = {}

    def fake_ask(question, facts, history):
        seen.update(question=question, facts=facts)
        yield "Your fund holds "
        yield "AAA and BBB."

    monkeypatch.setattr(assistant, "ask", fake_ask)
    build_ai_oil(app)
    app.chat_input[0].set_value("What do I hold?").run()
    assert seen["question"] == "What do I hold?" and seen["facts"]["mode"].startswith("Build my ETF")
    assert seen["facts"]["funnel"] and seen["facts"]["on_chain"]["launched"] is False
    texts = [m.value for msg in app.chat_message for m in msg.markdown]
    assert "What do I hold?" in texts and "Your fund holds AAA and BBB." in texts


def test_chat_error_is_a_message(app, monkeypatch):
    def failing_ask(question, facts, history):
        raise assistant.AssistantError("The Claude helper needs ANTHROPIC_API_KEY in the project's .env file.")
        yield  # pragma: no cover

    monkeypatch.setattr(assistant, "ask", failing_ask)
    build_ai_oil(app)
    app.button(key="example_How bad could a bad year be?").click()
    app.run()
    assert any("ANTHROPIC_API_KEY" in e.value for e in app.error)


# ---- Launch on Monad ----

def test_launch_tab_without_a_chain_shows_rules_steps_and_offchain_preview(app):
    build_ai_oil(app)
    assert any("Want **AI**" in m.value for m in app.markdown)
    assert any("Avoid **Oil**" in m.value for m in app.markdown)
    assert any("chain isn't connected yet" in w.value and "FACTORY_ADDRESS" in w.value for w in app.warning)
    app.text_input(key="try_ticker").set_value("XOM")
    app.button(key="try_add").click()
    app.run()
    rejection = next(e.value for e in app.error if e.value.startswith("Rejected"))
    assert "Mandate: Oil exposure too high (XOM is Moderate for Oil)." in rejection


def test_launch_flow_with_a_chain(app, monkeypatch):
    calls = []
    account = SimpleNamespace(address="0xWALLET")
    w3 = SimpleNamespace(eth=SimpleNamespace(chain_id=10143))
    fund = {"name": "AI ex-Oil Fund", "symbol": "AIXO", "address": "0xFUND", "chain_id": 10143,
            "network": "Monad testnet", "explorer_url": "https://testnet.monadexplorer.com/address/0xFUND",
            "tx_url": "https://testnet.monadexplorer.com/tx/0x1",
            "rules": [{"kind": 0, "label": "AI"}, {"kind": 1, "label": "Oil"}]}

    def unlock(password, cfg):
        calls.append(("unlock", password))
        if password != "pw":
            raise app_actions.PublishError("Wrong keystore password.")
        return w3, account

    def publish_basket(b, w, a, c):
        calls.append("publish")
        return {"stocks": ["AAA", "BBB", "XOM"], "tiers_posted": 6, "tiers_total": 6, "price_date": "2026-11-13"}

    def launch_basket(b, w, a, n, s, m, c):
        calls.append(("launch", n, s, m))
        return fund

    def deposit_dollars(addr, d, w, a, c):
        calls.append(("deposit", d))
        return {"shares": 1000.0, "nav_usd": 1000.0, "nav_per_share_usd": 1.0}

    monkeypatch.setattr(app_actions, "config", lambda: READY)
    monkeypatch.setattr(app_actions, "unlock", unlock)
    monkeypatch.setattr(app_actions, "publish_basket", publish_basket)
    monkeypatch.setattr(app_actions, "launch_basket", launch_basket)
    monkeypatch.setattr(app_actions, "deposit_dollars", deposit_dollars)
    monkeypatch.setattr(app_actions, "try_adding", lambda addr, t, c: (False, "Mandate: Oil exposure too high"))
    build_ai_oil(app)

    app.text_input(key="keystore_password").set_value("nope")
    app.button(key="unlock").click()
    app.run()
    assert any("Wrong keystore password" in e.value for e in app.error)
    app.text_input(key="keystore_password").set_value("pw")
    app.button(key="unlock").click()
    app.run()
    assert any("0xWALLET on Monad testnet" in c.value for c in app.caption)
    assert app.button(key="deposit_button").disabled and app.button(key="try_add").disabled

    app.button(key="publish").click()
    app.run()
    assert any("Published 3 stocks" in s.value for s in app.success)
    app.button(key="launch").click()
    app.run()
    assert any("AI ex-Oil Fund ($AIXO) is live on Monad testnet at 0xFUND" in s.value for s in app.success)
    app.number_input(key="deposit_amount").set_value(1000.0)
    app.button(key="deposit_button").click()
    app.run()
    assert any("You now hold 1,000.00 $AIXO" in s.value for s in app.success)
    app.text_input(key="try_ticker").set_value("XOM")
    app.button(key="try_add").click()
    app.run()
    assert any(e.value == "Rejected by the fund contract: Mandate: Oil exposure too high" for e in app.error)
    assert ("launch", "AI ex-Oil Fund", "AIXO", 60.0) in calls and ("deposit", 1000.0) in calls
    assert not app.exception


def test_chain_failures_are_messages(app, monkeypatch):
    def fail(*args):
        raise app_actions.PublishError("Not on the exchange yet: AAA. Run `python -m chain.publish` first.")

    def unlock(password, cfg):
        return SimpleNamespace(eth=SimpleNamespace(chain_id=31337)), SimpleNamespace(address="0xW")

    monkeypatch.setattr(app_actions, "config", lambda: READY)
    monkeypatch.setattr(app_actions, "unlock", unlock)
    monkeypatch.setattr(app_actions, "launch_basket", fail)
    monkeypatch.setattr(app_actions, "publish_basket", fail)
    build_ai_oil(app)
    app.text_input(key="keystore_password").set_value("pw")
    app.button(key="unlock").click()
    app.run()
    assert any("local test chain (id 31337)" in c.value for c in app.caption)
    app.button(key="publish").click()
    app.run()
    assert any(e.value.startswith("Publishing failed: Not on the exchange yet") for e in app.error)
    app.button(key="launch").click()
    app.run()
    assert any(e.value.startswith("Not on the exchange yet: AAA") for e in app.error)
    assert not app.exception
