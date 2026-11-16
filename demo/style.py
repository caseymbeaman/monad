"""Colors, fonts and small HTML building blocks for demo_app.py.

Nothing here computes a number. Every function takes values the engine already produced and
returns HTML (or restyles a Plotly figure) so the dashboard looks like one product with the
League page: black background, rose for buttons and "want", champagne gold for "avoid", mint and
coral only for gains and losses (always with a + or - sign). Type has a sportsbook / scoreboard feel:
headings, labels and the big numbers in a bold condensed face (Barlow Condensed, uppercase for headers and
labels), text, buttons and tables in Inter, addresses and hashes in JetBrains Mono. Every digit is tabular
(fixed width), so numbers don't jiggle while they count.
"""

from __future__ import annotations

import re
from html import escape

# ---------------------------------------------------------------------------------------------
# Palette and type (shared with the League page design)
# ---------------------------------------------------------------------------------------------

INK = "#0B0A0B"          # page background (black)
CARD = "#171315"         # panels
RAISED = "#211B1E"       # inputs, hover
LINE = "#2E2529"         # borders
TEXT = "#F5EEF1"
MUTED = "#B8A9B0"
ROSE = "#C2456F"         # buttons and "want" fills (white text reads on it)
ROSE_HOVER = "#AD3A61"
BLUSH = "#F4A6BF"        # highlights: the fund line, numbers you want to see
BLUSH_TEXT = "#F9C9D8"   # text on rose-tinted chips
ROSE_SOFT = "#3A1A27"    # rose-tinted chip background
CHAMPAGNE = "#E8C98F"    # "avoid"
CHAMPAGNE_SOFT = "#2E2516"
GAIN = "#6FD6AE"
LOSS = "#FF8A7A"
NEUTRAL_BAR = "#3A3034"  # themes that aren't part of your choices

TIER_STYLE = {  # (background, text) per tier, readable on black
    "High": (ROSE_SOFT, BLUSH_TEXT),
    "Moderate": ("#2C1A22", "#E9A9BF"),
    "Limited": ("#16261F", "#8FDDBD"),
    "Limited (lower confidence)": ("#17221D", "#A4CFBB"),
    "Not determined": (CHAMPAGNE_SOFT, CHAMPAGNE),
    "Not screened": ("#1E191B", MUTED),
}

FONTS = ("https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800"
         "&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap")
DISPLAY = "'Barlow Condensed', 'Arial Narrow', 'Roboto Condensed', system-ui, sans-serif"  # headings, labels, big numbers
SANS = "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"  # text, buttons, inputs, tables
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"  # addresses and hashes

