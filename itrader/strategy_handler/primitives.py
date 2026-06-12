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

import numbers
from typing import Any, cast

__all__ = [
	"crossover",
	"crossunder",
	"is_above",
	"is_below",
]


def _at(series_or_scalar: Any, idx: int) -> float:
	"""D-02 scalar broadcast: a scalar reads as ``b[-1] == b[-2] == scalar``."""
	# WR-03: reject `bool` BEFORE the scalar check. `bool` subclasses `int`
	# (and is a `numbers.Number`), so `crossover(hist, True)` would otherwise be
	# silently coerced to the scalar `1.0` — almost certainly an author error
	# (a comparison result passed where a level was meant). Fail loudly instead.
	if isinstance(series_or_scalar, bool):
		raise TypeError("bool is not a valid scalar threshold; pass a numeric level")
	# WR-02: detect scalars via `numbers.Number` (covers numpy scalars like
	# numpy.float64/numpy.int64 produced by np.array(...)[i] / series.mean()),
	# not a native int/float whitelist. A pandas Series / list-backed
	# IndicatorHandle is NOT a numbers.Number, so it correctly takes the
	# positional-index path; the reference literal `0` stays scalar.
	if isinstance(series_or_scalar, numbers.Number):
		# `numbers.Number` is not statically known to be float-convertible, but
		# every concrete numeric (int/float/numpy scalar) supports float() — cast
		# at the conversion edge so mypy --strict stays clean (WR-02).
		return float(cast(Any, series_or_scalar))
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
