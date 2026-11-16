"""Build the theme YAML files in themes/ from FMP evidence.

Run:  python -m engine.build_themes

Each pick below names WHICH FMP segments (or income-statement lines) count toward the theme.
The evidence % itself is computed from FMP data (engine/evidence.py), never typed in by hand,
so every number in themes/*.yaml traces back to a cached FMP response in data/cache/fmp/.

The one exception is AI: that reference set is the user's own research (AI share of revenue
from 10-Ks / earnings calls) and is used exactly as given.

Tier guide used for picking (judgment, not part of the regression method):
High = theme is ~40%+ of revenue; Moderate = roughly 5-40%.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from engine import fmp
from engine.controls import style_controls
from engine.evidence import nii_share, segment_share, statement_ratio

ROOT = Path(__file__).resolve().parent.parent
THEMES_DIR = ROOT / "themes"
ALL = "ALL"  # every reported segment counts toward the theme


# ---------------------------------------------------------------------------------------------
# AI: the user's reference set, used exactly as given.
# ---------------------------------------------------------------------------------------------
AI_SOURCE = "User-provided research: AI share of revenue from 10-K filings / earnings calls"
AI_FISCAL_YEAR = "From capstone research, most recent filings at the time"
AI = {
    "key": "ai",
    "name": "AI",
    "measures": "AI share of revenue",
    "ground_truth": None,
    "references": {
        "High": [
            ("NVDA", 90, "Data-center GPUs are most of revenue."),
            ("MU", 55.5, "High-bandwidth and data-center memory for AI servers."),
            ("VRT", 50, "Power and cooling for AI data centers."),
            ("AVGO", 49, "Custom AI chips and AI networking."),
        ],
        "Moderate": [
            ("TSM", 18, "Manufactures most AI accelerators, but also phones, PCs, autos."),
            ("MSFT", 11.2, "AI services inside Azure; most revenue is other software and cloud.",
             ("Fails the group-consistency price check (doesn't move with TSM/VST beyond the market). Expected: "
             "TSM, MSFT and VST are different businesses. Kept by decision.")),
            ("VST", 8.6, "Power producer selling electricity to AI data centers."),
        ],
    },
    "control": ("ADM", 0, "Agricultural processor with no AI revenue."),
    "direct": [
        ("CRWV", "High", 100, "AI cloud provider: renting GPUs is the whole business."),
        ("GOOGL", "High", None, "Large AI exposure through Gemini and Cloud, but no disclosed AI share."),
        ("JPM", "Moderate", None, "Big AI spender and user, but no disclosed AI revenue share."),
        ("META", "Moderate", None, "AI drives ad ranking and capex, but no disclosed AI revenue share."),
        ("TSLA", "Moderate", None, "Autonomy and robotics bets, but no disclosed AI revenue share."),
    ],
}


# ---------------------------------------------------------------------------------------------
# Other themes: picks with the FMP segments that count toward each theme.
# Reference entry: (ticker, segments or ALL, reason). Rates uses ("ratio", numerator) instead.
# ---------------------------------------------------------------------------------------------
THEMES = [
    {
        "key": "oil", "plain": "oil producers", "name": "Oil", "ground_truth": "USO",
        "measures": "Crude-oil share of revenue (CVX: upstream oil & gas production share)",
        "High": [
            ("PR", ["Crude Oil"], "Permian pure-play producer; almost all revenue is crude sales."),
            ("FANG", ["Oil Exploration and Production"], "Permian oil producer; revenue follows crude prices."),
            ("COP", ["Crude oil product line"], "Largest US independent producer; two-thirds of revenue is crude."),
            ("EOG", ["Oil and Condensate"], "Large low-cost US producer; most revenue is oil and condensate."),
        ],
        "Moderate": [
            ("CVX", ["Upstream"], "Integrated major: production is ~30% of segment revenue; refining offsets part of oil moves."),
            ("SHEL", ["Crude oil"], "Integrated major: crude sales are a minority; most revenue is refined products and gas."),
        ],
        "control": ("ADBE", "Design and document software; no oil-related segment or fuel-cost dependence."),
        "direct": [
            ("OXY", "High", "94% of revenue is its Oil and Gas segment, but FMP doesn't split oil from gas."),
            ("SLB", "Moderate", "Oilfield services: revenue depends on drilling budgets; no disclosed oil-price share."),
            ("HAL", "Moderate", "Oilfield services: revenue depends on drilling budgets; no disclosed oil-price share."),
        ],
    },
    {
        "key": "bank_lending", "name": "Bank lending / net interest income", "ground_truth": None,
        "plain": "banks that earn mostly from lending",
        "notes": "Validated by group consistency only (like AI). TLT was dropped as ground truth: over this window banks did not move opposite to long-term bonds beyond the market.",
        "measures": "Net interest income / (net interest income + non-interest income)",
        "High": [
            ("MTB", ("nii_share",), "Regional bank; most income is lending spread."),
            ("ZION", ("nii_share",), "Regional bank; most income is lending spread."),
            ("CFG", ("nii_share",), "Regional bank; most income is lending spread."),
            ("RF", ("nii_share",), "Regional bank; most income is lending spread."),
        ],
        "Moderate": [
            ("WFC", ("nii_share",), "Large bank; lending spread plus a big fee business."),
            ("C", ("nii_share",), "Global bank; lending spread plus fees and trading."),
            ("BAC", ("nii_share",), "Large bank; lending spread plus fees and markets."),
        ],
        "control": ("COST", "Warehouse retailer with no lending or deposit business."),
        "direct": [],
    },
    {
        "key": "gold", "plain": "gold and silver miners", "name": "Gold & precious metals", "ground_truth": "GLD",
        "measures": "Gold and silver share of revenue",
        "High": [
            ("SSRM", ["Gold", "Silver"], "Gold and silver miner; nearly all revenue is precious metals."),
            ("CDE", ["Gold", "Product, Silver"], "Gold and silver miner; all revenue is precious metals."),
            ("PAAS", ["Refined Silver and Gold", "Silver Concentrate"], "Silver and gold miner."),
            ("NEM", ["Gold Dore"], "World's largest gold miner. Lower bound: gold inside concentrate isn't split out."),
        ],
        # FCX and SCCO were dropped: they're copper miners, and copper co-moves with unrelated themes.
        # No real partial precious-metals company found (SBSW and HL are mostly precious metals -> High-level;
        # BVN's FMP segment labels are unclear), so Moderate is empty.
        "Moderate": [],
        "notes": "Exception (approved): no Moderate references. FCX and SCCO (copper miners) were dropped.",
        "control": ("KO", "Soft-drink company; no metals revenue or link to gold prices."),
        "direct": [
            ("WPM", "High", "Precious-metals streaming company; FMP has no segment data."),
            ("KGC", "High", "Gold miner; FMP has no segment data."),
            ("AEM", "High", "Gold miner; FMP's latest segment data is from 2013, too old to cite."),
        ],
    },
    {
        "key": "defense", "plain": "aerospace and defense companies", "name": "Aerospace & defense", "ground_truth": "ITA",
        "measures": "Defense / government segment share of revenue",
        "High": [
            ("LMT", ALL, "Largest defense contractor; all four segments serve defense customers."),
            ("NOC", ALL, "Defense contractor; all segments serve defense and government."),
            ("HII", ALL, "Navy shipbuilder; all segments serve defense."),
            ("GD", ["Marine Systems", "Technologies", "Combat Systems"], "Defense segments; Gulfstream jets are the rest."),
        ],
        "Moderate": [
            ("RTX", ["Raytheon Intelligence & Space"], "Raytheon defense unit; Pratt and Collins are mostly commercial aviation."),
            ("BA", ["Defense, Space & Security"], "Defense unit; most revenue is commercial airplanes."),
            ("GE", ["Defense & Propulsion Technologies"], "Military engines; most revenue is commercial engines."),
        ],
        "control": ("INTU", "Tax and accounting software; no defense or government-contract revenue."),
        "direct": [],
    },
    {
        "key": "healthcare", "plain": "healthcare companies", "name": "Healthcare", "ground_truth": "XLV",
        "measures": "Healthcare share of revenue",
        "notes": "Exception (approved): no Moderate references. PG and WM were dropped (don't trade like healthcare), "
                 "then KR (failed the price check once style controls were added).",
        "High": [
            ("PFE", ["Biopharma Segment"], "Large drugmaker."),
            ("MRK", ["Pharmaceutical segment"], "Large drugmaker; animal health is the rest."),
            ("LLY", ALL, "Drugmaker; all revenue is medicines."),
            ("GEHC", ALL, "Medical imaging and diagnostics; all segments are healthcare."),
        ],
        "Moderate": [
            # Only one real partial-healthcare business found. Rejected: GLW (Life Sciences 6%, but the stock
            # moves with optical fiber), ECL (Life Sciences 5%, an industrial service), MTD/WAT (lab equipment
            # with no healthcare share disclosed), PG and WM (don't trade like healthcare).
        ],
        "control": ("ADM", "Crop processing and food ingredients; no healthcare segment."),
        "direct": [
            ("UNH", "High", "Health insurer; FMP segments are revenue types (premiums, services), not a health share."),
        ],
    },
    {
        "key": "metals", "plain": "copper and lithium producers", "name": "Industrial / EV metals (copper + lithium)", "ground_truth": "COPX",
        "measures": "Copper and lithium share of revenue",
        "High": [
            ("SCCO", ["Copper"], "Copper miner; three-quarters of revenue is copper."),
            ("FCX", ["Copper Cathode", "Copper In Concentrates", "Refined Copper Products", "Purchased Copper"],
             "Largest US-listed copper miner."),
            ("BHP", ["Copper"], "Diversified miner; copper is about half of revenue."),
            ("ALB", ["Energy Storage"], "Largest lithium producer; Energy Storage is its lithium segment."),
            ("SQM", ["Lithium and Derivatives"], "Chilean lithium producer; lithium is half of revenue."),
        ],
        "Moderate": [
            ("RIO", ["Copper", "Lithium"], "Diversified miner; mostly iron ore and aluminium."),
            ("VALE", ["Copper"], "Mostly iron ore; copper is a growing minority."),
        ],
        "control": ("INTU", "Tax and accounting software; no metals revenue."),
        "direct": [
            ("TECK", "High", "Copper-focused miner after selling its coal unit; FMP has no segment data."),
            ("HBM", "High", "Copper miner; FMP has no segment data."),
            ("LAC", "High", "Lithium developer; no meaningful revenue yet."),
        ],
    },
    {
        "key": "clean_energy", "plain": "solar and renewable-energy companies", "name": "Clean energy (solar & renewables)",
        "ground_truth": "ICLN",
        "measures": "Solar and renewable-energy share of revenue",
        "notes": "Exception (approved): 1 Moderate reference (NEE). Uranium/nuclear names (LEU, BWXT, CCJ) were "
                 "dropped to keep the group to solar and renewables.",
        "High": [
            ("FSLR", ALL, "US solar panel maker; all revenue is solar modules."),
            ("SEDG", ["Optimizers", "Inverters", "Energy Storage Systems"], "Solar inverters and optimizers."),
            ("RUN", ALL, "Residential solar installer; all segments are solar systems and contracts."),
        ],
        "Moderate": [
            ("NEE", ["NEER"], "Utility; NextEra Energy Resources (renewables developer) is about a third."),
        ],
        "control": ("KO", "Soft-drink company; no energy-generation revenue."),
        "direct": [
            ("ENPH", "High", "Solar microinverters; FMP reports a single segment with no product split."),
            ("BEP", "High", "Renewable power producer; FMP has no segment data."),
        ],
    },
    {
        "key": "consumer_disc", "plain": "consumer discretionary companies", "name": "Consumer discretionary", "ground_truth": "XLY",
        "measures": "Discretionary-spending share of revenue",
        "High": [
            ("HD", ALL, "Home improvement retailer; all categories are discretionary home spending."),
            ("NKE", ["Footwear", "Apparel"], "Sportswear brand."),
            ("TJX", ALL, "Off-price clothing and home goods retailer."),
            ("RCL", ["Cruise Itinerary"], "Cruise line; travel spending."),
        ],
        "Moderate": [
            ("COST", ["Non-Foods"], "Warehouse club; non-food goods are about a quarter, the rest is groceries."),
            ("DG", ["Seasonal", "Home Products", "Apparel"],
             "Discount store; seasonal, home and apparel goods are a fifth, the rest is consumables."),
        ],
        "control": ("ADM", "Crop processing and food ingredients; no discretionary-spending revenue."),
        "direct": [
            ("MCD", "High", "Restaurants; FMP segments are geographic, not by spending type."),
            ("AMZN", "Moderate", "Online retail is large, but FMP doesn't split discretionary from essentials."),
        ],
    },
    {
        "key": "cyber", "plain": "cybersecurity companies", "name": "Cybersecurity", "ground_truth": "CIBR",
        "measures": "Security share of revenue",
        "notes": "Exception (approved): only 1 Moderate reference instead of 2-4. FMP doesn't disclose a "
                 "security share for any other company with partial exposure.",
        "High": [
            ("CRWD", ALL, "Endpoint security; all revenue is security."),
            ("PANW", ALL, "Network and cloud security; all revenue is security."),
            ("FTNT", ALL, "Firewalls and security services; all revenue is security."),
            ("CHKP", ALL, "Firewalls and security software; all revenue is security."),
        ],
        "Moderate": [
            ("CSCO", ["Security"], "Networking giant; Security is a minority segment."),
        ],
        "control": ("VMC", "Crushed stone and asphalt; no software or security revenue."),
        "direct": [
            ("ZS", "High", "Cloud security; FMP reports a single segment."),
            ("S", "High", "Endpoint security (SentinelOne); FMP has no segment data."),
            ("NET", "Moderate", "Network services where security is a large share; FMP reports a single segment."),
            ("AKAM", "Moderate", "Security is a large share alongside delivery and cloud; FMP reports a single segment."),
        ],
    },
]


# Business check (Way 2): a "want" pick must be in one of its theme's FMP industries, or be a named reference /
# Tier 2 company. The rule of thumb: the industry's core business IS the theme.
ALLOWED_INDUSTRIES = {
    "ai": ["Semiconductors", "Software - Infrastructure", "Software - Application", "Information Technology Services",
           "Computer Hardware", "Hardware, Equipment & Parts", "Communication Equipment", "Electrical Equipment & Parts",
           "Internet Content & Information", "Independent Power Producers", "REIT - Specialty"],
    "oil": ["Oil & Gas Exploration & Production", "Oil & Gas Integrated", "Oil & Gas Equipment & Services",
            "Oil & Gas Drilling"],
    "bank_lending": ["Banks", "Banks - Diversified", "Banks - Regional", "Financial - Mortgages"],
    "gold": ["Gold", "Silver", "Other Precious Metals"],
    "defense": ["Aerospace & Defense"],
    "healthcare": ["Biotechnology", "Drug Manufacturers - General", "Drug Manufacturers - Specialty & Generic",
                   "Medical - Care Facilities", "Medical - Devices", "Medical - Diagnostics & Research",
                   "Medical - Distribution", "Medical - Healthcare Plans", "Medical - Instruments & Supplies",
                   "Medical - Pharmaceuticals", "Medical - Specialties"],
    "metals": ["Copper", "Industrial Materials", "Other Industrial Metals & Mining"],
    "clean_energy": ["Solar", "Renewable Utilities"],
    "consumer_disc": ["Apparel - Footwear & Accessories", "Apparel - Manufacturers", "Apparel - Retail",
                      "Auto - Dealerships", "Auto - Manufacturers", "Auto - Parts", "Furnishings, Fixtures & Appliances",
                      "Gambling, Resorts & Casinos", "Home Improvement", "Leisure", "Luxury Goods",
                      "Residential Construction", "Restaurants", "Specialty Retail", "Travel Lodging", "Travel Services"],
    "cyber": ["Software - Infrastructure"],
}


def _name(ticker: str) -> str:
    rows = fmp.profile(ticker)
    if not rows:
        raise ValueError(f"{ticker}: FMP has no profile (bad ticker?)")
    return rows[0].get("companyName", ticker)


def _evidence(ticker: str, spec) -> dict:
    """Compute evidence for one reference from its spec (segments list, ALL, or a ratio)."""
    if isinstance(spec, tuple) and spec[0] == "nii_share":
        return nii_share(ticker)
    if isinstance(spec, tuple) and spec[0] == "ratio":
        return statement_ratio(ticker, spec[1])
    if spec == ALL:
        from engine.evidence import _latest  # every positive segment counts
        row = _latest(fmp.revenue_product_segments(ticker), None)
        names = [k for k, v in (row.get("data") or {}).items() if isinstance(v, (int, float)) and v > 0]
        result = segment_share(ticker, names)
        result["source"] = f"FMP revenue-product-segmentation FY{result['fiscal_year']}: all segments are theme business"
        return result
    return segment_share(ticker, spec)


def _check_tier(tier: str, pct: float, ticker: str, warnings: list):
    if tier == "High" and pct < 40:
        warnings.append(f"{ticker}: listed High but evidence is only {pct}%")
    if tier == "Moderate" and not 5 <= pct < 40:
        warnings.append(f"{ticker}: listed Moderate but evidence is {pct}%")


def build_ai() -> dict:
    refs = {}
    for tier, rows in AI["references"].items():
        refs[tier] = []
        for t, pct, why, *note in rows:
            ref = {"ticker": t, "name": _name(t), "evidence_pct": pct, "measures": AI["measures"],
                   "fiscal_year": AI_FISCAL_YEAR, "source": AI_SOURCE, "reason": why}
            if note:
                ref["note"] = note[0]
            refs[tier].append(ref)
    # Independent check: FMP's NVDA Data Center share should be close to the user's 90%.
    nvda = segment_share("NVDA", ["Data Center"])
    refs["High"][0]["fmp_cross_check"] = f"FMP FY{nvda['fiscal_year']} Data Center share = {nvda['evidence_pct']}%"
    ct, cpct, cwhy = AI["control"]
    return {
        "key": AI["key"], "name": AI["name"], "plain": "AI companies", "measures": AI["measures"],
        "ground_truth": AI["ground_truth"], "references": refs,
        "control": {"ticker": ct, "name": _name(ct), "evidence_pct": cpct, "measures": AI["measures"],
                    "fiscal_year": AI_FISCAL_YEAR, "source": AI_SOURCE, "reason": cwhy},
        "direct_classification": [{"ticker": t, "name": _name(t), "tier": tier, "evidence_pct": pct,
                                   "source": AI_SOURCE if pct is not None else "No disclosed number (Tier 2)",
                                   "reason": why} for t, tier, pct, why in AI["direct"]],
    }


def build_theme(theme: dict, warnings: list) -> dict:
    refs = {}
    for tier in ("High", "Moderate"):
        refs[tier] = []
        for ticker, spec, why in theme[tier]:
            ev = _evidence(ticker, spec)
            _check_tier(tier, ev["evidence_pct"], ticker, warnings)
            refs[tier].append({"ticker": ticker, "name": _name(ticker), "evidence_pct": ev["evidence_pct"],
                               "measures": theme["measures"], "fiscal_year": ev["fiscal_year"],
                               "source": ev["source"], "reason": why})
    ct, cwhy = theme["control"]
    if theme["key"] == "bank_lending":
        cev = nii_share(ct)
        control = {"evidence_pct": cev["evidence_pct"], "fiscal_year": cev["fiscal_year"], "source": cev["source"]}
    else:
        from engine.evidence import show_segments
        control = {"evidence_pct": 0, "fiscal_year": None,
                   "source": f"No theme-related segment in FMP data ({show_segments(ct)})"}
    count = len(refs["High"]) + len(refs["Moderate"])
    if not 3 <= len(refs["High"]) <= 5:
        warnings.append(f"{theme['key']}: {len(refs['High'])} High references (rule is 3-5)")
    if not 2 <= len(refs["Moderate"]) <= 4 and "notes" not in theme:
        warnings.append(f"{theme['key']}: {len(refs['Moderate'])} Moderate references (rule is 2-4)")
    ai_refs = {r[0] for rows in AI["references"].values() for r in rows}
    for r in refs["High"] + refs["Moderate"]:
        if r["ticker"] in ai_refs:
            warnings.append(f"{theme['key']}: {r['ticker']} is also an AI reference")
    out = {
        "key": theme["key"], "name": theme["name"], "plain": theme["plain"], "measures": theme["measures"],
        "ground_truth": theme.get("ground_truth"),
        "references": refs,
        "control": {"ticker": ct, "name": _name(ct), "measures": theme["measures"], **control, "reason": cwhy},
        "direct_classification": [{"ticker": t, "name": _name(t), "tier": tier, "evidence_pct": None,
                                   "source": "No disclosed number (Tier 2)", "reason": why}
                                  for t, tier, why in theme["direct"]],
        "reference_count": count,
    }
    if "ground_truth_sign" in theme:
        out["ground_truth_sign"] = theme["ground_truth_sign"]
    if "notes" in theme:
        out["notes"] = theme["notes"]
    return out


def summary_table(t: dict) -> str:
    """Markdown table for the checkpoint."""
    sign = ", sign flipped" if t.get("ground_truth_sign") == -1 else ""
    lines = [f"### {t['name']}  (ground truth: {t.get('ground_truth') or 'none'}{sign}; controls: {', '.join(t['controls'])})",
             f"Measure: {t['measures']}" + (f"  \nNote: {t['notes']}" if t.get("notes") else ""), "",
             "| Group | Ticker | Company | Evidence | FY | Reason |", "|---|---|---|---|---|---|"]
    for tier in ("High", "Moderate"):
        for r in t["references"][tier]:
            why = r["reason"] + (f" **Note:** {r['note']}" if r.get("note") else "")
            lines.append(f"| {tier} | {r['ticker']} | {r['name'][:30]} | {r['evidence_pct']}% | {r['fiscal_year'] or '-'} | {why} |")
    c = t["control"]
    lines.append(f"| Control | {c['ticker']} | {c['name'][:30]} | {c['evidence_pct']}% | {c['fiscal_year'] or '-'} | {c['reason']} |")
    for d in t["direct_classification"]:
        ev = f"{d['evidence_pct']}%" if d["evidence_pct"] is not None else "n/a"
        lines.append(f"| Tier 2 → {d['tier']} | {d['ticker']} | {d['name'][:30]} | {ev} | - | {d['reason']} |")
    return "\n".join(lines)


def apply_controls(t: dict) -> None:
    """Market + style controls via the objective 15% skip rule (engine/controls.py)."""
    kept, skipped = style_controls(t)
    t["controls"] = ["SPY", "TLT"] + kept
    t["style_skips"] = skipped


def main():
    THEMES_DIR.mkdir(exist_ok=True)
    warnings: list[str] = []
    built = [build_ai()] + [build_theme(t, warnings) for t in THEMES]
    for t in built:
        t.pop("reference_count", None)
        apply_controls(t)
        t["allowed_industries"] = ALLOWED_INDUSTRIES[t["key"]]
        path = THEMES_DIR / f"{t['key']}.yaml"
        header = (f"# Theme: {t['name']}. Generated by engine/build_themes.py from FMP data "
                  f"(AI: user-provided research). Don't edit by hand; edit the picks and re-run.\n")
        path.write_text(header + yaml.safe_dump(t, sort_keys=False, allow_unicode=True, width=120))
    (ROOT / "themes" / "SUMMARY.md").write_text("# Theme summary\n\n" + "\n\n".join(summary_table(t) for t in built) + "\n")
    print(f"Wrote {len(built)} theme files.")
    for w in warnings:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
