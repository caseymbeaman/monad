"""Tests for the Phase 6 risk report and the mean-variance check (no internet)."""

import json

import numpy as np
import pandas as pd
import pytest

from engine import frontier_view as fv
from engine import monte_carlo, risk, shocks
from engine.mean_variance import analyze_portfolio as mv
from engine.mean_variance.errors import DataFetchError
from engine.screen import InputError
from tests.mean_variance.price_simulator import make_prices
from tests.test_shocks import THEME, returns_table

THEMES = {"oil": THEME, "ai": {**THEME, "key": "ai", "name": "AI", "plain": "AI companies",
                                "controls": ["SPY", "TLT"]}}


@pytest.fixture
def offline(monkeypatch):
    """Made-up returns everywhere, two themes, and a stand-in mean-variance check."""
    table = returns_table()
    monkeypatch.setattr(monte_carlo, "get_returns", lambda tickers, s, e: table)
    monkeypatch.setattr(shocks, "get_returns", lambda tickers, s, e: table)
    monkeypatch.setattr(shocks, "load_theme", lambda key: THEMES[key])
    monkeypatch.setattr(risk, "load_all", lambda: THEMES)
    monkeypatch.setattr(risk, "frontier_view", lambda pct: ({"available": True, "sentences": ["MV check."]}, None))
    return table


# ---- shock parsing ----

def test_parse_shocks():
    assert risk.parse_shocks(["oil=30", " AI = -20 "], ["oil", "ai"]) == {"oil": 0.30, "ai": -0.20}
    assert risk.parse_shocks(None, ["oil"]) == {}


@pytest.mark.parametrize("item, message", [
    ("oil", "THEME=PERCENT"), ("=30", "THEME=PERCENT"), ("gas=30", "No theme called 'gas'"),
    ("oil=lots", "isn't a number"), ("oil=150", "between -100 and 100"), ("oil=nan", "between"),
])
def test_parse_shocks_errors(item, message):
    with pytest.raises(InputError, match=message):
        risk.parse_shocks([item], ["oil", "ai"])


# ---- the full report ----

def test_report_defaults_to_every_theme_at_plus_30(offline):
    report, figures = risk.run_risk({"HOLD": 60, "ZERO": 20, "CASH": 20})
    assert [s["theme"] for s in report["shocks"]] == ["oil", "ai"]
    assert all(s["shock"] == 0.30 for s in report["shocks"])
    assert report["holdings_pct"] == {"HOLD": 60.0, "ZERO": 20.0, "CASH": 20.0}
    assert report["monte_carlo"]["n_paths"] == 5000
    assert report["frontier"] == {"available": True, "sentences": ["MV check."]}
    assert figures["fan_chart"] is not None
    assert any("Most sensitive theme" in s for s in report["summary"])
    assert any("not a forecast" in s for s in report["summary"])
    json.dumps(report)  # the whole report is JSON-ready


def test_summary_leads_with_the_history_warning(offline):
    report, _ = risk.run_risk({"HOLD": 100}, {"oil": 0.3}, include_frontier=False)
    base = risk.summary_sentences(monte_carlo.MonteCarloResult(**{
        **report["monte_carlo"], "portfolio": monte_carlo.OutcomeStats(**report["monte_carlo"]["portfolio"]),
        "benchmark": monte_carlo.OutcomeStats(**report["monte_carlo"]["benchmark"]),
        "history_note": "Heads-up: short window."}), report["shocks"])
    assert base[0] == "Heads-up: short window."
    assert base[1].startswith("Chance of losing more than 10%") and base[2].startswith("Bad year (5% VaR)")


def test_report_with_chosen_shocks_and_no_frontier(offline):
    report, figures = risk.run_risk({"HOLD": 100}, {"oil": -0.2}, include_frontier=False)
    assert [(s["theme"], s["shock"]) for s in report["shocks"]] == [("oil", -0.2)]
    assert report["frontier"] is None and "frontier" not in figures
    text = risk.summary_text(report)
    for part in ("MONTE CARLO", "THEME SHOCKS", "IN SHORT", "-20%  ->  portfolio"):
        assert part in text
    assert "MEAN-VARIANCE" not in text


# ---- command line ----

def write_build(tmp_path, holdings):
    (tmp_path / "results").mkdir(exist_ok=True)
    (tmp_path / "results" / "build_latest.json").write_text(json.dumps({"holdings": holdings}))


