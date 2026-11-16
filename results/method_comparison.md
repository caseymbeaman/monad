# Method comparison: A vs B vs C

## Update: re-run on the 666-stock universe (sector-control version C deleted)

| Measure | A (before) | A* | **B (kept)** |
|---|---|---|---|
| False alarms, real stocks from unrelated sectors (target ≤ 5%) | 28.5% | 28.5% | **11.3%** |
| (calibration) false alarms, pure-noise references | 1.9% | 1.9% | 1.8% |
| Leave-one-out: reference re-found as High/Moderate | 96.5% | 98.2% | **96.5%** |
| ETF agreement, median Spearman (8 themes, 649 stocks) | 0.64 | 0.64 | **0.49** |
| Results that are Not determined | 33.9% | 34.0% | 34.2% |
| Price check | 66/67 | 66/67 | 64/67 |
| Simulated stocks correct (of 600) | 590 | 590 | 588 |
| High/Moderate calls in the 9×10 sanity table | 19 | 19 | 12 |

On the larger universe B's advantage is much bigger than on the old 106 names (false alarms 28.5% → 11.3%), so B stays.
ETF agreement per theme under B: GLD 0.75, CIBR 0.65, XLY 0.54, USO 0.53, ITA 0.45, COPX 0.44, ICLN 0.42, XLV 0.38.

---

*Earlier run (106-name universe), kept for the record:*

**Kept: version B** (market + four style controls chosen by the objective 15% rule, no sector control).
It's the only version that meaningfully cuts false alarms on real stocks (20.4% → 15.9%). It keeps the leave-one-out
hit rate (96.5%) and the price check (64/67), and it fixes 3 of the 4 named sanity problems. The sector control
(C) did worse than B on every aggregate measure, so it is implemented but switched off.
**No version reaches the 5% false-alarm target.** The style controls help, but they don't fix the problem at the source.

Run `python -m engine.method_comparison` (raw numbers in `results/method_comparison.json`). All versions use the same
themes (KR and DIS dropped, ADM as the Healthcare control), the same 499 days and the same random draws.
CRWV is excluded (short history).

| Version | Controls |
|---|---|
| A | SPY, TLT, VALUE (AI and Cyber without VALUE, by hand) — the previous method |
| A* | A, but VALUE kept or skipped by the 15% rule (skipped for AI only) |
| **B** | **SPY, TLT + VALUE, SIZE, MOM, LOWVOL, each kept or skipped by the 15% rule** |
| C | B + each holding's sector ETF − SPY (also with the 15% rule) |

## Objective skips (15% rule; Tier 1 references' share of the control ETF's holdings)

| Theme | Skipped | Exact % |
|---|---|---|
| AI | VALUE (style) | IWF 27.06% (IWD 5.05%) |
| AI | XLK (sector, used in C only) | 34.01% |
| Oil | XLE (sector, C only) | 31.68% |
| Healthcare | XLV (sector, C only) | 25.06% |
| Aerospace & defense | XLI (sector, C only) | 19.46% |
| All other themes / controls | none | all under 15% |

MOM, SIZE and LOWVOL are kept for every theme, AI included: AI references are under 15% of MTUM, RSP and USMV.
Cybersecurity now gets VALUE, because the rule replaces the old hand-made exception.

## Before → after

| Measure | A (before) | A* | **B (kept)** | C |
|---|---|---|---|---|
| 1. False alarms, real stocks from unrelated sectors (target ≤ 5%) | 20.4% | 20.4% | **15.9%** | 17.9% |
| (calibration) false alarms, pure-noise references | 1.0% | 1.0% | 1.5% | 1.4% |
| 3. Leave-one-out: reference re-found as High/Moderate | 96.5% | 98.2% | **96.5%** | 89.5% |
| 4. ETF agreement, median Spearman (8 themes) | 0.68 | 0.68 | **0.53** | 0.45 |
| 5. Results that are Not determined | 33.5% | 33.8% | **33.6%** | 32.9% |
| 6. Price check | 65/67 | 65/67 | **64/67** | 62/67 |
| Known answers (600 simulated stocks) | 593 | 593 | **593** | 593 |
| Math check vs hand calculation | exact | exact | **exact** | exact |

ETF agreement per theme, A → B: GLD 0.94 → 0.86, XLY 0.85 → 0.49, CIBR 0.70 → 0.68, XLV 0.72 → **0.02**, ICLN 0.66 → 0.59,
COPX 0.63 → 0.44, ITA 0.58 → 0.56, USO 0.48 → 0.49. Some drop is expected, because the ETF beta is measured against SPY only
and so still contains the style swings B removes. Healthcare's collapse is a real warning: the low-volatility ETF (USMV)
leans heavily on defensive healthcare stocks, so LOWVOL absorbs much of the healthcare signal, even though healthcare references are under 15% of USMV.

