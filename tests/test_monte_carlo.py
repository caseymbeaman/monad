"""Tests for the Monte Carlo simulation, using made-up returns with known answers (no internet)."""

import itertools

import numpy as np
import pandas as pd
import pytest

from engine import monte_carlo as mc
from engine.monte_carlo import SimulationError


def returns_table(n=500, seed=1, extra=None):
    """Made-up daily returns for SPY and two stocks."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-11-15", periods=n)
    spy = rng.normal(0.0004, 0.01, n)
    data = {"SPY": spy,
            "AAA": 1.5 * spy + rng.normal(0.0002, 0.01, n),
            "BBB": 0.5 * spy + rng.normal(0.0, 0.008, n)}
    data.update(extra or {})
    return pd.DataFrame(data, index=idx)


# ---- inputs ----

def test_to_weights_rescales_and_keeps_cash():
    w = mc.to_weights({"nvda": 30, "XOM": 20, "cash": 50})
    assert w == pytest.approx({"NVDA": 0.3, "XOM": 0.2, "CASH": 0.5})
    assert sum(mc.to_weights({"A": 1, "B": 3}).values()) == pytest.approx(1.0)


@pytest.mark.parametrize("holdings, message", [
    ({}, "No holdings"),
    ({"A": 0}, "positive"),
    ({"A": -5}, "positive"),
    ({"A": float("nan")}, "positive"),
    ({"A": True}, "positive"),
    ({"A": "10"}, "positive"),
    ({"a": 10, "A": 5}, "listed twice"),
])
def test_to_weights_bad_input(holdings, message):
    with pytest.raises(SimulationError, match=message):
        mc.to_weights(holdings)


def test_portfolio_daily_returns_by_hand():
    r = pd.DataFrame({"AAA": [0.10, -0.05], "BBB": [0.0, 0.02]})
    out = mc.portfolio_daily_returns({"AAA": 0.5, "BBB": 0.3, "CASH": 0.2}, r)
    assert out.tolist() == pytest.approx([0.05, -0.019])


def test_cash_only_portfolio_never_moves():
    r = returns_table(50)
    assert (mc.portfolio_daily_returns({"CASH": 1.0}, r) == 0).all()


def test_missing_holding_returns():
    with pytest.raises(SimulationError, match="No returns for: ZZZ"):
        mc.portfolio_daily_returns({"ZZZ": 1.0}, returns_table(20))


# ---- the bootstrap ----

def test_block_indices_are_real_consecutive_stretches():
    idx = mc.block_indices(n_history=100, n_paths=200, horizon=252, block=5, seed=7)
    assert idx.shape == (200, 252)
    assert idx.min() >= 0 and idx.max() <= 99
    full_blocks = idx[:, :250].reshape(200, 50, 5)
    assert (np.diff(full_blocks, axis=2) == 1).all()   # each block = 5 consecutive real days
    assert (np.diff(idx[:, 250:], axis=1) == 1).all()   # last block cut to 2 days, still consecutive


def test_block_indices_fixed_seed_is_reproducible():
    a = mc.block_indices(300, 100, seed=1)
    assert (a == mc.block_indices(300, 100, seed=1)).all()
    assert not (a == mc.block_indices(300, 100, seed=2)).all()


def test_block_indices_uses_every_possible_start():
    idx = mc.block_indices(n_history=12, n_paths=2000, horizon=5, block=5, seed=3)
    assert set(idx[:, 0]) == set(range(8))  # starts 0..7 all appear (12 - 5 + 1 = 8)


def test_too_little_history():
    with pytest.raises(SimulationError, match="at least 5 days"):
        mc.block_indices(n_history=4)


def test_growth_paths_constant_return():
    daily = np.full(10, 0.01)
    paths = mc.growth_paths(daily, mc.block_indices(10, 100, horizon=252, block=5))
    assert paths.shape == (100, 253)
    assert paths[:, 0] == pytest.approx(1.0)
    assert paths[:, -1] == pytest.approx(1.01 ** 252)


def test_vectorized_bootstrap_matches_slow_loop():
    """Independent check: rebuild every path with plain Python loops from the same random draws."""
    r = returns_table(80)
    daily = mc.portfolio_daily_returns({"AAA": 0.6, "BBB": 0.4}, r).to_numpy()
    n_paths, horizon, block, seed = 50, 23, 5, 11
    fast = mc.growth_paths(daily, mc.block_indices(len(daily), n_paths, horizon, block, seed))[:, -1]

    rng = np.random.default_rng(seed)
    n_blocks = -(-horizon // block)
    starts = rng.integers(0, len(daily) - block + 1, size=(n_paths, n_blocks))
    slow = []
    for p in range(n_paths):
        days = [s + k for s in starts[p] for k in range(block)][:horizon]
        value = 1.0
        for d in days:
            value *= 1 + daily[d]
        slow.append(value)
    assert fast == pytest.approx(slow, rel=1e-12)


# ---- summary numbers ----

def test_outcome_stats_known_answers():
    r = np.linspace(-0.5, 0.5, 101)          # -50%, -49%, ..., +50%
    s = mc.outcome_stats(r)
    assert s.median == pytest.approx(0.0, abs=1e-12)
    assert s.mean == pytest.approx(0.0, abs=1e-12)
    assert s.p_loss_over_10 == pytest.approx(40 / 101)   # -50% .. -11%
    assert s.var_5 == pytest.approx(0.45)
    assert s.cvar_5 == pytest.approx(0.475)               # average of -50% .. -45%
    assert s.best_5 == pytest.approx(0.45)


def test_outcome_stats_all_gains():
    s = mc.outcome_stats(np.full(50, 0.08))
    assert s.p_loss_over_10 == 0 and s.var_5 == pytest.approx(-0.08) and s.cvar_5 == pytest.approx(-0.08)


@pytest.mark.parametrize("bad", [[], [0.1, float("nan")], [float("inf")]])
def test_outcome_stats_bad_input(bad):
    with pytest.raises(SimulationError, match="empty or invalid"):
        mc.outcome_stats(np.array(bad))


# ---- the full simulation ----

def test_simulation_is_reproducible_and_complete():
    r = returns_table()
    a = mc.simulate_from_returns({"AAA": 0.6, "BBB": 0.2, "CASH": 0.2}, r, n_paths=500)
    b = mc.simulate_from_returns({"AAA": 0.6, "BBB": 0.2, "CASH": 0.2}, r, n_paths=500)
    assert a.to_dict() == b.to_dict()
    assert a.n_paths == 500 and a.horizon_days == 252 and a.block_days == 5 and a.seed == mc.SEED
    assert a.history_days == 500 and len(a.fan["days"]) == 253
    for side in ("portfolio", "benchmark"):
        bands = [np.array(a.fan[side][str(p)]) for p in mc.FAN_PERCENTILES]
        assert all((lo <= hi + 1e-12).all() for lo, hi in itertools.pairwise(bands))
        assert bands[2][0] == pytest.approx(1.0)
    assert len(a.sentences) == 6
    assert "not a forecast" in a.sentences[0] and "beat SPY" in a.sentences[-1]


def test_holding_spy_itself_matches_benchmark_exactly():
    """Portfolio and SPY are resampled on the same dates, so 100% SPY gives identical stats."""
    res = mc.simulate_from_returns({"SPY": 1.0}, returns_table(), n_paths=300)
    assert res.portfolio == res.benchmark
    assert res.p_beat_benchmark == 0.0


def test_cash_lowers_risk_proportionally():
    r = returns_table()
    full = mc.simulate_from_returns({"AAA": 1.0}, r, n_paths=1000)
    half = mc.simulate_from_returns({"AAA": 0.5, "CASH": 0.5}, r, n_paths=1000)
    assert half.portfolio.var_5 < full.portfolio.var_5
    assert half.portfolio.p_loss_over_10 <= full.portfolio.p_loss_over_10


def test_very_volatile_stock_has_bigger_tail_loss():
    r = returns_table(extra={"WILD": np.random.default_rng(5).normal(0, 0.06, 500)})
    calm = mc.simulate_from_returns({"BBB": 1.0}, r, n_paths=1000)
    wild = mc.simulate_from_returns({"WILD": 1.0}, r, n_paths=1000)
    assert wild.portfolio.cvar_5 > calm.portfolio.cvar_5 > 0


def test_sentences_handle_a_portfolio_that_gains_even_in_bad_years():
    idx = pd.bdate_range("2024-11-15", periods=100)
    r = pd.DataFrame({"SPY": np.full(100, 0.001), "UP": np.full(100, 0.002)}, index=idx)
    res = mc.simulate_from_returns({"UP": 1.0}, r, n_paths=200)
    assert "still gain" in res.sentences[3] and "gain" in res.sentences[4]
    assert res.p_beat_benchmark == 1.0


def test_all_cash_reads_as_break_even_not_a_gain():
    res = mc.simulate_from_returns({"CASH": 1.0}, returns_table(), n_paths=200)
    assert res.portfolio.var_5 == 0 and res.portfolio.p_loss_over_10 == 0
    assert "you'd roughly break even" in res.sentences[3]
    assert "roughly break-even" in res.sentences[4]
    assert "still gain" not in " ".join(res.sentences)


def test_simulation_input_errors():
    with pytest.raises(SimulationError, match="benchmark SPY"):
        mc.simulate_from_returns({"AAA": 1.0}, returns_table().drop(columns="SPY"))
    with pytest.raises(SimulationError, match="at least 100 paths"):
        mc.simulate_from_returns({"AAA": 1.0}, returns_table(), n_paths=10)


def test_simulate_fetches_holdings_plus_spy(monkeypatch):
    seen = {}

    def fake_get_returns(tickers, start, end):
        seen["tickers"] = tickers
        return returns_table()

    monkeypatch.setattr(mc, "get_returns", fake_get_returns)
    res = mc.simulate({"aaa": 70, "CASH": 30}, n_paths=200)
    assert seen["tickers"] == ["AAA", "SPY"]
    assert res.weights == {"AAA": 0.7, "CASH": 0.3}


def test_fan_chart_has_bands_medians_and_loss_line():
    fig = mc.fan_chart(mc.simulate_from_returns({"AAA": 1.0}, returns_table(), n_paths=200))
    names = [t.name for t in fig.data]
    assert "Portfolio: typical path (median)" in names and "SPY: typical path (median)" in names
    assert "Portfolio: 90% of outcomes" in names
    assert "not a forecast" in fig.layout.title.text
    assert any(s.y0 == pytest.approx(9_000) for s in fig.layout.shapes)


# ---- small VaR wording and shortened-history warning ----

def test_tiny_var_reads_as_break_even_not_a_zero_percent_gain():
    port = mc.OutcomeStats(median=0.9, mean=1.1, p_loss_over_10=0.03, var_5=-0.0047, cvar_5=0.144, best_5=2.8)
    bench = mc.OutcomeStats(median=0.22, mean=0.24, p_loss_over_10=0.02, var_5=0.043, cvar_5=0.108, best_5=0.55)
    text = mc.sentences(port, bench, 0.94, 5000, "Mar 2025", "Nov 2026")
    bad_year = next(s for s in text if s.startswith("Bad year"))
    assert "roughly break even" in bad_year and "still gain at least 0%" not in bad_year
    assert any("a 14% loss" in s for s in text)


def test_history_note_is_the_second_sentence():
    port = mc.outcome_stats(np.linspace(-0.2, 0.4, 101))
    text = mc.sentences(port, port, 0.5, 100, "Mar 2025", "Nov 2026", history_note="Heads-up: short.")
    assert text[1] == "Heads-up: short." and len(text) == 7


def _young_stock_returns(monkeypatch, n_shared=300, raise_for=()):
    """The fund's shared window is short because YNG listed late; OLD has the full two years."""
    full = pd.bdate_range("2024-11-18", periods=500)

    def fake_get_returns(tickers, start, end):
        if tickers == ["YNG"]:
            if "YNG" in raise_for:
                raise mc.DataError("no data")
            return pd.DataFrame({"YNG": 0.0}, index=full[-n_shared:])
        if tickers == ["OLD"]:
            if "OLD" in raise_for:
                raise mc.DataError("no data")
            return pd.DataFrame({"OLD": 0.0}, index=full)
        rng = np.random.default_rng(0)
        return pd.DataFrame({t: rng.normal(0.0005, 0.01, n_shared) for t in tickers}, index=full[-n_shared:])

    monkeypatch.setattr(mc, "get_returns", fake_get_returns)


def test_simulate_warns_and_names_the_young_holding(monkeypatch):
    _young_stock_returns(monkeypatch)
    res = mc.simulate({"OLD": 50, "YNG": 50}, n_paths=200)
    assert res.history_note.startswith("Heads-up: YNG only has prices from")
    assert "about 14 months" in res.history_note and "not the usual two years" in res.history_note
    assert res.sentences[1] == res.history_note


def test_no_warning_with_a_full_window(monkeypatch):
    _young_stock_returns(monkeypatch, n_shared=480)
    assert mc.simulate({"OLD": 50, "YNG": 50}, n_paths=200).history_note is None


def test_warning_still_shown_if_start_dates_cant_be_found(monkeypatch):
    _young_stock_returns(monkeypatch, raise_for=("OLD", "YNG"))
    note = mc.simulate({"OLD": 50, "YNG": 50}, n_paths=200).history_note
    assert note.startswith("Heads-up: some holdings have short price histories")


def test_cash_only_needs_no_warning():
    idx = pd.bdate_range("2024-11-18", periods=100)
    assert mc.shortened_history_note([], pd.DataFrame({"SPY": 0.0}, index=idx), "a", "b") is None