def test_cli_from_build_writes_report_and_charts(offline, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(risk, "ROOT", tmp_path)
    write_build(tmp_path, [{"ticker": "HOLD", "weight_pct": 70}, {"ticker": "CASH", "weight_pct": 30},
                           {"ticker": "ZERO", "weight_pct": 0}])
    assert risk.main(["--from-build", "--shock", "oil=30"]) == 0
    out = capsys.readouterr().out
    assert "Portfolio: HOLD 70.0%, CASH 30.0%" in out and "MEAN-VARIANCE CHECK" in out
    saved = json.loads((tmp_path / "results" / "risk_latest.json").read_text())
    assert saved["holdings_pct"] == {"HOLD": 70.0, "CASH": 30.0}
    assert (tmp_path / "results" / "risk_fan_chart.html").exists()


def test_cli_holdings_and_json(offline, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(risk, "ROOT", tmp_path)
    assert risk.main(["HOLD:50", "CASH:50", "--shock", "ai=10", "--no-frontier", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["shocks"][0]["theme"] == "ai"


@pytest.mark.parametrize("argv, build, message", [
    (["HOLD:50", "--from-build"], None, "not both"),
    (["--from-build"], None, "build_latest.json not found"),
    (["--from-build"], [], "no holdings"),
    ([], None, "No holdings given"),
    (["HOLD:50", "--shock", "gas=10"], None, "No theme called 'gas'"),
])
def test_cli_errors_are_messages(offline, tmp_path, monkeypatch, capsys, argv, build, message):
    monkeypatch.setattr(risk, "ROOT", tmp_path)
    if build is not None:
        write_build(tmp_path, build)
    assert risk.main(argv) == 2
    assert message in capsys.readouterr().err


# ---- mean-variance check ----

def test_invested_weights_split_out_cash():
    invested, cash = fv._invested_weights({"A": 30, "B": 30, "CASH": 40})
    assert invested == pytest.approx({"A": 0.5, "B": 0.5}) and cash == pytest.approx(0.4)
    assert fv._invested_weights({"CASH": 100}) == ({}, 1.0)
    with pytest.raises(ValueError):
        fv._invested_weights({"A": 0})


def test_frontier_skipped_for_fewer_than_two_stocks():
    report, fig = fv.frontier_view({"NVDA": 60, "CASH": 40})
    assert report["available"] is False and fig is None
    assert "at least two stocks" in report["sentences"][0]


def test_frontier_data_problem_is_reported(monkeypatch):
    def fail(*args, **kwargs):
        raise DataFetchError("FMP rate limit reached.")

    monkeypatch.setattr(fv, "analyze_portfolio", fail)
    report, fig = fv.frontier_view({"A": 50, "B": 50})
    assert report["available"] is False and fig is None
    assert "couldn't run: FMP rate limit reached." in report["sentences"][0]


def _fake_analyze(rf):
    prices = make_prices(["AAA", "BBB", "CCC"])

    def fake(weights, window_mode, today=None):
        return mv.evaluate(weights, prices, rf, window_mode)

    return fake


def test_frontier_view_with_made_up_prices(monkeypatch):
    monkeypatch.setattr(fv, "analyze_portfolio", _fake_analyze(0.04))
    report, fig = fv.frontier_view({"AAA": 40, "BBB": 30, "CCC": 10, "CASH": 20})
    assert report["available"] and fig is not None and report["cash_pct"] == 20.0
    mine = report["portfolios"]["Your portfolio"]
    assert mine["weights"] == pytest.approx({"AAA": 0.5, "BBB": 0.375, "CCC": 0.125})
    text = " ".join(report["sentences"])
    assert "best risk-adjusted mix" in text and "20.0% cash" in text and "check only" in text
    json.dumps(report)


def test_frontier_view_without_tangency(monkeypatch):
    monkeypatch.setattr(fv, "analyze_portfolio", _fake_analyze(5.0))
    report, _ = fv.frontier_view({"AAA": 50, "BBB": 50})
    assert any("no best risk-adjusted mix" in s for s in report["sentences"])
    assert not any("cash" in s for s in report["sentences"])


def test_frontier_sentence_math():
    summary = pd.DataFrame({"return": [0.10, 0.08, 0.12], "volatility": [0.2, 0.15, 0.2],
                            "sharpe": [0.3, 0.27, 0.4]},
                           index=["Your portfolio", "Minimum-variance portfolio", "Tangency portfolio"])
    s = fv.sentences(summary, 0.0)
    assert "10.0% a year with 20.0%" in s[0] and "15.0% risk" in s[1] and "75% of the way" in s[2]
    assert np.isnan(float("nan"))  # keeps numpy import used if sentences change
