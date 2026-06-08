"""Optional presentation module — the minimal plotly figure set (M5-07, D-19).

Presentation ONLY, split from computation (D-14): every figure consumes the SAME
run-artifact frames as ``itrader.reporting.metrics`` — the equity ``pd.Series``
(or a drawdown series derived from it) and the closed-trades ``pd.DataFrame``
(``build_trade_log`` shape: ``exit_date`` + ``realised_pnl`` columns) — never
portfolio/handler objects.

Kept set (D-19): equity curve, drawdown, trade P/L scatter, and the 3-row
composition. Verified plotly-6 idioms throughout: ``title=dict(text=...,
font=dict(size=...))`` (``titlefont_size`` raises a hard ``ValueError`` on
plotly 6.8.0) and ``add_trace(..., row=, col=)`` (``append_trace`` deprecated).
Smoke-tested in ``tests/unit/reporting/test_plots_smoke.py``.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

CHART_THEME = 'plotly_dark'  # others include seaborn, ggplot2, plotly_dark, plotly_white


def line_equity(equity: pd.Series) -> go.Figure:
	"""
	Line chart of the equity curve (the run-artifact ``total_equity`` series).
	"""
	chart = go.Figure()
	chart.add_trace(go.Scatter(x=equity.index, y=equity,
						mode='lines',
						name='Equity',
						line=dict(color='green')))
	chart.update_layout(template=CHART_THEME,
						margin=dict(t=50, b=50, l=25, r=25),
						height=500,
						plot_bgcolor='rgba(0, 0, 0, 0)',
						paper_bgcolor='rgba(0, 0, 0, 0)')
	chart.update_layout(
						xaxis=dict(tickfont=dict(size=12)),
						yaxis=dict(
							title=dict(text='Equity [$]', font=dict(size=14)),
							tickfont=dict(size=12),
							))
	chart.update_layout(showlegend=True)
	return chart


def line_drwdwn(drawdown: pd.Series) -> go.Figure:
	"""
	Line chart of the drawdown series (``equity / equity.cummax() - 1``, <= 0).
	"""
	chart = go.Figure()
	chart.add_trace(go.Scatter(x=drawdown.index, y=drawdown,
						mode='lines',
						name='DrawDown',
						line=dict(color='red'),
						fill='tozeroy'))
	chart.layout.template = CHART_THEME
	chart.layout.height = 300
	chart.update_layout(margin=dict(t=50, b=50, l=25, r=25))
	chart.update_layout(
		xaxis=dict(tickfont=dict(size=12)),
		yaxis=dict(
			title=dict(text='[%]', font=dict(size=14)),
			tickfont=dict(size=12),
			))
	chart.update_layout(showlegend=False)
	return chart


def profit_loss_scatter(trades: pd.DataFrame) -> go.Figure:
	"""
	Scatter of per-trade realised P/L at exit date (``build_trade_log`` frame:
	``exit_date`` + ``realised_pnl`` columns).
	"""
	profit = trades[trades['realised_pnl'] > 0]
	loss = trades[trades['realised_pnl'] <= 0]

	chart = go.Figure()
	chart.add_trace(go.Scatter(x=profit['exit_date'], y=profit['realised_pnl'],
						mode='markers',
						name='profit',
						marker=dict(size=8, color='green', symbol='triangle-up')))
	chart.add_trace(go.Scatter(x=loss['exit_date'], y=loss['realised_pnl'],
						mode='markers',
						name='loss',
						marker=dict(size=8, color='red', symbol='triangle-down')))
	chart.layout.template = CHART_THEME
	chart.layout.height = 300
	chart.update_layout(margin=dict(t=50, b=50, l=25, r=25))
	chart.update_layout(
		xaxis=dict(tickfont=dict(size=12), showgrid=False),
		yaxis=dict(
			title=dict(text='Profit / Loss [$]', font=dict(size=14)),
			tickfont=dict(size=12),
			))
	chart.update_layout(showlegend=False)
	return chart


def sub_plots3(plt_1: go.Figure, plt_2: go.Figure, plt_3: go.Figure) -> go.Figure:
	"""
	Compose equity / drawdown / trade P/L into one 3-row figure.
	"""
	chart = make_subplots(rows=3, cols=1,
						  subplot_titles=('Equity Line', 'Drawdown', 'Profit / Loss'),
						  row_heights=[0.6, 0.2, 0.2],
						  shared_xaxes=True,
						  vertical_spacing=0.05)

	chart.add_trace(plt_1['data'][0], row=1, col=1)
	chart.add_trace(plt_2['data'][0], row=2, col=1)
	for trace in plt_3['data']:
		chart.add_trace(trace, row=3, col=1)

	chart.update_yaxes(row=2, col=1, autorange='reversed')
	chart.update_layout(template=CHART_THEME,
						margin=dict(t=50, b=50, l=25, r=25),
						height=1000,
						plot_bgcolor='rgba(0, 0, 0, 0)',
						paper_bgcolor='rgba(0, 0, 0, 0)')
	return chart
