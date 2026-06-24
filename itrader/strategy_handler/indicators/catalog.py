"""
Typed indicator adapter catalog for the iTrader strategy engine (IND-01, D-04/D-07/D-08).

This module is the typed-symbol catalog the declared-indicator framework reads
through (the ``core/sizing.py`` singleton-instance + union-alias analog, and the
``fee_model/`` pluggable-typed-model analog).

**PERF-05 / Phase 5 (P5-D07/D11/D12) — Model B stateful recurrences.** The four
adapters no longer call ``ta`` per tick. ``ta`` had NO incremental/streaming API
(Series-in / Series-out only — spec §10.H), which forced the per-tick full-series
recompute this phase removes. Each adapter is now STATELESS and hands out a fresh
``_*State`` recurrence object (``new_state()``) that holds its own O(1) derived
state and advances on a pure push ``update(value)`` (P5-D07), exposing ``value`` /
``is_ready`` (= ``count >= min_period``, P5-D06) / ``reset()`` (P5-D19) and a
``causal`` flag (P5-D20, all v1 adapters causal). ``ta``/pandas survive ONLY as the
test-time convergence oracle (P5-D11 — ``tests/unit/strategy/test_indicator_convergence.py``).

- **D-04 — typed adapter symbols (no string lookup).** ``SMA`` / ``MACDHist`` /
  ``EMA`` / ``RSI`` are real importable singleton instances (mypy-visible under
  ``--strict``), each exposing ``new_state()``, ``min_period(params)``, ``causal``.
  Growth means adding an adapter here, never a string branch in a handler.
- **D-07 — v1 catalog.** SMA + MACDHist (oracle-required) + EMA + RSI.
- **D-08 / P5-D06 — first-valid-period ``min_period`` (UNCHANGED).** SMA/EMA/RSI ->
  ``window``; MACDHist -> ``slow + signal`` (==15 for 6/12/3). NO convergence buffer
  (that would push the reference ``max_window`` off 100 and drift the golden oracle).
  SMA_MACD fires at the 100th bar — byte-identical firing tick.

The FOUR recurrences are EMPIRICALLY VERIFIED against ``ta`` 0.11.0 / pandas 2.3.3 on
``data/BTCUSD_1d_ohlcv_2018_2026.csv`` (RESEARCH §Code Examples — measured margins, not
assumed): SMA running-sum deque (P5-D05, max_abs 1.9e-10); EMA factored seed-from-first
``y += alpha*(x-y)``, ``alpha=2/(n+1)`` (P5-D04, max_abs 1.5e-11 — 2x closer than the
expanded form); MACD two factored EMAs + signal (post-bar-100 max_abs 1.7e-11); RSI
factored-RMA ``alpha=1/n`` over ``close.diff(1)`` gain/loss seeded from bar 1 (Pitfall 1,
max_abs 2.84e-14 — NOT textbook Wilder mean-of-first-n per Pitfall 2).

Indicator values are ``float64`` (the ``ta`` compute domain), NOT money — they are
look-ahead-safe values the primitives compare, never routed through ``to_money``
(RESEARCH Pitfall 5 — the recurrences stay float64; the float-summation order of the
SMA running-sum is the INTENDED re-baseline driver P5-D05, not a defect to "fix").
"""

from collections import deque
from typing import Protocol, runtime_checkable

__all__ = [
	"EMA",
	"MACDHist",
	"RSI",
	"SMA",
	"IndicatorAdapter",
	"IndicatorState",
]


@runtime_checkable
class IndicatorState(Protocol):
	"""The per-symbol stateful recurrence surface (Model B push contract, P5-D07).

	A fresh state advances on a pure ``update(value)`` from the global first bar;
	``value`` is ``None`` until the recurrence has produced its first output,
	``is_ready`` is ``count >= min_period`` (P5-D06), and ``reset()`` returns the
	state to its just-constructed shape (P5-D19).
	"""

	value: float | None

	def update(self, x: float) -> None: ...

	def reset(self) -> None: ...

	@property
	def is_ready(self) -> bool: ...


@runtime_checkable
class IndicatorAdapter(Protocol):
	"""The stateless adapter surface the handle wraps and types against (D-04).

	The adapter is a stateless factory: ``new_state(params)`` mints a fresh
	per-symbol ``IndicatorState`` (the fan-out keys one set per symbol, P5-D10),
	``min_period`` is the first-valid period (D-08/P5-D06, UNCHANGED), and
	``causal`` declares the look-ahead-safety flag the decision path guards on
	(P5-D20 — a non-causal adapter is rejected at registration).
	"""

	causal: bool

	def new_state(self, params: tuple[int, ...]) -> IndicatorState: ...

	def min_period(self, params: tuple[int, ...]) -> int: ...


