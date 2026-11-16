"""Theme Funds: the Monad Blitz demo dashboard.

    ./run_demo.sh            (or: streamlit run demo_app.py with the theme flags inside run_demo.sh)

One scrolling story in four steps, built for presenting on a projector:
1. Choose themes (Want / Don't care / Avoid per theme + region), or check your own stocks.
2. See what you own: the fund's fingerprint across every theme, how the stocks were picked, the
   holdings, and the re-check that the finished fund matches your choices.
3. Stress test: a range of possible years (Monte Carlo) and "what if this theme moves" shocks.
4. Launch on Monad: the choices become rules the fund contract enforces; try adding XOM and watch it fail.

This is a separate front end from app.py (the full dashboard). It calls exactly the same engine/ and
chain/ functions and changes no logic; demo/style.py only handles the look.
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import streamlit as st

from chain import app_actions
from chain.publish import PublishError
from demo import league, style
from engine import assistant, builder, dashboard, risk, screen
from engine.data import DEFAULT_END, DEFAULT_START, DataError
from engine.monte_carlo import SimulationError
from engine.shocks import LABEL as SHOCK_LABEL
from engine.shocks import ShockError
from engine.theme_loader import load_all

st.set_page_config(page_title="Theme Funds", page_icon="◆", layout="wide", initial_sidebar_state="collapsed")
st.html(style.CSS)

BUILD, CHECK = "Build my ETF", "Check my portfolio"
WANT, SKIP, AVOID = dashboard.CHOICES
SHORT = {WANT: "Want", SKIP: "Skip", AVOID: "Avoid"}  # display only; values stay dashboard.CHOICES
SHOCK_SIZES = [-50, -30, -20, -10, 10, 20, 30, 50]
HIGH_MOD = {"High", "Moderate"}
CHAIN_ERRORS = (PublishError, ValueError, ConnectionError, TimeoutError, OSError)


# ---------------------------------------------------------------------------------------------
# Engine calls, cached exactly as in app.py
# ---------------------------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def themes() -> dict[str, dict]:
    return load_all()


@st.cache_resource(show_spinner="Loading every stock's score on every theme...")
def universe_table() -> dict[str, dict[str, dict]]:
    return builder.prescreen()


@st.cache_data(show_spinner="Picking your stocks...")
def run_build(prefs: tuple[tuple[str, str], ...], region: str) -> dict:
    return builder.build(dict(prefs), region=region)


@st.cache_data(show_spinner="Scoring each stock on every theme...")
def run_check(holdings: tuple[tuple[str, float], ...]) -> dict:
    return screen.run_screen(dict(holdings))


@st.cache_data(show_spinner="Simulating 5,000 possible years and every theme shock...")
def run_risk(holdings: tuple[tuple[str, float], ...]):
    return risk.run_risk(dict(holdings))


@st.cache_data(show_spinner=False)
def companies(tickers: tuple[str, ...]) -> dict[str, dict]:
    return assistant.company_info(list(tickers))


@st.cache_data(show_spinner=False)
def screen_ticker(ticker: str, theme_keys: tuple[str, ...]) -> dict[str, dict]:
    all_themes = themes()
    return {k: screen._screen_one(ticker, all_themes[k], DEFAULT_START, DEFAULT_END) for k in theme_keys}


def new_portfolio(portfolio: dict) -> None:
    st.session_state["portfolio"] = portfolio
    for key in ("chat", "fund", "deposit", "published"):
        st.session_state.pop(key, None)


# ---------------------------------------------------------------------------------------------
# Step 1: choose
# ---------------------------------------------------------------------------------------------

def choose_step(mode: str) -> None:
    if mode == BUILD:
        st.html(style.step(1, "Choose your themes", "Want means the fund must have it. Avoid means it must "
                           "stay clear. Skip means you don't care either way."))
        items = list(themes().items())
        choices = {}
        for start in range(0, len(items), 5):
            cols = st.columns(5, gap="medium")
            for col, (key, theme) in zip(cols, items[start:start + 5], strict=False):
                choices[key] = col.segmented_control(theme["name"], dashboard.CHOICES, default=SKIP,
                                                     format_func=SHORT.get, key=f"demo_choice_{key}") or SKIP
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        region = c1.pills("Region", list(builder.REGIONS), format_func=builder.REGIONS.get, default="all",
                          key="demo_region") or "all"
        if c2.button("Build my ETF", type="primary", width="stretch", key="demo_build"):
            prefs = dashboard.prefs_from_choices(choices)
            if not prefs:
                st.warning("Pick at least one theme to Want or Avoid.")
                return
            try:
                build = run_build(tuple(sorted(prefs.items())), region)
            except builder.BuildError as exc:
                st.error(str(exc))
                return
            new_portfolio({"kind": "build", "build": build, "prefs": prefs})
    else:
        st.html(style.step(1, "Enter your stocks", "Ticker and weight, for example NVDA:30 XOM:20 CASH:50. "
                           "Weights are rescaled to 100%."))
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        text = c1.text_input("Your holdings", "NVDA:30 XOM:20 JNJ:20 CASH:30", key="demo_holdings")
        if c2.button("Check my portfolio", type="primary", width="stretch", key="demo_check"):
            try:
                report = run_check(tuple(dashboard.parse_holdings_text(text).items()))
            except screen.InputError as exc:
                st.error(str(exc))
                return
            new_portfolio({"kind": "check", "report": report})


# ---------------------------------------------------------------------------------------------
# Step 2: what you own
# ---------------------------------------------------------------------------------------------

def fingerprint_columns(table: dict[str, dict[str, dict]], weights: dict[str, float],
                        prefs: dict[str, str]) -> list[dict]:
    """Share of the fund (in %) held in stocks rated High or Moderate on each theme."""
    cols = []
    for key, theme in themes().items():
        pct = sum(w for t, w in weights.items()
                  if t != dashboard.CASH and table.get(t, {}).get(key, {}).get("tier") in HIGH_MOD)
        cols.append({"name": theme["name"], "pct": pct, "role": prefs.get(key, "none")})
    # Your choices first (wants, then avoids), then everything else by size.
    order = {"want": 0, "avoid": 1, "none": 2}
    return sorted(cols, key=lambda c: (order[c["role"]], -c["pct"]))


def heatmap_and_audit(table: dict[str, dict[str, dict]], weights: dict[str, float]) -> None:
    with st.expander("Every holding against every theme, and how each rating was decided"):
        matrix = dashboard.tier_matrix(table, list(weights), themes())
        if matrix.empty:
            st.info("Only cash: nothing to score.")
            return
        st.caption("Pink = High or Moderate, green = Limited (doesn't rise with the theme), "
                   "brown ? = the data can't tell, which is not the same as zero.")
        fig = style.recolor_heatmap(dashboard.heatmap_figure(matrix, weights), dashboard.TIER_ORDER)
        st.plotly_chart(fig, width="stretch")
        c1, c2 = st.columns(2)
        ticker = c1.selectbox("Holding", list(matrix.index), key="demo_audit_ticker")
        names = {th["name"]: k for k, th in themes().items()}
        theme_name = c2.selectbox("Theme", list(names), key="demo_audit_theme")
        result = table.get(ticker, {}).get(names[theme_name], {})
        rows = dashboard.audit_rows(result)
        st.table({"": [r[0] for r in rows], "Value": [r[1] for r in rows]})
        groups = dashboard.group_table(result)
        if groups is not None:
            st.caption("A group counts if its beta sum is above 0.05 and its one-sided p-value is below the "
                       "threshold. The largest counting group sets the rating.")
            st.dataframe(groups, hide_index=True, width="stretch")


def why_in(h: dict) -> str:
    """One plain-English line on why a holding is in the fund (from the builder's own labels)."""
    if h["ticker"] == "CASH":
        return "Cash for the part of the fund no stock could fill under your rules."
    theme, rating = h.get("picked_for"), h.get("picked_tier")
    if not theme or theme == "_cap":
        return "One of the largest companies that passes every theme you chose to avoid."
    if (h.get("reference") or {}).get(theme):
        article = "An" if theme[:1].upper() in "AEIOU" else "A"
        return f"{article} {theme} reference company: its own filings show {theme} is a big part of its revenue."
    if rating == "High":
        return f"Rated High for {theme}: it's in the business, and its revenue or price moves strongly with it."
    if rating == "Moderate":
        return f"Rated Moderate for {theme}: it's in the business, with a real but smaller link."
    return f"Picked for {theme}."


def own_step_build(build: dict, prefs: dict[str, str]) -> dict[str, float]:
    weights = dashboard.holdings_from_build(build)
    st.html(style.step(2, "See what you own", "Each column is the share of your fund in stocks that really "
                       "move with that theme. Your wants should be tall, your avoids flat."))
    if not weights:
        st.error("No stock passes every rule you chose. Try fewer or looser choices, or another region.")
        for w in build.get("warnings", []):
            st.caption(w)
        return {}
    table = universe_table()
    st.html(style.fingerprint(fingerprint_columns(table, weights, prefs)))

    left, right = st.columns([5, 6], gap="large")
    with left:
        st.subheader("How we picked")
        st.caption(f"From {build.get('universe_size', 0):,} scored stocks, each of your rules narrows the list.")
        st.html(style.funnel(build.get("funnel", [])))
        verification = build.get("verification") or {}
        if verification:
            st.subheader("Does the finished fund match your choices?")
            st.caption("The final basket is re-checked from scratch.")
            items = [(c["pass"], (f"<b>{escape(c['choice'].title())} {escape(c['theme'])}.</b> "
                                  f"{escape(c['sentence'])}")) for c in verification["checks"].values()]
            st.html(style.checks(items))
        for w in build.get("warnings", []):
            st.caption(w)
    with right:
        st.subheader(f"Your {len([t for t in weights if t != dashboard.CASH])} stocks")
        rows = []
        for h in build["holdings"]:
            # one chip for the theme it was picked for, plus each avoided theme (shows it stays clear of it)
            shown = list((h.get("avoid_tiers") or {}).items())
            if h.get("picked_for") not in (None, "_cap") and h.get("picked_tier"):
                shown.insert(0, (h["picked_for"], h["picked_tier"]))
            chips = [style.theme_chip(name, tier) for name, tier in shown]
            rows.append({"ticker": h["ticker"], "name": h.get("name", "Cash" if h["ticker"] == "CASH" else ""),
                         "industry": h.get("industry", ""), "weight": h["weight_pct"], "chips": chips,
                         "why": why_in(h)})
        st.html(style.holdings(rows))
    heatmap_and_audit(table, weights)
    return weights


def own_step_check(report: dict) -> dict[str, float]:
    weights = dashboard.holdings_from_screen(report)
    st.html(style.step(2, "See what you own", "Each column is the share of your portfolio in stocks that "
                       "really move with that theme."))
    if report.get("weights_rescaled_to_100"):
        st.caption("Your weights didn't add up to 100%, so they were rescaled.")
    cols = [{"name": f["name"], "pct": f.get("high_moderate_pct", 0), "role": "none"}
            for f in report.get("fingerprint", {}).values()]
    st.html(style.fingerprint(sorted(cols, key=lambda c: -c["pct"])))
    st.dataframe(dashboard.fingerprint_rows(report), hide_index=True, width="stretch")
    for problem in dashboard.screen_errors(report):
        st.warning(f"Couldn't fully score {problem}")
    heatmap_and_audit(dashboard.results_from_screen(report), weights)
    return weights


# ---------------------------------------------------------------------------------------------
# Step 3: stress test
# ---------------------------------------------------------------------------------------------

def fan_figure(fan: dict) -> go.Figure:
    """Value of $10,000 over one simulated year: middle 90% and middle 50% of outcomes, plus SPY."""
    days = fan["days"]
    p, b = fan["portfolio"], fan["benchmark"]
    k = 10_000
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=days, y=[v * k for v in p["95"]], line={"width": 0}, hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=days, y=[v * k for v in p["5"]], fill="tonexty", line={"width": 0},
                             fillcolor="rgba(244,166,191,0.14)", name="9 in 10 years land here"))
    fig.add_trace(go.Scatter(x=days, y=[v * k for v in p["75"]], line={"width": 0}, hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=days, y=[v * k for v in p["25"]], fill="tonexty", line={"width": 0},
                             fillcolor="rgba(244,166,191,0.30)", name="Half of years land here"))
    fig.add_trace(go.Scatter(x=days, y=[v * k for v in p["50"]], line={"color": style.BLUSH, "width": 3},
                             name="Your fund, typical year"))
    fig.add_trace(go.Scatter(x=days, y=[v * k for v in b["50"]], line={"color": style.MUTED, "width": 2,
                                                                         "dash": "dot"},
                             name="SPY, typical year"))
    fig.update_layout(yaxis_tickprefix="$", yaxis_tickformat=",.0f", xaxis_title="Trading days from today",
                      legend={"orientation": "h", "y": -0.18}, hovermode="x unified")
    return style.plotly_dark(fig, height=420)