# NOTE: no "<" + letter anywhere inside this CSS (Streamlit's sanitizer would drop the whole block).
CSS = f"""
<style>
@import url('{FONTS}');
html, body, .stApp, .stMarkdown, p, label, input, textarea, button, table {{ font-family: {SANS}; }}
.stApp {{ background: {INK}; color: {TEXT}; font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; }}
code, pre, .tf-mono {{ font-family: {MONO} !important; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"], [data-testid="stDecoration"], footer {{ display: none; }}
.block-container {{ max-width: 1240px; padding-top: 2.2rem; padding-bottom: 6rem; }}
h1, h2, h3 {{ font-family: {DISPLAY} !important; font-weight: 700 !important; text-transform: uppercase;
  letter-spacing: 0.02em; line-height: 1.05; color: {TEXT}; }}
p, li, label, .stMarkdown {{ color: {TEXT}; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {MUTED} !important; }}
[data-testid="stWidgetLabel"] p {{ color: {TEXT}; font-weight: 600; }}
.stButton > button, .stLinkButton > a {{ border-radius: 10px; min-height: 44px; font-weight: 600; }}
[data-testid="stBaseButton-primary"], .stButton button[kind="primary"] {{ background: {ROSE}; border: 0; color: #fff; }}
[data-testid="stBaseButton-primary"]:hover, .stButton button[kind="primary"]:hover {{ background: {ROSE_HOVER}; color: #fff; }}
[data-testid="stBaseButton-primary"] p, .stButton button[kind="primary"] p {{ color: #fff; font-weight: 600; }}
[data-testid="stBaseButton-secondary"] {{ background: {RAISED}; border: 1px solid {LINE}; color: {TEXT}; }}
/* Link buttons (st.link_button) look like the regular buttons above. */
.stApp [data-testid="stBaseLinkButton-primary"] {{ background: linear-gradient(180deg, #D65A84, {ROSE}); border: 0;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .28), 0 10px 26px -10px rgba(194, 69, 111, .85); }}
.stApp [data-testid="stBaseLinkButton-primary"]:hover {{ background: linear-gradient(180deg, #DE6990, #C74B76); }}
.stApp [data-testid="stBaseLinkButton-primary"] p {{ color: #fff; font-weight: 600; }}
.stApp [data-testid="stBaseLinkButton-secondary"] {{ background: {RAISED}; border: 1px solid {LINE}; }}
.stApp [data-testid="stBaseLinkButton-secondary"]:hover {{ border-color: {ROSE}; }}
.stApp [data-testid="stBaseLinkButton-secondary"] p {{ color: {TEXT}; font-weight: 600; }}
[data-testid="stExpander"] {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; }}
.stApp [data-testid="stButtonGroup"] button {{ background: {RAISED}; border-color: {LINE}; color: {MUTED}; }}
.stApp [data-testid="stButtonGroup"] button p {{ color: {MUTED}; font-weight: 600; }}
.stApp [data-testid="stButtonGroup"] button:hover {{ border-color: {ROSE}; }}
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"] {{ background: {ROSE_SOFT}; border-color: {ROSE}; }}
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"] p {{ color: {BLUSH_TEXT}; }}
[data-testid="stMetricValue"] {{ font-family: {DISPLAY}; font-weight: 800; font-variant-numeric: tabular-nums; }}
[data-testid="stMetricLabel"] p {{ font-family: {DISPLAY}; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.04em; color: {MUTED}; }}
[data-testid="stTabs"] button p {{ font-size: 16px; font-weight: 600; }}
[data-testid="stTabs"] [aria-selected="true"] p {{ color: {BLUSH}; }}
div[data-baseweb="select"] > div, input, textarea {{ background: {RAISED} !important; color: {TEXT} !important; }}
:focus-visible {{ outline: 2px solid {BLUSH} !important; outline-offset: 2px; }}

.tf-hero {{ position: relative; overflow: hidden; isolation: isolate; padding: 48px 40px 40px; margin-bottom: 8px;
  border: 1px solid {LINE}; border-radius: 16px; background: {CARD}; }}
.tf-hero::before {{ content: ""; position: absolute; inset: -40%; z-index: -2;
  background: radial-gradient(40% 35% at 20% 30%, rgba(194, 69, 111, .30), transparent 70%),
              radial-gradient(35% 30% at 80% 20%, rgba(244, 166, 191, .16), transparent 70%),
              radial-gradient(45% 40% at 70% 85%, rgba(232, 201, 143, .12), transparent 70%);
  animation: tf-drift 18s ease-in-out infinite alternate; will-change: transform; }}
/* No raw less-than signs anywhere in this CSS: Streamlit's sanitizer drops the WHOLE style block if its text
   looks like a tag. The grain image is %-encoded and @property syntax uses the CSS escape \\3C. */
.tf-hero::after {{ content: ""; position: absolute; inset: 0; z-index: -1; opacity: .07; pointer-events: none;
  background-image: url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"); }}
@keyframes tf-drift {{ from {{ transform: translate3d(-4%, -2%, 0) scale(1); }} to {{ transform: translate3d(4%, 3%, 0) scale(1.08); }} }}
.tf-hero .eyebrow {{ font-family: {DISPLAY}; font-weight: 700; font-size: 16px; letter-spacing: .06em;
  text-transform: uppercase; color: {BLUSH}; margin-bottom: 12px; }}
.tf-hero .props {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 24px; }}
.tf-hero .props span {{ font-size: 13px; color: {TEXT}; background: rgba(23, 19, 21, .7); border: 1px solid {LINE};
  border-radius: 999px; padding: 6px 12px; }}
@property --tf-a {{ syntax: "\\3C integer\\3E"; initial-value: 0; inherits: false; }}
@property --tf-b {{ syntax: "\\3C integer\\3E"; initial-value: 0; inherits: false; }}
.tf-count {{ --tf-a: var(--a); --tf-b: var(--b); counter-reset: a var(--tf-a) b var(--tf-b);
  animation: tf-count 900ms cubic-bezier(.2,.8,.2,1) both; }}
.tf-count .i::after {{ content: counter(a); }}
.tf-count .f::after {{ content: counter(b, var(--fs, decimal)); }}
@keyframes tf-count {{ from {{ --tf-a: 0; --tf-b: 0; }} }}
.tf-tile {{ animation: tf-rise 400ms cubic-bezier(.2,.8,.2,1) both; animation-delay: var(--d, 0ms); }}
@keyframes tf-rise {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes tf-bar {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
@media (prefers-reduced-motion: reduce) {{ .tf-hero::before, .tf-count, .tf-tile, .tf-r .bar span {{ animation: none; }} }}
.tf-hero h1 {{ font-size: clamp(56px, 9vw, 104px); line-height: 0.9; margin: 0; font-weight: 800 !important;
  letter-spacing: 0.01em; }}
.tf-hero p {{ margin: 16px 0 0; color: {MUTED}; font-size: 19px; max-width: 640px; line-height: 1.55; }}

.tf-step {{ margin: 64px 0 20px; padding-top: 28px; border-top: 1px solid {LINE}; }}
.tf-step h2 {{ font-size: clamp(34px, 5vw, 46px); margin: 0; line-height: 1; font-weight: 800 !important; }}
.tf-step p {{ margin: 8px 0 0; color: {MUTED}; font-size: 16px; max-width: 720px; line-height: 1.55; }}

.tf-fp {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 18px; padding: 28px 28px 18px; }}
.tf-fp-cols {{ display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); gap: 12px; align-items: end;
  height: 260px; border-bottom: 1px solid {LINE}; }}
.tf-fp-col {{ position: relative; height: 100%; display: flex; flex-direction: column; justify-content: flex-end;
  align-items: stretch; }}
.tf-fp-bar {{ border-radius: 8px 8px 2px 2px; min-height: 3px; transform-origin: bottom;
  animation: tf-grow 900ms cubic-bezier(.2,.8,.2,1) both; animation-delay: var(--d); }}
.tf-fp-val {{ font-family: {DISPLAY}; font-weight: 800; font-size: 26px; margin-bottom: 6px; line-height: 1;
  text-align: center; font-variant-numeric: tabular-nums; }}
.tf-fp-names {{ display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); gap: 12px; padding-top: 10px; }}
.tf-fp-names div {{ font-size: 13px; line-height: 1.3; color: {MUTED}; text-align: center; }}
.tf-fp-names b {{ display: block; color: {TEXT}; font-weight: 600; }}
.tf-fp-legend {{ display: flex; gap: 18px; flex-wrap: wrap; margin-top: 16px; font-size: 14px; color: {MUTED}; }}
.tf-fp-legend i {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px;
  vertical-align: -1px; }}
@keyframes tf-grow {{ from {{ transform: scaleY(0); }} to {{ transform: scaleY(1); }} }}
@media (prefers-reduced-motion: reduce) {{ .tf-fp-bar {{ animation: none; }} }}

.tf-funnel {{ display: flex; flex-direction: column; gap: 12px; }}
.tf-funnel .row {{ display: grid; grid-template-columns: minmax(0, 1fr) 64px; column-gap: 12px; align-items: end; }}
.tf-funnel .lbl {{ font-size: 14px; color: {TEXT}; line-height: 1.35; margin-bottom: 6px; }}
.tf-funnel .bar {{ background: {RAISED}; border-radius: 6px; height: 10px; overflow: hidden; }}
.tf-funnel .bar span {{ display: block; height: 100%; background: {ROSE}; border-radius: 6px; }}
.tf-funnel .num {{ font-family: {DISPLAY}; font-weight: 800; font-size: 30px; text-align: right;
  font-variant-numeric: tabular-nums; line-height: 1; }}

/* One stock row, used by "Your N stocks" and the League entry card (same layout as the League page):
   TICKER | company (one line, ellipsis) / industry + theme chip | weight, then a full-width weight bar.
   Own class names (tf-r-*) so no card-level rule can restyle them. */
.tf-rows {{ display: flex; flex-direction: column; }}
.tf-r {{ display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; gap: 4px 16px; align-items: start;
  padding: 14px 0; border-top: 1px solid {LINE}; line-height: 1.35; }}
.tf-r:first-child {{ border-top: 0; padding-top: 4px; }}
.tf-r .tf-r-tk {{ font-family: {DISPLAY}; font-weight: 700; font-size: 20px; line-height: 1.25; letter-spacing: 0.02em;
  text-transform: uppercase; color: {TEXT}; }}
.tf-r .tf-r-main {{ min-width: 0; }}
.tf-r .tf-r-co {{ font-family: {SANS}; font-weight: 500; font-size: 15px; line-height: 1.35; text-transform: none;
  letter-spacing: 0; color: {TEXT}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }}
.tf-r .tf-r-meta {{ display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; margin-top: 4px; min-width: 0; }}
.tf-r .tf-r-ind {{ font-family: {SANS}; font-size: 13px; line-height: 1.35; color: {MUTED}; }}
.tf-r .tf-r-w {{ font-family: {SANS}; font-weight: 600; font-size: 15px; line-height: 1.35; text-align: right;
  font-variant-numeric: tabular-nums; color: {TEXT}; white-space: nowrap; }}
.tf-r .tf-r-why {{ grid-column: 2 / -1; font-size: 13px; line-height: 1.45; color: {MUTED}; }}
.tf-r .bar {{ grid-column: 1 / -1; height: 6px; background: {RAISED}; border-radius: 6px; overflow: hidden; margin-top: 8px; }}
.tf-r .bar span {{ display: block; height: 100%; background: {ROSE}; border-radius: 6px; transform-origin: left;
  animation: tf-bar 600ms cubic-bezier(.2,.8,.2,1) both; }}
.tf-chip {{ display: inline-block; font-family: {SANS}; font-size: 12px; font-weight: 600; line-height: 1.35;
  padding: 3px 9px; border-radius: 999px; white-space: nowrap; text-transform: none; letter-spacing: 0; }}

.tf-tiles {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
@media (max-width: 900px) {{ .tf-tiles {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .tf-fp-cols {{ height: 200px; }} .tf-fp-val {{ font-size: 20px; }} }}
.tf-tile {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; padding: 16px 18px; }}
.tf-tile .k {{ font-family: {DISPLAY}; font-weight: 700; font-size: 15px; letter-spacing: 0.04em;
  text-transform: uppercase; color: {MUTED}; line-height: 1.2; }}
.tf-tile .v {{ font-family: {DISPLAY}; font-size: 48px; font-weight: 800; margin-top: 6px; line-height: 1;
  font-variant-numeric: tabular-nums; }}
.tf-tile .b {{ font-size: 13px; color: {MUTED}; margin-top: 2px; }}

.tf-big {{ font-family: {DISPLAY}; font-size: clamp(80px, 12vw, 120px); font-weight: 800; line-height: 0.95;
  font-variant-numeric: tabular-nums; letter-spacing: 0; }}
.tf-sentence {{ font-size: 17px; line-height: 1.55; color: {TEXT}; max-width: 680px; }}
.tf-checks {{ display: flex; flex-direction: column; gap: 8px; }}
.tf-check {{ display: flex; gap: 12px; align-items: flex-start; background: {CARD}; border: 1px solid {LINE};
  border-radius: 12px; padding: 12px 14px; font-size: 15px; line-height: 1.5; }}
.tf-check .ic {{ flex: none; width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center;
  justify-content: center; font-weight: 600; font-size: 13px; margin-top: 1px; }}
.tf-rules {{ display: flex; flex-direction: column; gap: 8px; }}
.tf-rule {{ display: flex; gap: 12px; align-items: center; background: {CARD}; border: 1px solid {LINE};
  border-radius: 12px; padding: 12px 14px; font-size: 15px; }}
.tf-banner {{ border-radius: 14px; padding: 18px 20px; font-size: 18px; font-weight: 600; line-height: 1.45; }}
.tf-banner.bad {{ background: #2B1513; border: 1px solid #7A3530; color: #FFB8AC; }}
.tf-banner.good {{ background: #13261E; border: 1px solid #2B5A46; color: #A6EBCF; }}
.tf-banner small {{ display: block; font-size: 14px; font-weight: 500; color: {MUTED}; margin-top: 6px; }}
.tf-addr {{ font-family: {MONO}; font-size: 12px; color: {MUTED}; word-break: break-all; }}
.tf-empty {{ background: {CARD}; border: 1px dashed {LINE}; border-radius: 16px; padding: 48px 24px; text-align: center;
  color: {MUTED}; font-size: 17px; margin-top: 24px; }}
.tf-empty b {{ display: block; font-family: {DISPLAY}; font-weight: 800; font-size: 30px; text-transform: uppercase;
  letter-spacing: 0.02em; color: {TEXT}; margin-bottom: 8px; }}
.tf-entry {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 16px; padding: 24px; margin-bottom: 16px; }}
.tf-entry .k {{ font-family: {DISPLAY}; font-weight: 700; font-size: 15px; letter-spacing: 0.04em;
  text-transform: uppercase; color: {MUTED}; }}
.tf-entry .tf-entry-name {{ font-family: {DISPLAY}; font-size: clamp(22px, 3vw, 28px); font-weight: 800;
  text-transform: uppercase; letter-spacing: 0.02em; line-height: 1.15; margin: 6px 0 12px; overflow-wrap: anywhere; }}
.tf-entry .note {{ font-size: 13px; color: {MUTED}; margin-top: 12px; line-height: 1.45; }}
.tf-intro {{ margin: 32px 0 24px; }}
.tf-intro h2 {{ font-size: 40px; margin: 0; line-height: 1.1; }}
.tf-intro p {{ margin: 8px 0 0; color: {MUTED}; font-size: 16px; max-width: 760px; line-height: 1.55; }}
.tf-intro .modes {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }}
.tf-intro .modes span {{ font-size: 13px; background: {CARD}; border: 1px solid {LINE}; border-radius: 999px;
  padding: 6px 12px; color: {TEXT}; }}
.tf-intro .modes b {{ color: {BLUSH}; font-weight: 600; }}
/* ============ DRAFT: richer look (backdrop grid, framed hero, radar, ticker tape, lit cards) ============ */
.stApp {{ background:
    radial-gradient(900px 520px at 88% -6%, rgba(194, 69, 111, .24), transparent 64%),
    radial-gradient(760px 520px at -12% 38%, rgba(232, 201, 143, .07), transparent 60%),
    {INK}; }}
.stApp::before {{ content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image: linear-gradient(rgba(245, 238, 241, .04) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(245, 238, 241, .04) 1px, transparent 1px);
  background-size: 56px 56px;
  -webkit-mask-image: radial-gradient(ellipse 85% 62% at 50% 18%, #000 25%, transparent 88%);
          mask-image: radial-gradient(ellipse 85% 62% at 50% 18%, #000 25%, transparent 88%); }}
[data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: transparent; position: relative; z-index: 1; }}

.tf-hero {{ padding: 0; border-color: rgba(245, 238, 241, .10); border-radius: 20px;
  background: linear-gradient(180deg, rgba(255, 255, 255, .04), rgba(255, 255, 255, 0) 38%), {CARD};
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .06), 0 40px 80px -48px rgba(194, 69, 111, .55); }}
.tf-hero-grid {{ position: relative; display: grid; grid-template-columns: minmax(0, 1fr) 440px; gap: 12px; align-items: center;
  padding: 52px 44px 36px; }}
.tf-hero .c {{ position: absolute; width: 22px; height: 22px; border: 2px solid {BLUSH}; opacity: .75; z-index: 1; }}
.tf-hero .c.tl {{ top: 14px; left: 14px; border-right: 0; border-bottom: 0; border-radius: 6px 0 0 0; }}
.tf-hero .c.tr {{ top: 14px; right: 14px; border-left: 0; border-bottom: 0; border-radius: 0 6px 0 0; }}
.tf-hero .c.bl {{ bottom: 14px; left: 14px; border-right: 0; border-top: 0; border-radius: 0 0 0 6px; }}
.tf-hero .c.br {{ bottom: 14px; right: 14px; border-left: 0; border-top: 0; border-radius: 0 0 6px 0; }}
.tf-hero .eyebrow {{ display: flex; align-items: center; gap: 10px; }}
.tf-hero .live {{ width: 9px; height: 9px; border-radius: 50%; background: {GAIN}; box-shadow: 0 0 0 0 rgba(111, 214, 174, .6);
  animation: tf-pulse 2.4s ease-out infinite; }}
@keyframes tf-pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(111, 214, 174, .55); }} 100% {{ box-shadow: 0 0 0 12px rgba(111, 214, 174, 0); }} }}
.tf-hero h1 {{ font-size: clamp(64px, 10vw, 128px); letter-spacing: 0;
  background: linear-gradient(180deg, #FFFFFF 28%, {BLUSH} 118%); -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent; filter: drop-shadow(0 0 34px rgba(194, 69, 111, .38)); }}
.tf-hero .stats {{ display: flex; gap: 0; margin-top: 30px; flex-wrap: wrap; }}
.tf-hero .stats div {{ padding: 0 26px; border-left: 1px solid {LINE}; }}
.tf-hero .stats div:first-child {{ padding-left: 0; border-left: 0; }}
.tf-hero .stats b {{ display: block; font-family: {DISPLAY}; font-weight: 800; font-size: 46px; line-height: 1; color: {TEXT}; }}
.tf-hero .stats span {{ display: block; margin-top: 6px; font-size: 13px; color: {MUTED}; }}

.tf-radar {{ margin: 0; }}
.tf-radar .plot {{ position: relative; width: 100%; aspect-ratio: 1 / 1; }}
.tf-radar .plot i {{ position: absolute; display: block; }}
.tf-radar figcaption {{ text-align: center; font-size: 12px; color: {MUTED}; margin-top: -6px; }}
.tf-radar .ring {{ left: 50%; top: 50%; width: calc(var(--r) * 2); height: calc(var(--r) * 2); transform: translate(-50%, -50%);
  border-radius: 50%; border: 1px solid rgba(245, 238, 241, .10); }}
.tf-radar .ring:nth-of-type(6) {{ border-color: rgba(244, 166, 191, .5); box-shadow: 0 0 30px -6px rgba(194, 69, 111, .6); }}
.tf-radar .spoke {{ left: 50%; top: 50%; width: 1px; height: var(--r); background: rgba(245, 238, 241, .09);
  transform-origin: 50% 0; transform: rotate(calc(var(--a) + 180deg)); }}
.tf-radar .ticks {{ left: 50%; top: 50%; width: calc(var(--r) * 2); height: calc(var(--r) * 2); transform: translate(-50%, -50%);
  border-radius: 50%; background: repeating-conic-gradient(rgba(245, 238, 241, .34) 0deg .7deg, transparent .7deg 6deg);
  -webkit-mask: radial-gradient(closest-side, transparent 94%, #000 94.5%); mask: radial-gradient(closest-side, transparent 94%, #000 94.5%); }}
.tf-radar .glow {{ inset: 0; filter: drop-shadow(0 0 12px rgba(194, 69, 111, .75)); transform-origin: 50% 50%;
  animation: tf-bloom 1100ms cubic-bezier(.2, .8, .2, 1) both; }}
.tf-radar .shape {{ inset: 0; background: radial-gradient(circle at 50% 50%, rgba(244, 166, 191, .30), rgba(194, 69, 111, .62)); }}
@keyframes tf-bloom {{ from {{ transform: scale(.2); opacity: 0; }} to {{ transform: scale(1); opacity: 1; }} }}
.tf-radar .dot {{ width: 7px; height: 7px; margin: -3.5px 0 0 -3.5px; border-radius: 50%; background: #fff;
  box-shadow: 0 0 10px 2px rgba(244, 166, 191, .9); }}
.tf-radar .lbl {{ position: absolute; transform: translate(-50%, -50%); white-space: nowrap; font-family: {DISPLAY}; font-weight: 700;
  font-size: 14px; letter-spacing: .05em; text-transform: uppercase; color: {MUTED}; line-height: 1; }}
.tf-radar .lbl.right {{ transform: translate(0, -50%); }}
.tf-radar .lbl.left {{ transform: translate(-100%, -50%); }}
.tf-radar .lbl b {{ color: {BLUSH}; font-weight: 800; margin-left: 6px; }}
.tf-radar .sweep {{ left: 50%; top: 50%; width: calc(var(--r) * 2); height: calc(var(--r) * 2); margin: calc(var(--r) * -1) 0 0 calc(var(--r) * -1);
  border-radius: 50%; background: conic-gradient(from 0deg, rgba(244, 166, 191, .22), transparent 22%, transparent);
  animation: tf-sweep 14s linear infinite; }}
@keyframes tf-sweep {{ to {{ transform: rotate(360deg); }} }}

.tf-tape {{ border-top: 1px solid rgba(245, 238, 241, .09); overflow: hidden; padding: 13px 0; background: rgba(11, 10, 11, .45);
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent);
          mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent); }}
.tf-tape .run {{ display: inline-flex; gap: 38px; white-space: nowrap; width: max-content; animation: tf-tape 60s linear infinite; }}
.tf-tape span {{ font-size: 13px; color: {MUTED}; display: inline-flex; align-items: baseline; gap: 8px; }}
.tf-tape b {{ font-family: {DISPLAY}; font-weight: 800; font-size: 17px; letter-spacing: .04em; color: {TEXT}; }}
.tf-tape em {{ font-style: normal; color: {BLUSH}; }}
@keyframes tf-tape {{ to {{ transform: translateX(-50%); }} }}
@media (prefers-reduced-motion: reduce) {{ .tf-hero .live, .tf-radar .shape, .tf-radar .sweep, .tf-tape .run {{ animation: none; }} }}
@media (max-width: 980px) {{ .tf-hero-grid {{ grid-template-columns: minmax(0, 1fr); padding: 40px 26px 28px; }}
  .tf-radar {{ max-width: 340px; margin: 0 auto; }} .tf-hero .stats div {{ padding: 0 16px; }} .tf-hero .stats b {{ font-size: 36px; }} }}

/* Section headings: a lit rule with a diamond marker instead of a flat line. */
.tf-step {{ position: relative; border-top: 0; padding-top: 34px; }}
.tf-step::before {{ content: ""; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, {ROSE}, rgba(194, 69, 111, .3) 16%, {LINE} 42%, transparent); }}
.tf-step::after {{ content: ""; position: absolute; top: -5px; left: 0; width: 10px; height: 10px; background: {BLUSH};
  transform: rotate(45deg); box-shadow: 0 0 16px 2px rgba(194, 69, 111, .9); }}

/* Panels catch a little light from above and sit on a soft shadow. */
.tf-fp, .tf-tile, .tf-check, .tf-rule, .tf-entry, .tf-empty, [data-testid="stExpander"] {{
  background: linear-gradient(180deg, rgba(255, 255, 255, .045), rgba(255, 255, 255, 0) 46%), {CARD};
  border-color: rgba(245, 238, 241, .09);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .06), 0 28px 48px -36px rgba(0, 0, 0, .95); }}
.tf-tile {{ position: relative; overflow: hidden; }}
.tf-tile::before {{ content: ""; position: absolute; top: 0; left: 18px; width: 30px; height: 2px; background: {ROSE};
  box-shadow: 0 0 12px {ROSE}; }}
.tf-fp-cols {{ background-image: linear-gradient(rgba(245, 238, 241, .06) 1px, transparent 1px); background-size: 100% 25%; }}
.tf-fp-bar {{ box-shadow: 0 -6px 26px -6px rgba(194, 69, 111, .55), inset 0 1px 0 rgba(255, 255, 255, .28); }}
.tf-funnel .bar span, .tf-hold .bar span {{ background: linear-gradient(90deg, {ROSE}, {BLUSH}); box-shadow: 0 0 12px rgba(194, 69, 111, .6); }}
.tf-hold .row {{ transition: background-color 160ms ease; border-radius: 10px; }}
.tf-hold .row:hover {{ background: rgba(255, 255, 255, .03); }}
.tf-big {{ filter: drop-shadow(0 0 30px rgba(194, 69, 111, .25)); }}

/* Controls. */
[data-testid="stBaseButton-primary"], .stButton button[kind="primary"] {{
  background: linear-gradient(180deg, #D65A84, {ROSE}); border: 0;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .28), 0 10px 26px -10px rgba(194, 69, 111, .85);
  transition: transform 120ms ease, box-shadow 120ms ease; }}
[data-testid="stBaseButton-primary"]:hover, .stButton button[kind="primary"]:hover {{
  background: linear-gradient(180deg, #DE6990, #C74B76); transform: translateY(-1px);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .32), 0 14px 30px -10px rgba(194, 69, 111, .95); }}
[data-testid="stTabs"] [role="tablist"] {{ gap: 30px; }}
[data-testid="stTabs"] [role="tablist"] [role="tab"] p {{ font-family: {DISPLAY}; font-weight: 700; font-size: 21px;
  letter-spacing: .05em; text-transform: uppercase; }}
/* Want / Skip / Avoid: all three labels fit without being cut off. */
.stApp [data-testid="stButtonGroup"] {{ flex-wrap: nowrap; }}
.stApp [data-testid="stButtonGroup"] button {{ padding-left: 11px; padding-right: 11px; min-width: 0; }}
.stApp [data-testid="stButtonGroup"] button p {{ font-size: 14px; }}
</style>
"""


