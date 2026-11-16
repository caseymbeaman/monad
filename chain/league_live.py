"""Fantasy Fund League: weekly matchups on LIVE prices, and a simulated trading day for demos.

    python -m chain.league weekly   --network monad-testnet --lock "Mon 06:30 PT" --end "Fri 13:00 PT" --stake 1
    python -m chain.league demo-day --network monad-testnet --entry-seconds 300 --stake 1

Both reuse the FundLeague contract as it is (no contract changes).

WEEKLY MATCHUP (like fantasy football)
- Opens this week's matchup now; anyone can enter until the lock (Monday market open, 6:30 AM PT).
- The contract needs a non-zero data hash and at least one window: the hash is of league/week.json (the week's
  rules: lock, end, price source), and windowCount = 1, since there's no random window on live prices.
- At the lock: lock -> live FMP prices for the stocks entries use -> start (records Monday-open prices).
- During the week: live FMP prices every --every seconds (default 5 min) while the US market is open
  (9:30-16:00 ET, Mon-Fri; holidays aren't modelled), one postPrices transaction per update; paused when closed.
  The contract's 1-day price freshness is never at risk: the longest gap (overnight) is about 17.5 hours.
- At the end (Friday close): final prices, settle (best return from Monday open to Friday close wins the pot),
  season standings updated in league/season.json and pushed, then next week's matchup opens.
- A status line every few minutes: entries, pot, current leader. The MON cost per week is estimated after the
  first price update, with a warning when the League wallet can't cover it.

SIMULATED TRADING DAY (for demos when markets are closed)
- 50 simulated days, 9:30 AM -> 4:00 PM in 20 steps. Each day resamples ONE real historical date for all pool
  stocks together (so they move together, as on a real day), splits that day's real return into 20 intraday steps
  (a random path pinned to the real day's close), caps extreme daily moves at +/-15%, fixed seed.
- Saved in the replay-file format (league/replay_prices.json) with window_stride = 21: window w is rows
  21w .. 21w+20, labeled by time. Its hash is recorded at openRound with windowCount = 50; a future block picks
  the day after entries close; one step every 3 s (a 60-second race); settle. Same fairness as before.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from web3 import Web3

from chain.league import (
    BASE_PRICE,
    DAY_SECONDS,
    PAGE,
    RACE_DAYS,
    REPLAY_FILE,
    ROOT,
    Chain,
    LeagueError,
    league_section,
    open_round,
    post_prices,
    print_results,
    results,
    run_round,
)

ET, PT = ZoneInfo("America/New_York"), ZoneInfo("America/Los_Angeles")
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEK_FILE = PAGE / "week.json"
HISTORY_FILE = PAGE / "week_history.json"
SEASON_FILE = PAGE / "season.json"
SEASON_FILE_ANVIL = ROOT / "data" / "cache" / "season_anvil.json"  # Anvil tests never touch the real season
STATUS_EVERY = 180  # seconds between status lines
SETTLE_MARGIN = 60  # the race may be settled this many seconds before the end time (start happens just after lock)

SIM_DAYS, SIM_STEPS, SIM_SEED, SIM_CAP = 50, RACE_DAYS, 20261115, 0.15


# ---------------------------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------------------------

def parse_when(spec: str, after: datetime | None = None) -> datetime:
    """'Mon 06:30 PT' -> the next such moment after `after` (default now). '+90s', '+5m', '+2h' -> relative."""
    after = after or datetime.now(UTC)
    m = re.fullmatch(r"\+(\d+)([smh])", spec.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return after + timedelta(seconds=n * {"s": 1, "m": 60, "h": 3600}[unit])
    m = re.fullmatch(r"(?i)(mon|tue|wed|thu|fri|sat|sun)\w*\s+(\d{1,2}):(\d{2})\s*(PT|ET|UTC)?", spec.strip())
    if not m:
        raise LeagueError(f"Can't read the time '{spec}'. Use e.g. 'Mon 06:30 PT' or '+5m'.")
    tz = {"PT": PT, "ET": ET, "UTC": UTC, None: PT}[(m.group(4) or "PT").upper()]
    local = after.astimezone(tz)
    t = local.replace(hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0)
    t += timedelta(days=(DAYS[m.group(1).lower()] - local.weekday()) % 7)
    if t <= local:
        t += timedelta(days=7)
    return t.astimezone(UTC)


def market_open(now: datetime | None = None) -> bool:
    """US regular session: Mon-Fri 9:30-16:00 New York time (exchange holidays not modelled)."""
    t = (now or datetime.now(UTC)).astimezone(ET)
    return t.weekday() < 5 and (9, 30) <= (t.hour, t.minute) < (16, 0)


def week_label(lock: datetime) -> str:
    """'Week of Nov 16 · locks Mon 6:30 AM PT' (the Monday of the lock's week)."""
    lp = lock.astimezone(PT)
    monday = lp - timedelta(days=lp.weekday())
    return f"Week of {monday:%b} {monday.day} · locks {lp:%a} {lp.hour % 12 or 12}:{lp:%M} {lp:%p} PT"


# ---------------------------------------------------------------------------------------------
# Live prices
# ---------------------------------------------------------------------------------------------

def live_quotes(tickers: list[str]) -> dict[str, float]:
    """Latest FMP prices, one batch request (the key is never printed: engine.fmp keeps it out of errors)."""
    from engine import fmp

    out: dict[str, float] = {}
    for i in range(0, len(tickers), 100):  # FMP batch-quote: up to ~100 symbols per request
        rows = fmp.get("batch-quote", {"symbols": ",".join(tickers[i:i + 100])}, use_cache=False)
        out.update({r["symbol"]: float(r["price"]) for r in rows if r.get("price")})
    missing = [t for t in tickers if t not in out]
    if missing:
        raise LeagueError(f"FMP returned no live price for: {', '.join(missing)}")
    return out


class PriceFeed:
    """Live FMP prices, or (simulate=True, for Anvil tests) a random walk starting from one live quote."""

    def __init__(self, simulate: bool, seed: int = 7):
        self.simulate, self.rng, self.last = simulate, np.random.default_rng(seed), {}

    def prices(self, tickers: list[str]) -> dict[str, float]:
        if not self.simulate:
            return live_quotes(tickers)
        new = [t for t in tickers if t not in self.last]
        if new:
            try:
                self.last.update(live_quotes(new))
            except Exception:  # noqa: BLE001 - offline test: start at $100
                self.last.update(dict.fromkeys(new, BASE_PRICE))
            return {t: self.last[t] for t in tickers}
        for t in tickers:
            self.last[t] *= float(np.exp(self.rng.normal(0, 0.004)))
        return {t: self.last[t] for t in tickers}


# ---------------------------------------------------------------------------------------------
# Season standings (league/season.json)
# ---------------------------------------------------------------------------------------------

def update_season(chain: Chain, r: dict, week: dict) -> dict:
    path = SEASON_FILE_ANVIL if chain.network == "anvil" else SEASON_FILE
    season = json.loads(path.read_text()) if path.exists() else {
        "about": "Fantasy Fund League season standings: one matchup per week, Monday open to Friday close.",
        "weeks": [], "players": {}}
    winners = [e for e in r["entries"] if e["winner"]]
    share = r["pot"] / len(winners) if winners else 0.0
    for e in r["entries"]:
        p = season["players"].setdefault(e["owner"], {"weeks": 0, "wins": 0, "mon_won": 0.0, "best_return_pct": None})
        p["weeks"] += 1
        p["last_name"] = e["name"]
        if e["winner"]:
            p["wins"] += 1
            p["mon_won"] = round(p["mon_won"] + share, 6)
        if e["return_pct"] is not None:
            p["best_return_pct"] = round(max(e["return_pct"], p["best_return_pct"] or -1e9), 4)
    season["weeks"].append({"round": r["round"], "label": week.get("label"), "lock": week.get("lock"),
                            "end": week.get("end"), "phase": r["phase"], "pot": r["pot"],
                            "winners": [{"owner": e["owner"], "name": e["name"], "return_pct": e["return_pct"]}
                                        for e in winners],
                            "entries": len(r["entries"])})
    season["updated"] = datetime.now(UTC).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(season, indent=1))
    return season