# --- the four verified O(1) recurrences (RESEARCH §Code Examples) -----------


class _SMAState:
	"""SMA running-sum O(1) (P5-D05) — ``sum += new - evicted``, never re-sum.

	The deque is a LOOKUP for the departing value (P5-D05 / RESEARCH "SMA private
	re-sum" pitfall): ``deque(maxlen=window)`` auto-evicts on append at the cap, but
	we capture the popped value explicitly so the running sum stays O(1) — the ring
	is NEVER re-summed (``sum(self._ring)`` is the anti-pattern). Accepts ~1e-9 ULP
	drift vs ta (verified max_abs 1.9e-10 on the golden, post-bar-100).
	"""

	def __init__(self, window: int) -> None:
		self._n = window
		self._ring: deque[float] = deque()
		self._sum = 0.0
		self._count = 0
		self.value: float | None = None

	def update(self, x: float) -> None:
		self._ring.append(x)
		self._sum += x
		if len(self._ring) > self._n:
			# P5-D05: subtract the EVICTED value; never re-sum the ring.
			self._sum -= self._ring.popleft()
		self._count += 1
		if len(self._ring) == self._n:
			self.value = self._sum / self._n

	def reset(self) -> None:
		self._ring.clear()
		self._sum = 0.0
		self._count = 0
		self.value = None

	@property
	def is_ready(self) -> bool:  # P5-D06
		return self._count >= self._n


class _EMAState:
	"""EMA seed-from-first-value, FACTORED form (P5-D04).

	``alpha = 2/(period+1)``; ``y[0] = x[0]`` seeded ONCE at the global first bar
	(Nautilus / ta ``ewm(adjust=False)``); thereafter ``y += alpha*(x - y)`` — the
	FACTORED form, verified 2x closer to ta (1.5e-11) than the expanded
	``alpha*x + (1-alpha)*y`` (2.9e-11). pandas ``ewm`` uses the factored form
	internally. (RESEARCH Pitfall 3: this matches Nautilus + ta, NOT LEAN's DEFAULT
	SMA-seeded EMA — the ta oracle the convergence test asserts against is what
	matters; do NOT "fix" the seed to SMA-seed.)
	"""

	def __init__(self, period: int) -> None:
		self._period = period
		self._alpha = 2.0 / (period + 1.0)  # P5-D04
		self._count = 0
		self.value: float | None = None

	def update(self, x: float) -> None:
		if self.value is None:
			self.value = x  # y[0] = x[0]
		else:
			self.value += self._alpha * (x - self.value)  # FACTORED form
		self._count += 1

	def reset(self) -> None:
		self._count = 0
		self.value = None

	@property
	def is_ready(self) -> bool:
		return self._count >= self._period


class _MACDHistState:
	"""MACD histogram = factored-EMA(fast) - factored-EMA(slow), then signal EMA (P5-D11).

	Both the fast and slow EMAs seed from bar 0 (defined every bar), so the macd
	line is defined every bar; the signal EMA smooths that line; the histogram is
	``macd_line - signal``. ``min_period = slow + signal`` (==15 for 6/12/3 —
	D-08/P5-D06, NO buffer). The EMA transient (bars 13-38) differs from ta's
	sliding-window re-seed (expected, RESEARCH Pitfall 4); post-bar-100 (the
	SMA_MACD firing region) max_abs is 1.7e-11 — fully converged.
	"""

	def __init__(self, fast: int, slow: int, signal: int) -> None:
		self._fast = _EMAState(fast)
		self._slow = _EMAState(slow)
		self._signal = _EMAState(signal)
		self._count = 0
		self._min_period = slow + signal  # P5-D06 / code D-08
		self.value: float | None = None

	def update(self, x: float) -> None:
		self._fast.update(x)
		self._slow.update(x)
		# Both seeded from bar 0 -> .value is non-None from the first bar.
		fast_v = self._fast.value
		slow_v = self._slow.value
		assert fast_v is not None and slow_v is not None  # seeded bar 0
		macd_line = fast_v - slow_v
		self._signal.update(macd_line)
		signal_v = self._signal.value
		assert signal_v is not None
		self.value = macd_line - signal_v
		self._count += 1

	def reset(self) -> None:
		self._fast.reset()
		self._slow.reset()
		self._signal.reset()
		self._count = 0
		self.value = None

	@property
	def is_ready(self) -> bool:
		return self._count >= self._min_period