THEME_SHORT = {  # short chip labels, by theme key and by display name
    "ai": "AI", "oil": "Oil", "cyber": "Cyber", "clean_energy": "Clean energy", "gold": "Gold",
    "healthcare": "Health", "bank_lending": "Banks", "consumer_disc": "Consumer", "defense": "Aero & defense",
    "metals": "Metals",
    "AI": "AI", "Oil": "Oil", "Cybersecurity": "Cyber", "Clean energy (solar & renewables)": "Clean energy",
    "Gold & precious metals": "Gold", "Healthcare": "Health", "Bank lending / net interest income": "Banks",
    "Consumer discretionary": "Consumer", "Aerospace & defense": "Aero & defense",
    "Industrial / EV metals (copper + lithium)": "Metals",
}


def short_theme(theme: str) -> str:
    """A theme key or display name -> its short chip label (unknown names pass through)."""
    return THEME_SHORT.get(theme, theme)


def theme_chip(theme: str, tier: str) -> str:
    """'Clean energy · High', colored by tier."""
    return chip(f"{short_theme(theme)} · {tier}", tier)


def chip(text: str, kind: str) -> str:
    """A small rounded label. kind: want, avoid, or a tier name."""
    if kind == "want":
        bg, fg = ROSE_SOFT, BLUSH_TEXT
    elif kind == "avoid":
        bg, fg = CHAMPAGNE_SOFT, CHAMPAGNE
    else:
        bg, fg = TIER_STYLE.get(kind, TIER_STYLE["Not screened"])
    return f'<span class="tf-chip" style="background:{bg};color:{fg}">{escape(text)}</span>'