def git_push(paths: list[Path], message: str, log=print, force: list[Path] | None = None) -> None:
    """Commit only these files and push (pull --rebase first). Testnet only. force: gitignored files to add anyway."""
    rel = [str(p.relative_to(ROOT)) for p in paths if p.exists()]
    forced = {str(p.relative_to(ROOT)) for p in force or []}
    try:
        subprocess.run(["git", "add", *[r for r in rel if r not in forced]], cwd=ROOT, check=True, capture_output=True)
        if forced & set(rel):
            subprocess.run(["git", "add", "-f", *sorted(forced & set(rel))], cwd=ROOT, check=True, capture_output=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet", "--", *rel], check=False, cwd=ROOT).returncode == 0:
            return
        subprocess.run(["git", "commit", "-m", message, "--", *rel], cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "pull", "--rebase", "-q", "origin", "main"], cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=ROOT, check=True, capture_output=True)
        log(f"  pushed {', '.join(rel)}")
    except subprocess.CalledProcessError as exc:
        log(f"  WARNING: couldn't push ({exc.stderr.decode(errors='ignore')[:200].strip()}). Push by hand.")


# ---------------------------------------------------------------------------------------------
# Weekly matchup
# ---------------------------------------------------------------------------------------------

def _status(chain: Chain, league, rid: int, log) -> None:
    info = league.functions.getRound(rid).call()
    phase, n, pot = info[10], info[11], info[14] / 1e18
    lead = ""
    if phase in (3, 4) and n:
        scores = league.functions.liveScores(rid).call()
        i = max(range(n), key=lambda k: scores[k])
        lead = f" · leader {league.functions.getEntry(rid, i).call()[1]} {scores[i] / 1e16:+.2f}%"
    log(f"[{datetime.now(PT):%a %H:%M} PT] round {rid}: {n} entries · pot {pot:g} MON{lead}")