def stress_step(weights: dict[str, float]) -> None:
    st.html(style.step(3, "Stress test it", "5,000 simulated years built from real past market days, and "
                       "what happens if one theme suddenly moves."))
    if not weights or set(weights) == {dashboard.CASH}:
        st.info("Build or check a portfolio with at least one stock to see its risk.")
        return
    try:
        report, figures = run_risk(tuple(sorted(weights.items())))
    except (DataError, SimulationError, ShockError, ValueError) as exc:
        st.error(f"The risk report couldn't run: {exc}")
        return
    mc = report["monte_carlo"]
    p, b = mc["portfolio"], mc["benchmark"]

    def loss(x: float) -> str:
        return f"−{x:.0%}" if x > 0 else "no loss"

    st.html(style.tiles([
        ("Chance of losing more than 10%", f"{p['p_loss_over_10']:.0%}", f"SPY: {b['p_loss_over_10']:.0%}"),
        ("A bad year (1 in 20)", loss(p["var_5"]), f"SPY: {loss(b['var_5'])}"),
        ("Average of the worst years", loss(p["cvar_5"]), f"SPY: {loss(b['cvar_5'])}"),
        ("Years it beats SPY", f"{mc['p_beat_benchmark']:.0%}", "out of 5,000 simulated"),
    ]))
    st.plotly_chart(fan_figure(mc["fan"]), width="stretch")
    for s in mc["sentences"]:
        st.markdown(f"- {s}")

    st.subheader("What if one theme suddenly moves?")
    st.caption(f"{SHOCK_LABEL[:1].upper()}{SHOCK_LABEL[1:]}.")
    by_name = {s["theme_name"]: s for s in report["shocks"]}
    default = max(report["shocks"], key=lambda s: abs(s["portfolio_move"]))["theme_name"]
    c1, c2 = st.columns([2, 3])
    theme_name = c1.selectbox("Theme", list(by_name), index=list(by_name).index(default), key="demo_shock_theme")
    size = c2.select_slider("How much it moves, beyond the market", SHOCK_SIZES, value=30,
                            format_func=lambda v: f"{v:+d}%", key="demo_shock_size")
    base = by_name[theme_name]
    result = dashboard.reshock(base, themes()[base["theme"]], size / 100)
    left, right = st.columns([2, 3], gap="large", vertical_alignment="center")
    with left:
        st.html(style.big_number(result.portfolio_move * 100))
        st.html(f'<div class="tf-sentence">{escape(result.sentence)}</div>')
    with right:
        contrib = [h for h in result.holdings if h.move is not None and h.ticker != dashboard.CASH]
        if contrib:
            contrib.sort(key=lambda h: h.contribution)
            fig = go.Figure(go.Bar(
                x=[h.contribution * 100 for h in contrib], y=[h.ticker for h in contrib], orientation="h",
                marker_color=[style.LOSS if h.contribution < 0 else style.GAIN for h in contrib],
                hovertemplate="%{y}: %{x:+.2f} percentage points<extra></extra>"))
            fig.update_layout(xaxis_ticksuffix="%", xaxis_title="Each stock's effect on the fund (points)")
            st.plotly_chart(style.plotly_dark(fig, height=max(260, 26 * len(contrib) + 90)), width="stretch")
    frontier = report.get("frontier") or {}
    if figures and figures.get("frontier") is not None:
        with st.expander("Could the same stocks be mixed better? (mean-variance check)"):
            st.plotly_chart(style.plotly_dark(figures["frontier"]), width="stretch")
            for s in frontier.get("sentences", []):
                st.markdown(f"- {s}")
    st.session_state["risk_report"] = report


