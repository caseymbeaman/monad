"""Fast skim check of each theme reference's evidence % against its latest FMP earnings-call transcript.

Run:  python -m engine.verify_evidence      -> writes themes/VERIFICATION.md

How each reference is checked (a skim, not an audit):
- Segment-share evidence: find the segment's $ revenue and the total $ revenue in the same call, compute
  the quarter's share, and compare with the fiscal-year evidence % (within 10 points = VERIFIED).
- Bank NII-share evidence: same idea with "net interest income" vs total revenue.
- AI (user-provided) evidence: look for an explicitly stated AI share of revenue (a % next to "AI").
- "All segments" evidence (100%): VERIFIED if the call describes the business as wholly in the theme is
  too fuzzy to automate, so these are NOT FOUND unless a share is stated.
Status: VERIFIED (numbers agree), MISMATCH (both numbers shown), NOT FOUND (couldn't confirm in the call).
A quarter's share can differ from a full fiscal year's share, so small gaps are expected.
Nothing in themes/*.yaml is changed.
"""

from __future__ import annotations

import re
from pathlib import Path

from engine import fmp
from engine.theme_loader import load_all

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE_PTS = 10.0
MONEY = re.compile(r"\$\s?([\d][\d,]*(?:\.\d+)?)\s?(billion|million|bn|b|m)\b", re.IGNORECASE)
PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?(?:%|percent)", re.IGNORECASE)
TOTAL_REV = re.compile(r"\b(total )?(net )?revenues?\b[^.]{0,40}?\b(was|were|of|came in at|reached|totaled|grew to|to)\b", re.IGNORECASE)


def _latest_transcript(ticker: str) -> tuple[str | None, str | None]:
    try:
        dates = fmp.get("earning-call-transcript-dates", {"symbol": ticker})
        if not dates:
            return None, None
        latest = max(dates, key=lambda d: (int(d["fiscalYear"]), int(d["quarter"])))
        rows = fmp.get("earning-call-transcript", {"symbol": ticker, "year": latest["fiscalYear"], "quarter": latest["quarter"]})
        if rows:
            return rows[0].get("content", ""), f"FMP earnings call transcript FY{latest['fiscalYear']} Q{latest['quarter']} ({rows[0].get('date', '')[:10]})"
    except fmp.FMPError:
        pass
    return None, None


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _money(s: str) -> float | None:
    m = MONEY.search(s)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v * (1000 if m.group(2).lower() in ("billion", "bn", "b") else 1)


def _segment_keywords(ref: dict) -> list[str]:
    src = ref.get("source", "")
    if "netInterestIncome" in src:
        return ["net interest income"]
    m = re.search(r"FY\d+: (.+?) / sum", src)
    if not m:
        return []
    out = []
    for seg in m.group(1).split(" + "):
        seg = re.sub(r"\b(segment|product line|member|\[member\])\b", "", seg, flags=re.IGNORECASE).strip(" ,")
        if seg:
            out.append(seg.lower())
    return out


AI_KW = re.compile(r"\b(AI|artificial intelligence|data cent(er|re))\b", re.IGNORECASE)
REV_WORD = re.compile(r"\b(revenues?|sales)\b", re.IGNORECASE)
NONII = re.compile(r"\b(non-?interest income|fee income|noninterest revenue)\b", re.IGNORECASE)


def _total_revenue(sents: list[str], exclude) -> tuple[float | None, str]:
    for s in sents:
        if TOTAL_REV.search(s) and not exclude(s) and _money(s):
            return _money(s), s
    return None, ""