def _wait(chain: Chain, until: float, league, rid: int, log) -> None:
    """Sleep until `until` (unix time), printing a status line every few minutes."""
    next_status = time.time()
    while time.time() < until:
        if time.time() >= next_status:
            _status(chain, league, rid, log)
            next_status = time.time() + STATUS_EVERY
        time.sleep(max(0.0, min(5.0, until - time.time())))


def current_weekly(chain: Chain) -> int | None:
    """The weekly round in league/week.json, if it is still open or racing on this League contract."""
    if not WEEK_FILE.exists():
        return None
    wk = json.loads(WEEK_FILE.read_text())
    lg = league_section(chain.network)
    if wk.get("fundLeague") != lg["fundLeague"] or not wk.get("roundId"):
        return None
    phase = chain.contract("FundLeague", lg["fundLeague"]).functions.getRound(wk["roundId"]).call()[10]
    return wk["roundId"] if phase in (1, 2, 3) else None


def record_history(chain: Chain, league, rid: int, log=print) -> None:
    """Append {time, entries: [{entryId, name, returnPct}]} from liveScores to league/week_history.json; push it."""
    try:
        info = league.functions.getRound(rid).call()
        if info[10] not in (3, 4):
            return
        scores = league.functions.liveScores(rid).call()
        names = [league.functions.getEntry(rid, i).call()[1] for i in range(info[11])]
        hist = json.loads(HISTORY_FILE.read_text()) if HISTORY_FILE.exists() else {"roundId": rid, "points": []}
        if hist.get("roundId") != rid:
            hist = {"roundId": rid, "points": []}
        hist["points"].append({"time": datetime.now(UTC).isoformat(timespec="seconds"),
                               "entries": [{"entryId": i, "name": n, "returnPct": round(scores[i] / 1e16, 4)}
                                           for i, n in enumerate(names)]})
        HISTORY_FILE.write_text(json.dumps(hist, separators=(",", ":")))
        if chain.network != "anvil":
            git_push([HISTORY_FILE], f"League: weekly history (round {rid})", log)
    except Exception as exc:  # noqa: BLE001 - history is a nice-to-have; never stop the matchup for it
        log(f"  (history not updated: {exc})")


