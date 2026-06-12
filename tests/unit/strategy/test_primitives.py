"""D-02 boundary-semantics + scalar-broadcast tests for the comparison primitives.

The four free functions (`itrader/strategy_handler/primitives.py`, D-01/D-02)
reproduce the SMA_MACD operators (lines 70, 77, 80) byte-exact:

- ``is_above(a, b)``   == ``a[-1] >= b[-1]`` (inclusive on current bar)
- ``is_below(a, b)``   == ``a[-1] <= b[-1]`` (inclusive on current bar)
- ``crossover(a, b)``  == ``a[-2] <  b[-2] and a[-1] >= b[-1]`` (strict prev, inclusive current)
- ``crossunder(a, b)`` == ``a[-2] >  b[-2] and a[-1] <= b[-1]``

The 2nd arg accepts a scalar (``crossover(macd_hist, 0)``) broadcast as
``b[-1] == b[-2] == scalar``. TAB-indented (D-05 / plan instruction).
"""

import numpy as np
import pytest

from itrader.strategy_handler.primitives import (
	crossover,
	crossunder,
	is_above,
	is_below,
)


class _Handle:
	"""List-backed stub mirroring IndicatorHandle's positional ``[idx]`` read.

	``[-1]``/``[-2]`` are positional (Python list semantics), exactly what the
	primitives expect from a real ``IndicatorHandle`` (which reads
	``.iloc[idx]``). A raw RangeIndex pandas Series would label-lookup ``-1``
	instead, so the stub models the positional contract directly.
	"""

	def __init__(self, values):
		self._values = [float(v) for v in values]

	def __getitem__(self, idx):
		return self._values[idx]


def _series(values):
	return _Handle(values)


# --- is_above / is_below ---------------------------------------------------

def test_is_above_when_greater():
	assert is_above(_series([1.0, 2.0]), _series([0.0, 1.0])) is True


def test_is_above_when_equal_is_inclusive():
	# a[-1] == b[-1] -> is_above is True (inclusive on current bar)
	assert is_above(_series([1.0, 2.0]), _series([0.0, 2.0])) is True


def test_is_above_when_less():
	assert is_above(_series([1.0, 1.0]), _series([0.0, 2.0])) is False


def test_is_below_when_less():
	assert is_below(_series([1.0, 1.0]), _series([0.0, 2.0])) is True


def test_is_below_when_equal_is_inclusive():
	assert is_below(_series([1.0, 2.0]), _series([0.0, 2.0])) is True


def test_is_below_when_greater():
	assert is_below(_series([1.0, 3.0]), _series([0.0, 2.0])) is False


def test_equal_current_bar_both_above_and_below_true():
	# Boundary: a[-1] == b[-1] -> is_above AND is_below both True
	a = _series([1.0, 5.0])
	b = _series([0.0, 5.0])
	assert is_above(a, b) is True
	assert is_below(a, b) is True


# --- crossover -------------------------------------------------------------

def test_crossover_true_when_prev_below_and_current_at_or_above():
	# a[-2] < b[-2] AND a[-1] >= b[-1]
	assert crossover(_series([-1.0, 1.0]), _series([0.0, 0.0])) is True


def test_crossover_inclusive_on_current_equal():
	# a[-1] == b[-1] still crosses over (inclusive on current bar)
	assert crossover(_series([-1.0, 0.0]), _series([0.0, 0.0])) is True


def test_crossover_false_when_prev_not_strictly_below():
	# a[-2] == b[-2] -> previous not strictly below -> no crossover
	assert crossover(_series([0.0, 1.0]), _series([0.0, 0.0])) is False


def test_crossover_false_when_current_below():
	assert crossover(_series([-1.0, -0.5]), _series([0.0, 0.0])) is False


# --- crossunder ------------------------------------------------------------

def test_crossunder_true_when_prev_above_and_current_at_or_below():
	# a[-2] > b[-2] AND a[-1] <= b[-1]
	assert crossunder(_series([1.0, -1.0]), _series([0.0, 0.0])) is True


def test_crossunder_inclusive_on_current_equal():
	assert crossunder(_series([1.0, 0.0]), _series([0.0, 0.0])) is True


def test_crossunder_false_when_prev_not_strictly_above():
	assert crossunder(_series([0.0, -1.0]), _series([0.0, 0.0])) is False


def test_crossunder_false_when_current_above():
	assert crossunder(_series([1.0, 0.5]), _series([0.0, 0.0])) is False


# --- scalar broadcast (the macd_hist-vs-0 BUY/SELL trigger) ----------------

def test_crossover_scalar_int_broadcast():
	# crossover(macd_hist, 0): b[-1] == b[-2] == 0.0
	assert crossover(_series([-0.5, 0.2]), 0) is True


def test_crossover_scalar_float_broadcast():
	assert crossover(_series([-0.5, 0.2]), 0.0) is True


def test_crossover_scalar_no_cross_when_prev_already_above():
	assert crossover(_series([0.1, 0.2]), 0) is False


def test_crossunder_scalar_int_broadcast():
	# crossunder(macd_hist, 0): b[-1] == b[-2] == 0.0
	assert crossunder(_series([0.5, -0.2]), 0) is True


def test_crossunder_scalar_no_cross_when_prev_already_below():
	assert crossunder(_series([-0.1, -0.2]), 0) is False


def test_macd_hist_buy_trigger_mirrors_sma_macd():
	# SMA_MACD BUY: MACDhist[-1] >= 0 and MACDhist[-2] < 0 -> crossover(hist, 0)
	macd_hist = _series([-0.3, 0.0])
	assert crossover(macd_hist, 0) is True


def test_macd_hist_sell_trigger_mirrors_sma_macd():
	# SMA_MACD SELL: MACDhist[-1] <= 0 and MACDhist[-2] > 0 -> crossunder(hist, 0)
	macd_hist = _series([0.3, 0.0])
	assert crossunder(macd_hist, 0) is True


# --- runtime-hardening regression locks (iter-2 WR-02) ---------------------
# These lock the iteration-1 source fixes in `_at` so a future refactor cannot
# silently revert them with the suite still green.

def test_crossover_rejects_bool_threshold():
	# WR-03 (orig): `bool` subclasses `int` (and is a numbers.Number), so a
	# `True`/`False` threshold would otherwise be silently coerced to 1.0/0.0 —
	# almost certainly an author error (a comparison result passed as a level).
	# `_at` must reject it loudly with TypeError BEFORE the scalar check.
	with pytest.raises(TypeError):
		crossover(_series([1.0, 2.0]), True)
	with pytest.raises(TypeError):
		crossunder(_series([2.0, 1.0]), False)


def test_crossover_numpy_scalar_threshold_broadcasts():
	# WR-02 (orig): a numpy scalar (np.float64/np.int64, the common
	# series.mean() / arr[i] producer) is a numbers.Number, so `_at` treats it
	# as a broadcast scalar (b[-1] == b[-2] == scalar) — NOT the positional
	# index path. crossover([-1, 1], np.float64(0.0)) crosses 0.0.
	assert crossover(_series([-1.0, 1.0]), np.float64(0.0)) is True
	assert crossover(_series([-1.0, 1.0]), np.int64(0)) is True
	# A numpy scalar threshold that is NOT crossed stays False.
	assert crossover(_series([0.1, 0.2]), np.float64(0.0)) is False
