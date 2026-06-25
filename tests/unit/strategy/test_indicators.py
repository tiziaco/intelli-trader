"""Indicator adapter catalog + IndicatorHandle tests (Plan 05-02, D-03/D-04/D-07/D-08).

PERF-05 re-baseline (P5-D11/D12): the adapters are now STATEFUL O(1) recurrences
(``new_state()`` push contract, Model B) — ``ta`` is DROPPED on the runtime path and
survives ONLY as the convergence oracle. These EMA/RSI/SMA/MACD value tests are
RE-BASELINED to the incremental values, asserting the stateful recurrence converges
to ``ta``'s batch output post-warmup (the deep convergence harness lives in
``test_indicator_convergence.py``; here we keep a focused unit check).

Covers:
- ``min_period`` first-valid formulas (D-08): SMA/EMA/RSI -> w, MACDHist -> slow+signal.
  For the reference params SMA(50)->50, SMA(100)->100, MACDHist(6,12,3)->15 => max == 100.
- EMA/RSI/SMA/MACD ``new_state()`` value-equality vs a direct ``ta`` call post-warmup
  (additive, D-07; P5-D12 re-baseline — the stateful recurrence is the runtime path).
- ``IndicatorHandle`` (D-03/P5-D08): ``__len__`` is 0 pre-warm; ``[-1]``/``[-2]``
  read the bounded output buffer post-warm; ``min_period()`` delegates to the adapter.

TAB-indented (D-05 / RESEARCH Pitfall 6).
"""

from datetime import datetime, timedelta, timezone

import numpy as np
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


def _close_frame(n: int = 200) -> pd.DataFrame:
	"""Synthetic daily-UTC OHLC frame with a non-trivial close path."""
	start = datetime(2020, 1, 1, tzinfo=timezone.utc)
	idx = pd.DatetimeIndex([start + timedelta(days=i) for i in range(n)])
	close = pd.Series(
		[100.0 + (i % 7) - (i % 3) * 0.5 + i * 0.1 for i in range(n)],
		index=idx,
	)
	return pd.DataFrame({"close": close}, index=idx)


def _feed(adapter, params, closes: np.ndarray) -> np.ndarray:
	"""Feed closes one-by-one through a fresh adapter state; collect running value."""
	state = adapter.new_state(params)
	out = np.full(len(closes), np.nan, dtype="float64")
	for i, c in enumerate(closes):
		state.update(float(c))
		if state.value is not None:
			out[i] = state.value
	return out


def _assert_converges(inc, ta_series, min_period, *, atol=1e-9, rtol=1e-6):
	ta = np.asarray(ta_series, dtype="float64")
	compared = 0
	for i in range(min_period, len(inc)):
		if np.isnan(ta[i]) or np.isnan(inc[i]):
			continue
		assert abs(ta[i] - inc[i]) <= atol + rtol * abs(ta[i]), (
			f"bar {i}: ta={ta[i]!r} inc={inc[i]!r}"
		)
		compared += 1
	assert compared > 0, "vacuous — no post-warmup overlap compared"


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


# --- all v1 adapters are causal (P5-D20) -----------------------------------

def test_v1_adapters_declare_causal():
	assert SMA.causal is True
	assert EMA.causal is True
	assert MACDHist.causal is True
	assert RSI.causal is True


# --- stateful value-equality vs ta post-warmup (P5-D12 re-baseline) --------

def test_ema_state_converges_to_ta():
	frame = _close_frame()
	closes = frame["close"].to_numpy()
	inc = _feed(EMA, (20,), closes)
	ta_series = trend.EMAIndicator(frame["close"], 20, fillna=False).ema_indicator()
	_assert_converges(inc, ta_series.to_numpy(), 20)


def test_rsi_state_converges_to_ta():
	frame = _close_frame()
	closes = frame["close"].to_numpy()
	inc = _feed(RSI, (14,), closes)
	ta_series = momentum.RSIIndicator(frame["close"], 14, fillna=False).rsi()
	_assert_converges(inc, ta_series.to_numpy(), 14)