def check_ref(ref: dict, theme: dict) -> dict:
    ticker, ev = ref["ticker"], ref["evidence_pct"]
    text, source = _latest_transcript(ticker)
    row = {"ticker": ticker, "evidence": ev, "status": "NOT FOUND", "found": None, "quote": "",
           "source": source or "no transcript in FMP"}
    if not text:
        return row
    sents = _sentences(text)
    src = ref.get("source", "")

    if theme["key"] == "ai":
        match = lambda x: bool(AI_KW.search(x))
    elif "netInterestIncome" in src:
        match = lambda x: "net interest income" in x.lower()
    else:
        kws = _segment_keywords(ref)
        if not kws or "all segments" in src:
            row["quote"] = "(evidence is 'all segments are theme business'; no single share to compare)"
            return row
        match = lambda x: any(k in x.lower() for k in kws)

    seg_val = seg_quote = None
    for x in sents:
        if not (match(x) and REV_WORD.search(x) or "net interest income" in x.lower() and match(x)):
            continue
        pct = PCT.search(x)
        if pct and re.search(r"^\s*of (total |our |the company's )?(revenue|sales)", x[pct.end():pct.end() + 30], re.IGNORECASE):
            row.update(found=float(pct.group(1)), quote=x[:220])
            break
        if seg_val is None and _money(x):
            seg_val, seg_quote = _money(x), x

    if row["found"] is None and seg_val:
        if "netInterestIncome" in src:
            fee = next(((_money(x), x) for x in sents if NONII.search(x) and _money(x)), (None, ""))
            if fee[0]:
                row.update(found=round(100 * seg_val / (seg_val + fee[0]), 1),
                           quote=f"{seg_quote[:140]} … {fee[1][:110]}")
        else:
            total, tq = _total_revenue(sents, match)
            if total and total >= seg_val:
                row.update(found=round(100 * seg_val / total, 1), quote=f"{seg_quote[:140]} … {tq[:110]}")

    if row["found"] is not None:
        row["status"] = "VERIFIED" if abs(row["found"] - ev) <= TOLERANCE_PTS else "MISMATCH"
    return row


# Hand review of the automated matches (the automation can pair the wrong numbers).
REVIEWED = {
    "AVGO": ("VERIFIED", 56.4, ("Reviewed: auto-match grabbed gross margin (75%). From the same call: AI semiconductor "
             "revenue $16.7B / consolidated revenue $29.6B = 56%, vs 49% evidence (quarter vs full year).")),
    "MTB": ("MISMATCH", 70.8, ("Reviewed: real gap from the definition. The call implies NII / (NII + fees) = 71%; FMP's "
            "income-statement revenue gives 56%. Bank evidence % is likely understated for all banks.")),
    "ZION": ("NOT FOUND", None, ("Reviewed: auto-match used an annualized fee projection, not the quarter's fees. "
             "Likely the same definition gap as MTB.")),
    "GD": ("NOT FOUND", None, ("Reviewed: only one of the three defense segments (Combat Systems) was matched, so no valid "
           "comparison.")),
}


def main():
    themes = load_all()
    order = ["ai", "oil"] + [k for k in themes if k not in ("ai", "oil")]
    lines = ["# Evidence verification (fast skim)", "",
             ("Each reference's evidence % checked against its latest FMP earnings-call transcript "
             "(`python -m engine.verify_evidence`). A quarter's share can differ from the fiscal-year share; "
             f"within {TOLERANCE_PTS:g} points counts as VERIFIED. NOT FOUND means the call didn't state a "
             "comparable number, not that the evidence is wrong. Nothing in themes/*.yaml was changed."), ""]
    totals = {"VERIFIED": 0, "MISMATCH": 0, "NOT FOUND": 0}
    for k in order:
        th = themes[k]
        lines += [f"## {th['name']}", "", "| Ticker | Group | Evidence | Found in call | Status | Quote | Source |",
                  "|---|---|---|---|---|---|---|"]
        for g in ("High", "Moderate"):
            for ref in th["references"].get(g, []):
                r = check_ref(ref, th)
                if r["ticker"] in REVIEWED:
                    r["status"], r["found"], note = REVIEWED[r["ticker"]]
                    r["quote"] = f"{note} Call text: {r['quote']}"
                totals[r["status"]] += 1
                found = f"{r['found']}%" if r["found"] is not None else "-"
                quote = r["quote"].replace("|", "/").replace("\n", " ")
                lines.append(f"| {r['ticker']} | {g} | {r['evidence']}% | {found} | **{r['status']}** | {quote} | {r['source']} |")
                print(f"{k:14} {r['ticker']:5} {r['status']:10} ev {r['evidence']} found {r['found']}")
        lines.append("")
    lines.insert(4, f"**Totals:** {totals['VERIFIED']} verified, {totals['MISMATCH']} mismatch, {totals['NOT FOUND']} not found.\n")
    (ROOT / "themes" / "VERIFICATION.md").write_text("\n".join(lines))
    print(totals)


if __name__ == "__main__":
    main()
