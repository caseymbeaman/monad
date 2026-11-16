# Fantasy Funds League: live demo guide

**Testnet MON only, no real money.** Anyone with a wallet builds their **own** mini-ETF from our stock pool,
stakes 1 MON and enters. After entries close, a future block's hash picks a random window of real past prices,
which is replayed on screen one day every 3 seconds. The entry with the best return takes the whole pot (ties
split it). With fewer than 2 entries, or if the round stalls, everyone gets their stake back.

## How it fits together

| Piece | What it does |
|---|---|
| `contracts/src/FundLeague.sol` | Entries (validated ETFs + stake), lock, random window, start/end prices, scoring, claims |
| `chain/league.py` | Operator: deploys the League's **own** oracle + FundLeague, builds the pool (the full universe), opens a round, runs lock → start → replay → settle |
| `chain/league_bets.py` | Backup: enters 3–4 sample ETFs from test wallets, and claims for them |
| `league/index.html` | The page: Build your ETF, entries list, countdown, live leaderboard, winner, Claim |
| `league/pool.json` | The pool: the full universe (652 of the 666 stocks; 14 lack the 400+ days of history a race window needs) with names, industries and each stock's engine result per theme (powers "Build your ETF": any pool stock can be picked) |
| `league/presets.json` | The engine builder's suggestions for common Want/Avoid combos, restricted to the pool |
| `league/replay_prices.json` | Real past closes for the whole pool; its hash is fixed on-chain before anyone enters |
| `deployments/<network>-league.json` | League addresses, in their **own** file (`deployments/<network>.json` belongs to the main deploy) |

The League never uses the main demo's contracts (it has its own oracle), so replaying old prices can't change
the dashboard or the "try adding XOM" demo.

**Pool on-chain = one Merkle root.** The contract stores only the root of a Merkle tree of the pool's tickers, so
opening a round costs the same for 652 stocks as for 10 (about 0.2M gas). Each entry sends one short proof per stock
(at most 10 hashes) that it is in the pool; the page and `league_bets` build the proofs from the pool list in the
deployment file. As entries come in, the contract keeps a deduplicated list of the tickers they use; **only those get
prices** ($100 right before start, then one price batch per replayed day). Pool stocks nobody picked never need a price.

**ETF rules** (checked by the contract and by the page): 3–8 stocks from the pool, no duplicates, each weight at
least 5%, weights adding up to exactly 100%, one entry per wallet per round, exactly the entry stake, and a name of
up to 32 characters.

## Commands

### Rehearsal on a local Anvil chain

```bash
# terminal 1: a local chain (--host 0.0.0.0 lets phones on the same Wi-Fi reach it)
~/.foundry/bin/anvil --host 0.0.0.0

# terminal 2, from the project folder
source .venv/bin/activate
(cd contracts && forge build)
python -m chain.league deploy --network anvil
python -m chain.league pool   --network anvil              # writes league/pool.json + league/presets.json
python -m chain.league open   --network anvil --entry-seconds 300 --stake 1

# terminal 3: serve the page from the project folder
python -m http.server 8000
#   laptop: http://localhost:8000/league/?network=anvil
#   phone on the same Wi-Fi: http://<laptop-ip>:8000/league/?network=anvil
#   (for phones on Anvil, set "rpc" in deployments/anvil-league.json to http://<laptop-ip>:8545)

# backup entries, if needed: 4 sample ETFs from 4 test wallets
python -m chain.league_bets enter --network anvil --count 4

# terminal 2 again: waits for the deadline, then lock -> start -> 20-day replay -> settle
python -m chain.league run --network anvil

# backup wallets claim (players press Claim on the page)
python -m chain.league_bets claim --network anvil
python -m chain.league status --network anvil
```

All in one go for a rehearsal: `python -m chain.league demo --network anvil --entry-seconds 60`.

### Live on Monad testnet