def open_weekly(chain: Chain, lock: datetime, end: datetime, stake_mon: float, log=print) -> int:
    lg = league_section(chain.network)
    week = {"mode": "live-weekly", "label": week_label(lock), "lock": lock.isoformat(), "end": end.isoformat(),
            "prices": "FMP live quotes (batch-quote), posted while the US market is open",
            "scoring": "return from the price at lock (Monday open) to the price at the end (Friday close)",
            "pool_size": len(lg["pool"])}
    raw = json.dumps(week, separators=(",", ":")).encode()  # its hash is recorded on-chain as the round's data hash
    data = {"mode": "live-weekly", "tickers": lg["pool"], "dates": [lock.isoformat(), end.isoformat()]}
    rid = open_round(chain, 0, stake_mon, prepared=(Web3.keccak(raw), 1, data), deadline=int(lock.timestamp()),
                     duration=int((end - lock).total_seconds()) - SETTLE_MARGIN, side=True)
    PAGE.mkdir(exist_ok=True)
    WEEK_FILE.write_text(json.dumps({**week, "roundId": rid, "fundLeague": lg["fundLeague"], "rules": raw.decode(),
                                     "rulesHash": Web3.to_hex(Web3.keccak(raw))}, indent=1))
    HISTORY_FILE.write_text(json.dumps({"roundId": rid, "points": []}))
    log(f"  {week['label']} · ends {end.astimezone(PT):%a %H:%M} PT")
    return rid


def run_weekly(chain: Chain, rid: int, lock: datetime, end: datetime, every: int, feed: PriceFeed,
               ignore_market_hours: bool, log=print) -> dict:
    lg = league_section(chain.network)
    league = chain.contract("FundLeague", lg["fundLeague"])
    oracle = chain.contract("ExposureOracle", lg["oracle"])
    log(f"Entries open until the lock ({lock.astimezone(PT):%a %H:%M:%S} PT).")
    _wait(chain, lock.timestamp(), league, rid, log)
    chain.wait_until_time(int(lock.timestamp()))

    chain.phase = "lock+start"
    r = chain.send(league.functions.lock(rid), "lock")
    if league.events.Cancelled().process_receipt(r):
        log("Fewer than 2 entries: no matchup this week; everyone can claim their stake back.")
        return results(chain, rid, live=True)
    target = league.events.Locked().process_receipt(r)[0]["args"]["targetBlock"]
    used = [bytes(t).rstrip(b"\0").decode() for t in league.functions.getRound(rid).call()[0]]
    post_prices(chain, oracle, feed.prices(used), "lock (Monday open)")
    chain.mine_until(target)
    chain.send(league.functions.start(rid), "start")
    log(f"Matchup started: {len(used)} stocks used by entries get live prices.")
    record_history(chain, league, rid, log)

    chain.phase = "live prices"
    first = True
    next_post, next_status = time.time() + every, time.time()
    while time.time() < end.timestamp():
        now = time.time()
        if now >= next_post:
            next_post = now + every
            if ignore_market_hours or market_open():
                post_prices(chain, oracle, feed.prices(used), f"{datetime.now(PT):%a %H:%M} PT")
                record_history(chain, league, rid, log)
                if first:
                    first = False
                    _cost_warning(chain, every, ignore_market_hours, log)
        if now >= next_status:
            _status(chain, league, rid, log)
            next_status = now + STATUS_EVERY
        time.sleep(max(0.0, min(2.0, next_post - time.time(), end.timestamp() - time.time())))

    chain.phase = "settle"
    post_prices(chain, oracle, feed.prices(used), "end (Friday close)")
    started = league.functions.getRound(rid).call()[4]
    chain.wait_until_time(started + league.functions.getRound(rid).call()[3])
    chain.send(league.functions.settle(rid), "settle")
    record_history(chain, league, rid, log)
    return results(chain, rid, live=True)


def _cost_warning(chain: Chain, every: int, ignore_market_hours: bool, log) -> None:
    """MON per week from the first price update's gas limit, at Monad testnet's gas price."""
    from chain.league import testnet_gas_price

    upd = next((c for c in reversed(chain.costs) if c["label"].startswith("posted")), None)
    if not upd:
        return
    price = testnet_gas_price() or upd["gas_price"]
    updates = (5 * 6.5 * 3600 if not ignore_market_hours else 5 * 24 * 3600) / every
    week_gas = updates * upd["gas_limit"] + 4_000_000  # + open, lock, start, settle
    mon = week_gas * price / 1e18
    bal = chain.w3.eth.get_balance(chain.address) / 1e18 if chain.network != "anvil" else None
    log(f"  cost estimate: {updates:.0f} price updates/week x {upd['gas_limit']:,} gas ≈ {mon:.2f} MON per week "
        f"(at {price / 1e9:.0f} gwei)" + (f"; League wallet has {bal:.2f} MON" if bal is not None else ""))
    if bal is not None and bal < 1.5 * mon:
        log("  WARNING: the League wallet may run out this week. Top it up or use a longer --every.")


