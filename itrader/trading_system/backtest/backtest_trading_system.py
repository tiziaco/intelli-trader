"""Thin backtest holder + the ``build_backtest_system`` factory.

The factory builds, the class is a thin holder. ``build_backtest_system(spec)`` derives
the COMPLETE supported-symbol set and folds it into the spec's ``ExchangeConfig``, builds
the infra ``EngineContext``, builds the run's paper venue, calls the
``build_handler_graph`` seam, constructs the ``BacktestRunner``, adds
strategies/portfolios in SPEC ORDER, wires subscriptions, and returns the holder. The
handlers OWN their order/signal storage backends (selected from ``ctx.environment``), so
the factory selects no storage concretes.

``BacktestTradingSystem`` also keeps a direct-construction ``__init__`` taking loose
params, which builds the same engine+runner internally through the same seam. Its
``run()`` delegates to the runner, then prints the metrics summary via ``reporting``.
"""

import dataclasses
import random
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from itrader import config, idgen
from itrader.config import ExchangeConfig, OrderConfig
from itrader.core.exceptions import ConfigurationError
from itrader.events_handler.bus import FifoEventBus
from itrader.execution_handler.execution_handler import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID
from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.feed.bar_feed import BacktestBarFeed
from itrader.price_handler.store.csv_store import CsvPriceStore
from itrader.reporting.frames import build_equity_curve, build_trade_log
from itrader.reporting.summary import print_metrics_summary
from itrader.results.records import PortfolioRecord, RunRecord
from itrader.results.serializers import (
	annual_periods,
	build_aggregate_equity_curve,
	build_run_metrics,
	curate_portfolio_params,
	curate_run_settings,
)
from itrader.strategy_handler.storage import SignalStore
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.execution_handler.exchanges.base import AbstractExchange
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.portfolio_handler.portfolio_factory import (
	AccountFactory,
	PortfolioFactory,
)
from itrader.trading_system.backtest.backtest_runner import BacktestRunner
from itrader.trading_system.engine_context import EngineContext
from itrader.trading_system.graph import Engine, build_handler_graph
from itrader.trading_system.system_spec import SystemSpec

from itrader.logger import get_itrader_logger


#: The default preset exchange symbols (the *USDT set) the complete supported-set
#: union starts from. BTCUSD (the golden ticker) is always unioned.
_DEFAULT_PRESET_SYMBOLS: frozenset[str] = frozenset(
	ExchangeConfig.default().limits.supported_symbols)


def _seed_supported_symbols(
	exchange_config: ExchangeConfig, tickers: "set[str]") -> ExchangeConfig:
	"""Fold the COMPLETE supported-symbol set into the exchange config.

	The final set = default preset symbols ∪ {BTCUSD} ∪ spec tickers (upper-cased).
	Seeded at CONSTRUCTION so it is replacement-safe: a later ``update_config`` that
	re-derives ``_supported_symbols`` from ``config.limits`` can never wipe a symbol.
	Deriving it root-side is what keeps ``build_handler_graph`` mode-agnostic.
	"""
	complete = set(_DEFAULT_PRESET_SYMBOLS) | {'BTCUSD'} | {t.upper() for t in tickers}
	exchange_config.limits.supported_symbols = complete
	return exchange_config


