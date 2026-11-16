"""demo/league.py: the dashboard's fund becomes a valid League entry (3-8 pool stocks, whole % adding to 100,
each >= 5%), with a pre-filled link."""
from urllib.parse import parse_qs, urlparse

from demo import league

POOL = frozenset(["NVDA", "AVGO", "MSFT", "MU", "VRT", "AMD", "ANET", "TSM", "ORCL", "XOM"])


def _valid(etf):
    return 3 <= len(etf) <= 8 and sum(etf.values()) == 100 and all(w >= 5 and isinstance(w, int) for w in etf.values())


def test_five_equal_stocks_enter_as_is():
    etf, notes = league.league_fund({t: 20 for t in ["NVDA", "AVGO", "MSFT", "MU", "VRT"]}, POOL)
    assert etf == {t: 20 for t in ["NVDA", "AVGO", "MSFT", "MU", "VRT"]} and notes == []


def test_more_than_eight_keeps_the_largest_eight_and_says_so():
    w = {"NVDA": 15, "AVGO": 14, "MSFT": 13, "MU": 12, "VRT": 11, "AMD": 10, "ANET": 9, "TSM": 8, "ORCL": 1, "CASH": 7}
    etf, notes = league.league_fund(w, POOL)
    assert _valid(etf) and "ORCL" not in etf and "CASH" not in etf
    assert any("8 largest" in n for n in notes)


def test_stocks_outside_the_pool_are_dropped_and_too_few_cannot_enter():
    etf, notes = league.league_fund({"NVDA": 50, "ZZZZ": 50}, POOL)
    assert etf == {} and any("ZZZZ is not in the League's stock pool" in n for n in notes)
    assert any("at least 3" in n for n in notes)


def test_equal_weights_keep_the_fund_ranking():
    w = {t: 100 / 10 for t in ["NVDA", "AVGO", "VRT", "MSFT", "MU", "AMD", "ANET", "TSM", "ORCL", "XOM"]}
    etf, _ = league.league_fund(w, POOL)
    assert list(etf) == ["NVDA", "AVGO", "VRT", "MSFT", "MU", "AMD", "ANET", "TSM"] and _valid(etf)


def test_small_weights_are_lifted_to_five_percent():
    etf = league.whole_percents({"A": 90, "B": 4, "C": 3, "D": 3})
    assert sum(etf.values()) == 100 and min(etf.values()) >= 5


def test_prefilled_link_and_name():
    name = league.fund_name({"ai": "want", "oil": "avoid"}, {"ai": "AI", "oil": "Oil"})
    assert name == "AI ex-Oil"
    url = league.prefill_url({"NVDA": 20, "AVGO": 20, "MSFT": 20, "MU": 20, "VRT": 20}, name)
    assert url.startswith(league.LEAGUE_URL + "?") and "network=" not in url
    q = parse_qs(urlparse(url).query)
    assert q["etf"] == ["NVDA:20,AVGO:20,MSFT:20,MU:20,VRT:20"] and q["name"] == ["AI ex-Oil"]
    long = league.fund_name({k: "want" for k in "abcdef"}, {k: "Aerospace & defense" for k in "abcdef"})
    assert len(long.encode()) <= 32


def test_pool_is_the_league_pool_file():
    assert len(league.pool_tickers()) > 600 and "NVDA" in league.pool_tickers()
