# Evidence verification (fast skim)

Each reference's evidence % checked against its latest FMP earnings-call transcript (`python -m engine.verify_evidence`). A quarter's share can differ from the fiscal-year share; within 10 points counts as VERIFIED. NOT FOUND means the call didn't state a comparable number, not that the evidence is wrong. Nothing in themes/*.yaml was changed.

**Totals:** 3 verified, 1 mismatch, 53 not found.

## AI

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| NVDA | High | 90% | 92.7% | **VERIFIED** | Q2 data center revenue increased 18% quarter-over-quarter to $89 billion with strong contributions from both sub segments hyperscale and ACI … Total revenue of $96 billion more than doubled year-over-year as growth accelerated for the fourth consecutive | FMP earnings call transcript FY2027 Q2 (2026-08-26) |
| MU | High | 55.5% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q4 (2026-09-30) |
| VRT | High | 50% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-28) |
| AVGO | High | 49% | 56.4% | **VERIFIED** | Reviewed: auto-match grabbed gross margin (75%). From the same call: AI semiconductor revenue $16.7B / consolidated revenue $29.6B = 56%, vs 49% evidence (quarter vs full year). Call text: Gross margin was 75% of revenue in the quarter, down 210 basis points sequentially as AI semiconductor revenue was a greater proportion of our total revenue mix. | FMP earnings call transcript FY2026 Q3 (2026-09-02) |
| TSM | Moderate | 18% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-15) |
| MSFT | Moderate | 11.2% | - | **NOT FOUND** |  | FMP earnings call transcript FY2027 Q1 (2026-10-28) |
| VST | Moderate | 8.6% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-06) |

## Oil

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| PR | High | 96.5% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-05) |
| FANG | High | 88.3% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-03) |
| COP | High | 66.3% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-05) |
| EOG | High | 61.6% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-06) |
| CVX | Moderate | 29.0% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-30) |
| SHEL | Moderate | 13.4% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-29) |

## Bank lending / net interest income

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| MTB | High | 79.2% | 70.8% | **MISMATCH** | Reviewed: real gap from the definition. The call implies NII / (NII + fees) = 71%; FMP's income-statement revenue gives 56%. Bank evidence % is likely understated for all banks. Call text: Taxable equivalent net interest income was $1.8 billion, largely unchanged from the linked quarter, as the benefits from one additional day  … Non-interest income was $743 million compared to $740 million in the linked quarter. | FMP earnings call transcript FY2026 Q3 (2026-10-16) |
| ZION | High | 77.6% | - | **NOT FOUND** | Reviewed: auto-match used an annualized fee projection, not the quarter's fees. Likely the same definition gap as MTB. Call text: Taxable equivalent net interest income was $684 million, up $7 million or 1% from the prior quarter, up $12 million or 2% from the year ago  … Before moving on, I will note that the $136 million fee income number shown for 2026 is annualized based on pe | FMP earnings call transcript FY2026 Q3 (2026-10-19) |
| CFG | High | 79.8% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-16) |
| RF | High | 66.3% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-16) |
| WFC | Moderate | 56.7% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-13) |
| C | Moderate | 70.2% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-13) |
| BAC | Moderate | 53.1% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-14) |

## Clean energy (solar & renewables)

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| FSLR | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-10-29) |
| SEDG | High | 93.5% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-04) |
| RUN | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-11-04) |
| NEE | Moderate | 32.4% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-21) |

## Consumer discretionary

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| HD | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q2 (2026-08-18) |
| NKE | High | 99.7% | - | **NOT FOUND** |  | FMP earnings call transcript FY2027 Q1 (2026-10-01) |
| TJX | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2027 Q2 (2026-08-19) |
| RCL | High | 95.2% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-27) |
| COST | Moderate | 25.5% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q4 (2026-09-24) |
| DG | Moderate | 18.0% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q2 (2026-08-27) |

## Cybersecurity

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| CRWD | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2027 Q2 (2026-08-26) |
| PANW | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q4 (2026-09-01) |
| FTNT | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-10-28) |
| CHKP | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-11-02) |
| CSCO | Moderate | 13.0% | - | **NOT FOUND** |  | FMP earnings call transcript FY2027 Q1 (2026-11-12) |

## Aerospace & defense

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| LMT | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-10-22) |
| NOC | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-10-20) |
| HII | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-10-29) |
| GD | High | 75.1% | - | **NOT FOUND** | Reviewed: only one of the three defense segments (Combat Systems) was matched, so no valid comparison. Call text: Combat Systems had revenue of $2.39 billion, up 6% over the year ago quarter. … We reported earnings of $4.49 per diluted share on revenue of $14.57 billion, operating earnings of $1.527 bil | FMP earnings call transcript FY2026 Q3 (2026-10-30) |
| RTX | Moderate | 30.8% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-20) |
| BA | Moderate | 30.4% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-27) |
| GE | Moderate | 23.0% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-20) |

## Gold & precious metals

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| SSRM | High | 94.8% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-03) |
| CDE | High | 100.0% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-05) |
| PAAS | High | 83.8% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-05) |
| NEM | High | 63.2% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-22) |

## Healthcare

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| PFE | High | 97.8% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-03) |
| MRK | High | 89.4% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-29) |
| LLY | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-10-29) |
| GEHC | High | 100.0% | - | **NOT FOUND** | (evidence is 'all segments are theme business'; no single share to compare) | FMP earnings call transcript FY2026 Q3 (2026-10-28) |

## Industrial / EV metals (copper + lithium)

| Ticker | Group | Evidence | Found in call | Status | Quote | Source |
|---|---|---|---|---|---|---|
| SCCO | High | 74.8% | 74.0% | **VERIFIED** | Copper represented 74% of our sales in the third quarter of this year. | FMP earnings call transcript FY2026 Q3 (2026-10-27) |
| FCX | High | 74.5% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-27) |
| BHP | High | 49.4% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q2 (2026-02-17) |
| ALB | High | 52.7% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-11-05) |
| SQM | High | 50.0% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q2 (2026-08-19) |
| RIO | Moderate | 12.6% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q2 (2026-07-28) |
| VALE | Moderate | 12.9% | - | **NOT FOUND** |  | FMP earnings call transcript FY2026 Q3 (2026-10-30) |