RADAR_LABEL = {"ai": "AI", "bank_lending": "Banks", "clean_energy": "Clean", "consumer_disc": "Consumer",
               "cyber": "Cyber", "defense": "Defense", "gold": "Gold", "healthcare": "Health", "metals": "Metals",
               "oil": "Oil"}


def _radar(counts: dict[str, int]) -> str:
    """A radar chart of real numbers: how many scored stocks are High or Moderate on each theme.

    Drawn with plain HTML and CSS (rings, spokes, a clip-path shape), because Streamlit strips inline SVG."""
    import math

    keys = [k for k in RADAR_LABEL if k in counts] or list(counts)
    if len(keys) < 3:
        return ""
    top = max(counts[k] for k in keys) or 1
    reach = 27.0  # radius of the outer ring, as a % of the box

    def at(i: int, r: float) -> tuple[float, float]:
        a = -math.pi / 2 + 2 * math.pi * i / len(keys)
        return 50 + r * math.cos(a), 50 + r * math.sin(a)

    rings = "".join(f'<i class="ring" style="--r:{reach * f:.2f}%"></i>' for f in (0.25, 0.5, 0.75, 1))
    spokes, labels, dots, pts = [], [], [], []
    for i, k in enumerate(keys):
        spokes.append(f'<i class="spoke" style="--a:{360 * i / len(keys):.1f}deg;--r:{reach}%"></i>')
        px, py = at(i, reach * (0.14 + 0.86 * counts[k] / top))
        pts.append(f"{px:.2f}% {py:.2f}%")
        dots.append(f'<i class="dot" style="left:{px:.2f}%;top:{py:.2f}%"></i>')
        lx, ly = at(i, reach + 5)
        side = "mid" if abs(lx - 50) < 4 else ("right" if lx > 50 else "left")
        labels.append(f'<span class="lbl {side}" style="left:{lx:.2f}%;top:{ly:.2f}%">'
                      f'{escape(RADAR_LABEL.get(k, k))}<b>{counts[k]}</b></span>')
    shape = f'<i class="glow"><i class="shape" style="clip-path:polygon({", ".join(pts)})"></i></i>'
    return (f'<figure class="tf-radar"><div class="plot" role="img" '
            f'aria-label="Number of scored stocks rated High or Moderate on each theme">'
            f'<i class="sweep" style="--r:{reach}%"></i><i class="ticks" style="--r:{reach + 2.6}%"></i>{rings}{"".join(spokes)}'
            f'{shape}{"".join(dots)}{"".join(labels)}</div>'
            f'<figcaption>Stocks rated High or Moderate, by theme</figcaption></figure>')


