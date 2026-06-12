"""
Typed indicator adapter catalog for the iTrader strategy engine (IND-01, D-04/D-07/D-08).

This module is the typed-symbol catalog the declared-indicator framework reads
through (the ``core/sizing.py`` singleton-instance + union-alias analog, and the
``fee_model/`` pluggable-typed-model analog):

- **D-04 — typed adapter symbols (no string lookup).** ``SMA`` / ``MACDHist`` /
  ``EMA`` / ``RSI`` are real importable singleton instances (mypy-visible under
  ``--strict``), each exposing ``compute(...)`` (its exact ``ta`` call) and
  ``min_period(params)``. Growth means adding an adapter here, never a string
  branch in a handler.
- **D-07 — v1 catalog.** SMA + MACDHist (oracle-required) + EMA + RSI (additive,
  oracle-dark — their own unit tests are their only guard).
- **D-08 — first-valid-period ``min_period`` ONLY.** SMA/EMA/RSI -> ``window``;
  MACDHist -> ``slow + signal`` (==15 for 6/12/3). NO convergence buffer baked in
  (that would push the reference ``max_window`` off 100 and drift the golden oracle).
- **Pitfall 1 [BYTE-EXACT] — per-indicator input slice.** ``_SMA.compute`` slices
  ``bars[start_dt:][input_col]`` with ``start_dt = now - timeframe * window`` and
  ``fillna=True`` (the 3rd positional arg). A uniform full-window SMA drifts the
  short SMA by 1 ULP and breaks the oracle. ``_MACDHist.compute`` uses the FULL
  ``bars[input_col]`` with ``fillna=False`` (NO slice). Do NOT "tidy" either into
  a uniform window — copy the exact ``SMA_MACD_strategy.py`` (lines 59-76) shape.

Indicator values are pandas ``float64`` (the ``ta`` compute domain), NOT money —
they are look-ahead-safe series the primitives compare, never routed through
``to_money``.
"""

from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

import pandas as pd
from ta import momentum, trend

__all__ = [
	"EMA",
	"MACDHist",
	"RSI",
	"SMA",
	"IndicatorAdapter",
]


@runtime_checkable
class IndicatorAdapter(Protocol):
	"""The stateless adapter surface the handle wraps and types against (D-04)."""

	def compute(
		self,
		bars: pd.DataFrame,
		input_col: str,
		params: tuple[int, ...],
		now: datetime,
		timeframe: timedelta,
	) -> "pd.Series": ...

	def min_period(self, params: tuple[int, ...]) -> int: ...


class _SMA:
	"""Simple moving average over a SLICED input window (Pitfall 1 — byte-exact)."""

	def compute(
		self,
		bars: pd.DataFrame,
		input_col: str,
		params: tuple[int, ...],
		now: datetime,
		timeframe: timedelta,
	) -> "pd.Series":
		(window,) = params
		# [BYTE-EXACT] sliced input (Pitfall 1): start_dt = now - timeframe*window,
		# fillna=True (3rd positional). Reproduces SMA_MACD_strategy.py lines 61-65.
		start_dt = now - timeframe * window
		return (
			trend.SMAIndicator(bars[start_dt:][input_col], window, True)
			.sma_indicator()
			.dropna()
		)

	def min_period(self, params: tuple[int, ...]) -> int:
		(window,) = params
		return window


class _MACDHist:
	"""MACD histogram over the FULL window (NO slice — byte-exact)."""

	def compute(
		self,
		bars: pd.DataFrame,
		input_col: str,
		params: tuple[int, ...],
		now: datetime,
		timeframe: timedelta,
	) -> "pd.Series":
		fast, slow, signal = params
		# [BYTE-EXACT] FULL window, NO slice, fillna=False. Reproduces
		# SMA_MACD_strategy.py lines 75-76.
		return (
			trend.MACD(
				bars[input_col],
				window_fast=fast,
				window_slow=slow,
				window_sign=signal,
				fillna=False,
			)
			.macd_diff()
			.dropna()
		)

	def min_period(self, params: tuple[int, ...]) -> int:
		# D-08: first-valid is slow + signal (==15 for 6/12/3); NO buffer.
		_fast, slow, signal = params
		return slow + signal


class _EMA:
	"""Exponential moving average (additive, oracle-dark, D-07)."""

	def compute(
		self,
		bars: pd.DataFrame,
		input_col: str,
		params: tuple[int, ...],
		now: datetime,
		timeframe: timedelta,
	) -> "pd.Series":
		(window,) = params
		return (
			trend.EMAIndicator(bars[input_col], window, fillna=False)
			.ema_indicator()
			.dropna()
		)

	def min_period(self, params: tuple[int, ...]) -> int:
		(window,) = params
		return window


class _RSI:
	"""Relative strength index (additive, oracle-dark, D-07)."""

	def compute(
		self,
		bars: pd.DataFrame,
		input_col: str,
		params: tuple[int, ...],
		now: datetime,
		timeframe: timedelta,
	) -> "pd.Series":
		(window,) = params
		return (
			momentum.RSIIndicator(bars[input_col], window, fillna=False)
			.rsi()
			.dropna()
		)

	def min_period(self, params: tuple[int, ...]) -> int:
		(window,) = params
		return window


# D-04: real importable singleton instances (RESEARCH Pattern 2 — cleaner under
# --strict than instantiated classes; the adapters are stateless).
SMA: IndicatorAdapter = _SMA()
MACDHist: IndicatorAdapter = _MACDHist()
EMA: IndicatorAdapter = _EMA()
RSI: IndicatorAdapter = _RSI()
