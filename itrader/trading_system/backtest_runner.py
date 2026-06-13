"""Backtest run driver — sync fail-fast for-loop over the engine (D-14/W4-02).

``BacktestRunner`` is the mode-specific run DRIVER (NOT shared with live — live
is a threaded daemon with publish-and-continue). It owns the session setup
(membership derive -> feed.bind -> ping-grid -> precompute) and the per-tick
for-loop extracted VERBATIM from the old ``BacktestTradingSystem._run_backtest``.

ORDERING IS BYTE-EXACT-SENSITIVE (Trap 4/6):

* per-tick loop: ``clock.set_time`` -> ``queue.put`` -> ``process_events`` ->
  ``record_metrics`` (DIRECT call, NEVER an event reroute) -> ``on_tick`` hook.
* session setup: membership derive -> ``feed.bind`` -> ping-grid
  ``reduce(pd.Index.union)`` -> ``time_generator.set_dates`` -> per-strategy
  ``feed.precompute`` in registration order.

The runner stays FAIL-FAST (it does NOT adopt live's publish-and-continue) — a
handler failure aborts the run via the EventHandler's re-raising error seam.

Indentation: TABS (``trading_system/`` package convention).
"""

from datetime import datetime
from functools import reduce
from typing import Any, Callable, Optional

import pandas as pd

from itrader.core.exceptions import ConfigurationError
from itrader.logger import get_itrader_logger
from itrader.trading_system.compose import Engine
from itrader.universe import derive_membership


class BacktestRunner:
	"""Drives the synchronous, fail-fast backtest loop over a wired ``Engine``.

	Holds the pre-built engine (D-04). ``run`` initialises the backtest session
	(ORDER-SENSITIVE) then drives the per-tick for-loop, preserving the exact
	post-bar ``record_metrics`` DIRECT call (W4-02, Trap 4).
	"""

	def __init__(self, engine: Engine) -> None:
		self.engine = engine
		self.logger = get_itrader_logger().bind(component="BacktestRunner")

	def _initialise_backtest_session(self) -> None:
		"""Derive membership, bind the feed factory, derive the ping clock, and
		precompute the per-strategy resampled frames (M5-03).

		ORDER-SENSITIVE (Trap 4): membership derive -> feed.bind -> ping-grid
		union -> time_generator.set_dates -> per-strategy precompute (registration
		order). W4-03 is a tidy, NOT a reorder.
		"""
		engine = self.engine
		self.logger.info('Initialising backtest session')

		# Membership derived at wiring time (M5-08, D-20): the union of strategy
		# tickers and the screener set — used by the feed's factory only for the
		# missing-ticker warning loop.
		membership = derive_membership(
			engine.strategies_handler.strategies,
			# D-screener deferred subsystem (ignore_errors override) — untyped to the gate.
			engine.screeners_handler.get_screeners_universe())  # type: ignore[no-untyped-call]
		engine.feed.bind(engine.global_queue, membership)
		# Ping clock derived from the store's bar index (T-06-16). WR-07: fail
		# loudly on an empty store, and derive the grid from the UNION of every
		# symbol's index so a sparse multi-symbol universe never silently drops
		# bars. For the single-symbol golden run the reduce returns that one index
		# UNCHANGED (no union call), so the tick grid stays byte-identical.
		symbols = engine.store.symbols()
		if not symbols:
			raise ConfigurationError(
				"Backtest store has no symbols — cannot derive the ping clock "
				"(empty data directory or bad store path)")
		ping_grid = reduce(
			pd.Index.union, (engine.store.index(s) for s in symbols))
		engine.time_generator.set_dates(ping_grid)
		# M5-03: resample ONCE at run-init per registered strategy declaration —
		# the per-tick window path is then a pure positional slice.
		for strategy in engine.strategies_handler.strategies:
			engine.feed.precompute(strategy.tickers, strategy.timeframe)

	def _run_backtest(self, on_tick: Optional[Callable[[Any, Any], None]] = None) -> None:
		"""Poll the events queue per tick and dispatch each event (fail-fast).

		``on_tick`` (Phase 6, D-06) is an OPTIONAL per-bar callback the E2E harness
		uses to play the OPERATOR. Invoked AFTER ``process_events`` + ``record_metrics``
		(post-bar). Default ``None`` invokes nothing and changes ZERO bytes on the
		production path (oracle-dark).
		"""
		engine = self.engine
		self.logger.info('    RUNNING BACKTEST   ')
		start_time = datetime.now()  # Capture start time

		for time_event in engine.time_generator:
			# Advance the injected clock to the current simulation/bar time to keep
			# the determinism seam staged. Result determinism comes from passing
			# time_event.time explicitly to record_metrics below, not clock.now().
			engine.clock.set_time(time_event.time)
			engine.global_queue.put(time_event)
			engine.event_handler.process_events()
			for portfolio in engine.portfolio_handler.get_active_portfolios():
				portfolio.record_metrics(time_event.time)
			# Phase 6 (D-06): post-bar operator hook. Default None = byte-exact
			# (oracle-dark); only the E2E harness wires it from spec.actions.
			if on_tick is not None:
				on_tick(self, time_event)
		self.logger.info('    BACKTEST COMPLETED   ')
		end_time = datetime.now()  # Capture end time
		duration = end_time - start_time
		self.logger.info('Backtest completed', duration_seconds=duration.total_seconds())

	def run(self, on_tick: Optional[Callable[[Any, Any], None]] = None) -> None:
		"""Initialise the session (ORDER-SENSITIVE) then drive the for-loop."""
		self._initialise_backtest_session()
		self._run_backtest(on_tick=on_tick)