class _RSIState:
	"""RSI factored-RMA, ta-style single-value seed (P5-D11/D12 — RESEARCH Pitfall 1/2).

	``alpha = 1/n`` (Wilder RMA == ``ewm(alpha=1/n, adjust=False)``). Gain/loss is
	aligned to ta's ``close.diff(1)`` THEN ``diff.where(diff>0, 0.0)`` — and the
	CRUCIAL alignment landmine (RESEARCH Pitfall 1): ``diff[0]`` is NaN, but
	``NaN > 0`` is False, so ``.where`` makes ``up[0] = dn[0] = 0.0``. ta therefore
	SEEDS the RMA at bar 0 with ``0.0`` (NOT at bar 1 with the first gain), and the
	``min_periods = window`` masks output until ``window`` ewm observations exist —
	i.e. the recurrence is seeded one bar EARLIER than a naive bar-1 seed. ``count``
	counts BARS seen (from bar 0), so ``count >= n`` matches ta's ``min_periods``.
	Seeding at bar 1 instead drifts ~28 RSI points early (RESEARCH Pitfall 1) and
	only slowly reconverges — verified WRONG. With the bar-0 zero-seed: max_abs
	2.84e-14 vs ta (Pitfall 2 — single-value seed, NOT textbook Wilder mean-of-n).
	"""

	def __init__(self, window: int) -> None:
		self._n = window
		self._alpha = 1.0 / window
		self._prev_close: float | None = None
		self._up: float = 0.0  # ta seeds up[0]=0.0 (diff[0]=NaN -> .where -> 0.0)
		self._dn: float = 0.0
		self._count = 0  # bars seen (from bar 0, matching ta's ewm observations)
		self.value: float | None = None

	def update(self, close: float) -> None:
		if self._prev_close is None:  # bar 0: ta's up[0]=dn[0]=0.0 SEED (Pitfall 1)
			self._prev_close = close
			self._up = 0.0
			self._dn = 0.0
		else:
			change = close - self._prev_close  # ta: close.diff(1)
			self._prev_close = close
			gain = change if change > 0.0 else 0.0
			loss = -change if change < 0.0 else 0.0
			self._up += self._alpha * (gain - self._up)
			self._dn += self._alpha * (loss - self._dn)
		self._count += 1
		# Output is masked until window ewm observations exist (ta min_periods=n).
		if self._count >= self._n:
			self.value = (
				100.0
				if self._dn == 0.0
				else 100.0 - 100.0 / (1.0 + self._up / self._dn)
			)

	def reset(self) -> None:
		self._prev_close = None
		self._up = 0.0
		self._dn = 0.0
		self._count = 0
		self.value = None

	@property
	def is_ready(self) -> bool:  # ta emits first at index window-1 (count == window)
		return self._count >= self._n


# --- the stateless typed adapters (D-04 factories) --------------------------


class _SMA:
	"""Simple moving average adapter — mints running-sum O(1) state (P5-D05)."""

	causal = True  # P5-D20

	def new_state(self, params: tuple[int, ...]) -> IndicatorState:
		(window,) = params
		return _SMAState(window)

	def min_period(self, params: tuple[int, ...]) -> int:
		(window,) = params
		return window


class _MACDHist:
	"""MACD histogram adapter — mints two factored EMAs + a signal EMA (P5-D11)."""

	causal = True  # P5-D20

	def new_state(self, params: tuple[int, ...]) -> IndicatorState:
		fast, slow, signal = params
		return _MACDHistState(fast, slow, signal)

	def min_period(self, params: tuple[int, ...]) -> int:
		# D-08: first-valid is slow + signal (==15 for 6/12/3); NO buffer.
		_fast, slow, signal = params
		return slow + signal


class _EMA:
	"""Exponential moving average adapter — factored seed-from-first (P5-D04)."""

	causal = True  # P5-D20

	def new_state(self, params: tuple[int, ...]) -> IndicatorState:
		(window,) = params
		return _EMAState(window)

	def min_period(self, params: tuple[int, ...]) -> int:
		(window,) = params
		return window


class _RSI:
	"""Relative strength index adapter — factored-RMA over close.diff(1) (P5-D11)."""

	causal = True  # P5-D20

	def new_state(self, params: tuple[int, ...]) -> IndicatorState:
		(window,) = params
		return _RSIState(window)

	def min_period(self, params: tuple[int, ...]) -> int:
		(window,) = params
		return window


# D-04: real importable singleton instances (the adapters are stateless factories).
SMA: IndicatorAdapter = _SMA()
MACDHist: IndicatorAdapter = _MACDHist()
EMA: IndicatorAdapter = _EMA()
RSI: IndicatorAdapter = _RSI()
