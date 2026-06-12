"""
Thin positional-index indicator handle (IND-01, D-03).

``IndicatorHandle`` is a thin wrapper over a per-tick-recomputed pandas Series
(RESEARCH Pattern 1) — the read surface migrated strategies use (``self.sma[-1]``):

- **D-03 — positional read.** ``[-1]`` / ``[-2]`` are positional reads off the
  computed Series (``.iloc[idx]``), returned as ``float`` at the read edge (the
  ``core/bar.py`` edge-cast discipline — indicator values are the ``ta`` float64
  domain, NOT money).
- **D-03 — empty before repopulate.** ``__len__`` is 0 until ``repopulate`` runs,
  then the Series length; ``repopulate`` delegates to ``adapter.compute`` and is
  re-runnable (idempotent — same frame/now/timeframe yields the same Series).
- **D-08 delegation.** ``min_period()`` delegates to ``adapter.min_period(params)``
  so the base can auto-derive ``warmup``/``max_window`` from the declared handles.

This module lives in the ``indicators`` subsystem (amended D-05) and MUST NOT
import ``base.py`` — the dependency is one-directional ``base -> indicators`` (no
cycle).
"""

from datetime import datetime, timedelta

import pandas as pd

from .catalog import IndicatorAdapter

__all__ = ["IndicatorHandle"]


class IndicatorHandle:
	"""Thin positional-index wrapper over a recomputed pandas Series (D-03)."""

	def __init__(
		self,
		adapter: IndicatorAdapter,
		input_col: str,
		params: tuple[int, ...],
	) -> None:
		self._adapter = adapter
		self._input = input_col
		self._params = params
		self._values: pd.Series | None = None

	def repopulate(
		self, bars: pd.DataFrame, now: datetime, timeframe: timedelta
	) -> None:
		"""Recompute the wrapped Series via the adapter (re-runnable, D-03)."""
		self._values = self._adapter.compute(
			bars, self._input, self._params, now, timeframe
		)

	def __getitem__(self, idx: int) -> float:
		"""Positional read ([-1]/[-2]); ``float`` at the read edge (D-03)."""
		assert self._values is not None, "repopulate() before reading the handle"
		return float(self._values.iloc[idx])

	def __len__(self) -> int:
		"""0 before the first repopulate, else the Series length (D-03)."""
		return 0 if self._values is None else len(self._values)

	def min_period(self) -> int:
		"""Delegate to the wrapped adapter (D-08 first-valid period)."""
		return self._adapter.min_period(self._params)
