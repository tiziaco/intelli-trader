"""
Comparison primitives for the declared-indicator framework (IND-01, D-01/D-02).

This module is the flat, free-function comparison surface migrated strategies
read through (the ``core/sizing.py`` free-function-module analog — NOT a
catalog/package, just a handful of pure functions):

- **D-01 — free-function comparison primitives.** ``crossover``/``crossunder``/
  ``is_above``/``is_below`` are module-level free functions (no class, no state),
  modelled on the ``core/sizing.py`` pure-validator convention.
- **D-02 [BYTE-EXACT] — inclusive-on-current-bar boundary semantics.** The
  operators reproduce ``SMA_MACD_strategy.py`` (lines 70, 77, 80) operator-for-
  operator: inclusive ``>=``/``<=`` on the CURRENT bar, strict ``<``/``>`` on the
  PREVIOUS bar. Switching to textbook-strict ``>`` would drift the golden oracle —
  this is a load-bearing byte-exact lever, do NOT "tidy" it.
- **D-02 scalar broadcast.** The 2nd arg accepts an ``int``/``float`` scalar
  (``crossover(macd_hist, 0)``), broadcast as ``b[-1] == b[-2] == scalar``.

The 1st arg is read positionally via ``[idx]`` (an ``IndicatorHandle`` or a
pandas ``Series`` both qualify); the 2nd arg is either such a sequence or a
scalar. ``float(...)`` at the read edge is correct here — indicator values are
the ``ta`` compute domain's ``float64``, NOT money (do NOT route them through
``to_money``).
"""

from typing import Any

__all__ = [
	"crossover",
	"crossunder",
	"is_above",
	"is_below",
]


def _at(series_or_scalar: Any, idx: int) -> float:
	"""D-02 scalar broadcast: a scalar reads as ``b[-1] == b[-2] == scalar``."""
	if isinstance(series_or_scalar, (int, float)):
		return float(series_or_scalar)
	return float(series_or_scalar[idx])


def is_above(a: Any, b: Any) -> bool:
	"""D-02: True iff ``a[-1] >= b[-1]`` (inclusive on the current bar)."""
	return _at(a, -1) >= _at(b, -1)


def is_below(a: Any, b: Any) -> bool:
	"""D-02: True iff ``a[-1] <= b[-1]`` (inclusive on the current bar)."""
	return _at(a, -1) <= _at(b, -1)


def crossover(a: Any, b: Any) -> bool:
	"""D-02: True iff ``a[-2] < b[-2]`` AND ``a[-1] >= b[-1]`` (strict prev, inclusive current)."""
	return _at(a, -2) < _at(b, -2) and _at(a, -1) >= _at(b, -1)


def crossunder(a: Any, b: Any) -> bool:
	"""D-02: True iff ``a[-2] > b[-2]`` AND ``a[-1] <= b[-1]`` (strict prev, inclusive current)."""
	return _at(a, -2) > _at(b, -2) and _at(a, -1) <= _at(b, -1)
