"""P5-D17 ta-convergence test — all four stateful adapters vs the ta batch oracle.

The de-risking gate for the PERF-05 re-baseline (P5-D11/D12): feed the golden
``data/BTCUSD_1d_ohlcv_2018_2026.csv`` Close path one-by-one to each STATEFUL
adapter (Model B push contract, P5-D07) and assert convergence to ``ta``'s batch
output from each indicator's ``min_period`` onward at ``atol=1e-9, rtol=1e-6``,
comparing ONLY indices where BOTH the incremental and the ta series are non-NaN.

``ta`` is the test-time convergence oracle ONLY (it is DROPPED on the runtime path
P5-D11) — these are the measured margins from RESEARCH §Code Examples:
  SMA   max_abs 1.9e-10  (running-sum deque, P5-D05)
  EMA   max_abs 1.5e-11  (factored seed-from-first, alpha=2/(n+1), P5-D04)
  MACD  max_abs 1.7e-11  post-bar-100 (two factored EMAs + signal; the EMA
        transient bars 13-38 differ pre-warmup, RESEARCH Pitfall 4 — we assert
        from a settle offset, the golden firing region bar-100+ is fully converged)
  RSI   max_abs 2.84e-14 (factored-RMA alpha=1/n over close.diff(1), P5-D11/Pitfall 1)

TAB-indented (RESEARCH Pitfall 6 — tests/unit/strategy/** uses TABS).
"""

from pathlib import Path

import numpy as np
import pandas as pd
from ta import momentum, trend

from itrader.strategy_handler.indicators.catalog import (
	_EMAState,
	_MACDHistState,
	_RSIState,
	_SMAState,
)

# The committed golden dataset the run-path feed + the oracle consume (RESEARCH A1).
_DATA = Path(__file__).resolve().parents[3] / "data" / "BTCUSD_1d_ohlcv_2018_2026.csv"


def _golden_closes() -> np.ndarray:
	"""The 3076-bar BTCUSD Close path (float64)."""
	frame = pd.read_csv(_DATA)
	return frame["Close"].astype("float64").to_numpy()


def _feed(state, closes: np.ndarray) -> np.ndarray:
	"""Feed closes one-by-one; collect the running ``value`` (NaN before ready)."""
	out = np.full(len(closes), np.nan, dtype="float64")
	for i, close in enumerate(closes):
		state.update(float(close))
		if state.value is not None:
			out[i] = state.value
	return out


def _assert_converges(
	inc: np.ndarray,
	ta_series: pd.Series,
	min_period: int,
	*,
	atol: float = 1e-9,
	rtol: float = 1e-6,
) -> None:
	"""Assert inc converges to ta from ``min_period`` onward where BOTH are defined."""
	ta = ta_series.to_numpy()
	compared = 0
	for i in range(min_period, len(inc)):
		if np.isnan(ta[i]) or np.isnan(inc[i]):
			continue
		assert abs(ta[i] - inc[i]) <= atol + rtol * abs(ta[i]), (
			f"bar {i}: ta={ta[i]!r} inc={inc[i]!r} "
			f"abs_err={abs(ta[i] - inc[i]):.3e}"
		)
		compared += 1
	# Guard the test actually compared something post-warmup (not a vacuous pass).
	assert compared > 0, "no non-NaN overlap compared — convergence test was vacuous"


def test_sma_converges_to_ta():
	closes = _golden_closes()
	series = pd.Series(closes)
	for window in (50, 100):
		inc = _feed(_SMAState(window), closes)
		ta_series = series.rolling(window=window, min_periods=window).mean()
		_assert_converges(inc, ta_series, window)


def test_ema_converges_to_ta():
	closes = _golden_closes()
	series = pd.Series(closes)
	period = 20
	inc = _feed(_EMAState(period), closes)
	ta_series = trend.EMAIndicator(series, period, fillna=False).ema_indicator()
	_assert_converges(inc, ta_series, period)


def test_macdhist_converges_to_ta():
	closes = _golden_closes()
	series = pd.Series(closes)
	fast, slow, signal = 6, 12, 3
	inc = _feed(_MACDHistState(fast, slow, signal), closes)
	ta_series = trend.MACD(
		series,
		window_fast=fast,
		window_slow=slow,
		window_sign=signal,
		fillna=False,
	).macd_diff()
	# RESEARCH Pitfall 4: the EMA transient leaves residual >1e-6 out to ~bar 38 on
	# the golden data; post-bar-100 (the SMA_MACD firing region) is fully converged
	# at 1.7e-11. Assert from a documented settle offset past the slow-EMA transient
	# (the oracle reads macd_hist ONLY at bar 100+, where drift is 1.7e-11).
	settle = 2 * slow + signal  # 27 — clears the slow-span-12 EMA transient
	_assert_converges(inc, ta_series, settle)


def test_rsi_converges_to_ta():
	closes = _golden_closes()
	series = pd.Series(closes)
	window = 14
	inc = _feed(_RSIState(window), closes)
	# ta RSI: close.diff(1) gain/loss, ewm(alpha=1/n, adjust=False), single-value seed.
	diff = series.diff(1)
	up = diff.where(diff > 0, 0.0)
	dn = -diff.where(diff < 0, 0.0)
	emaup = up.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
	emadn = dn.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
	ta_series = np.where(emadn == 0, 100.0, 100.0 - 100.0 / (1.0 + emaup / emadn))
	ta_series = pd.Series(ta_series)
	# Mask the pre-min_periods region ta leaves NaN (min_periods=window).
	ta_series[emaup.isna()] = np.nan
	_assert_converges(inc, ta_series, window)