# ---------------------------------------------------------------------------------------------
# Step 4: launch on Monad
# ---------------------------------------------------------------------------------------------

def launch_step(portfolio: dict) -> None:
    st.html(style.step(4, "Launch it on Monad", "Your choices become rules written into the fund's contract. "
                       "Nobody, including us, can quietly break them."))
    if portfolio["kind"] != "build":
        st.info("Launching needs a fund from Build my ETF: your Want and Avoid choices become its rules.")
        return
    build = portfolio["build"]
    if not dashboard.holdings_from_build(build):
        st.info("Build an ETF with at least one stock first.")
        return
    try:
        default = app_actions.plan_for(build)
    except PublishError as exc:
        st.error(str(exc))
        return

    c1, c2, c3 = st.columns([3, 1, 2])
    name = c1.text_input("Fund name", default["name"], key="demo_fund_name")
    symbol = c2.text_input("Ticker", default["symbol"], key="demo_fund_symbol")
    want_min = c3.number_input("Want rules: minimum % in High or Moderate stocks", 1.0, 100.0, 60.0, 5.0,
                               key="demo_want_min")
    try:
        plan = app_actions.plan_for(build, name, symbol, want_min)
    except PublishError as exc:
        st.error(str(exc))
        return
    st.subheader("The rules, fixed forever once launched")
    st.html(style.rules([
        ("want", f"At least {r['min_bps'] / 100:g}% of the fund in stocks rated High or Moderate for {r['label']}")
        if r["kind"] == 0 else
        ("avoid", f"No holding rated High or Moderate for {r['label']}")
        for r in plan["rules"]
    ]))

    cfg = app_actions.config()
    if not cfg["ready"]:
        st.warning("The chain isn't connected on this computer yet. To launch for real:\n\n" +
                   "\n\n".join(f"{i}. {m}" for i, m in enumerate(cfg["missing"], 1)))
        return

    wallet = st.session_state.get("wallet")
    if wallet is None:
        st.caption(f"Wallet: Foundry keystore '{cfg['keystore']}'. The password unlocks it for this session "
                   "only and is never saved.")
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        password = c1.text_input("Keystore password", type="password", key="demo_keystore_password")
        if c2.button("Unlock wallet", type="primary", width="stretch", key="demo_unlock"):
            try:
                st.session_state["wallet"] = app_actions.unlock(password, cfg)
                st.rerun()
            except CHAIN_ERRORS as exc:
                st.error(str(exc))
        return
    w3, account = wallet
    st.caption(f"Wallet {account.address} on {app_actions.network_name(w3.eth.chain_id)}.")

    a, b, c = st.columns(3)
    with a:
        st.markdown("**Publish the data**")
        st.caption("Ratings and prices go on-chain.")
        if st.button("Publish", width="stretch", key="demo_publish"):
            try:
                with st.spinner("Publishing ratings and prices..."):
                    st.session_state["published"] = app_actions.publish_basket(build, w3, account, cfg)
            except CHAIN_ERRORS as exc:
                st.error(f"Publishing failed: {exc}")
    pub = st.session_state.get("published")
    with b:
        st.markdown("**Launch the fund**")
        st.caption("Creates its token and rules.")
        if st.button("Launch on Monad", type="primary", width="stretch", key="demo_launch", disabled=not pub):
            try:
                with st.spinner("Launching..."):
                    st.session_state["fund"] = app_actions.launch_basket(build, w3, account, name, symbol,
                                                                         want_min, cfg)
            except CHAIN_ERRORS as exc:
                st.error(str(exc))
    fund = st.session_state.get("fund")
    with c:
        st.markdown("**Deposit**")
        dollars = st.number_input("Test dollars", 1.0, 1_000_000.0, 1000.0, 100.0, key="demo_deposit_amount",
                                  label_visibility="collapsed")
        if st.button("Deposit", width="stretch", key="demo_deposit", disabled=not fund):
            try:
                with st.spinner("Depositing..."):
                    st.session_state["deposit"] = app_actions.deposit_dollars(fund["address"], dollars, w3,
                                                                              account, cfg)
            except CHAIN_ERRORS as exc:
                st.error(str(exc))
    if pub:
        st.html(style.banner(f"Published {len(pub['stocks'])} stocks with prices from {pub['price_date']}.", True))
    if fund:
        links = app_actions.explorer_links(fund)
        st.html(style.banner(f"{fund['name']} (${fund['symbol']}) is live on {fund['network']}.", True,
                             fund["address"]))
        if links:
            st.link_button("View the fund on the Monad explorer", links["fund"])
    dep = st.session_state.get("deposit")
    if dep and fund:
        st.html(style.banner(f"You hold {dep['shares']:,.2f} ${fund['symbol']}. The fund is worth "
                             f"${dep['nav_usd']:,.2f}, or ${dep['nav_per_share_usd']:.4f} a token.", True))


