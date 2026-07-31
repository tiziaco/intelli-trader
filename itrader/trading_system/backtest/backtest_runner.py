"""Backtest run driver — sync fail-fast for-loop over the engine.

``BacktestRunner`` is the mode-specific run DRIVER, not shared with live (live is a
threaded daemon with publish-and-continue). It owns the session setup and the per-tick
for-loop, and stays FAIL-FAST: a handler failure aborts the run via the
``EventHandler``'s re-raising error seam.

ORDERING IS BYTE-EXACT-SENSITIVE:

* per-tick loop: ``clock.set_time`` -> ``queue.put`` -> ``process_events`` ->
  ``record_metrics`` (DIRECT call, NEVER an event reroute) -> ``on_tick`` hook.
* session setup: membership derive -> ``feed.bind`` -> ping-grid
  ``reduce(pd.Index.union)`` -> ``time_generator.set_dates`` -> per-strategy
  ``feed.precompute`` in registration order.
"""

from datetime import datetime
from functools import reduce
from typing import Any, Callable, Optional, cast

import pandas as pd

from itrader.core.exceptions import ConfigurationError
from itrader.logger import get_itrader_logger
from itrader.price_handler.feed.bar_feed import BacktestBarFeed
from itrader.price_handler.store.base import PriceStore
from itrader.trading_system.graph import Engine
from itrader.trading_system.universe_wiring import wire_universe


class BacktestRunner:
	"""Drives the synchronous, fail-fast backtest loop over a pre-built ``Engine``.

	``run`` initialises the backtest session (ORDER-SENSITIVE) then drives the per-tick
	for-loop, preserving the post-bar ``record_metrics`` DIRECT call.
	"""

	def __init__(self, engine: Engine) -> None:
		self.engine = engine
		self.logger = get_itrader_logger().bind(component="BacktestRunner")
		self.duration_seconds: float | None = None

	def _initialise_backtest_session(self) -> None:
		"""Derive membership, bind the feed factory, derive the ping clock, and
		precompute the per-strategy resampled frames.

		ORDER-SENSITIVE: universe wiring -> ping-grid union ->
		``time_generator.set_dates`` -> per-strategy precompute (registration order).
		"""
		engine = self.engine
		self.logger.info('Initialising backtest session')

		# The shared, oracle-critical universe-injection ordering lives in the ONE
		# greppable home wire_universe(), reused byte-exact by the live
		# SessionInitializer. It holds the built Universe on engine.universe.
		wire_universe(engine)
		# The shared Engine holder widens store/feed to the base ``Optional[PriceStore]``
		# / ``BarFeed`` so the mode-agnostic seam can also produce a live Engine, but on
		# THIS path they are always the concrete backtest backends. Narrow them for the
		# store symbols/index reads and for ``precompute`` — a BacktestBarFeed-only
		# capability the live feed does not carry.
		store = cast(PriceStore, engine.store)
		feed = cast(BacktestBarFeed, engine.feed)
		# Ping clock derived from the store's bar index: fail loudly on an empty store,
		# and derive the grid from the UNION of every symbol's index so a sparse
		# multi-symbol universe never silently drops bars. For the single-symbol golden
		# run the reduce returns that one index UNCHANGED (no union call).
		symbols = store.symbols()
		if not symbols:
			raise ConfigurationError(
				reason=(
					"Backtest store has no symbols — cannot derive the ping clock "
					"(empty data directory or bad store path)"))
		ping_grid = reduce(
			pd.Index.union, (store.index(s) for s in symbols))
		engine.time_generator.set_dates(ping_grid)
		# Resample ONCE at run-init per registered strategy declaration — the per-tick
		# window path is then a pure positional slice.
		for strategy in engine.strategies_handler.strategies:
			feed.precompute(strategy.tickers, strategy.timeframe)

	def _run_backtest(self, on_tick: Optional[Callable[[Any, Any], None]] = None) -> None:
		"""Poll the events queue per tick and dispatch each event (fail-fast).

		Parameters
		----------
		on_tick : Optional[Callable]
			An OPTIONAL per-bar callback the E2E harness uses to play the OPERATOR,
			invoked AFTER ``process_events`` + ``record_metrics``. Default ``None``
			invokes nothing, so the production path is unaffected.
		"""
		engine = self.engine
		self.logger.info('    RUNNING BACKTEST   ')
		start_time = datetime.now()

		for time_event in engine.time_generator:
			# Advance the injected clock to keep the determinism seam staged. Result
			# determinism comes from passing time_event.time explicitly to
			# record_metrics below, not from clock.now().
			engine.clock.set_time(time_event.time)
			engine.global_queue.put(time_event)
			engine.event_handler.process_events()
			for portfolio in engine.portfolio_handler.get_active_portfolios():
				portfolio.record_metrics(time_event.time)
			if on_tick is not None:
				on_tick(self, time_event)

		# Run-end time-in-force sweep — the shutdown bookend to the per-tick loop. Every
		# still-resting order is swept to EXPIRED, then ONE final drain clears them
		# through the exchange (EXPIRE -> matching_engine.cancel -> FillEvent(EXPIRED)
		# -> reconcile). One drain suffices because the sweep provably cannot cascade:
		# the routes literal sends ORDER -> on_order only and FILL -> portfolio +
		# reconcile only, and EXPIRE emits no SignalEvent and no new OrderEvent(NEW).
		engine.order_handler.expire_all_resting()
		engine.event_handler.process_events()
		self.logger.info('    BACKTEST COMPLETED   ')
		end_time = datetime.now()
		duration = end_time - start_time
		self.duration_seconds = duration.total_seconds()
		self.logger.info('Backtest completed', duration_seconds=duration.total_seconds())

	def run(self, on_tick: Optional[Callable[[Any, Any], None]] = None) -> None:
		"""Initialise the session (ORDER-SENSITIVE) then drive the for-loop."""
		self._initialise_backtest_session()
		self._run_backtest(on_tick=on_tick)