def hero(active_step: int = 0, tape: list[tuple[str, str, str]] | None = None,
         radar: dict[str, int] | None = None, scored: int = 666) -> str:
    """The page title inside a framed panel: drifting rose glow, corner brackets, a radar of how many stocks carry
    each theme, and a ticker tape of the reference companies. `tape` is (ticker, theme, fact) and `radar` is
    {theme key: stocks rated High or Moderate}; both come from the engine and are optional. active_step is kept
    for older callers."""
    stats = "".join(f'<div><b>{escape(str(n))}</b><span>{escape(label)}</span></div>' for n, label in (
        (scored, "stocks scored"), (len(radar) if radar else 10, "themes"), (0, "rule changes after launch")))
    corners = '<i class="c tl"></i><i class="c tr"></i><i class="c bl"></i><i class="c br"></i>'
    run = ""
    if tape:
        items = "".join(f'<span><b>{escape(t)}</b>{escape(theme)}<em>{escape(fact)}</em></span>' for t, theme, fact in tape)
        run = f'<div class="tf-tape" aria-hidden="true"><div class="run">{items}{items}</div></div>'
    return (f'<div class="tf-hero"><div class="tf-hero-grid">{corners}<div class="copy">'
            '<div class="eyebrow"><i class="live"></i>Built on Monad testnet</div><h1>Theme Funds</h1>'
            '<p>Invest in what you believe in. Tell us the themes you want and the ones to avoid. We pick '
            'stocks by what they actually move with, not their labels, then lock your rules on Monad.</p>'
            f'<div class="stats">{stats}</div></div>{_radar(radar) if radar else ""}</div>{run}</div>')