def test_sma_state_converges_to_ta():
	frame = _close_frame()
	closes = frame["close"].to_numpy()
	inc = _feed(SMA, (50,), closes)
	ta_series = frame["close"].rolling(window=50, min_periods=50).mean()
	_assert_converges(inc, ta_series.to_numpy(), 50)


def test_macdhist_state_converges_to_ta_post_warmup():
	frame = _close_frame()
	closes = frame["close"].to_numpy()
	inc = _feed(MACDHist, (6, 12, 3), closes)
	ta_series = trend.MACD(
		frame["close"],
		window_fast=6,
		window_slow=12,
		window_sign=3,
		fillna=False,
	).macd_diff()
	# Pitfall 4: assert past the slow-EMA transient (>= ~5x the slow span); the
	# stateful EMA seeds once vs ta's per-tick sliding re-seed, so the transient
	# region is legitimately different (the oracle reads macd_hist only at bar 100+).
	_assert_converges(inc, ta_series.to_numpy(), 5 * 12)


# --- IndicatorHandle (D-03 / P5-D08) ---------------------------------------

def test_handle_len_zero_before_warm():
	handle = IndicatorHandle(SMA, "close", (50,))
	assert len(handle) == 0


def test_handle_min_period_delegates_to_adapter():
	handle = IndicatorHandle(SMA, "close", (50,))
	assert handle.min_period() == 50


def test_handle_repopulate_exposes_recurrence_tail():
	frame = _close_frame()
	now = frame.index[-1]
	tf = timedelta(days=1)
	handle = IndicatorHandle(SMA, "close", (50,))
	handle.repopulate(frame, now, tf)

	# The handle's [-1] is the stateful SMA value at the window's last bar — equal
	# to ta's batch SMA at that bar within the running-sum ULP margin (P5-D05).
	ta_series = frame["close"].rolling(window=50, min_periods=50).mean()
	assert handle[-1] == pytest.approx(float(ta_series.iloc[-1]), abs=1e-9, rel=1e-6)
	assert isinstance(handle[-1], float)
	# Depth-2 bounded buffer: [-2] is the prior bar's value.
	assert handle[-2] == pytest.approx(float(ta_series.iloc[-2]), abs=1e-9, rel=1e-6)


def test_handle_repopulate_is_re_runnable():
	frame = _close_frame()
	now = frame.index[-1]
	tf = timedelta(days=1)
	handle = IndicatorHandle(EMA, "close", (20,))
	handle.repopulate(frame, now, tf)
	first = handle[-1]
	handle.repopulate(frame, now, tf)
	assert handle[-1] == first


def test_handle_update_drives_buffer():
	# P5-D07: the push contract — update() advances the recurrence + buffer.
	handle = IndicatorHandle(SMA, "close", (3,))
	for px in (10.0, 20.0, 30.0):
		handle.update(px)
	assert len(handle) == 1
	assert handle[-1] == pytest.approx(20.0)  # (10+20+30)/3
	handle.update(40.0)
	assert handle[-1] == pytest.approx(30.0)  # (20+30+40)/3
	assert handle[-2] == pytest.approx(20.0)


def test_handle_reset_clears_buffer_and_state():
	handle = IndicatorHandle(SMA, "close", (3,))
	for px in (10.0, 20.0, 30.0):
		handle.update(px)
	assert len(handle) == 1
	handle.reset()
	assert len(handle) == 0
	assert handle.is_ready is False
	with pytest.raises(RuntimeError):
		_ = handle[-1]


def test_handle_getitem_before_warm_raises():
	# WR-01: read-before-warm must raise RuntimeError unconditionally (survives -O).
	handle = IndicatorHandle(SMA, "close", (50,))
	with pytest.raises(RuntimeError):
		_ = handle[-1]
