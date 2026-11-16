"""Draws the risk/return chart and the summary table underneath it.

The chart shows:
- the efficient frontier (best return for each level of risk),
- the capital market line (mixing the tangency portfolio with the risk-free asset),
- the minimum-variance, tangency and user portfolios,
- each individual stock, for context.

Hovering over any point shows its return, risk, Sharpe ratio and weights.
"""

import math

import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Headroom around the plotted points, so markers are not cut off at the edges.
AXIS_PADDING = 1.15
COLORS = {
    "frontier": "#2563eb",
    "cml": "#6b7280",
    "min_variance": "#16a34a",
    "tangency": "#d97706",
    "portfolio": "#dc2626",
    "stocks": "#9ca3af",
}


def _pct(value):
    return "n/a" if value is None or math.isnan(value) else f"{value:.2%}"


def _ratio(value):
    return "n/a" if value is None or math.isnan(value) else f"{value:.2f}"


def _weights_text(weights):
    """'AAPL 40.0%<br>MSFT 60.0%', skipping zero weights."""
    parts = [f"{t} {w:.1%}" for t, w in weights.items() if w > 0]
    return "<br>".join(parts)


def _point(fig, name, row, color, symbol, size):
    fig.add_trace(
        go.Scatter(
            x=[row["volatility"]],
            y=[row["return"]],
            mode="markers",
            name=name,
            marker={"color": color, "symbol": symbol, "size": size,
                    "line": {"color": "white", "width": 1}},
            hovertemplate=(
                f"<b>{name}</b><br>Return: {_pct(row['return'])}"
                f"<br>Risk: {_pct(row['volatility'])}"
                f"<br>Sharpe: {_ratio(row['sharpe'])}"
                f"<br><br>{_weights_text(row['weights'])}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )


def build_chart(summary, frontier, stocks, risk_free_rate, notes=None):
    """Build the chart.

    summary:  table of marked portfolios. Columns: return, volatility, sharpe,
              weights (a Series). Index: portfolio names.
    frontier: table from optimizer.efficient_frontier.
    stocks:   table with return and volatility for each individual stock.
    notes:    optional list of lines shown under the title (e.g. data windows).
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.08,
        specs=[[{"type": "xy"}], [{"type": "table"}]],
    )

    fig.add_trace(
        go.Scatter(
            x=frontier["volatility"],
            y=frontier["return"],
            mode="lines",
            name="Efficient frontier",
            line={"color": COLORS["frontier"], "width": 3},
            hovertemplate="Frontier<br>Return: %{y:.2%}<br>Risk: %{x:.2%}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # Axis ranges come from the actual points, so a steep capital market line
    # cannot stretch the chart. The line simply runs off the top edge.
    max_x = max(frontier["volatility"].max(), stocks["volatility"].max(),
                summary["volatility"].max()) * AXIS_PADDING
    all_returns = [frontier["return"], stocks["return"], summary["return"]]
    top = max(max(r.max() for r in all_returns), risk_free_rate)
    bottom = min(min(r.min() for r in all_returns), risk_free_rate, 0.0)
    span = top - bottom
    y_range = [bottom - 0.05 * span, top + (AXIS_PADDING - 1) * span]

    has_tangency = "Tangency portfolio" in summary.index
    if has_tangency:
        slope = summary.loc["Tangency portfolio", "sharpe"]
        fig.add_trace(
            go.Scatter(
                x=[0.0, max_x],
                y=[risk_free_rate, risk_free_rate + slope * max_x],
                mode="lines",
                name="Capital market line",
                line={"color": COLORS["cml"], "width": 2, "dash": "dash"},
                hovertemplate="Capital market line<br>Return: %{y:.2%}"
                "<br>Risk: %{x:.2%}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=stocks["volatility"],
            y=stocks["return"],
            mode="markers+text",
            name="Individual stocks",
            text=list(stocks.index),
            textposition="top center",
            marker={"color": COLORS["stocks"], "size": 8},
            hovertemplate="<b>%{text}</b><br>Return: %{y:.2%}<br>Risk: %{x:.2%}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    styles = {
        "Minimum-variance portfolio": (COLORS["min_variance"], "diamond", 14),
        "Tangency portfolio": (COLORS["tangency"], "star", 18),
        "Your portfolio": (COLORS["portfolio"], "circle", 15),
    }
    for name, row in summary.iterrows():
        color, symbol, size = styles.get(name, (COLORS["portfolio"], "circle", 12))
        _point(fig, name, row, color, symbol, size)

    fig.add_trace(
        go.Table(
            header={"values": ["Portfolio", "Expected return", "Risk (volatility)",
                               "Sharpe ratio"],
                    "fill_color": "#e5e7eb", "align": "left", "height": 30},
            cells={
                "values": [
                    list(summary.index),
                    [_pct(v) for v in summary["return"]],
                    [_pct(v) for v in summary["volatility"]],
                    [_ratio(v) for v in summary["sharpe"]],
                ],
                "align": "left",
                "height": 28,
            },
        ),
        row=2,
        col=1,
    )

    subtitle = [f"Risk-free rate (10-year Treasury): {risk_free_rate:.2%}"]
    if not has_tangency:
        subtitle.append(
            "No stock beat the risk-free rate, so there is no tangency portfolio "
            "or capital market line."
        )
    subtitle.extend(notes or [])

    fig.update_layout(
        title={"text": "Mean-variance analysis<br><sup>" + "<br>".join(subtitle) + "</sup>"},
        template="plotly_white",
        height=800,
        margin={"t": 100 + 15 * len(subtitle), "b": 10},
        legend={"x": 0.01, "y": 0.99, "bgcolor": "rgba(255,255,255,0.85)"},
    )
    fig.update_xaxes(title_text="Risk (annual volatility)", tickformat=".0%",
                     range=[0, max_x], row=1, col=1)
    fig.update_yaxes(title_text="Expected annual return", tickformat=".0%",
                     range=y_range, row=1, col=1)
    return fig