def step(n: int, title: str, sentence: str) -> str:
    """A section heading. n is kept for older callers but no longer shown."""
    return f'<div class="tf-step"><h2>{escape(title)}</h2><p>{escape(sentence)}</p></div>'


def fingerprint(columns: list[dict]) -> str:
    """The fund's exposure to every theme as one row of columns.

    columns: [{"name", "pct" (0-100), "role": "want" | "avoid" | "none"}] in display order.
    """
    n = len(columns)
    cols, names = [], []
    for i, c in enumerate(columns):
        pct = max(0.0, min(100.0, float(c["pct"])))
        if c["role"] == "want":
            fill, val_color = ROSE, BLUSH
        elif c["role"] == "avoid":
            fill, val_color = (LOSS if pct > 0 else CHAMPAGNE), CHAMPAGNE
        else:
            fill, val_color = NEUTRAL_BAR, MUTED
        cols.append(f'<div class="tf-fp-col"><div class="tf-fp-val" style="color:{val_color}">{pct:.0f}%</div>'
                    f'<div class="tf-fp-bar" style="height:{max(pct, 1.2):.1f}%;background:{fill};'
                    f'--d:{i * 60}ms"></div></div>')
        role = {"want": "Want", "avoid": "Avoid"}.get(c["role"], "")
        names.append(f'<div><b>{escape(c["name"])}</b>{role}</div>')
    legend = (f'<div class="tf-fp-legend"><span><i style="background:{ROSE}"></i>A theme you want</span>'
              f'<span><i style="background:{CHAMPAGNE}"></i>A theme you avoid (should stay near 0%)</span>'
              f'<span><i style="background:{NEUTRAL_BAR}"></i>Not part of your choices</span></div>')
    return (f'<div class="tf-fp" role="img" aria-label="Share of the fund in High or Moderate stocks for each theme">'
            f'<div class="tf-fp-cols" style="--n:{n}">{"".join(cols)}</div>'
            f'<div class="tf-fp-names" style="--n:{n}">{"".join(names)}</div>{legend}</div>')