def _build_paper_venue(
	ctx: EngineContext, exchange_config: ExchangeConfig,
) -> "tuple[dict[tuple[str, str], Optional[AbstractExchange]], PortfolioFactory]":
	"""Build the backtest's ONE venue: its paper exchange and its account factory.

	The backtest root chooses its own concretions and hands them to the graph builder,
	which therefore needs no venue substrate and no mode branch. Both construction arms
	call this, so the byte-exact oracle covers the wiring whichever arm it drives.

	The exchange is built with ``ctx.rng``, the one seeded ``random.Random`` of the run:
	two ``random.Random(42)`` instances look identical until the call order diverges, so
	a fresh one breaks reproducibility silently. ``exchange_config`` is the RUN-derived
	one — a default preset omits the golden BTCUSD ticker and the exchange would refuse
	it — and is never read off the process-wide config singleton.

	``connect()`` is not ceremony: ``SimulatedExchange.validate_order`` refuses an order
	on a disconnected exchange, so an unconnected paper venue fills nothing.
	"""
	exchange = SimulatedExchange(ctx.bus, config=exchange_config, rng=ctx.rng)
	exchange.connect()
	exchange_registry: dict[tuple[str, str], Optional[AbstractExchange]] = {
		(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID): exchange}
	portfolio_factory = PortfolioFactory(
		account_factory=AccountFactory(),
		environment=ctx.environment,
		sql_engine=ctx.sql_engine)
	return exchange_registry, portfolio_factory