```bash
# The League has its OWN operator wallet (never the main deployer's): Foundry keystore "league-operator" in
# ~/.foundry/keystores, password in ~/.foundry/keystores/.league-operator.password (both chmod 600, outside the repo).
# Override with LEAGUE_KEYSTORE / LEAGUE_KEYSTORE_PASSWORD_FILE. Fund it with 20 MON first.

python -m chain.league deploy --network monad-testnet      # -> deployments/monad-testnet-league.json
#   (add --reuse-oracle to deploy only a new FundLeague and keep the League's oracle)
python -m chain.league pool   --network monad-testnet
python -m chain.league open   --network monad-testnet --entry-seconds 300 --stake 1
python -m chain.league run    --network monad-testnet      # start right away and leave it running (see "Timing")
```

**Timing.** `run` must call `start` within 256 blocks of the target block, otherwise the contract falls back to
`prevrandao`. That's about 2 minutes on Monad. `run` does it automatically, so start it before the deadline and
leave it running.

## Hosting the page (GitHub Pages)

The page is static: it reads everything from the chain plus a few JSON files next to it, so GitHub Pages can
host it. These must be **committed and pushed** for the live round:

- `league/index.html`, `league/pool.json`, `league/presets.json`, `league/replay_prices.json`
- `deployments/monad-testnet-league.json` (written by `deploy`/`pool`/`open`)

Then enable Pages for the repo (Settings → Pages → Source: "Deploy from a branch" → Branch: `main`, folder `/ (root)` → Save). The link to share is
`https://shannon-maccallum.github.io/portfolio_risk_exposure/league/?network=monad-testnet`. Put it in the QR code on the big screen;
the page shows its own QR code too.

Re-push `deployments/monad-testnet-league.json` and `league/replay_prices.json` after each `open`, because a new round
writes a new replay file. The live leaderboard and the replay day come from the chain, so nothing needs pushing
during the race. Don't push `deployments/anvil-league.json`, `league/live.json` or `league/cost_report.json`; they're
local only.

## Testnet MON budget

Measured on Anvil (one round with 4 entries using 20 distinct stocks, 652-stock pool), priced at Monad testnet's
102 gwei. Monad charges the gas **limit** a transaction asks for; every transaction asks for the estimate × 1.15.

| Who / step | Transactions | Gas limit | MON |
|---|---|---|---|
| Operator: deploy oracle + FundLeague (once) | 2 | 4.40 M | 0.45 |
| Operator: open (Merkle root only, no prices) | 1 | 0.23 M | 0.024 |
| Operator: lock, $100 reset for the used stocks, start | 3 | 1.99 M | 0.20 |
| Operator: 20-day replay (20 used stocks per day) | 20 | 6.28 M | 0.64 |
| Operator: settle (4 entries) | 1 | 1.04 M | 0.11 |
| **Operator: one round** | 25 | 9.54 M | **0.97** |
| Player: one entry (proofs + new stocks added to the used list) | 1 | ~0.59 M | 0.060 + the 1 MON stake |
| Player: one claim | 1 | 0.09 M | 0.009 |

The replay and start/settle costs grow with the number of **distinct stocks entries use** (about 0.3M gas per used
stock per round), not with the pool size. Before this change (60-stock pool, prices for every pool stock) a round
cost the operator 3.06 MON.

**Operator wallet: put in 20 MON.** Setup plus 3 rounds is about 9.6 MON. That covers a rehearsal, the live round
and a spare, with roughly 2× margin for gas-price spikes and bigger rounds.
**Each player: 5 MON** covers stakes and gas for 3 rounds with room to spare. With about 200 MON across the team,
that's 20 for the operator, 5 each for 3–4 players and a few for the backup wallets (`league_bets` tops each one
up with 1.05 MON). That leaves well over 100 MON in reserve.

## Checklist for each teammate (before the pitch)

1. **Install MetaMask** on your phone and create or import a wallet.
2. **Add Monad Testnet**: open the League page inside the MetaMask app's browser and tap **Add Monad Testnet**.
   Or add it by hand: name `Monad Testnet`, RPC `https://testnet-rpc.monad.xyz`, chain ID `10143`, symbol
   `MON`, explorer `https://testnet.monadexplorer.com`.
