"""Smoke tests for ``itrader.reporting.plots`` (M5-09 / TC4, D-19).

D-19 smoke discipline: each kept figure function, fed a small synthetic frame in
the SAME shape the metric functions consume (equity ``pd.Series``, trades
``pd.DataFrame``), must return a ``plotly.graph_objects.Figure`` without raising
under the suite's ``filterwarnings=["error"]`` regime. This proves the plotly-6
breakage is fixed (``titlefont_size`` raised a hard ``ValueError`` on 6.8.0 the
moment any figure built).

The ``unit`` marker is folder-derived (tests/unit/) — not hand-added here.
"""

import pandas as pd
import plotly.graph_objects as go
import pytest

from itrader.reporting.plots import (
    line_drwdwn,
    line_equity,
    profit_loss_scatter,
    sub_plots3,
)

# PURPOSE-axis marker (hand-applied); adds to the folder-derived `unit` TYPE mark.
pytestmark = pytest.mark.smoke

_INDEX = pd.date_range("2020-01-01", periods=4, freq="D")

# Equity in the run-artifact shape (total_equity series indexed by timestamp).
EQUITY = pd.Series([100.0, 110.0, 99.0, 121.0], index=_INDEX)

# Drawdown series as the metrics module derives it (<= 0 by construction).
DRAWDOWN = EQUITY / EQUITY.cummax() - 1.0

# Trades frame in the build_trade_log shape (the columns the scatter consumes).
TRADES = pd.DataFrame(
    {
        "entry_date": _INDEX[:3],
        "exit_date": _INDEX[1:],
        "side": ["LONG", "LONG", "SHORT"],
        "realised_pnl": [10.0, -5.0, 20.0],
    }
)


def test_line_equity_builds_figure():
    fig = line_equity(EQUITY)
    assert isinstance(fig, go.Figure)


def test_line_drwdwn_builds_figure():
    fig = line_drwdwn(DRAWDOWN)
    assert isinstance(fig, go.Figure)


def test_profit_loss_scatter_builds_figure():
    fig = profit_loss_scatter(TRADES)
    assert isinstance(fig, go.Figure)


def test_profit_loss_scatter_handles_empty_trades():
    empty = TRADES.iloc[0:0]
    fig = profit_loss_scatter(empty)
    assert isinstance(fig, go.Figure)


def test_sub_plots3_composes_kept_figures():
    fig = sub_plots3(line_equity(EQUITY), line_drwdwn(DRAWDOWN), profit_loss_scatter(TRADES))
    assert isinstance(fig, go.Figure)