# ---------------------------------------------------------------------------------------------
# Ask about your fund
# ---------------------------------------------------------------------------------------------

def ask_section(portfolio: dict, weights: dict[str, float]) -> None:
    with st.expander("Ask about your fund"):
        st.caption("Answers come only from this fund's data. No predictions and no buy or sell advice.")
        report = st.session_state.get("risk_report")
        chain = dashboard.chain_facts(st.session_state.get("fund"), st.session_state.get("deposit"))
        info = companies(tuple(sorted(weights)))
        if portfolio["kind"] == "build":
            facts = assistant.fund_facts(portfolio["build"], report, chain, info)
        else:
            facts = assistant.fund_facts(None, report, chain, info, screen_report=portfolio["report"])
        history = st.session_state.setdefault("chat", [])
        for m in history:
            st.chat_message(m["role"]).write(m["content"])
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        question = c1.text_input("Your question", "In plain English, what does this fund hold and why?",
                                 key="demo_question")
        if c2.button("Ask", width="stretch", key="demo_ask") and question:
            st.chat_message("user").write(question)
            with st.chat_message("assistant"):
                try:
                    answer = st.write_stream(assistant.ask(question, facts, history))
                except assistant.AssistantError as exc:
                    st.error(str(exc))
                    return
            history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


# ---------------------------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------------------------

