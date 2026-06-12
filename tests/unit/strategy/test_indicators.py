"""Indicator adapter catalog + IndicatorHandle tests (Plan 03-01, D-03/D-04/D-07/D-08).

Covers:
- ``min_period`` first-valid formulas (D-08): SMA/EMA/RSI -> w, MACDHist -> slow+signal.
  For the reference params SMA(50)->50, SMA(100)->100, MACDHist(6,12,3)->15 => max == 100.
- EMA/RSI ``compute`` value-equality against a direct ``ta`` call (additive, D-07, oracle-dark).
- ``IndicatorHandle`` (D-03): ``__len__`` is 0 pre-repopulate; ``[-1]``/``[-2]`` return the
  Series tail floats post-repopulate; ``min_period()`` delegates to the wrapped adapter.

No SMA_MACD value test here — the oracle is the only MACD guard (RESEARCH Pitfall 2).
TAB-indented (D-05 / plan instruction).
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from ta import momentum, trend

from itrader.strategy_handler.indicators import (
	EMA,
	MACDHist,
	RSI,
	SMA,
	IndicatorHandle,
)


def _close_frame(n: int = 120) -> pd.DataFrame:
	"""Synthetic daily-UTC OHLC frame with a non-trivial close path."""
	start = datetime(2020, 1, 1, tzinfo=timezone.utc)
	idx = pd.DatetimeIndex([start + timedelta(days=i) for i in range(n)])
	close = pd.Series(
		[100.0 + (i % 7) - (i % 3) * 0.5 + i * 0.1 for i in range(n)],
		index=idx,
	)
	return pd.DataFrame({"close": close}, index=idx)


# --- min_period (D-08, first-valid only) -----------------------------------

def test_sma_min_period():
	assert SMA.min_period((50,)) == 50
	assert SMA.min_period((100,)) == 100


def test_ema_min_period():
	assert EMA.min_period((50,)) == 50


def test_rsi_min_period():
	assert RSI.min_period((14,)) == 14


def test_macdhist_min_period_is_slow_plus_signal():
	# D-08: MACDHist -> slow + signal (==15 for 6/12/3); NO convergence buffer
	assert MACDHist.min_period((6, 12, 3)) == 15


def test_reference_max_window_is_100():
	# Pitfall 3: max(50, 100, 15) must equal 100 (golden anchor)
	assert max(
		SMA.min_period((50,)),
		SMA.min_period((100,)),
		MACDHist.min_period((6, 12, 3)),
	) == 100


# --- EMA/RSI compute value-equality (additive, D-07, oracle-dark) ----------

def test_ema_compute_matches_direct_ta():
	frame = _close_frame()
	now = frame.index[-1]
	tf = timedelta(days=1)
	got = EMA.compute(frame, "close", (20,), now, tf)
	expected = trend.EMAIndicator(frame["close"], 20, fillna=False).ema_indicator().dropna()
	pd.testing.assert_series_equal(got, expected)


def test_rsi_compute_matches_direct_ta():
	frame = _close_frame()
	now = frame.index[-1]
	tf = timedelta(days=1)
	got = RSI.compute(frame, "close", (14,), now, tf)
	expected = momentum.RSIIndicator(frame["close"], 14, fillna=False).rsi().dropna()
	pd.testing.assert_series_equal(got, expected)


# --- SMA compute slice semantics (Pitfall 1) -------------------------------

def test_sma_compute_slices_input():
	frame = _close_frame()
	now = frame.index[-1]
	tf = timedelta(days=1)
	window = 50
	got = SMA.compute(frame, "close", (window,), now, tf)
	start_dt = now - tf * window
	expected = (
		trend.SMAIndicator(frame[start_dt:]["close"], window, True)
		.sma_indicator()
		.dropna()
	)
	pd.testing.assert_series_equal(got, expected)


def test_macdhist_compute_uses_full_window():
	frame = _close_frame()
	now = frame.index[-1]
	tf = timedelta(days=1)
	got = MACDHist.compute(frame, "close", (6, 12, 3), now, tf)
	expected = (
		trend.MACD(
			frame["close"],
			window_fast=6,
			window_slow=12,
			window_sign=3,
			fillna=False,
		)
		.macd_diff()
		.dropna()
	)
	pd.testing.assert_series_equal(got, expected)


# --- IndicatorHandle (D-03) ------------------------------------------------

def test_handle_len_zero_before_repopulate():
	handle = IndicatorHandle(SMA, "close", (50,))
	assert len(handle) == 0


def test_handle_min_period_delegates_to_adapter():
	handle = IndicatorHandle(SMA, "close", (50,))
	assert handle.min_period() == 50


def test_handle_repopulate_exposes_series_tail():
	frame = _close_frame()
	now = frame.index[-1]
	tf = timedelta(days=1)
	handle = IndicatorHandle(SMA, "close", (50,))
	handle.repopulate(frame, now, tf)

	series = SMA.compute(frame, "close", (50,), now, tf)
	assert len(handle) == len(series)
	assert handle[-1] == float(series.iloc[-1])
	assert handle[-2] == float(series.iloc[-2])
	assert isinstance(handle[-1], float)


def test_handle_repopulate_is_re_runnable():
	frame = _close_frame()
	now = frame.index[-1]
	tf = timedelta(days=1)
	handle = IndicatorHandle(EMA, "close", (20,))
	handle.repopulate(frame, now, tf)
	first = handle[-1]
	handle.repopulate(frame, now, tf)
	assert handle[-1] == first


def test_handle_getitem_before_repopulate_raises():
	# WR-01 (orig): the read-before-repopulate contract must raise UNCONDITIONALLY
	# (it was an `assert`, stripped under `-O`/PYTHONOPTIMIZE — turning the
	# violation into a confusing 'NoneType' has no attribute 'iloc'). A fresh
	# handle (never repopulated) must raise RuntimeError on __getitem__, not
	# AttributeError. `__len__` stays 0 (covered separately); this locks the
	# `[idx]` guard.
	handle = IndicatorHandle(SMA, "close", (50,))
	with pytest.raises(RuntimeError):
		_ = handle[-1]