## 2. Sanity table: the four named problems

| Case | A | B | C |
|---|---|---|---|
| AAPL Healthcare | High ⚠️ | Lim-low ✅ | Lim-low ✅ |
| KO Healthcare / Discretionary / Clean energy | High / Mod / Mod ⚠️ | ND ✅ / **High ⚠️** / Mod ⚠️ | Lim-low / Lim-low / ND ✅ |
| COP Aerospace & defense | High ⚠️ | **High ⚠️** | ND ✅ |
| SMH Gold | High ⚠️ | Lim-low ✅ | Lim-low ✅ |

High/Moderate calls in the 9×10 table: A 19 (≈9 wrong), B 12 (4 wrong: **COP AI High**, COP Aerospace & defense High, KO Discretionary High,
KO Clean energy Moderate), C 12 (4 wrong: NVDA Aerospace & defense, NEM AI, NEM Bank lending, JNJ Clean energy).

Version B sanity table:

| | AI | Bank | Clean | Disc | Cyber | Aerospace & defense | Gold | Health | Metals | Oil |
|---|---|---|---|---|---|---|---|---|---|---|
| SMH | High | Lim | ND | Lim | Lim-low | Lim-low | Lim-low | ND | ND | Lim-low |
| NVDA | High (listed) | ND | ND | Lim | Lim-low | ND | Lim-low | Lim-low | ND | ND |
| XOM | ND | ND | ND | Lim-low | ND | ND | Lim | Lim | Lim-low | Mod |
| COP | **High ⚠️** | ND | ND | Lim-low | Lim-low | **High ⚠️** | Lim | Lim-low | Lim-low | High (listed) |
| JNJ | Lim | Lim-low | ND | ND | Lim | Lim-low | Lim-low | High | ND | Lim-low |
| LMT | ND | Lim-low | ND | Lim-low | Lim-low | High (listed) | Lim | Lim | ND | ND |
| NEM | ND | ND | ND | Lim-low | Lim-low | ND | High (listed) | ND | Mod | ND |
| KO | Lim | Lim-low | **Mod ⚠️** | **High ⚠️** | Lim | ND | Lim | ND | Lim-low | Lim-low |
| AAPL | Lim | ND | Lim-low | ND | ND | Lim-low | Lim | Lim-low | ND | Lim-low |

## Builder with version B

**Want AI + avoid Oil:** 7 holdings at 14.29% each: CDNS, CRM, GOOGL, META, SMH, XLK, XLU. Both goals pass on
the re-screen, and every pick is lower-confidence on Oil. COP is AI High in B, but it's excluded here because it's Oil High.
A plain "want AI" basket would include it.

**Want Gold + want Aerospace & defense:** 1 holding (HII, 15%) + 85% cash. The goals pass, but HII as "Gold High" is wrong.
The two-key rule removed only CEG and QCOM from Gold, and BAC, COP, CVX and GEHC from Aerospace & defense. It confirmed other wrong picks
(Gold: DG, HII, ALB, SQM; Aerospace & defense: C, WFC, XLF, NFLX, TJX, RCL), because the ETF check runs on the same controls
and picks up the same co-movement.

## Pitch numbers (version B)

1. **99%**: 593 of 600 simulated stocks with known exposure classified correctly.
2. **1.5%**: false alarms on pure noise, inside the 5% budget. (On real stocks from unrelated sectors it's 15.9%; don't claim 1.5% for real stocks.)
3. **96.5%**: reference companies hidden from the model are still found exposed to their own theme.

## Open problems, most serious first

1. Real-stock false alarms are still 15.9%, and the two-key ETF check doesn't catch them. "Want" baskets for Gold and Aerospace & defense contain unrelated stocks.
2. COP comes out AI High under B (KO comes out Discretionary High). Themes without an ETF (AI) get no second key.
3. Healthcare's agreement with its ETF collapses under B (0.72 → 0.02), because LOWVOL absorbs defensive healthcare.
4. Bank Moderates (WFC 57%, C 70%, BAC 53%) now exceed the 40% High cutoff under the new NII formula, and the formula overstates MTB versus its call (79% vs ~71%).
5. Price check under B: COST and DG (Discretionary Moderate) fail; MSFT fails (accepted).