def build_tab() -> None:
    """Everything the demo had before the League tab, unchanged."""
    mode = st.segmented_control("Start from", [BUILD, CHECK], default=BUILD, key="demo_mode") or BUILD
    choose_step(mode)
    portfolio = st.session_state.get("portfolio")
    st.session_state.pop("demo_weights", None)
    if not portfolio:
        return
    if portfolio["kind"] == "build":
        weights = own_step_build(portfolio["build"], portfolio["prefs"])
    else:
        weights = own_step_check(portfolio["report"])
    if not weights:
        return
    st.session_state["demo_weights"] = weights  # the League tab enters this fund
    stress_step(weights)
    launch_step(portfolio)
    ask_section(portfolio, weights)


# ---------------------------------------------------------------------------------------------
# Fantasy Fund League
# ---------------------------------------------------------------------------------------------

def league_rows(etf: dict[str, int], portfolio: dict) -> list[dict]:
    """Entry rows for the card: ticker, company, industry, whole-percent weight and the theme it was picked for."""
    info = league.pool_info()
    picked = {h["ticker"]: h for h in portfolio["build"]["holdings"]} if portfolio["kind"] == "build" else {}
    rows = []
    for t, w in etf.items():
        h = picked.get(t, {})
        theme, tier = h.get("picked_for"), h.get("picked_tier")
        chips = [style.theme_chip(theme, tier)] if theme and theme != "_cap" and tier else []
        rows.append({"ticker": t, "name": info.get(t, {}).get("name", ""), "industry": info.get(t, {}).get("industry", ""),
                     "weight": float(w), "chips": chips})
    return rows