def weekly(chain: Chain, lock_spec: str, end_spec: str, stake_mon: float, every: int = 300,
           simulate: bool = False, ignore_market_hours: bool = False, weeks: int | None = None, log=print) -> None:
    """Run matchup after matchup: open -> wait for the lock -> live prices -> settle -> season -> next week."""
    feed = PriceFeed(simulate)
    done = 0
    while weeks is None or done < weeks:
        now = datetime.now(UTC)
        lock = parse_when(lock_spec, now)
        end = parse_when(end_spec, lock)
        rid = current_weekly(chain)
        if rid:
            wk = json.loads(WEEK_FILE.read_text())
            lock, end = datetime.fromisoformat(wk["lock"]), datetime.fromisoformat(wk["end"])
            log(f"Weekly matchup already open: round {rid} ({wk['label']}). Continuing it.")
        else:
            rid = open_weekly(chain, lock, end, stake_mon, log)
            log(f"Weekly matchup: round {rid}")
            if chain.network != "anvil":
                git_push([WEEK_FILE, HISTORY_FILE], f"League: open weekly matchup (round {rid})", log)
        r = run_weekly(chain, rid, lock, end, every, feed, ignore_market_hours, log)
        print_results(r, log)
        if r["phase"] == "Settled":
            update_season(chain, r, league_section(chain.network).get("weekly", {}))
            if chain.network != "anvil":
                git_push([SEASON_FILE], f"League: season standings after round {rid}", log)
        done += 1


# ---------------------------------------------------------------------------------------------
# Simulated trading day
# ---------------------------------------------------------------------------------------------

def step_times(steps: int = SIM_STEPS) -> list[str]:
    """9:30 AM to 4:00 PM in `steps` equal steps: ['09:30', '09:49', ..., '16:00']."""
    start = 9 * 60 + 30
    return [f"{(start + round(390 * k / steps)) // 60:02d}:{(start + round(390 * k / steps)) % 60:02d}"
            for k in range(steps + 1)]


def chosen_day_row(rets, day: str) -> int:
    """Row of `rets` for the trading day the organiser picked (YYYY-MM-DD). Says what is available if it isn't one."""
    try:
        want = date.fromisoformat(day.strip())
    except ValueError:
        raise LeagueError(f"--day '{day}' isn't a date. Use YYYY-MM-DD, e.g. 2026-04-09.") from None
    dates = [d.date() for d in rets.index]
    if want in dates:
        return dates.index(want)
    if not dates[0] <= want <= dates[-1]:
        raise LeagueError(f"{want} is outside the price history. Pick a trading day from {dates[0]} to {dates[-1]}.")
    before = max(d for d in dates if d < want)
    after = min(d for d in dates if d > want)
    raise LeagueError(f"{want} wasn't a trading day in the price history (weekend or holiday). "
                      f"Nearest trading days: {before} and {after}.")


def simulate_days(prices, days: int = SIM_DAYS, steps: int = SIM_STEPS, seed: int = SIM_SEED,
                  cap: float = SIM_CAP, day: str | None = None) -> tuple[list[str], list[list[float]], list[str]]:
    """Rows of simulated intraday prices: `days` blocks of steps + 1 rows, all stocks sharing each day's real date.

    With `day` (YYYY-MM-DD) there is exactly ONE block, built from that real trading day's moves, so that is the
    day every round races. Returns (row labels, closes rows, the real dates sampled)."""
    rng = np.random.default_rng(seed)
    rets = prices.pct_change().dropna()
    vol = rets.std().to_numpy()  # each stock's real daily volatility
    base = prices.iloc[-1].to_numpy()  # start every day from the latest real close
    picks = [chosen_day_row(rets, day)] if day else rng.choice(len(rets), size=days, replace=True)
    times = step_times(steps)
    labels, rows, sampled = [], [], []
    for k, i in enumerate(picks):
        day_ret = np.clip(rets.iloc[i].to_numpy(), -cap, cap)  # extreme moves capped
        total = np.log1p(day_ret)
        z = rng.normal(size=(steps, len(base))) * (vol / np.sqrt(steps))
        inc = z - (z.sum(axis=0) - total) / steps  # a random intraday path pinned to the real day's close
        path = base * np.exp(np.vstack([np.zeros(len(base)), np.cumsum(inc, axis=0)]))
        rows += [[round(float(x), 6) for x in r] for r in path]
        labels += [f"Day {k + 1:02d} · {t}" for t in times]
        sampled.append(rets.index[i].date().isoformat())
    return labels, rows, sampled


