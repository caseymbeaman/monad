"""Tests for the chart: right pieces present, labels readable, edge cases handled."""

import math

import pandas as pd

from engine.mean_variance import chart_builder as cb


def _inputs(with_tangency=True):
    rows = {
        "Your portfolio": (0.10, 0.18, 0.333, pd.Series({"A": 0.5, "B": 0.5})),
        "Minimum-variance portfolio": (0.08, 0.14, 0.286, pd.Series({"A": 0.8, "B": 0.2})),
    }
    if with_tangency:
        rows["Tangency portfolio"] = (0.11, 0.19, 0.368, pd.Series({"A": 0.4, "B": 0.6}))
    summary = pd.DataFrame(
        {name: {"return": r, "volatility": v, "sharpe": s} for name, (r, v, s, _) in
         rows.items()}).T.astype(float)
    summary["weights"] = pd.Series({name: w for name, (*_, w) in rows.items()}, dtype=object)
    frontier = pd.DataFrame({"return": [0.08, 0.10, 0.12], "volatility": [0.14, 0.16, 0.22]})
    stocks = pd.DataFrame({"return": [0.07, 0.12], "volatility": [0.15, 0.22]},
                          index=["A", "B"])
    return summary, frontier, stocks


def _names(fig):
    return [trace.name for trace in fig.data]


def test_all_required_elements_present():
    fig = cb.build_chart(*_inputs(), risk_free_rate=0.04, notes=["Data: test"])
    names = _names(fig)
    for required in ["Efficient frontier", "Capital market line", "Individual stocks",
                     "Your portfolio", "Minimum-variance portfolio", "Tangency portfolio"]:
        assert required in names
    title = fig.layout.title.text
    assert "4.00%" in title and "Data: test" in title


def test_capital_market_line_starts_at_risk_free_rate_and_passes_through_tangency():
    fig = cb.build_chart(*_inputs(), risk_free_rate=0.04)
    cml = next(t for t in fig.data if t.name == "Capital market line")
    assert cml.x[0] == 0.0 and cml.y[0] == 0.04
    slope = (cml.y[1] - cml.y[0]) / (cml.x[1] - cml.x[0])
    assert math.isclose(0.04 + slope * 0.19, 0.04 + 0.368 * 0.19)


def test_no_tangency_means_no_cml_and_an_explanation():
    summary, frontier, stocks = _inputs(with_tangency=False)
    fig = cb.build_chart(summary, frontier, stocks, risk_free_rate=0.20)
    assert "Capital market line" not in _names(fig)
    assert "no tangency portfolio" in fig.layout.title.text


def test_summary_table_values_formatted():
    fig = cb.build_chart(*_inputs(), risk_free_rate=0.04)
    table = next(t for t in fig.data if t.type == "table")
    columns = table.cells.values
    assert list(columns[0]) == ["Your portfolio", "Minimum-variance portfolio",
                                "Tangency portfolio"]
    assert columns[1][0] == "10.00%" and columns[3][0] == "0.33"


def test_axis_range_covers_every_point():
    fig = cb.build_chart(*_inputs(), risk_free_rate=0.04)
    low, high = fig.layout.yaxis.range
    assert low <= 0.0 and high >= 0.12
    assert fig.layout.xaxis.range[1] >= 0.22


def test_negative_returns_fit_on_chart():
    summary, frontier, stocks = _inputs()
    stocks.loc["A", "return"] = -0.30
    fig = cb.build_chart(summary, frontier, stocks, risk_free_rate=0.04)
    assert fig.layout.yaxis.range[0] < -0.30


def test_formatting_helpers():
    assert cb._pct(0.1234) == "12.34%"
    assert cb._pct(float("nan")) == "n/a"
    assert cb._pct(None) == "n/a"
    assert cb._ratio(1.234) == "1.23"
    assert cb._ratio(float("nan")) == "n/a"
    assert cb._weights_text(pd.Series({"A": 0.25, "B": 0.0, "C": 0.75})) == "A 25.0%<br>C 75.0%"


def test_unrecognized_portfolio_name_still_drawn():
    summary, frontier, stocks = _inputs()
    summary = summary.rename(index={"Your portfolio": "Proposed"})
    fig = cb.build_chart(summary, frontier, stocks, risk_free_rate=0.04)
    assert "Proposed" in _names(fig)