3. **Get testnet MON**: from the team pool (ask the operator) or https://faucet.monad.xyz. You need 5 MON.
4. **Open the page**: scan the QR code, or tap **Open in MetaMask app** if your phone opened it in a normal
   browser. Tap **Connect MetaMask** and approve.
5. **Rehearse once**: in the rehearsal round, build an ETF (pick Want/Avoid, adjust it, name it), tap
   **Enter (1 MON)** and check it appears in the entries list. Press **Claim** after the race.

## Who does what during the pitch

| Who | Job |
|---|---|
| **Operator** (laptop) | Runs `open` before the pitch and `run` straight after; shows the page full-screen on the projector |
| **Presenter** | Explains the game while entries are open; points at the QR code; narrates the race |
| **Teammates 1–3** (phones) | Build and enter their own ETFs live, ideally with different themes; press **Claim** after the winner banner |
| **Backup** (second laptop) | If phones fail, runs `python -m chain.league_bets enter --network monad-testnet --count 4` before the deadline, then `claim` after |

**Script, about 6 minutes:**
1. 0:00: the round is already open, and the QR code is on screen. "Build your own ETF: pick what you want and what to avoid."
2. 0:00–5:00: teammates build and enter; the entries list and pot grow on every phone.
3. 5:00: entries close. "A block that doesn't exist yet now picks which stretch of real history we replay."
4. 5:05–6:10: the race. One day every 3 seconds; the leaderboard reorders live.
5. 6:10: the winner banner. The winner taps **Claim** and the pot lands in their wallet.

## If something goes wrong

| Problem | Fix |
|---|---|
| A phone can't connect | Use the MetaMask app's built-in browser (not Safari/Chrome); tap **Add Monad Testnet** |
| "Entries are closed" | The deadline passed; this round's entries are over |
| Enter button stays grey | Check the list under the stocks: 3–8 stocks, each ≥ 5%, total 100%, no duplicates, a name |
| Nobody can enter | Run the backup entries from `chain.league_bets` before the deadline |
| Only one entry | No race: the round is cancelled at lock and the stake can be claimed back |
| `run` crashed before start | Run `python -m chain.league run --network <net>` again |
| `run` crashed mid-replay | Prices stop moving; once the race time has passed, `python -m chain.league run` can't restart it, so call `settle` with `cast send <FundLeague> "settle(uint256)" <round>` |
| A round never started | After 1 day anyone can call `cancelStalled`; everyone claims their stake back |

## Weekly matchups (live prices) and the simulated demo day

Both use the deployed FundLeague as it is (no contract changes). Code: `chain/league_live.py`.

### Weekly matchup: like fantasy football

```bash
python -m chain.league weekly --network monad-testnet --lock "Mon 06:30 PT" --end "Fri 13:00 PT" --stake 1
```

- Opens this week's matchup right away; anyone can build an ETF and enter until the lock (Monday market open).
- The contract needs a replay hash and at least one window: the hash is of `league/week.json` (the week's
  rules: lock, end, price source) and `windowCount = 1` (no random window on live prices).