def write_demo_day_file(tickers: list[str], day: str | None = None) -> tuple[bytes, int, dict]:
    """Write the simulated-day price file. With `day` (YYYY-MM-DD) it holds only that real trading day, so the
    contract has one day to "pick" and every round races it. NOTE: this file is public, so with a chosen day the
    prices can be read before entries close; the page says the organiser picked the day instead of promising
    nobody can know it."""
    from engine.data import get_prices

    prices, _ = get_prices(tickers)
    labels, rows, sampled = simulate_days(prices, day=day)
    what = (f"ONE simulated trading day chosen by the organiser, built from the real moves of {sampled[0]}"
            if day else "50 simulated trading days")
    data = {"about": f"Fantasy Fund League demo day: {what} (9:30 AM-4:00 PM, 20 steps). Each "
                     "day resamples one real historical date for all stocks together, split into intraday steps "
                     "pinned to that day's real close; daily moves capped at +/-15%; fixed seed. Window w is rows "
                     "w*window_stride .. w*window_stride + race_days.",
            "mode": "demo-day", "race_days": RACE_DAYS, "day_seconds": DAY_SECONDS, "base_price": BASE_PRICE,
            "window_stride": SIM_STEPS + 1, "step_times": step_times(), "sampled_dates": sampled,
            "dates": labels, "tickers": list(prices.columns), "closes": rows}
    if day:
        data["chosen_day"] = sampled[0]
    raw = json.dumps(data, separators=(",", ":")).encode()
    REPLAY_FILE.write_bytes(raw)
    return Web3.keccak(raw), len(sampled), data


def demo_day(chain: Chain, entry_seconds: int, stake_mon: float, log=print, day: str | None = None) -> dict:
    lg = league_section(chain.network)
    data_hash, windows, data = write_demo_day_file(lg["pool"], day)
    rid = open_round(chain, entry_seconds, stake_mon, prepared=(data_hash, windows, data))
    if day:
        log(f"Demo day: the organiser picked {data['chosen_day']} (9:30 AM → 4:00 PM); one step every {DAY_SECONDS}s. "
            "The price file is public, so this day is not a secret.")
    else:
        log(f"Demo day: {windows} simulated trading days (9:30 AM → 4:00 PM); a future block picks one after entries "
            f"close; one step every {DAY_SECONDS}s.")
    if chain.network != "anvil":
        git_push([ROOT / "deployments" / f"{chain.network}-league.json", REPLAY_FILE],
                 f"League: open demo-day round {rid}", log)
    return {"round": rid}


def run_demo_day(chain: Chain, log=print) -> dict:
    r = run_round(chain)
    print_results(r, log)
    return r


# ---------------------------------------------------------------------------------------------
# Always-on League: exactly one round open for entries at all times
# ---------------------------------------------------------------------------------------------