def funnel(steps: list[dict]) -> str:
    """steps: [{"step": text, "left": count}] from the builder."""
    if not steps:
        return ""
    top = max(1, steps[0]["left"])
    rows = []
    for s in steps:
        w = 100 * s["left"] / top
        rows.append(f'<div class="row"><div><div class="lbl">{escape(s["step"])}</div>'
                    f'<div class="bar"><span style="width:{max(w, 1.5):.1f}%"></span></div></div>'
                    f'<div class="num">{s["left"]:,}</div></div>')
    return f'<div class="tf-funnel">{"".join(rows)}</div>'


def holdings(rows: list[dict], decimals: int = 1) -> str:
    """rows: [{"ticker", "name", "industry", "weight", "chips": [html], "why" (optional one line)}]
    Each row: TICKER | company (one line) over industry + theme chips | weight, then a full-width weight bar
    (relative to the largest holding). Used for "Your N stocks" and the League entry card."""
    top = max([r["weight"] for r in rows] or [1]) or 1
    out = []
    for i, r in enumerate(rows):
        name = r.get("name") or ""
        why = f'<div class="tf-r-why">{escape(r["why"])}</div>' if r.get("why") else ""
        out.append(f'<div class="tf-r"><span class="tf-r-tk">{escape(r["ticker"])}</span>'
                   f'<div class="tf-r-main"><div class="tf-r-co" title="{escape(name)}">{escape(name)}</div>'
                   f'<div class="tf-r-meta"><span class="tf-r-ind">{escape(r.get("industry") or "")}</span>'
                   f'{"".join(r.get("chips", []))}</div></div>'
                   f'<span class="tf-r-w">{r["weight"]:.{decimals}f}%</span>{why}'
                   f'<div class="bar"><span style="width:{100 * r["weight"] / top:.0f}%;animation-delay:{i * 30}ms">'
                   f'</span></div></div>')
    return f'<div class="tf-rows">{"".join(out)}</div>'


_NUM = re.compile(r"^([−+-]?)(\d+)(?:\.(\d{1,2}))?(%?)$")


def count_up(value: str) -> str:
    """A number that counts up from 0 when it first appears (CSS only; st.html runs no scripts). Text that
    isn't a plain number (e.g. "no loss") is shown as is."""
    m = _NUM.match(value)
    if not m:
        return escape(value)
    sign, whole, frac, pct = m.groups()
    if frac is None:
        return f'<span class="tf-count" style="--a:{int(whole)};--b:0">{sign}<span class="i"></span>{pct}</span>'
    style = "--fs:decimal-leading-zero" if len(frac) == 2 else ""
    return (f'<span class="tf-count" style="--a:{int(whole)};--b:{int(frac)};{style}">{sign}<span class="i"></span>.'
            f'<span class="f"></span>{pct}</span>')