class BacktestTradingSystem(object):
	"""Thin holder of a pre-built ``Engine`` + ``BacktestRunner``.

	``__init__`` is a dumb holder: it stores the engine and runner and exposes ``run()``.
	The direct-construction signature is retained for the oracle/integration sites, and
	builds the engine+runner internally via the same seam the factory uses.
	"""

	def __init__(
		self, exchange: str = 'paper',
		start_date: Optional[str] = None,
		end_date: str = '',
		to_sql: bool = False,
		timeframe: str = '1d',
		csv_paths: dict[str, "str | Path"] | None = None,
		*,
		engine: Optional[Engine] = None,
		runner: Optional[BacktestRunner] = None,
	) -> None:
		"""Construct the holder.

		Two construction modes:

		* **Factory mode:** ``build_backtest_system`` passes a pre-built ``engine`` +
		  ``runner``; the holder is a dumb wrapper.
		* **Direct-construction mode:** the oracle/integration sites pass the loose params
		  and the holder builds the engine+runner internally via the same
		  ``build_handler_graph`` seam, with byte-identical wiring.

		``exchange`` names the run's VENUE and defaults to ``'paper'`` — the ONE name for the
		simulated fill engine across backtest and live-paper. It is a HOLDER attribute only:
		routing reads each portfolio's own ``exchange``/``venue_name``, never this field, so
		the default documents intent rather than feeding routing.
		"""
		self.logger = get_itrader_logger().bind(component="Engine")
		self.exchange = exchange
		self.start_date = start_date
		self.end_date = end_date
		self.to_sql = to_sql

		if engine is not None and runner is not None:
			# Factory mode: dumb holder of pre-built components.
			self.engine = engine
			self.runner = runner
		else:
			# Build the engine+runner here using the shared seam. The COMPLETE
			# supported-symbol set is seeded into a construction-time ExchangeConfig via
			# the same _seed_supported_symbols path the factory uses. csv_paths=None is
			# the single-golden-ticker default, so the seeded set is the preset ∪ {BTCUSD}.
			tickers = {str(t).upper() for t in (csv_paths or {}).keys()}
			exchange_config = _seed_supported_symbols(
				ExchangeConfig.default(), tickers)
			# The oracle runs through THIS spec-less arm, so it is folded onto the same
			# seam as the factory. Synthesize a minimal frozen SystemSpec — ticker and
			# starting_cash are PLACEHOLDERS nothing downstream reads, and
			# strategies/portfolios stay empty because the direct-construction sites add
			# them through the handler seams instead. Empty spec fields map back to None.
			spec = SystemSpec(
				start=start_date or '',
				end=end_date or '',
				timeframe=timeframe,
				ticker='BTCUSD',
				starting_cash=0,
				data=csv_paths or {},
				strategies=[],
				portfolios=[],
				exchange=exchange_config,
			)
			# The store + feed read-models are built HERE, not in the graph seam, then
			# injected onto ctx.
			store = CsvPriceStore(
				csv_paths=spec.data or None,
				start_date=spec.start or None,
				end_date=spec.end or None)
			feed = BacktestBarFeed(store, to_timedelta(spec.timeframe))
			# The ONE seeded determinism RNG, built at the wiring seam and injected on ctx
			# — ExecutionHandler carries no determinism seam. Exactly ONE per run: the
			# exchange, its slippage model, and the venue recipe that builds them all draw
			# from this object.
			rng = random.Random(int(config.rng_seed))
			# The handler OWNS its bus (FifoEventBus — byte-exact FIFO) and its storage
			# (from environment='backtest'). sql_engine is None, which keeps the backtest
			# path SQL-import-inert.
			ctx = EngineContext(
				bus=FifoEventBus(),
				config=config,
				environment='backtest',
				feed=feed,
				rng=rng,
				store=store,
				sql_engine=None,
			)
			# The run's ONE venue, built from THIS run's seeded ExchangeConfig, then the
			# graph. This arm has no results store.
			exchange_registry, portfolio_factory = _build_paper_venue(
				ctx, spec.exchange)
			self.engine = build_handler_graph(
				ctx,
				exchange_registry=exchange_registry,
				portfolio_factory=portfolio_factory,
				results_store=None)
			self.runner = BacktestRunner(self.engine)

		self.logger.info('Trading system initialised')

	# -- Attribute seams (the engine holds the real components) --
	# The oracle/integration/e2e/scripts sites read these off the system directly
	# (system.strategies_handler.add_strategy, system.portfolio_handler.add_portfolio,
	# system.store.read_bars, system.order_handler.cancel_order, ...). Read-only
	# properties delegating to the engine, so no caller can rebind a component.

	@property
	def global_queue(self) -> Any:
		return self.engine.global_queue

	@property
	def clock(self) -> Any:
		return self.engine.clock

	@property
	def store(self) -> Any:
		return self.engine.store

	@property
	def feed(self) -> Any:
		return self.engine.feed

	@property
	def strategies_handler(self) -> Any:
		return self.engine.strategies_handler

	@property
	def screeners_handler(self) -> Any:
		return self.engine.screeners_handler

	@property
	def portfolio_handler(self) -> Any:
		return self.engine.portfolio_handler

	@property
	def execution_handler(self) -> Any:
		return self.engine.execution_handler

	@property
	def order_handler(self) -> Any:
		return self.engine.order_handler

	@property
	def event_handler(self) -> Any:
		return self.engine.event_handler

	@property
	def time_generator(self) -> Any:
		return self.engine.time_generator

	def run(self, print_summary: bool = True,
			on_tick: Optional[Callable[["BacktestTradingSystem", Any], None]] = None,
			persist: bool = False) -> None:
		"""Run the backtest, then optionally print the summary and persist results.

		Delegates the session setup + for-loop to the ``BacktestRunner``, where the
		byte-exact ordering lives.

		Parameters
		----------
		print_summary : bool
		    Print ``reporting.print_metrics_summary`` after the run. Display only — it
		    changes no artifact bytes.
		on_tick : Optional[Callable]
		    An OPTIONAL per-bar operator hook, wrapped so the callback receives THIS
		    holder (``system``) as its first argument — the e2e harness reaches
		    ``system.order_handler`` through it.
		persist : bool
		    The POST-LOOP results dump switch. Defaults to ``False``, so the run loop
		    touches no SQL and the dump code is never reached. When True (and a results
		    store was injected at composition), a complete ``RunRecord`` + artifact
		    frames are assembled from post-run portfolio state and written through the
		    injected store AFTER the loop — structurally off the hot path.
		"""
		wrapped: Optional[Callable[[Any, Any], None]] = None
		if on_tick is not None:
			def wrapped(_runner: Any, time_event: Any) -> None:
				on_tick(self, time_event)

		self.runner.run(on_tick=wrapped)

		# Structurally after the run loop and guarded by ``persist``, so the default path
		# executes no dump code at all. The store guard lives inside ``_persist_results``.
		if persist:
			self._persist_results()

		if print_summary:
			# Assemble the three run-level header inputs from reachable handles, then pass
			# them to the printer.
			duration = self.runner.duration_seconds
			# Period span from the pinned bar-date grid; an empty/None index
			# omits the Period line rather than raising.
			dates = self.engine.time_generator.dates
			period: Optional[tuple[Any, Any, int]] = None
			if dates is not None and len(dates) > 0:
				period = (dates[0], dates[-1], len(dates))
			# Per-portfolio instrument universe: union (dedup, order-preserving)
			# of each subscribed strategy's tickers, keyed by the same
			# PortfolioId handle that portfolio.portfolio_id carries.
			portfolio_tickers: dict[Any, list[str]] = {}
			for strategy in self.strategies_handler.strategies:
				for pid in strategy.subscribed_portfolios:
					bucket = portfolio_tickers.setdefault(pid, [])
					for ticker in strategy.tickers:
						if ticker not in bucket:
							bucket.append(ticker)
			print_metrics_summary(
				self.portfolio_handler.get_active_portfolios(), self.logger,
				duration_seconds=duration,
				period=period,
				portfolio_tickers=portfolio_tickers)

	def _persist_results(self) -> None:
		"""Assemble + write the post-loop ``RunRecord`` through the injected store.

		For each active portfolio: build its run-artifact frames (the SAME pure
		``reporting.frames`` builders the print block uses), compute its per-portfolio
		``RunMetrics`` and curate its strategy ``params``. Then assemble the AGGREGATE
		``RunMetrics`` from the multi-portfolio aggregate equity curve (mixed-timeframe-safe)
		and the concatenated trades, curate the credential-free run-level ``settings``, and
		write ``runs`` + ``run_portfolios`` atomically plus the equity_curve/trade_log
		artifacts. ``run_id`` is a UUIDv7 idgen value — the stable ORDER BY tiebreak.

		Dump-failure policy: a failure re-raises when the store's ``strict_persist`` is True;
		otherwise it is logged-and-swallowed so a sweep never loses good in-memory runs to
		one bad write.

		Raises
		------
		ConfigurationError
		    When no results store was injected at composition.
		"""
		store = self.engine.results_store
		if store is None:
			raise ConfigurationError(
				"results_store",
				reason="run(persist=True) requires a results store injected at composition")

		# Short-circuit when there are NO active portfolios: the aggregate builder runs
		# build_aggregate_equity_curve([]) -> pd.concat([], axis=1) -> ValueError, which
		# would propagate out of run() even with strict_persist=False, contradicting the
		# swallow policy. There is nothing to dump anyway.
		active = list(self.portfolio_handler.get_active_portfolios())
		if not active:
			self.logger.warning(
				"persist requested but no active portfolios; nothing to dump")
			return

		run_id = idgen.generate_run_id()

		# The ENTIRE assembly+write body lives inside the strict_persist-gated try/except,
		# not just the store writes: a builder failure (metrics/serializer) is just as much
		# a "persist failure" as a write failure and must honour the same contract.
		try:
			# Map each active portfolio -> the strategies subscribed to it (the same
			# strategy/subscribed_portfolios walk the print block performs).
			strategies_by_pid: dict[Any, list[Any]] = {}
			for strategy in self.strategies_handler.strategies:
				for pid in strategy.subscribed_portfolios:
					strategies_by_pid.setdefault(pid, []).append(strategy)

			portfolio_records: list[PortfolioRecord] = []
			equity_frames: list[pd.DataFrame] = []
			trades_frames: list[pd.DataFrame] = []
			# (portfolio_id, equity_frame, trades_frame) for the per-portfolio artifacts.
			artifacts: list[tuple[Any, pd.DataFrame, pd.DataFrame]] = []
			timeframe_aliases: list[str] = []
			tickers: list[str] = []
			starting_cash_total = 0.0

			for portfolio in active:
				trades = build_trade_log(portfolio)
				equity = build_equity_curve(portfolio)
				metrics = build_run_metrics(equity, trades)
				strategies_for_pid = strategies_by_pid.get(portfolio.portfolio_id, [])
				params = curate_portfolio_params(strategies_for_pid)
				portfolio_records.append(PortfolioRecord(
					portfolio_id=portfolio.portfolio_id,
					name=portfolio.name,
					metrics=metrics,
					params=params))
				equity_frames.append(equity)
				trades_frames.append(trades)
				artifacts.append((portfolio.portfolio_id, equity, trades))
				# Annualization basis + run-level settings inputs from subscribed strategies.
				for strategy in strategies_for_pid:
					timeframe_aliases.append(strategy.timeframe_alias)
					for ticker in strategy.tickers:
						if ticker not in tickers:
							tickers.append(ticker)
				equity_series = equity["total_equity"].astype(float)
				starting_cash_total += (
					float(equity_series.iloc[0]) if not equity_series.empty else 0.0)

			# The aggregate equity curve is a total_equity Series indexed by timestamp;
			# to_frame() yields the total_equity column build_run_metrics reads, and
			# reset_index() yields the persistable frame.
			aggregate_series = build_aggregate_equity_curve(equity_frames)
			aggregate_equity_frame = aggregate_series.reset_index()
			aggregate_trades = (
				pd.concat(trades_frames, ignore_index=True)
				if trades_frames else pd.DataFrame())
			periods = annual_periods(timeframe_aliases)
			aggregate_metrics = build_run_metrics(
				aggregate_series.to_frame(), aggregate_trades, periods=periods)

			# Curated run settings, credential-free: the fee/slippage models are read off the
			# live paper exchange, market_execution off the order handler.
			exchange = self.execution_handler.exchanges.get(
				(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID))
			order_config = OrderConfig(market_execution=self.order_handler.market_execution)
			settings = curate_run_settings(
				exchange,
				order_config,
				tickers=tickers,
				timeframe=timeframe_aliases[0] if timeframe_aliases else "1d",
				start_date=self.start_date,
				end_date=self.end_date,
				starting_cash=starting_cash_total,
				rng_seed=config.rng_seed)

			record = RunRecord(
				run_id=run_id,
				metrics=aggregate_metrics,
				settings=settings,
				per_portfolio=portfolio_records)

			# runs + run_portfolios atomically, then the artifacts.
			store.save_run(record)
			for portfolio_id, equity, trades in artifacts:
				store.save_artifact(run_id, portfolio_id, "equity_curve", equity)
				store.save_artifact(run_id, portfolio_id, "trade_log", trades)
			store.save_artifact(run_id, None, "equity_curve", aggregate_equity_frame)
		except Exception:
			if getattr(store, "_strict_persist", False):
				raise
			self.logger.error("results persist failed", exc_info=True)

	def get_signal_records(self) -> list[SignalRecord]:
		"""Return the signals captured during the run.

		Reads the handler-owned signal-store sink AFTER the run completes, reached through
		its owning handler rather than a re-surfaced holder copy. A sink read, NOT a
		cross-domain handler call — the queue-only contract is preserved.
		"""
		return self.engine.strategies_handler.signal_store.get_all()

	def get_signal_store(self) -> SignalStore:
		"""Return the signal-store itself for post-run filtered queries.

		Reaches the store through its owning handler.
		"""
		return self.engine.strategies_handler.signal_store


