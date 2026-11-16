# Regression check (666-stock universe, method version B)

**Verdict.** The math is exact, and on simulated stocks the method gets the right answer 588–589 times out of 600. Pure-noise
references flag under 1% of holdings. On real stocks it's better than before but still not at target. With real companies from
unrelated sectors as references, it flags **11.5%** of holdings, against a 5% target (it was 15.9% on the old 106-name universe).
The previous method (A) flags 28.5% on this universe, so the style controls are clearly earning their place. Leave-one-out stays
at 96.5%. The sanity table still has 4 wrong calls out of 12 High/Moderate results (COP as AI High and Aerospace & defense High; KO as
Discretionary High and Clean-energy Moderate). Way 2 guards against these with the business check: those stocks can't be picked
for a theme they don't do business in. Method and thresholds unchanged.

Data: 499 trading days (Nov 18 2024 – Nov 13 2026), 649 universe stocks plus test names, in one shared frame. 17 short-history
stocks are left out of these tests: AMRZ, BSP, CBRS, CRCL, CRWV, FDXF, HONA, JBS, MDLN, PS, Q, SKHY, SNDK, SPCX, SUNB, VG, VYLR.
Run `python -m engine.regression_check`; raw numbers are in `results/regression_check_raw.json`.

## Scorecard

| # | Test | Result | Verdict |
|---|---|---|---|
| 1 | Math check: SMH/AI, XOM/Oil, JNJ/Healthcare redone by hand (statsmodels + covariance algebra) | Tiers identical; largest difference 5e-17 | ✅ Pass |
| 2a | Simulated stocks, AI: High-group / Moderate-group / market-only (100 each) | 100% / 100% / 100% (market-only: 59% reach a clean Limited) | ✅ Pass |
| 2b | Simulated stocks, Oil | 100% / 90% / 99% (market-only: 35% reach Limited) | ✅ Pass |
| 3a | False alarms, pure-noise references (1,000 holdings) | 0.9% | ✅ Pass (≤ 5%) |
| 3b | False alarms, random real tickers as references, holdings from other sectors (1,000 holdings) | **11.5%** | ⚠️ Concern (> 5%) |
| 4 | Leave-one-out: each reference re-found as High/Moderate in its own theme (57) | 96.5% (exact group 73.7%); misses: MU, MSFT | ✅ Pass / ⚠️ High vs Moderate blurry |
| 5 | ETF agreement: Spearman of method score vs direct beta on the theme ETF (649 stocks) | GLD 0.75, CIBR 0.65, XLY 0.54, USO 0.53, ITA 0.45, COPX 0.44, ICLN 0.42, XLV 0.38; median 0.49; all p < 1e-20 | ✅ Pass (moderate) |
| 6 | Price check (references move with their group; control doesn't) | 64/67 (fails: MSFT accepted; COST, DG) | ✅ mostly |

Leave-one-out detail: 10 of 22 Moderate references come out High when hidden (TSM, VST, NEE, COST, DG, CSCO, RTX, RIO, CVX, SHEL).

## Sanity table (computed fresh; L = listed tier)

| | AI | Bank | Clean | Disc | Cyber | Aerospace & defense | Gold | Health | Metals | Oil |
|---|---|---|---|---|---|---|---|---|---|---|
| SMH | High | Lim | ND | Lim | Lim-low | Lim-low | Lim-low | ND | ND | Lim-low |
| NVDA | High (L) | ND | ND | Lim | Lim-low | ND | Lim-low | Lim-low | ND | ND |
| XOM | ND | ND | ND | Lim-low | ND | ND | Lim | Lim | Lim-low | Mod |
| COP | **High ⚠️** | ND | ND | Lim-low | Lim-low | **High ⚠️** | Lim | Lim | Lim-low | High (L) |
| JNJ | Lim | Lim-low | ND | ND | Lim | Lim-low | Lim-low | High | ND | Lim-low |
| LMT | ND | Lim-low | ND | Lim-low | Lim-low | High (L) | Lim | Lim | ND | ND |
| NEM | ND | ND | ND | Lim-low | Lim-low | ND | High (L) | ND | Mod | ND |
| KO | Lim | Lim-low | **Mod ⚠️** | **High ⚠️** | Lim | ND | Lim | ND | Lim-low | Lim-low |
| AAPL | Lim | ND | Lim-low | ND | ND | Lim-low | Lim | Lim-low | ND | Lim-low |

None of the four wrong calls can reach a Way 2 "want" basket. COP isn't in an AI or aerospace & defense industry, and KO isn't in a
discretionary or clean-energy one, so the business check stops them.

## 3 pitch numbers

1. **98%**: 589 of 600 simulated stocks with known exposure classified correctly.
2. **Under 1%**: false alarms on pure noise (0.9%).
3. **96.5%**: hide a reference company from the model, and it still finds that company exposed to its own theme.

(On real stocks from unrelated sectors the false-alarm rate is 11.5%. Don't quote "under 1%" for real stocks. The business check is
what keeps those false alarms out of baskets.)

## Problems, most serious first

1. Real-stock false alarms: 11.5% (target 5%). Way 2's business check blocks them from "want" baskets, but Way 1 (check my portfolio)
   still reports them as exposure (e.g. COP shows as AI High).
2. TSM comes out **Oil High**, so it fails "avoid Oil" baskets even though it's a core AI name.
3. Ranking by strength (beta sum) favours very volatile names (CRWV, NBIS, SMCI) over core references (NVDA ranks 53rd of 65 for
   want AI + avoid Oil).
4. High vs Moderate is blurry: 10 of 22 Moderate references come out High when hidden.
5. 35% of all results are Not determined.