def _sign_color(value: str) -> str:
    """A signed value is a return: mint when it starts with +, coral when it starts with a minus. Anything else
    (a probability, "no loss") keeps the normal text color."""
    v = value.strip()
    return GAIN if v.startswith("+") else LOSS if v.startswith(("−", "-")) else TEXT


def tiles(items: list[tuple[str, str, str]]) -> str:
    """items: [(label, value, comparison line)]. Values count up on first render; tiles rise in one by one."""
    cells = "".join(f'<div class="tf-tile" style="--d:{i * 60}ms"><div class="k">{escape(k)}</div>'
                    f'<div class="v" style="color:{_sign_color(v)}" aria-label="{escape(v)}">{count_up(v)}</div>'
                    f'<div class="b">{escape(b)}</div></div>' for i, (k, v, b) in enumerate(items))
    return f'<div class="tf-tiles">{cells}</div>'


def checks(items: list[tuple[bool, str]]) -> str:
    rows = []
    for ok, text in items:
        bg, fg, mark = ("#13261E", GAIN, "✓") if ok else ("#2B1513", LOSS, "!")
        rows.append(f'<div class="tf-check"><span class="ic" style="background:{bg};color:{fg}" '
                    f'aria-label="{"passes" if ok else "does not pass"}">{mark}</span><span>{text}</span></div>')
    return f'<div class="tf-checks">{"".join(rows)}</div>'


def rules(items: list[tuple[str, str]]) -> str:
    """items: [(kind want/avoid, plain-English rule)]"""
    rows = "".join(f'<div class="tf-rule">{chip("Want" if k == "want" else "Avoid", k)}<span>{escape(t)}</span></div>'
                   for k, t in items)
    return f'<div class="tf-rules">{rows}</div>'


def banner(text: str, good: bool, small: str = "") -> str:
    extra = f"<small>{escape(small)}</small>" if small else ""
    return f'<div class="tf-banner {"good" if good else "bad"}">{escape(text)}{extra}</div>'


def big_number(value: float, suffix: str = "%") -> str:
    color = GAIN if value > 0 else LOSS if value < 0 else TEXT
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f'<div class="tf-big" style="color:{color}">{sign}{abs(value):.1f}{suffix}</div>'


# ---------------------------------------------------------------------------------------------
# Plotly
# ---------------------------------------------------------------------------------------------

HEATMAP_COLORS = {  # tier -> cell color for the dark heatmap (same order as engine.dashboard.TIER_ORDER)
    "High": ROSE, "Moderate": "#5E2840", "Limited": "#173A2D", "Limited (lower confidence)": "#182A22",
    "Not determined": "#3A3020", "Not screened": "#1E191B",
}


def recolor_heatmap(fig, tier_order: list[str]):
    """Swap app.py's light heatmap colors for dark-theme ones. Same tiers, same cells; only colors change."""
    n = len(tier_order)
    scale = []
    for i, tier in enumerate(tier_order):
        color = HEATMAP_COLORS.get(tier, "#1E191B")
        scale += [[i / n, color], [(i + 1) / n, color]]
    fig.update_traces(colorscale=scale, textfont={"color": TEXT, "size": 13}, xgap=3, ygap=3)
    return plotly_dark(fig, height=fig.layout.height)


COLORWAY = [BLUSH, CHAMPAGNE, ROSE, GAIN, MUTED, "#E07A9B", "#D9B37A", LOSS]


def plotly_dark(fig, height: int | None = None):
    """Restyle any Plotly figure to match the page: palette colors, no gridline clutter, short eased transitions,
    clean hover labels."""
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": SANS, "color": TEXT, "size": 14}, colorway=COLORWAY,
        margin={"t": 30, "l": 10, "r": 10, "b": 10},
        hoverlabel={"bgcolor": CARD, "bordercolor": LINE, "font": {"family": SANS, "color": TEXT, "size": 13}},
        legend={"bgcolor": "rgba(0,0,0,0)", "font": {"color": MUTED}},
        transition={"duration": 300, "easing": "cubic-in-out"},
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=LINE, tickfont={"color": MUTED})
    fig.update_yaxes(showgrid=True, gridcolor="rgba(46, 37, 41, .5)", zeroline=False, linecolor=LINE,
                     tickfont={"color": MUTED})
    if height:
        fig.update_layout(height=height)
    return fig


# ---------------------------------------------------------------------------------------------
# Fantasy Fund League tab
# ---------------------------------------------------------------------------------------------

def empty_state(text: str, title: str = "Nothing here yet") -> str:
    return f'<div class="tf-empty"><b>{escape(title)}</b>{escape(text)}</div>'


def league_entry(name: str, rows: list[dict], note: str = "", label: str = "Your League entry") -> str:
    """The fund as it will be entered in the League: full name (wraps, never cut) over a compact holdings table.
    rows: same as holdings() (ticker, name, industry, weight, chips)."""
    extra = f'<div class="note">{escape(note)}</div>' if note else ""
    return (f'<div class="tf-entry"><div class="k">{escape(label)}</div>'
            f'<div class="tf-entry-name">{escape(name)}</div>{holdings(rows, decimals=0)}{extra}</div>')


def weekly_intro(subtitle: str, facts: list[tuple[str, str]]) -> str:
    """The League tab's heading: this week's matchup. facts: [(bold part, rest)] shown as small pills."""
    pills = "".join(f"<span><b>{escape(b)}</b> · {escape(r)}</span>" for b, r in facts)
    return ('<div class="tf-intro"><h2>This week\'s matchup</h2>'
            f'<p>{escape(subtitle)}</p><div class="modes">{pills}</div></div>')