- At the lock: `lock` → live FMP prices (`batch-quote`, one request) for the stocks entries use → `start`.
- During the week: one `postPrices` every `--every` seconds (default 300) while the US market is open (9:30–16:00
  ET, Mon–Fri; exchange holidays aren't modelled), paused when it's closed. The longest gap (overnight, ~17.5 h)
  stays inside the contract's 1-day price freshness.
- At the end: final prices → `settle` (best return from Monday open to Friday close takes the pot) → season
  standings in `league/season.json` (per wallet: weeks entered, wins, MON won, best weekly return), committed
  and pushed (`git pull --rebase` first) → next week's matchup opens automatically.
- A status line every 3 minutes (entries, pot, current leader). After the first price update it prints the
  estimated MON per week and warns if the League wallet can't cover 1.5× that.
- Keep it running (e.g. in `tmux` or `screen`) all week. `--weeks N` stops after N matchups.
- Tests on Anvil: `--lock +1m --end +6m --every 30 --simulate-prices --ignore-market-hours --weeks 1`
  (Anvil standings go to `data/cache/season_anvil.json`, never the real season file).

**Cost per week.** Measured on Anvil: one price update for 15 used stocks has a 288,458 gas limit (about
0.029 MON at 102 gwei); it grows by ~14k gas per extra stock. A 6.5-hour session every 5 minutes is 78 updates a
day, 390 a week:

| Price update every | Updates / week | MON / week (15 used stocks) |
|---|---|---|
| 5 min (default) | 390 | ≈ 11.5 |
| 15 min | 130 | ≈ 3.8 |
| 30 min | 65 | ≈ 1.9 |

Plus about 0.3 MON per week for open, lock, start and settle. Pick `--every` to fit the League wallet.

### Simulated trading day (demos when the market is closed)

```bash
python -m chain.league demo-day --network monad-testnet --entry-seconds 300 --stake 1
```

- Writes `league/replay_prices.json` with 50 simulated trading days, 9:30 AM → 4:00 PM in 20 steps. Each day
  resamples ONE real historical date for every pool stock together (they move together, as on a real day), and
  splits each stock's real return for that date into 20 intraday steps: a random path, scaled to the stock's own
  volatility, pinned to that day's real close. Daily moves are capped at ±15%. Fixed seed (20261115).
- Rows are labeled by time ("Day 07 · 10:09"); `window_stride = 21`, so window w is rows 21w … 21w + 20.
- Same fairness as a replay round: the file's hash is recorded at `openRound` with `windowCount = 50`; a future
  block picks the day after entries close; one step every 3 s (a 60-second race); `settle`.
- It opens the round, pushes the deployment file and replay file for the page, then waits for the deadline and
  runs the race. Cost: the same as a replay round, about 1 MON for the operator with ~20 distinct stocks.

### Picking the trading day yourself (`--day`)

By default a future block picks the simulated day after entries close, so nobody can know it in advance. To race a
specific real trading day instead, add `--day YYYY-MM-DD` to `demo-day` or `always-on`:

```bash
python -m chain.league demo-day  --network monad-testnet --entry-seconds 300 --stake 1 --day 2026-04-09
python -m chain.league always-on --network monad-testnet --entry-seconds 150 --stake 1 --data simulated --day 2026-04-09
```

- The price file then holds only that day (built from its real moves, same simulation otherwise), so the contract has
  one day to pick. No contract change and no redeploy: the next round opened this way uses it.
- A weekend, holiday or date outside the price history is refused, and the message names the nearest trading days.
- **The day is public.** The price file is published when the round opens, so anyone can read that day's prices
  before entries close. The page switches its wording to "picked by the organiser" and drops "nobody can know it in
  advance". Use it for a themed demo ("race the day of the tariff sell-off"), not when the surprise matters.

### Always-on League (one round always open)

```bash
python -m chain.league always-on --network monad-testnet --entry-seconds 150 --stake 1 --data simulated
```

- Exactly one round takes entries at all times. At its deadline the NEXT round opens first, then the closed
  round locks → starts → replays its simulated trading day (60 s) → settles in the background.
- Fewer than 2 entries: `lock` cancels the round and entrants claim their stake back (no round is left locked).
- All rounds share one simulated-day file (fixed seed, its hash recorded at every `openRound`); each round's day
  is picked by its own future block.
- `league/live.json`: `openRoundId` + `deadline`, `racingRoundId`, `lastFinishedRoundId`, plus the current race's
  progress. Pushed with the deployment file on every new round.
- Status line every 30 s with a warning below 10 MON. Ctrl+C: opens nothing new, finishes the open round at its
  deadline (race or refund) and waits for every race, so no stake is stranded.
- Cost: an open costs ~0.02 MON and a cancelled round ~0.01 MON; a round that races costs ~0.7 MON (15 used stocks).
