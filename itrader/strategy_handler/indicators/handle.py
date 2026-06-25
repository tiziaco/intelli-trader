"""
Thin positional-index indicator handle (IND-01, D-03; PERF-05 / P5-D08).

``IndicatorHandle`` is a thin wrapper over an ``update()``-driven bounded
output-history buffer (Model B, P5-D07/D08) — the read surface migrated strategies
use (``self.sma[-1]`` / ``self.sma[-2]``):

- **D-03 / P5-D08 — positional read off a bounded buffer.** ``[-1]`` / ``[-2]``
  index a bounded output-history buffer (default depth 2 — the primitives read at
  most ``[-2]``), returned as ``float`` at the read edge (indicator values are the
  ``ta`` float64 domain, NOT money — never ``to_money``, RESEARCH Pitfall 5).
- **D-03 — empty before warm.** ``__len__`` is 0 until the buffer holds at least
  one produced value. ``__getitem__`` before any value raises ``RuntimeError``
  unconditionally (NOT an ``assert`` — stripped under ``-O``/PYTHONOPTIMIZE, which
  would turn the ordering-contract violation into a confusing ``IndexError`` far
  from the cause).
- **P5-D07 — value production via the stateful adapter.** ``update(x)`` pushes a
  single value through the per-handle ``IndicatorState`` (``adapter.new_state``)
  and records ``state.value`` into the output buffer when the recurrence has
  produced one. ``is_ready`` delegates to the state (``count >= min_period``,
  P5-D06). ``reset()`` clears the buffer AND the state (P5-D19).
- **D-03 — re-runnable repopulate (the Plan-B compatibility seam).** ``repopulate``
  drives the SAME stateful contract from the legacy ``evaluate`` window: it mints a
  fresh state, feeds the window's ``input_col`` value-by-value, and rebuilds the
  bounded buffer. The firing tick is byte-identical (the value at ``[-1]`` is the
  recurrence value at the window's last bar); only VALUE production changes (ta ->
  stateful). Plan C decouples ``evaluate`` to pure per-tick ``update`` (no window).
- **D-08 delegation.** ``min_period()`` delegates to ``adapter.min_period(params)``
  so the base can auto-derive ``warmup``/``max_window`` from the declared handles.

This module lives in the ``indicators`` subsystem (amended D-05) and MUST NOT
import ``base.py`` — the dependency is one-directional ``base -> indicators`` (no
cycle).
"""

from collections import deque
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .catalog import IndicatorAdapter

__all__ = ["IndicatorHandle"]

# P5-D08: the primitives read at most [-2]; depth 2 is the bounded output history.
_BUFFER_DEPTH = 2


class IndicatorHandle:
	"""Thin positional-index wrapper over an update()-driven output buffer (D-03, P5-D08)."""

	def __init__(
		self,
		adapter: IndicatorAdapter,
		input_col: str,
		params: tuple[int, ...],
		depth: int = _BUFFER_DEPTH,
	) -> None:
		self._adapter = adapter
		self._input = input_col
		self._params = params
		self._depth = depth
		self._state = adapter.new_state(params)
		# Bounded output history; holds the last ``depth`` produced values.
		self._buffer: deque[float] = deque(maxlen=depth)

	def update(self, x: float) -> None:
		"""Push one input value through the stateful recurrence (P5-D07)."""
		self._state.update(x)
		if self._state.value is not None:
			self._buffer.append(self._state.value)

	@property
	def is_ready(self) -> bool:
		"""Delegate readiness to the state (count >= min_period, P5-D06)."""
		return self._state.is_ready

	def reset(self) -> None:
		"""Clear the output buffer AND the recurrence state (P5-D19)."""
		self._state.reset()
		self._buffer.clear()

	def repopulate(
		self, bars: pd.DataFrame, now: datetime, timeframe: timedelta
	) -> None:
		"""Drive the stateful recurrence from the legacy window (D-03 — re-runnable).

		Mints a fresh state and feeds the window's ``input_col`` value-by-value,
		rebuilding the bounded output buffer. Re-runnable (idempotent — the same
		window yields the same buffer). This is the Plan-B compatibility seam: it
		preserves the byte-identical firing tick while VALUE production switches
		from ``ta``-recompute to the stateful recurrence (Plan C removes the window
		and drives ``update`` per tick directly).
		"""
		self._state = self._adapter.new_state(self._params)
		self._buffer = deque(maxlen=self._depth)
		# Feed the window's input column one value at a time (Model B push).
		for x in bars[self._input].to_numpy():
			self.update(float(x))

	def snapshot_state(self) -> tuple[Any, "deque[float]"]:
		"""Return ``(state, buffer)`` for per-symbol fan-out save/restore (P5-D10).

		The per-symbol fan-out (P5-D14) drives ONE set of registration handles (the
		author-bound ``self.short_sma`` etc.) and swaps each ticker's recurrence
		state in/out before dispatch — so the read surface (``self.short_sma[-1]``)
		always reflects the ACTIVE ticker. ``snapshot_state`` hands out the live
		``(state, buffer)`` to stash; ``load_state`` swaps a stashed pair back in. A
		fresh (just-constructed) ticker gets a fresh state via ``fresh_state``.
		"""
		return (self._state, self._buffer)

	def load_state(self, state: Any, buffer: "deque[float]") -> None:
		"""Swap a previously-snapshotted ``(state, buffer)`` back in (P5-D10)."""
		self._state = state
		self._buffer = buffer

	def fresh_state(self) -> tuple[Any, "deque[float]"]:
		"""Mint + install a fresh ``(state, buffer)`` for a never-seen ticker (P5-D10a)."""
		self._state = self._adapter.new_state(self._params)
		self._buffer = deque(maxlen=self._depth)
		return (self._state, self._buffer)

	def __getitem__(self, idx: int) -> float:
		"""Positional read ([-1]/[-2]); ``float`` at the read edge (D-03)."""
		# WR-01: a real runtime ordering contract (read-before-warm) must raise
		# unconditionally — an `assert` is stripped under `-O`/PYTHONOPTIMIZE,
		# turning the violation into a confusing IndexError far from the cause.
		if not self._buffer:
			raise RuntimeError("handle must be warmed (update/repopulate) before reading")
		return float(self._buffer[idx])

	def __len__(self) -> int:
		"""0 before the first produced value, else the bounded buffer length (D-03)."""
		return len(self._buffer)

	def min_period(self) -> int:
		"""Delegate to the wrapped adapter (D-08 first-valid period)."""
		return self._adapter.min_period(self._params)