def always_on(chain: Chain, entry_seconds: int, stake_mon: float, data: str = "simulated", push: bool = True,
              max_rounds: int | None = None, log=print, day: str | None = None) -> None:
    """Keep one round open. At each deadline: open the NEXT round first, then race the closed one in the background
    (simulated trading day, 60 s). Fewer than 2 entries: lock() cancels it and entrants claim their stake back, so
    no round is ever left 'locked'. Ctrl+C: stop opening rounds, finish every round that has stakes, then exit.

    All rounds share one simulated-day file (fixed seed, hash recorded at every openRound); each round's day is
    still picked by its own future block after its entries close. With `day` (YYYY-MM-DD) the file holds only that
    trading day, so every round races the day the organiser picked."""
    import threading

    import chain.league as lg_mod

    if data != "simulated":
        raise LeagueError("always-on supports --data simulated (live prices only trade during market hours).")
    send_lock = threading.Lock()  # one nonce at a time: the opener and the racer share the operator wallet
    raw_finish = chain.finish
    chain.finish = lambda *a, **k: _locked(send_lock, raw_finish, *a, **k)

    live_file = PAGE / "live.json"
    state = {"mode": "always-on", "openRoundId": None, "deadline": None, "racingRoundId": None,
             "lastFinishedRoundId": None, "race": None}

    def save(race: dict | None = None):
        if race is not None:
            state["race"] = race
        live_file.write_text(json.dumps({**state, "updated": int(time.time())}))

    lg_mod.write_live = lambda st: save(st)  # run_round's progress goes into the 'race' part of live.json

    prepared = write_demo_day_file(league_section(chain.network)["pool"], day)
    if day:
        log(f"Every round races {prepared[2]['chosen_day']}, the day you picked. The price file is public, so this "
            "day is not a secret.")
    racers: list[threading.Thread] = []

    def open_next() -> int:
        rid = open_round(chain, entry_seconds, stake_mon, prepared=prepared)
        state.update(openRoundId=rid, deadline=league_section(chain.network)["currentDeadline"])
        save()
        if push and chain.network != "anvil":
            git_push([ROOT / "deployments" / f"{chain.network}-league.json", REPLAY_FILE, live_file],
                     f"League: round {rid} open", log, force=[live_file])
        return rid

    def race(rid: int):
        state["racingRoundId"] = rid
        save()
        try:
            r = run_round(chain, rid)
            log(f"  round {rid}: {r['phase']}" + (f", winner {', '.join(e['name'] for e in r['entries'] if e['winner'])}"
                                                   if r["phase"] == "Settled" else " (stakes refundable via Claim)"))
        except Exception as exc:  # noqa: BLE001 - keep the League running; the round can still be cancelled
            log(f"  round {rid}: ERROR {exc}")
        finally:
            state.update(racingRoundId=None, lastFinishedRoundId=rid)
            save()

    league = chain.contract("FundLeague", league_section(chain.network)["fundLeague"])
    opened, rid = 0, open_next()
    opened += 1
    next_status = 0.0
    try:
        while True:
            now = time.time()
            if now >= next_status:
                next_status = now + 30
                info = league.functions.getRound(rid).call()
                bal = chain.w3.eth.get_balance(chain.address) / 1e18
                log(f"[{datetime.now(PT):%H:%M:%S}] open round {rid}: {info[11]} entries, pot {info[14] / 1e18:g} MON, "
                    f"closes in {max(0, info[2] - int(now))}s · racing {state['racingRoundId'] or '-'} · "
                    f"wallet {bal:.2f}" + ("  WARNING: League wallet below 10 MON" if bal < 10 and chain.network != "anvil" else ""))
            if now >= state["deadline"]:
                closed = rid
                if max_rounds is None or opened < max_rounds:
                    rid = open_next()  # the next round opens FIRST, so there's always one taking entries
                    opened += 1
                t = threading.Thread(target=race, args=(closed,), daemon=False, name=str(closed))
                t.start()
                racers.append(t)
                if rid == closed:  # --rounds reached (tests): nothing new was opened
                    break
            time.sleep(1)
    except KeyboardInterrupt:
        log(f"\nStopping: no new rounds. Finishing open round {rid} at its deadline so no stake is stranded ...")
        wait = state["deadline"] - time.time()
        if wait > 0:
            time.sleep(wait + 1)
        if not any(t.is_alive() and t.name == str(rid) for t in racers):
            t = threading.Thread(target=race, args=(rid,), daemon=False, name=str(rid))
            t.start()
            racers.append(t)
    for t in racers:
        t.join()
    state.update(openRoundId=None, deadline=None)
    save()
    log("Stopped. Every round is settled or cancelled; winners and refunds can be claimed on the League page.")


def _locked(lock, fn, *a, **k):
    with lock:
        return fn(*a, **k)
