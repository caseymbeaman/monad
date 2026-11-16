"""Theme Funds dashboard (Phase 8).

    streamlit run app.py

Two ways in, one regression engine:
- Build my ETF: Want / Don't care / Avoid per theme + region -> the builder's funnel -> the basket,
  re-checked with Way 1 -> heatmap + audit trail.
- Check my portfolio: any stocks + weights -> each stock scored on every theme -> % of the portfolio
  exposed to each theme -> heatmap + audit trail.
Then, for either: risk (Monte Carlo, theme shocks, mean-variance check) and "Ask about your fund".
For a built fund: launch it on Monad (publish its data, launch, deposit, try adding a forbidden stock).

All the logic lives in engine/ and chain/; this file only lays it out.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from chain import app_actions
from chain.publish import PublishError
from engine import assistant, builder, dashboard, risk, screen
from engine.data import DEFAULT_END, DEFAULT_START, DataError
from engine.monte_carlo import SimulationError
from engine.shocks import LABEL as SHOCK_LABEL
from engine.shocks import ShockError
from engine.theme_loader import load_all

st.set_page_config(page_title="Theme Funds", page_icon="📈", layout="wide")

BUILD, CHECK = "Build my ETF", "Check my portfolio"
EXAMPLE_QUESTIONS = [
    "In plain English, what does this fund hold and why?",
    "How bad could a bad year be?",
    "What happens to my fund if oil prices jump?",
]
SHOCK_SIZES = [-50, -30, -20, -10, 10, 20, 30, 50]
CHAIN_ERRORS = (PublishError, ValueError, ConnectionError, TimeoutError, OSError)


# ---------------------------------------------------------------------------------------------
# Cached engine calls (the engine also caches on disk; these keep reruns instant)
# ---------------------------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def themes() -> dict[str, dict]:
    return load_all()


@st.cache_resource(show_spinner="Loading the exposure table (every stock scored on every theme)...")
def universe_table() -> dict[str, dict[str, dict]]:
    return builder.prescreen()


@st.cache_data(show_spinner="Building your ETF...")
def run_build(prefs: tuple[tuple[str, str], ...], region: str) -> dict:
    return builder.build(dict(prefs), region=region)


@st.cache_data(show_spinner="Scoring each stock on every theme (new stocks are pulled live from FMP)...")
def run_check(holdings: tuple[tuple[str, float], ...]) -> dict:
    return screen.run_screen(dict(holdings))


@st.cache_data(show_spinner="Running 5,000 simulated years, theme shocks and the mean-variance check...")
def run_risk(holdings: tuple[tuple[str, float], ...]):
    return risk.run_risk(dict(holdings))


@st.cache_data(show_spinner=False)
def companies(tickers: tuple[str, ...]) -> dict[str, dict]:
    return assistant.company_info(list(tickers))


@st.cache_data(show_spinner=False)
def screen_ticker(ticker: str, theme_keys: tuple[str, ...]) -> dict[str, dict]:
    """Tier results for a ticker outside the exposure table."""
    all_themes = themes()
    return {k: screen._screen_one(ticker, all_themes[k], DEFAULT_START, DEFAULT_END) for k in theme_keys}


def _new_portfolio(portfolio: dict) -> None:
    """Start fresh: a new fund means a new chat and nothing launched yet."""
    st.session_state["portfolio"] = portfolio
    for key in ("chat", "fund", "deposit", "published"):
        st.session_state.pop(key, None)


# ---------------------------------------------------------------------------------------------
# Sidebar: the two ways in
# ---------------------------------------------------------------------------------------------

def sidebar() -> None:
    mode = st.sidebar.radio("How do you want to start?", [BUILD, CHECK], key="mode")
    if mode == BUILD:
        st.sidebar.header("Choose your themes")
        st.sidebar.caption("Want = the fund must have it. Avoid = the fund must stay clear of it.")
        choices = {k: st.sidebar.radio(t["name"], dashboard.CHOICES, index=1, horizontal=True, key=f"choice_{k}")
                   for k, t in themes().items()}
        region = st.sidebar.selectbox("Region", list(builder.REGIONS), format_func=builder.REGIONS.get,
                                      key="region")
        if st.sidebar.button("Build my ETF", type="primary", width="stretch", key="build_button"):
            prefs = dashboard.prefs_from_choices(choices)
            if not prefs:
                st.sidebar.warning("Pick at least one theme to Want or Avoid.")
                return
            try:
                build = run_build(tuple(sorted(prefs.items())), region)
            except builder.BuildError as exc:
                st.sidebar.error(str(exc))
                return
            _new_portfolio({"kind": "build", "build": build, "prefs": prefs})
    else:
        st.sidebar.header("Your stocks")
        st.sidebar.caption("Ticker and weight, e.g. NVDA:30 XOM:20 CASH:50. Weights are rescaled to 100%.")
        text = st.sidebar.text_area("Holdings", "NVDA:30 XOM:20 JNJ:20 CASH:30", key="holdings_text")
        if st.sidebar.button("Check my portfolio", type="primary", width="stretch", key="check_button"):
            try:
                holdings = dashboard.parse_holdings_text(text)
                report = run_check(tuple(holdings.items()))
            except screen.InputError as exc:
                st.sidebar.error(str(exc))
                return
            _new_portfolio({"kind": "check", "report": report})


# ---------------------------------------------------------------------------------------------
# Shared: heatmap + audit trail
# ---------------------------------------------------------------------------------------------

def heatmap_and_audit(table: dict[str, dict[str, dict]], holdings: dict[str, float]) -> None:
    st.subheader("Theme heatmap")
    st.caption("Every holding against every theme. Dark blue = High, light blue = Moderate, grey = Limited "
               "(Ltd* = lower confidence), amber ? = the data can't tell (not the same as zero).")
    matrix = dashboard.tier_matrix(table, list(holdings), themes())
    if matrix.empty:
        st.info("Only cash: nothing to score.")
        return
    st.plotly_chart(dashboard.heatmap_figure(matrix, holdings), width="stretch")

    st.subheader("Audit trail")
    st.caption("How any one tier was decided: the regression numbers and the thresholds they were held to.")
    c1, c2 = st.columns(2)
    ticker = c1.selectbox("Holding", list(matrix.index), key="audit_ticker")
    names = {th["name"]: k for k, th in themes().items()}
    theme_name = c2.selectbox("Theme", list(names), key="audit_theme")
    result = table.get(ticker, {}).get(names[theme_name], {})
    rows = dashboard.audit_rows(result)
    st.table({"": [r[0] for r in rows], "Value": [r[1] for r in rows]})
    groups = dashboard.group_table(result)
    if groups is not None:
        st.caption("A group counts if its beta sum is above 0.05 and its one-sided p-value is below the "
                   "threshold. The largest counting group sets the tier.")
        st.dataframe(groups, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------------------------
# Tab 1a: Build my ETF
# ---------------------------------------------------------------------------------------------

def build_tab(build: dict) -> None:
    funnel = dashboard.funnel_rows(build)
    if funnel:
        st.subheader("How we picked")
        st.caption(f"From {build.get('universe_size', 0)} scored stocks, each rule narrows the list.")
        st.dataframe(funnel, hide_index=True, width="stretch")
    holdings = dashboard.holdings_from_build(build)
    if not holdings:
        st.error("No stock passes every rule you chose. Try fewer or looser preferences, or another region.")
        for w in build.get("warnings", []):
            st.caption(w)
        return

    st.subheader("Your ETF")
    rows = []
    for h in build["holdings"]:
        row = {"Holding": h["ticker"], "Weight": f"{h['weight_pct']:.1f}%"}
        row.update(h.get("tiers") or {})
        row["Notes"] = "; ".join(h.get("labels") or [])
        rows.append(row)
    st.dataframe(rows, hide_index=True, width="stretch")
    for w in build.get("warnings", []):
        st.warning(w)

    verification = build.get("verification") or {}
    if verification:
        st.subheader("Does the finished ETF match your choices?")
        st.caption("The final basket is re-checked from scratch with 'Check my portfolio'.")
        for c in verification["checks"].values():
            (st.success if c["pass"] else st.error)(f"**{c['choice'].title()} {c['theme']}**: {c['sentence']}")
    heatmap_and_audit(universe_table(), holdings)


# ---------------------------------------------------------------------------------------------
# Tab 1b: Check my portfolio
# ---------------------------------------------------------------------------------------------

def check_tab(report: dict) -> None:
    st.subheader("How exposed is your portfolio to each theme?")
    if report.get("weights_rescaled_to_100"):
        st.caption("Your weights didn't add up to 100%, so they were rescaled.")
    st.dataframe(dashboard.fingerprint_rows(report), hide_index=True, width="stretch")
    for problem in dashboard.screen_errors(report):
        st.warning(f"Couldn't fully score {problem}")
    heatmap_and_audit(dashboard.results_from_screen(report), dashboard.holdings_from_screen(report))


# ---------------------------------------------------------------------------------------------
# Tab 2: risk
# ---------------------------------------------------------------------------------------------

def risk_report(holdings: dict[str, float]):
    if not holdings or set(holdings) == {"CASH"}:
        return None, None
    try:
        return run_risk(tuple(sorted(holdings.items())))
    except (DataError, SimulationError, ShockError, ValueError) as exc:
        st.error(f"The risk report couldn't run: {exc}")
        return None, None


def risk_tab(report: dict | None, figures: dict | None) -> None:
    if report is None:
        st.info("Build or check a portfolio with at least one stock to see its risk.")
        return
    mc = report["monte_carlo"]
    p, b = mc["portfolio"], mc["benchmark"]

    def loss(x):
        return f"-{x:.0%}" if x > 0 else "no loss"

    st.subheader("A range of possible years")
    if mc.get("history_note"):
        st.warning(mc["history_note"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Chance of losing >10%", f"{p['p_loss_over_10']:.0%}")
    m1.caption(f"SPY (the market): {b['p_loss_over_10']:.0%}")
    m2.metric("Bad year (5% VaR)", loss(p["var_5"]))
    m2.caption(f"SPY (the market): {loss(b['var_5'])}")
    m3.metric("Average of worst years (CVaR)", loss(p["cvar_5"]))
    m3.caption(f"SPY (the market): {loss(b['cvar_5'])}")
    m4.metric("Beat SPY", f"{mc['p_beat_benchmark']:.0%} of years")
    st.plotly_chart(figures["fan_chart"], width="stretch")
    for s in mc["sentences"]:
        if s != mc.get("history_note"):  # already shown above as a warning
            st.markdown(f"- {s}")

    st.subheader("Theme shocks")
    st.caption(f"What if one theme's stocks moved more than the overall market? ({SHOCK_LABEL}.)")
    by_name = {s["theme_name"]: s for s in report["shocks"]}
    default = max(report["shocks"], key=lambda s: abs(s["portfolio_move"]))["theme_name"]
    c1, c2 = st.columns([2, 3])
    theme_name = c1.selectbox("Theme", list(by_name), index=list(by_name).index(default), key="shock_theme")
    size = c2.select_slider("Shock size", SHOCK_SIZES, value=30, format_func=lambda v: f"{v:+d}%",
                            key="shock_size")
    base = by_name[theme_name]
    result = dashboard.reshock(base, themes()[base["theme"]], size / 100)
    st.metric(f"Estimated portfolio move if {theme_name} moves {size:+d}%", f"{result.portfolio_move:+.1%}")
    st.write(result.sentence)
    contrib = [h for h in result.holdings if h.move is not None and h.ticker != "CASH"]
    if contrib:
        contrib.sort(key=lambda h: h.contribution)
        fig = go.Figure(go.Bar(x=[h.contribution * 100 for h in contrib], y=[h.ticker for h in contrib],
                               orientation="h", marker_color=["#dc2626" if h.contribution < 0 else "#2563eb"
                                                              for h in contrib],
                               hovertemplate="%{y}: %{x:+.2f}% of the portfolio<extra></extra>"))
        fig.update_layout(title="Each holding's effect on the portfolio (percentage points)",
                          xaxis_ticksuffix="%", template="plotly_white", height=max(240, 28 * len(contrib) + 90),
                          margin={"t": 40, "l": 10, "r": 10, "b": 10})
        st.plotly_chart(fig, width="stretch")
    with st.expander("Every theme at +30%"):
        st.dataframe([{"Theme": s["theme_name"], "Estimated portfolio move": f"{s['portfolio_move']:+.1%}"}
                      for s in sorted(report["shocks"], key=lambda s: -abs(s["portfolio_move"]))],
                     hide_index=True, width="stretch")

    st.subheader("Mean-variance check")
    frontier = report.get("frontier") or {}
    if figures and figures.get("frontier") is not None:
        st.plotly_chart(figures["frontier"], width="stretch")
    for s in frontier.get("sentences", []):
        st.markdown(f"- {s}")


# ---------------------------------------------------------------------------------------------
# Tab 3: ask Claude
# ---------------------------------------------------------------------------------------------

def chat_tab(portfolio: dict, holdings: dict[str, float], report: dict | None) -> None:
    st.subheader("Ask about your fund")
    st.caption("Answers come only from this fund's data. No predictions and no buy/sell advice.")
    chain = dashboard.chain_facts(st.session_state.get("fund"), st.session_state.get("deposit"))
    info = companies(tuple(sorted(holdings)))
    if portfolio["kind"] == "build":
        facts = assistant.fund_facts(portfolio["build"], report, chain, info)
    else:
        facts = assistant.fund_facts(None, report, chain, info, screen_report=portfolio["report"])
    history = st.session_state.setdefault("chat", [])
    cols = st.columns(len(EXAMPLE_QUESTIONS))
    for col, q in zip(cols, EXAMPLE_QUESTIONS, strict=True):
        if col.button(q, key=f"example_{q}"):
            st.session_state["pending_question"] = q
    conversation = st.container()  # messages go above the input box, like a normal chat
    question = st.chat_input("Ask a question about your fund") or st.session_state.pop("pending_question", None)
    for m in history:
        conversation.chat_message(m["role"]).write(m["content"])
    if not question:
        return
    conversation.chat_message("user").write(question)
    with conversation.chat_message("assistant"):
        try:
            answer = st.write_stream(assistant.ask(question, facts, history))
        except assistant.AssistantError as exc:
            st.error(str(exc))
            return
    history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


# ---------------------------------------------------------------------------------------------
# Tab 4: launch on Monad
# ---------------------------------------------------------------------------------------------

def _try_adding_offchain(prefs: dict[str, str], ticker: str) -> None:
    table = universe_table()
    results = table.get(ticker) or screen_ticker(ticker, tuple(sorted(prefs)))
    tiers = {k: (results.get(k) or {}).get("tier", dashboard.NOT_SCREENED) for k in prefs}
    allowed, reasons = dashboard.mandate_check(ticker, prefs, tiers, themes())
    if allowed:
        st.success(f"{ticker} fits every rule of this fund, so it could be added.")
    else:
        st.error(f"Rejected: {ticker} can't be added.\n\n" + "\n\n".join(reasons))
    st.caption("Preview: checked off-chain with the same rules, because no chain is connected yet.")


def chain_tab(portfolio: dict) -> None:
    st.subheader("Launch your fund on Monad")
    if portfolio["kind"] != "build":
        st.info("Launching needs a fund from 'Build my ETF': your Want / Avoid choices become the fund's "
                "on-chain rules. A checked portfolio has no choices to turn into rules.")
        return
    build, prefs = portfolio["build"], portfolio["prefs"]
    if not dashboard.holdings_from_build(build):
        st.info("Build an ETF with at least one stock first.")
        return

    c1, c2, c3 = st.columns([3, 1, 1])
    try:
        default = app_actions.plan_for(build)
    except PublishError as exc:
        st.error(str(exc))
        return
    name = c1.text_input("Fund name", default["name"], key="fund_name")
    symbol = c2.text_input("Symbol", default["symbol"], key="fund_symbol")
    want_min = c3.number_input("Want rules: min % in High/Moderate", 1.0, 100.0, 60.0, 5.0, key="want_min")
    try:
        plan = app_actions.plan_for(build, name, symbol, want_min)
    except PublishError as exc:
        st.error(str(exc))
        return
    st.markdown("**The fund's rules (fixed forever once launched):**")
    for r in plan["rules"]:
        if r["kind"] == 0:
            st.markdown(f"- Want **{r['label']}**: at least {r['min_bps'] / 100:g}% of the fund in High or "
                        "Moderate names")
        else:
            st.markdown(f"- Avoid **{r['label']}**: every holding must be Limited or Limited (lower confidence)")

    cfg = app_actions.config()
    if not cfg["ready"]:
        st.warning("The chain isn't connected yet. To launch for real:\n\n" +
                   "\n\n".join(f"{i}. {m}" for i, m in enumerate(cfg["missing"], 1)))
        st.subheader("Try to break the rules")
        ticker = st.text_input("Stock to add", value="XOM", key="try_ticker").strip().upper()
        if st.button("Try adding it", key="try_add") and ticker:
            _try_adding_offchain(prefs, ticker)
        return

    wallet = st.session_state.get("wallet")
    if wallet is None:
        st.caption(f"Wallet: Foundry keystore '{cfg['keystore']}'. The password is used once to unlock it "
                   "for this session and is never saved.")
        password = st.text_input("Keystore password", type="password", key="keystore_password")
        if st.button("Unlock wallet", key="unlock"):
            try:
                st.session_state["wallet"] = app_actions.unlock(password, cfg)
                st.rerun()
            except CHAIN_ERRORS as exc:
                st.error(str(exc))
        return
    w3, account = wallet
    st.caption(f"Wallet {account.address} on {app_actions.network_name(w3.eth.chain_id)}.")

    st.markdown("**1. Publish the fund's data to the oracle** (tiers and prices; owner wallet only)")
    if st.button("Publish", key="publish"):
        try:
            with st.spinner("Publishing tiers and prices..."):
                st.session_state["published"] = app_actions.publish_basket(build, w3, account, cfg)
        except CHAIN_ERRORS as exc:
            st.error(f"Publishing failed: {exc}")
    pub = st.session_state.get("published")
    if pub:
        st.success(f"Published {len(pub['stocks'])} stocks ({pub['tiers_posted']} tier(s) changed) with prices "
                   f"from {pub['price_date']}.")

    st.markdown("**2. Launch the fund**")
    if st.button("Launch fund on Monad", type="primary", key="launch"):
        try:
            with st.spinner("Launching..."):
                st.session_state["fund"] = app_actions.launch_basket(build, w3, account, name, symbol, want_min,
                                                                     cfg)
        except CHAIN_ERRORS as exc:
            st.error(str(exc))
    fund = st.session_state.get("fund")
    if fund:
        st.success(f"{fund['name']} (${fund['symbol']}) is live on {fund['network']} at {fund['address']}.")
        links = app_actions.explorer_links(fund)
        if links:
            st.link_button("View on the Monad explorer", links["fund"])

    st.markdown("**3. Deposit test dollars**")
    dollars = st.number_input("Amount ($)", 1.0, 1_000_000.0, 1000.0, 100.0, key="deposit_amount")
    if st.button("Deposit", key="deposit_button", disabled=not fund):
        try:
            with st.spinner("Depositing..."):
                st.session_state["deposit"] = app_actions.deposit_dollars(fund["address"], dollars, w3, account,
                                                                          cfg)
        except CHAIN_ERRORS as exc:
            st.error(str(exc))
    dep = st.session_state.get("deposit")
    if dep and fund:
        st.success(f"You now hold {dep['shares']:,.2f} ${fund['symbol']}. The fund is worth "
                   f"${dep['nav_usd']:,.2f} (${dep['nav_per_share_usd']:.4f} a share).")

    st.markdown("**4. Try to break the rules**")
    ticker = st.text_input("Stock to add", value="XOM", key="try_ticker").strip().upper()
    if st.button("Try adding it", key="try_add", disabled=not fund) and ticker:
        try:
            allowed, reason = app_actions.try_adding(fund["address"], ticker, cfg)
        except CHAIN_ERRORS as exc:
            st.error(str(exc))
            return
        if allowed:
            st.success(f"The fund would accept {ticker}: it doesn't break any rule.")
        else:
            st.error(f"Rejected by the fund contract: {reason}")
        st.caption("Rehearsed against the live contract; nothing was sent.")


# ---------------------------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------------------------

def main() -> None:
    st.title("Theme Funds")
    st.caption("Build an ETF from the themes you want and avoid, or check how exposed your own stocks are. "
               "Every result comes in plain English, and a built fund can launch on Monad with rules that "
               "can't be broken.")
    sidebar()
    portfolio = st.session_state.get("portfolio")
    if not portfolio:
        st.markdown("**Two ways in:**\n\n"
                    "- **Build my ETF**: choose Want / Don't care / Avoid for each theme and a region. We pick "
                    "the stocks.\n"
                    "- **Check my portfolio**: type your own stocks and weights. We show how exposed you are to "
                    "each theme.")
        return
    if portfolio["kind"] == "build":
        holdings = dashboard.holdings_from_build(portfolio["build"])
        prefs = portfolio["prefs"]
        region = builder.REGIONS.get(portfolio["build"].get("region") or "all", "All regions")
        st.caption("Your choices: " + ", ".join(f"{v} {themes()[k]['name']}" for k, v in prefs.items())
                   + f" · region: {region}")
    else:
        holdings = dashboard.holdings_from_screen(portfolio["report"])
        st.caption("Your portfolio: " + ", ".join(f"{t} {w:.0f}%" for t, w in holdings.items()))
    report, figures = risk_report(holdings)
    first = "Your ETF" if portfolio["kind"] == "build" else "Your portfolio"
    t1, t2, t3, t4 = st.tabs([first, "Risk", "Ask about your fund", "Launch on Monad"])
    with t1:
        if portfolio["kind"] == "build":
            build_tab(portfolio["build"])
        else:
            check_tab(portfolio["report"])
    with t2:
        risk_tab(report, figures)
    with t3:
        chat_tab(portfolio, holdings, report)
    with t4:
        chain_tab(portfolio)


main()
