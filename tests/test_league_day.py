"""Tests for the League's "organiser picks the trading day" option (chain/league_live.py --day)."""

import json

import numpy as np
import pandas as pd
import pytest

from chain import league_live
from chain.league import LeagueError


def prices():
    """Three stocks over ten business days starting Mon 2026-04-06, with known closes."""
    days = pd.bdate_range("2026-04-06", periods=10)
    rng = np.random.default_rng(3)
    moves = 1 + rng.normal(0, 0.02, size=(10, 3))
    moves[3] = [1.05, 0.90, 1.00]  # Thu 2026-04-09: A +5%, B -10%, C flat
    return pd.DataFrame(100 * np.cumprod(moves, axis=0), index=days, columns=["AAA", "BBB", "CCC"])


def test_chosen_day_gives_one_block_pinned_to_that_days_real_moves():
    p = prices()
    labels, rows, sampled = league_live.simulate_days(p, day="2026-04-09")

    assert sampled == ["2026-04-09"]
    assert len(rows) == len(labels) == league_live.SIM_STEPS + 1          # one day, 9:30 AM to 4:00 PM
    assert labels[0].endswith("09:30") and labels[-1].endswith("16:00")
    start, end = np.array(rows[0]), np.array(rows[-1])
    assert start == pytest.approx(p.iloc[-1].to_numpy(), rel=1e-6)        # starts from the latest real close
    assert end / start == pytest.approx([1.05, 0.90, 1.00], rel=1e-5)     # ends exactly at that day's real move


def test_chosen_day_is_the_same_every_time():
    a = league_live.simulate_days(prices(), day="2026-04-09")
    b = league_live.simulate_days(prices(), day="2026-04-09")
    assert a == b


def test_without_a_day_nothing_changes():
    _, rows, sampled = league_live.simulate_days(prices())
    assert len(sampled) == league_live.SIM_DAYS
    assert len(rows) == league_live.SIM_DAYS * (league_live.SIM_STEPS + 1)


def test_extreme_moves_on_the_chosen_day_are_still_capped():
    p = prices()
    p.iloc[5:, 0] *= 1.6                                                    # AAA jumps 60% on 2026-04-13
    _, rows, _ = league_live.simulate_days(p, day="2026-04-13")
    assert rows[-1][0] / rows[0][0] == pytest.approx(1 + league_live.SIM_CAP, rel=1e-5)


@pytest.mark.parametrize("day, message", [
    ("next tuesday", "isn't a date. Use YYYY-MM-DD"),
    ("2026-04-11", "wasn't a trading day.*Nearest trading days: 2026-04-10 and 2026-04-13"),   # a Saturday
    ("2025-01-02", "outside the price history. Pick a trading day from 2026-04-07 to 2026-04-17"),
    ("2026-04-06", "outside the price history"),      # the first price day has no previous close to move from
])
def test_bad_days_are_refused_with_a_plain_reason(day, message):
    with pytest.raises(LeagueError, match=message):
        league_live.simulate_days(prices(), day=day)


def test_file_for_a_chosen_day_has_one_window_and_says_so(tmp_path, monkeypatch):
    from engine import data

    monkeypatch.setattr(data, "get_prices", lambda tickers: (prices()[tickers], {}))
    monkeypatch.setattr(league_live, "REPLAY_FILE", tmp_path / "replay_prices.json")

    data_hash, windows, written = league_live.write_demo_day_file(["AAA", "BBB", "CCC"], "2026-04-09")
    saved = json.loads((tmp_path / "replay_prices.json").read_text())
    assert windows == 1                                   # the contract can only "pick" this day
    assert saved["chosen_day"] == written["chosen_day"] == "2026-04-09"
    assert saved["sampled_dates"] == ["2026-04-09"] and saved["mode"] == "demo-day"
    assert "chosen by the organiser" in saved["about"]
    assert len(data_hash) == 32

    _, windows, written = league_live.write_demo_day_file(["AAA", "BBB", "CCC"])
    assert windows == league_live.SIM_DAYS and "chosen_day" not in written


def test_day_option_only_applies_to_the_simulated_day_commands(capsys):
    from chain import league

    with pytest.raises(SystemExit):
        league.main(["open", "--day", "2026-04-09"])
    assert "--day only works with demo-day and always-on" in capsys.readouterr().err
