"""P5-D19 reset() determinism — reset() -> re-feed reproduces a fresh run.

Each stateful adapter implements ``reset()`` clearing its scalar/ring state, its
readiness count, and its output buffer; feeding N bars, calling ``reset()``, and
re-feeding the SAME N bars must reproduce a value series identical to a fresh
instance fed the same bars (SC3b).

The analog is ``test_indicators.py::test_handle_repopulate_is_re_runnable``.
TAB-indented (RESEARCH Pitfall 6).
"""

import numpy as np

from itrader.strategy_handler.indicators.catalog import (
	_EMAState,
	_MACDHistState,
	_RSIState,
	_SMAState,
)


def _closes(n: int = 200) -> np.ndarray:
	"""A non-trivial synthetic close path (deterministic)."""
	return np.array(
		[100.0 + (i % 7) - (i % 3) * 0.5 + i * 0.1 for i in range(n)],
		dtype="float64",
	)


def _collect(state, closes: np.ndarray) -> np.ndarray:
	out = np.full(len(closes), np.nan, dtype="float64")
	for i, close in enumerate(closes):
		state.update(float(close))
		if state.value is not None:
			out[i] = state.value
	return out


def _assert_reset_reproduces(factory):
	closes = _closes()
	# Fresh run.
	fresh = _collect(factory(), closes)
	# Re-used instance: feed -> reset -> re-feed.
	state = factory()
	_collect(state, closes)
	state.reset()
	reused = _collect(state, closes)
	# Identical (NaN-aware) — reset() fully clears scalar/ring/count/output state.
	np.testing.assert_array_equal(
		np.nan_to_num(fresh, nan=-1.0),
		np.nan_to_num(reused, nan=-1.0),
	)


def test_sma_reset_reproduces_fresh_run():
	_assert_reset_reproduces(lambda: _SMAState(50))


def test_ema_reset_reproduces_fresh_run():
	_assert_reset_reproduces(lambda: _EMAState(20))


def test_macdhist_reset_reproduces_fresh_run():
	_assert_reset_reproduces(lambda: _MACDHistState(6, 12, 3))


def test_rsi_reset_reproduces_fresh_run():
	_assert_reset_reproduces(lambda: _RSIState(14))


def test_reset_clears_readiness():
	"""After reset() the adapter is no longer ready until re-warmed (P5-D19)."""
	state = _SMAState(50)
	for i in range(60):
		state.update(float(100 + i))
	assert state.is_ready
	state.reset()
	assert not state.is_ready
	assert state.value is None