def interleaved(weights: dict[str, float], portfolio: dict) -> dict[str, float]:
    """Same weights, ordered by alternating the wanted themes (AI, Clean energy, AI, ...), so when the League keeps
    the 8 largest of equal weights, every wanted theme is represented, like the fund."""
    if portfolio["kind"] != "build":
        return weights
    groups: dict[str, list[str]] = {}
    for h in portfolio["build"]["holdings"]:
        if h["ticker"] in weights:
            groups.setdefault(h.get("picked_for") or "", []).append(h["ticker"])
    order = [t for i in range(max(map(len, groups.values()), default=0)) for g in groups.values() if i < len(g)
             for t in [g[i]]]
    order += [t for t in weights if t not in order]
    return {t: weights[t] for t in order}


WEEKLY_URL = league.LEAGUE_URL + "weekly.html"  # this week's matchup (GitHub Pages)
FINISHED_RACE_URL = league.LEAGUE_URL + "?round=1"
WEEK_FILE = league.POOL_FILE.parent / "week.json"  # written by the League operator when the week's round opens
PT = ZoneInfo("America/Los_Angeles")


@st.cache_data(ttl=60, show_spinner=False)
def this_week() -> dict:
    """league/week.json: round id, label, lock and end times. Empty if it isn't there."""
    try:
        return json.loads(WEEK_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _pt(iso: str, fmt: str) -> str:
    return datetime.fromisoformat(iso).astimezone(PT).strftime(fmt).replace(" 0", " ")


def weekly_link(etf: dict[str, int], name: str, embed: bool = False) -> str:
    """weekly.html with the fund filled in: ?etf=TICKER:PCT,...&name=... (same format as the League page)."""
    q = [("embed", "1")] if embed else []
    if etf:
        q += [("etf", ",".join(f"{t}:{w}" for t, w in etf.items())), ("name", name)]
    return WEEKLY_URL + ("?" + urlencode(q, safe=":,") if q else "")


def league_tab() -> None:
    weights = st.session_state.get("demo_weights")
    portfolio = st.session_state.get("portfolio")
    week = this_week()
    lock, end = "Mon 6:30 AM PT", "Friday"
    facts = []
    if week.get("lock") and week.get("end"):
        lock, end = _pt(week["lock"], "%a %I:%M %p PT"), _pt(week["end"], "%A")
        facts = [(week.get("label", "").split(" · ")[0] or "This week", f"round {week.get('roundId', '?')}"),
                 ("Locks", lock), ("Ends", _pt(week["end"], "%a %I:%M %p PT")), ("Entry", "1 MON stake")]
    st.html(style.weekly_intro(f"Enter your fund once. Locks {lock}, live prices all week, best fund {end} "
                               "wins the pot.", facts))
    etf: dict[str, int] = {}
    name = ""
    if not weights or not portfolio:
        st.html(style.empty_state("Build a fund first, then enter it in this week's matchup."))
    else:
        prefs = portfolio.get("prefs", {}) if portfolio["kind"] == "build" else {}
        name = league.fund_name(prefs, {k: t["name"] for k, t in themes().items()})
        etf, notes = league.league_fund(interleaved(weights, portfolio))
        stocks = [t for t, w in weights.items() if t != dashboard.CASH and w > 0]
        if etf and len(stocks) > len(etf):
            sentence = (f"A matchup entry holds at most 8 stocks, so it uses your {len(etf)} largest holdings, "
                        "rescaled to add up to 100%.")
        elif etf:
            sentence = f"Your {len(etf)} stocks, rescaled to add up to 100% as whole percents."
        else:
            sentence = ""
        other = [n for n in notes if "at most" not in n]
        left, right = st.columns([3, 2], gap="large")
        with left:
            if etf:
                st.html(style.league_entry(name, league_rows(etf, portfolio), " ".join([sentence, *other]).strip(),
                                           label="Your entry this week"))
            else:
                for n in notes:
                    st.warning(n)
        with right:
            if etf:
                st.link_button("Enter this fund in this week's matchup →", weekly_link(etf, name), type="primary",
                               width="stretch")
                st.caption("Opens the matchup with your fund filled in. You check it and confirm the 1 MON stake "
                           "in MetaMask.")
            st.caption(f"[See a finished race on Monad →]({FINISHED_RACE_URL})")
    st.html('<div style="height:16px"></div>')
    st.iframe(weekly_link(etf, name, embed=True), height=900)


# ---------------------------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def hero_facts() -> tuple[list[tuple[str, str, str]], dict[str, int], int]:
    """Real numbers for the page header: each theme's reference companies with their disclosed share, how many
    scored stocks are High or Moderate on each theme, and how many stocks were scored."""
    tape, counts, scored = [], {}, 666
    for key, theme in themes().items():
        short = style.RADAR_LABEL.get(key, theme["name"])
        for ref in (theme.get("references", {}).get("High") or [])[:2]:
            if ref.get("evidence_pct") is not None:
                tape.append((ref["ticker"], short, f"{ref['evidence_pct']:g}% of the business"))
    try:
        table = builder.prescreen()
        scored = len(table)
        for key in themes():
            counts[key] = sum(1 for results in table.values() if results.get(key, {}).get("tier") in ("High", "Moderate"))
    except (OSError, KeyError, ValueError):  # the header still draws without the radar
        counts = {}
    return tape, counts, scored


def main() -> None:
    tape, counts, scored = hero_facts()
    st.html(style.hero(tape=tape, radar=counts, scored=scored))
    build, league_view = st.tabs(["Build your fund", "Fantasy Fund League"])
    with build:
        build_tab()
    with league_view:
        league_tab()


main()
