# Theme summary

### AI  (ground truth: none; controls: SPY, TLT, SIZE, MOM, LOWVOL)
Measure: AI share of revenue

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | NVDA | NVIDIA Corporation | 90% | From capstone research, most recent filings at the time | Data-center GPUs are most of revenue. |
| High | MU | Micron Technology, Inc. | 55.5% | From capstone research, most recent filings at the time | High-bandwidth and data-center memory for AI servers. |
| High | VRT | Vertiv Holdings Co | 50% | From capstone research, most recent filings at the time | Power and cooling for AI data centers. |
| High | AVGO | Broadcom Inc. | 49% | From capstone research, most recent filings at the time | Custom AI chips and AI networking. |
| Moderate | TSM | Taiwan Semiconductor Manufactu | 18% | From capstone research, most recent filings at the time | Manufactures most AI accelerators, but also phones, PCs, autos. |
| Moderate | MSFT | Microsoft Corporation | 11.2% | From capstone research, most recent filings at the time | AI services inside Azure; most revenue is other software and cloud. **Note:** Fails the group-consistency price check (doesn't move with TSM/VST beyond the market). Expected: TSM, MSFT and VST are different businesses. Kept by decision. |
| Moderate | VST | Vistra Corp. | 8.6% | From capstone research, most recent filings at the time | Power producer selling electricity to AI data centers. |
| Control | ADM | Archer-Daniels-Midland Company | 0% | From capstone research, most recent filings at the time | Agricultural processor with no AI revenue. |
| Tier 2 → High | CRWV | CoreWeave, Inc. Class A Common | 100% | - | AI cloud provider: renting GPUs is the whole business. |
| Tier 2 → High | GOOGL | Alphabet Inc. | n/a | - | Large AI exposure through Gemini and Cloud, but no disclosed AI share. |
| Tier 2 → Moderate | JPM | JPMorgan Chase & Co. | n/a | - | Big AI spender and user, but no disclosed AI revenue share. |
| Tier 2 → Moderate | META | Meta Platforms, Inc. | n/a | - | AI drives ad ranking and capex, but no disclosed AI revenue share. |
| Tier 2 → Moderate | TSLA | Tesla, Inc. | n/a | - | Autonomy and robotics bets, but no disclosed AI revenue share. |

### Oil  (ground truth: USO; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Crude-oil share of revenue (CVX: upstream oil & gas production share)

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | PR | Permian Resources Corporation | 96.5% | 2025 | Permian pure-play producer; almost all revenue is crude sales. |
| High | FANG | Diamondback Energy, Inc. | 88.3% | 2025 | Permian oil producer; revenue follows crude prices. |
| High | COP | ConocoPhillips | 66.3% | 2025 | Largest US independent producer; two-thirds of revenue is crude. |
| High | EOG | EOG Resources, Inc. | 61.6% | 2025 | Large low-cost US producer; most revenue is oil and condensate. |
| Moderate | CVX | Chevron Corporation | 29.0% | 2025 | Integrated major: production is ~30% of segment revenue; refining offsets part of oil moves. |
| Moderate | SHEL | Shell plc | 13.4% | 2025 | Integrated major: crude sales are a minority; most revenue is refined products and gas. |
| Control | ADBE | Adobe Inc. | 0% | - | Design and document software; no oil-related segment or fuel-cost dependence. |
| Tier 2 → High | OXY | Occidental Petroleum Corporati | n/a | - | 94% of revenue is its Oil and Gas segment, but FMP doesn't split oil from gas. |
| Tier 2 → Moderate | SLB | Slb N.V. | n/a | - | Oilfield services: revenue depends on drilling budgets; no disclosed oil-price share. |
| Tier 2 → Moderate | HAL | Halliburton Company | n/a | - | Oilfield services: revenue depends on drilling budgets; no disclosed oil-price share. |

### Bank lending / net interest income  (ground truth: none; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Net interest income / (net interest income + non-interest income)  
Note: Validated by group consistency only (like AI). TLT was dropped as ground truth: over this window banks did not move opposite to long-term bonds beyond the market.

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | MTB | M&T Bank Corporation | 79.2% | 2025 | Regional bank; most income is lending spread. |
| High | ZION | Zions Bancorporation, National | 77.6% | 2025 | Regional bank; most income is lending spread. |
| High | CFG | Citizens Financial Group, Inc. | 79.8% | 2025 | Regional bank; most income is lending spread. |
| High | RF | Regions Financial Corporation | 66.3% | 2025 | Regional bank; most income is lending spread. |
| Moderate | WFC | Wells Fargo & Company | 56.7% | 2025 | Large bank; lending spread plus a big fee business. |
| Moderate | C | Citigroup Inc. | 70.2% | 2025 | Global bank; lending spread plus fees and trading. |
| Moderate | BAC | Bank of America Corporation | 53.1% | 2025 | Large bank; lending spread plus fees and markets. |
| Control | COST | Costco Wholesale Corporation | 0.2% | 2026 | Warehouse retailer with no lending or deposit business. |

### Gold & precious metals  (ground truth: GLD; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Gold and silver share of revenue  
Note: Exception (approved): no Moderate references. FCX and SCCO (copper miners) were dropped.

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | SSRM | SSR Mining Inc. | 94.8% | 2025 | Gold and silver miner; nearly all revenue is precious metals. |
| High | CDE | Coeur Mining, Inc. | 100.0% | 2025 | Gold and silver miner; all revenue is precious metals. |
| High | PAAS | Pan American Silver Corp. | 83.8% | 2025 | Silver and gold miner. |
| High | NEM | Newmont Corporation | 63.2% | 2025 | World's largest gold miner. Lower bound: gold inside concentrate isn't split out. |
| Control | KO | The Coca-Cola Company | 0% | - | Soft-drink company; no metals revenue or link to gold prices. |
| Tier 2 → High | WPM | Wheaton Precious Metals Corp. | n/a | - | Precious-metals streaming company; FMP has no segment data. |
| Tier 2 → High | KGC | Kinross Gold Corporation | n/a | - | Gold miner; FMP has no segment data. |
| Tier 2 → High | AEM | Agnico Eagle Mines Limited | n/a | - | Gold miner; FMP's latest segment data is from 2013, too old to cite. |

### Aerospace & defense  (ground truth: ITA; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Defense / government segment share of revenue

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | LMT | Lockheed Martin Corporation | 100.0% | 2025 | Largest defense contractor; all four segments serve defense customers. |
| High | NOC | Northrop Grumman Corporation | 100.0% | 2025 | Defense contractor; all segments serve defense and government. |
| High | HII | Huntington Ingalls Industries, | 100.0% | 2025 | Navy shipbuilder; all segments serve defense. |
| High | GD | General Dynamics Corporation | 75.1% | 2025 | Defense segments; Gulfstream jets are the rest. |
| Moderate | RTX | RTX Corporation | 30.8% | 2025 | Raytheon defense unit; Pratt and Collins are mostly commercial aviation. |
| Moderate | BA | The Boeing Company | 30.4% | 2025 | Defense unit; most revenue is commercial airplanes. |
| Moderate | GE | GE Aerospace | 23.0% | 2025 | Military engines; most revenue is commercial engines. |
| Control | INTU | Intuit Inc. | 0% | - | Tax and accounting software; no defense or government-contract revenue. |

### Healthcare  (ground truth: XLV; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Healthcare share of revenue  
Note: Exception (approved): no Moderate references. PG and WM were dropped (don't trade like healthcare), then KR (failed the price check once style controls were added).

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | PFE | Pfizer Inc. | 97.8% | 2025 | Large drugmaker. |
| High | MRK | Merck & Co., Inc. | 89.4% | 2025 | Large drugmaker; animal health is the rest. |
| High | LLY | Eli Lilly and Company | 100.0% | 2025 | Drugmaker; all revenue is medicines. |
| High | GEHC | GE HealthCare Technologies Inc | 100.0% | 2025 | Medical imaging and diagnostics; all segments are healthcare. |
| Control | ADM | Archer-Daniels-Midland Company | 0% | - | Crop processing and food ingredients; no healthcare segment. |
| Tier 2 → High | UNH | UnitedHealth Group Incorporate | n/a | - | Health insurer; FMP segments are revenue types (premiums, services), not a health share. |

### Industrial / EV metals (copper + lithium)  (ground truth: COPX; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Copper and lithium share of revenue

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | SCCO | Southern Copper Corporation | 74.8% | 2025 | Copper miner; three-quarters of revenue is copper. |
| High | FCX | Freeport-McMoRan Inc. | 74.5% | 2025 | Largest US-listed copper miner. |
| High | BHP | BHP Group Limited | 49.4% | 2026 | Diversified miner; copper is about half of revenue. |
| High | ALB | Albemarle Corporation | 52.7% | 2025 | Largest lithium producer; Energy Storage is its lithium segment. |
| High | SQM | Sociedad Química y Minera de C | 50.0% | 2025 | Chilean lithium producer; lithium is half of revenue. |
| Moderate | RIO | Rio Tinto Group | 12.6% | 2025 | Diversified miner; mostly iron ore and aluminium. |
| Moderate | VALE | Vale S.A. | 12.9% | 2025 | Mostly iron ore; copper is a growing minority. |
| Control | INTU | Intuit Inc. | 0% | - | Tax and accounting software; no metals revenue. |
| Tier 2 → High | TECK | Teck Resources Limited | n/a | - | Copper-focused miner after selling its coal unit; FMP has no segment data. |
| Tier 2 → High | HBM | Hudbay Minerals Inc. | n/a | - | Copper miner; FMP has no segment data. |
| Tier 2 → High | LAC | Lithium Americas Corp. | n/a | - | Lithium developer; no meaningful revenue yet. |

### Clean energy (solar & renewables)  (ground truth: ICLN; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Solar and renewable-energy share of revenue  
Note: Exception (approved): 1 Moderate reference (NEE). Uranium/nuclear names (LEU, BWXT, CCJ) were dropped to keep the group to solar and renewables.

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | FSLR | First Solar, Inc. | 100.0% | 2025 | US solar panel maker; all revenue is solar modules. |
| High | SEDG | SolarEdge Technologies, Inc. | 93.5% | 2025 | Solar inverters and optimizers. |
| High | RUN | Sunrun Inc. | 100.0% | 2025 | Residential solar installer; all segments are solar systems and contracts. |
| Moderate | NEE | NextEra Energy, Inc. | 32.4% | 2025 | Utility; NextEra Energy Resources (renewables developer) is about a third. |
| Control | KO | The Coca-Cola Company | 0% | - | Soft-drink company; no energy-generation revenue. |
| Tier 2 → High | ENPH | Enphase Energy, Inc. | n/a | - | Solar microinverters; FMP reports a single segment with no product split. |
| Tier 2 → High | BEP | Brookfield Renewable Partners  | n/a | - | Renewable power producer; FMP has no segment data. |

### Consumer discretionary  (ground truth: XLY; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Discretionary-spending share of revenue

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | HD | The Home Depot, Inc. | 100.0% | 2025 | Home improvement retailer; all categories are discretionary home spending. |
| High | NKE | NIKE, Inc. | 99.7% | 2026 | Sportswear brand. |
| High | TJX | The TJX Companies, Inc. | 100.0% | 2026 | Off-price clothing and home goods retailer. |
| High | RCL | Royal Caribbean Cruises Ltd. | 95.2% | 2025 | Cruise line; travel spending. |
| Moderate | COST | Costco Wholesale Corporation | 25.5% | 2026 | Warehouse club; non-food goods are about a quarter, the rest is groceries. |
| Moderate | DG | Dollar General Corporation | 18.0% | 2025 | Discount store; seasonal, home and apparel goods are a fifth, the rest is consumables. |
| Control | ADM | Archer-Daniels-Midland Company | 0% | - | Crop processing and food ingredients; no discretionary-spending revenue. |
| Tier 2 → High | MCD | McDonald's Corporation | n/a | - | Restaurants; FMP segments are geographic, not by spending type. |
| Tier 2 → Moderate | AMZN | Amazon.com, Inc. | n/a | - | Online retail is large, but FMP doesn't split discretionary from essentials. |

### Cybersecurity  (ground truth: CIBR; controls: SPY, TLT, VALUE, SIZE, MOM, LOWVOL)
Measure: Security share of revenue  
Note: Exception (approved): only 1 Moderate reference instead of 2-4. FMP doesn't disclose a security share for any other company with partial exposure.

| Group | Ticker | Company | Evidence | FY | Reason |
|---|---|---|---|---|---|
| High | CRWD | CrowdStrike Holdings, Inc. | 100.0% | 2026 | Endpoint security; all revenue is security. |
| High | PANW | Palo Alto Networks, Inc. | 100.0% | 2026 | Network and cloud security; all revenue is security. |
| High | FTNT | Fortinet, Inc. | 100.0% | 2025 | Firewalls and security services; all revenue is security. |
| High | CHKP | Check Point Software Technolog | 100.0% | 2025 | Firewalls and security software; all revenue is security. |
| Moderate | CSCO | Cisco Systems, Inc. | 13.0% | 2026 | Networking giant; Security is a minority segment. |
| Control | VMC | Vulcan Materials Company | 0% | - | Crushed stone and asphalt; no software or security revenue. |
| Tier 2 → High | ZS | Zscaler, Inc. | n/a | - | Cloud security; FMP reports a single segment. |
| Tier 2 → High | S | SentinelOne, Inc. | n/a | - | Endpoint security (SentinelOne); FMP has no segment data. |
| Tier 2 → Moderate | NET | Cloudflare, Inc. | n/a | - | Network services where security is a large share; FMP reports a single segment. |
| Tier 2 → Moderate | AKAM | Akamai Technologies, Inc. | n/a | - | Security is a large share alongside delivery and cloud; FMP reports a single segment. |