def build_backtest_system(spec: SystemSpec) -> BacktestTradingSystem:
	"""Build a backtest system from a declarative ``SystemSpec``.

	Derives the COMPLETE supported-symbol set from the spec data keys (∪ default preset ∪
	{BTCUSD}) and folds it into the spec's ``ExchangeConfig``, builds the infra
	``EngineContext``, calls the shared ``build_handler_graph`` seam, constructs the
	``BacktestRunner``, adds strategies/portfolios in SPEC ORDER, wires the portfolio
	subscriptions, and returns the thin holder. The handlers OWN their order/signal
	storage backends (selected from ``ctx.environment``).
	"""
	# Seed the complete symbol set into the spec's ExchangeConfig BEFORE the exchange
	# reads it. SystemSpec is frozen, so the seeded exchange rides back onto the spec via
	# ``dataclasses.replace``.
	exchange_config = spec.exchange if spec.exchange is not None else ExchangeConfig.default()
	tickers = {str(t) for t in spec.data.keys()}
	exchange_config = _seed_supported_symbols(exchange_config, tickers)
	spec = dataclasses.replace(spec, exchange=exchange_config)

	# The results store is read off the spec via getattr, and is commonly None — so the
	# oracle path stays store-free and this module imports NO SQL surface at top level. A
	# persistence caller builds the store DIRECTLY and injects it on the spec, e.g.
	# ``SqlResultsStore(SqlEngine(SqlSettings.results_default()),
	# strict_persist=SqlSettings.results_default().strict_persist)``, with the SQL surface
	# imported on THAT path only — never here.
	# The store + feed read-models are built HERE, not in the graph seam, then injected
	# onto ctx (feed required, store real in backtest).
	store = CsvPriceStore(
		csv_paths=spec.data or None,
		start_date=spec.start or None,
		end_date=spec.end or None)
	feed = BacktestBarFeed(store, to_timedelta(spec.timeframe))
	# The ONE seeded determinism RNG, built here at the wiring seam and injected on ctx.
	# Deliberately identical to the direct-construction arm above: the oracle drives THAT
	# arm, so a divergence here would leave the gate passing while proving nothing about
	# this path.
	rng = random.Random(int(config.rng_seed))
	ctx = EngineContext(
		bus=FifoEventBus(),
		config=config,
		environment='backtest',
		feed=feed,
		rng=rng,
		store=store,
		sql_engine=None,
	)
	# The run's ONE venue, from the seeded run-derived ExchangeConfig (spec.exchange,
	# complete symbol set already folded in above), then the graph. getattr keeps a
	# duck-typed spec safe when the field is absent -> None -> store-free.
	exchange_registry, portfolio_factory = _build_paper_venue(ctx, spec.exchange)
	engine = build_handler_graph(
		ctx,
		exchange_registry=exchange_registry,
		portfolio_factory=portfolio_factory,
		results_store=getattr(spec, 'results_store', None))
	runner = BacktestRunner(engine)

	# Add strategies/portfolios in SPEC ORDER — get_active_portfolios is
	# dict-insertion order and callers depend on it. Then wire subscriptions: each
	# strategy subscribes to every spec portfolio (the e2e harness convention).
	for strategy in spec.strategies:
		engine.strategies_handler.add_strategy(strategy)

	portfolio_ids = []
	for portfolio_spec in spec.portfolios:
		# Backtest portfolios name the ``'paper'`` venue — the ONE name for the
		# simulated fill engine across backtest and live-paper — and pass ``venue_name``
		# EXPLICITLY as well as ``exchange``, so a backtest portfolio and a live
		# portfolio are structurally identical at creation. ``portfolio.py`` derives
		# ``self.exchange`` from ``venue_name`` when supplied, so the routing key is
		# ``('paper', DEFAULT_ACCOUNT_ID)`` either way; the explicit field is about
		# honesty of identity, not routing.
		#
		# The portfolio's exchange string is carried onto its orders, so using
		# spec.ticker here would route to an unregistered venue and produce no fills.
		pid = engine.portfolio_handler.add_portfolio(
			name=portfolio_spec.name,
			exchange='paper',
			venue_name='paper',
			cash=portfolio_spec.cash,
		)
		portfolio_ids.append(pid)

	for strategy in spec.strategies:
		for pid in portfolio_ids:
			strategy.subscribe_portfolio(pid)

	return BacktestTradingSystem(engine=engine, runner=runner)
