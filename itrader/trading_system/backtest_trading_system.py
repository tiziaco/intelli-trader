"""Thin backtest holder + the ``build_backtest_system`` factory (D-03/D-04).

D-03: ``TradingSystem`` is renamed ``BacktestTradingSystem`` (symmetry with
``LiveTradingSystem``, matches the filename). Wave 4 (04-05) migrated all
existing import sites to the new name, so no backward-compat ``TradingSystem``
alias is exported from this module.

D-04: the factory builds, the class is a thin holder. ``build_backtest_system(spec)``
derives the COMPLETE symbol set and folds it into the spec's ``ExchangeConfig``
(D-13/Trap 1), builds the infra ``EngineContext(bus=FifoEventBus(),
environment='backtest', sql_engine=None)`` (02-03/D-06), calls the two-arg
``compose_engine`` seam, constructs the ``BacktestRunner``, adds
strategies/portfolios in spec order (Trap 6), wires subscriptions, and returns the
holder. The handlers now OWN their order/signal storage backends (selected from
``ctx.environment``, 02-02), so the factory no longer selects those concretes.

The holder keeps a direct-construction ``__init__`` (legacy loose params) that
builds the same engine+runner internally, so the oracle/integration sites work
by renaming the class only (Wave 4 swaps them to the factory). Its ``run()``
delegates to the runner then lifts the metrics printout into ``reporting``
(W4-07).

Indentation: TABS (``trading_system/`` package convention).
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
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
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
from itrader.trading_system.backtest_runner import BacktestRunner
from itrader.trading_system.compose import Engine, compose_engine
from itrader.trading_system.engine_context import EngineContext
from itrader.trading_system.system_spec import SystemSpec
# 11.1-07 (D-04): the backtest joins the SAME venue path live uses. All four names are
# import-INERT — the registry runs no runtime imports, PaperVenuePlugin lazy-imports its
# SimulatedExchange inside build_bundle, ConnectorProvider is inert as of 11.1-01, and
# bundles.py is TYPE_CHECKING-only — so they belong at module top, not in a lazy body.
# tests/integration/test_okx_inertness.py is the check that this stays true.
from itrader.connectors.provider import ConnectorProvider
from itrader.venues.bundles import VenueBundles
from itrader.venues.paper_plugin import PaperVenuePlugin
from itrader.venues.registry import ExecutionVenueRegistry

from itrader.logger import get_itrader_logger


#: The default preset exchange symbols (the *USDT set) the complete supported-set
#: union starts from (D-13/Trap 1). BTCUSD (the golden ticker) is always unioned.
_DEFAULT_PRESET_SYMBOLS: frozenset[str] = frozenset(
	ExchangeConfig.default().limits.supported_symbols)


def _seed_supported_symbols(
	exchange_config: ExchangeConfig, tickers: "set[str]") -> ExchangeConfig:
	"""Fold the COMPLETE supported-symbol set into the exchange config (D-13/Trap 1).

	The final set = default preset symbols ∪ {BTCUSD} ∪ spec tickers (upper-cased).
	Seeded at construction so it is REPLACEMENT-SAFE — a later ``update_config``
	that re-derives ``_supported_symbols`` from ``config.limits`` can never wipe a
	symbol. This is the FACTORY-side derivation (Open Question 2) that keeps
	``compose_engine`` mode-agnostic.
	"""
	complete = set(_DEFAULT_PRESET_SYMBOLS) | {'BTCUSD'} | {t.upper() for t in tickers}
	exchange_config.limits.supported_symbols = complete
	return exchange_config


class BacktestTradingSystem(object):
	"""Thin holder of a pre-built ``Engine`` + ``BacktestRunner`` (D-03/D-04).

	The class ``__init__`` is a dumb holder: it stores the engine and runner and
	exposes ``run()``. The legacy direct-construction signature is retained for
	the oracle/integration sites (it builds the engine+runner internally via the
	same seam the factory uses) until Wave 4 migrates them to
	``build_backtest_system(spec)``.
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

		* **Factory mode (D-04):** ``build_backtest_system`` passes a pre-built
		  ``engine`` + ``runner``; the holder is a dumb wrapper.
		* **Legacy direct-construction mode:** the oracle/integration sites pass
		  the loose params; the holder builds the engine+runner internally via the
		  same ``compose_engine`` seam (byte-identical wiring) so they work by
		  renaming the class only (Wave 4 swaps them to the factory).

		``exchange`` names the run's VENUE and defaults to ``'paper'`` (D-05) —
		the ONE name for the simulated fill engine across backtest and
		live-paper. It is a HOLDER attribute only: routing reads each
		portfolio's own ``exchange``/``venue_name``, never this field, so the
		default is documentation of intent rather than a routing input.
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
			# Legacy direct-construction mode: build the engine+runner here using
			# the shared seam. The COMPLETE supported-symbol set is seeded into a
			# construction-time ExchangeConfig (default preset ∪ {BTCUSD} ∪ the
			# csv_paths tickers, upper-cased) via the same _seed_supported_symbols
			# path the factory uses — replacement-safe (D-13/Trap 1). csv_paths=None
			# is the single-golden-ticker default, so the seeded set is the preset ∪
			# {BTCUSD}, byte-identical to the old ExecutionHandler no-config fallback.
			tickers = {str(t).upper() for t in (csv_paths or {}).keys()}
			exchange_config = _seed_supported_symbols(
				ExchangeConfig.default(), tickers)
			# 02-03 (D-06/Pitfall 1): the oracle runs through THIS spec-LESS legacy
			# arm, so it is folded to the two-arg compose seam too. Synthesize a
			# minimal frozen SystemSpec — ticker/starting_cash are PLACEHOLDERS
			# compose NEVER reads (A1); strategies/portfolios stay empty (the legacy
			# sites add them via the backward-compat handler seams). The seeded
			# ExchangeConfig rides on spec.exchange. Empties map back to None inside
			# compose, byte-identical to the old csv_paths=None / start/end kwargs.
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
			# 06.1-01 (D-01/D-04): store + feed CONSTRUCTION moved out of the spec-free
			# compose seam onto the factory/legacy arm — built with the SAME argument
			# values compose used (data/start/end/timeframe off the synthesized spec,
			# empties->None) so the run stays byte-identical, then injected onto ctx.
			store = CsvPriceStore(
				csv_paths=spec.data or None,
				start_date=spec.start or None,
				end_date=spec.end or None)
			feed = BacktestBarFeed(store, to_timedelta(spec.timeframe))
			# 11.1-04 (D-07): the ONE seeded determinism RNG is built HERE, at the wiring
			# seam, and injected on ctx — it is no longer derived inside ExecutionHandler.
			# Same resolution ExecutionHandler._resolve_rng_seed performed (int off the
			# process-wide config.rng_seed, default 42), so the seed and the instance count
			# are unmoved and the run stays byte-exact. Exactly ONE per run: the exchange
			# and its slippage model (and from D-06 the venue plugin that builds them) all
			# draw from this object.
			rng = random.Random(int(config.rng_seed))
			# The handler now OWNS its bus (FifoEventBus — byte-exact FIFO, D-07) and
			# its storage (from environment='backtest'); config is carried, sql_engine
			# is None (SQL-import-inert, GATE-01). feed rides required on ctx, store real.
			ctx = EngineContext(
				bus=FifoEventBus(),
				config=config,
				environment='backtest',
				feed=feed,
				rng=rng,
				store=store,
				sql_engine=None,
			)
			# 11.1-07 (D-04/D-17): the LEGACY arm joins the same venue path live uses —
			# a real ExecutionVenueRegistry holding a PaperVenuePlugin built from THIS
			# run's seeded ExchangeConfig (never a default preset: the preset omits the
			# golden BTCUSD ticker and the exchange would refuse it), plus a REAL, EMPTY
			# ConnectorProvider. Empty is the representation of "this mode has no venue
			# sessions" — never None (D-04 rejects a nullable seam here).
			#
			# BOTH arms are migrated deliberately: the byte-exact oracle drives THIS
			# legacy arm, so migrating only the factory below would leave the oracle
			# proving nothing about the change (RESEARCH F-5).
			exec_registry = ExecutionVenueRegistry()
			exec_registry.register('paper', PaperVenuePlugin(spec.exchange))
			connectors = ConnectorProvider({})
			venue_bundles = VenueBundles(exec_registry, connectors, ctx)
			# 06.1-01 (D-04): spec-free compose — pass venue_bundles/results_store
			# explicitly (the legacy arm has no results store).
			self.engine = compose_engine(
				ctx, venue_bundles=venue_bundles, results_store=None)
			self.runner = BacktestRunner(self.engine)

		self.logger.info('Trading system initialised')

	# -- Backward-compat attribute seams (the engine holds the real components) --
	# The oracle/integration/e2e/scripts sites read these off the system directly
	# (system.strategies_handler.add_strategy, system.portfolio_handler.add_portfolio,
	# system.store.read_bars, system.order_handler.cancel_order, ...). Expose them
	# as read-only properties delegating to the engine so those sites work by
	# renaming the class only (Wave 4 may collapse some onto the spec).

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

		Delegates the session setup + for-loop to the ``BacktestRunner`` (the
		byte-exact ordering lives there, Trap 4). When ``print_summary`` is True
		(the default) it calls ``reporting.print_metrics_summary`` after the run
		(W4-07 — display only, no artifact bytes change; oracle-inert).

		``on_tick`` (Phase 6, D-06) is an OPTIONAL per-bar operator hook. It is
		wrapped so the callback receives THIS holder (``system``) as its first
		argument — preserving the e2e ``on_tick(system, time_event)`` contract
		(the harness reaches ``system.order_handler`` from it). Default ``None`` is
		byte-exact (oracle-dark).

		``persist`` (RESULT-01, D-01/D-04) is the POST-LOOP results dump switch.
		It defaults to ``False`` — the run loop touches NO SQL and the dump code is
		never reached, so the SMA_MACD oracle stays byte-exact and the path stays
		SQL-import-inert (GATE-01). When True (and a results store was injected at
		composition, D-03), a complete ``RunRecord`` + artifact frames are assembled
		from post-run portfolio state and written through the injected store AFTER
		the loop — structurally off the hot path.
		"""
		wrapped: Optional[Callable[[Any, Any], None]] = None
		if on_tick is not None:
			def wrapped(_runner: Any, time_event: Any) -> None:
				on_tick(self, time_event)

		self.runner.run(on_tick=wrapped)

		# POST-LOOP results dump (D-01): structurally after the run loop, guarded by
		# ``persist`` so the default path executes no dump code at all (byte-exact,
		# GATE-01). The D-03 store guard lives first inside ``_persist_results``.
		if persist:
			self._persist_results()

		if print_summary:
			# 260623-ajs: assemble the three run-level header inputs from
			# reachable handles, then pass them to the enriched printer.
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

		The POST-LOOP dump (D-01/D-05/D-06/D-13). Guard first (D-03): persistence
		requires a results store injected at composition. Then, for each active
		portfolio, build its run-artifact frames (the SAME pure ``reporting.frames``
		builders the print block uses), compute its per-portfolio ``RunMetrics`` and
		curate its strategy ``params``; assemble the AGGREGATE ``RunMetrics`` from the
		multi-portfolio aggregate equity curve (D-14, mixed-timeframe-safe) and the
		concatenated trades; curate the run-level ``settings`` (credential-free, the
		02-02 serializer); and write ``runs`` + ``run_portfolios`` atomically plus the
		equity_curve/trade_log artifacts. ``run_id`` is a single-UUIDv7 idgen value
		(the stable ORDER BY tiebreak).

		Dump-failure policy (D-17): a write failure re-raises when the store's
		``strict_persist`` is True; otherwise it is logged-and-swallowed so a sweep
		never loses good in-memory runs to one bad write.
		"""
		# D-03 — persistence requires a store injected at composition (clear error).
		store = self.engine.results_store
		if store is None:
			raise ConfigurationError(
				"results_store",
				reason="run(persist=True) requires a results store injected at composition")

		# WR-02 — short-circuit when there are NO active portfolios. The aggregate
		# builder runs build_aggregate_equity_curve([]) -> pd.concat([], axis=1) ->
		# ValueError, which would propagate out of run() even with strict_persist=False,
		# contradicting the D-17 swallow policy. There is nothing to dump anyway, so
		# warn-and-return before any assembly.
		active = list(self.portfolio_handler.get_active_portfolios())
		if not active:
			self.logger.warning(
				"persist requested but no active portfolios; nothing to dump")
			return

		run_id = idgen.generate_run_id()

		# WR-02 — the ENTIRE assembly+write body lives inside the strict_persist-gated
		# try/except, NOT just the store writes. D-17 promises a persist failure is
		# re-raised only when strict_persist is True; otherwise it is logged-and-swallowed
		# so a sweep never loses good in-memory runs to one bad dump. A builder failure
		# (metrics/serializer) is just as much a "persist failure" as a write failure and
		# must honour the same contract — so the whole body is guarded.
		try:
			# Map each active portfolio -> the strategies subscribed to it (mirror the
			# strategy/subscribed_portfolios walk the print block already performs).
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

			# Aggregate metrics across portfolios (D-14): the aggregate equity curve is a
			# total_equity Series indexed by timestamp; to_frame() yields the total_equity
			# column build_run_metrics reads, reset_index() yields the persistable frame.
			aggregate_series = build_aggregate_equity_curve(equity_frames)
			aggregate_equity_frame = aggregate_series.reset_index()
			aggregate_trades = (
				pd.concat(trades_frames, ignore_index=True)
				if trades_frames else pd.DataFrame())
			periods = annual_periods(timeframe_aliases)
			aggregate_metrics = build_run_metrics(
				aggregate_series.to_frame(), aggregate_trades, periods=periods)

			# Curated run settings (D-11, credential-free): the fee/slippage models are
			# read off the LIVE paper exchange; market_execution off the order handler.
			exchange = self.execution_handler.exchanges.get(
				('paper', DEFAULT_ACCOUNT_ID))  # D-27/D-05 pair key
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

			# Write (D-13/D-17): runs + run_portfolios atomically, then the artifacts.
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
		"""Return the signals captured during the run (Plan 05-03, SIG-02).

		Post-run read-model accessor (D-12): reads the handler-owned signal-store
		sink AFTER the run completes (D-03 — reached through its owning handler,
		``engine.strategies_handler.signal_store``, not a re-surfaced holder copy).
		A sink read, NOT a cross-domain handler call — the queue-only contract is
		preserved.
		"""
		return self.engine.strategies_handler.signal_store.get_all()

	def get_signal_store(self) -> SignalStore:
		"""Return the signal-store itself for post-run filtered queries (SIG-02).

		Reaches the store through its owning handler (D-03).
		"""
		return self.engine.strategies_handler.signal_store


def build_backtest_system(spec: SystemSpec) -> BacktestTradingSystem:
	"""Build a backtest system from a declarative ``SystemSpec`` (D-04).

	The FACTORY (D-14a): derives the COMPLETE supported-symbol set from the spec
	data keys (∪ default preset ∪ {BTCUSD}) and folds it into the spec's
	``ExchangeConfig`` (D-13/Trap 1), builds the infra ``EngineContext`` (a fresh
	``FifoEventBus`` + ``environment='backtest'`` + ``sql_engine=None``, 02-03/D-06),
	calls the shared two-arg ``compose_engine`` seam, constructs the
	``BacktestRunner``, adds strategies/portfolios in SPEC ORDER (Trap 6 — preserve
	``get_active_portfolios`` insertion order), wires the portfolio subscriptions,
	and returns the thin holder. The handlers OWN their order/signal storage
	backends now (selected from ``ctx.environment``, 02-02).
	"""
	# 1. Complete symbol-set seeding (D-13/Trap 1): default preset ∪ {BTCUSD} ∪
	#    spec data tickers, folded into the spec's ExchangeConfig BEFORE the
	#    exchange reads it (replacement-safe construction-time seeding). SystemSpec
	#    is frozen, so the seeded exchange rides back onto the spec via
	#    ``dataclasses.replace`` — compose reads ``spec.exchange`` (02-03 A1). The
	#    handlers now OWN their storage backends (from environment='backtest'), so
	#    the factory no longer selects order/signal storage concretes here (02-02).
	exchange_config = spec.exchange if spec.exchange is not None else ExchangeConfig.default()
	tickers = {str(t) for t in spec.data.keys()}
	exchange_config = _seed_supported_symbols(exchange_config, tickers)
	spec = dataclasses.replace(spec, exchange=exchange_config)

	# 2. Wire the graph mode-agnostically through the shared two-arg seam. compose
	#    reads the OPTIONAL results store off the spec via getattr (D-04/D-19,
	#    GATE-01): commonly None, so the oracle path stays store-free AND
	#    SQL-import-inert — this module imports NO SQL surface at top level. A
	#    persistence caller builds the store DIRECTLY (NO factory, D-19) and injects
	#    it on the spec, e.g. ``SqlResultsStore(SqlEngine(SqlSettings.results_default()),
	#    strict_persist=SqlSettings.results_default().strict_persist)`` with the SQL
	#    surface imported on THAT path only — never here.
	# 06.1-01 (D-01/D-04): build the store + feed read-models HERE (the spec-free
	# compose seam no longer constructs them) with the SAME argument values compose
	# used off the spec (data/start/end/timeframe, empties->None) — byte-identical —
	# and inject them onto ctx (feed required, store real in backtest).
	store = CsvPriceStore(
		csv_paths=spec.data or None,
		start_date=spec.start or None,
		end_date=spec.end or None)
	feed = BacktestBarFeed(store, to_timedelta(spec.timeframe))
	# 11.1-04 (D-07): the ONE seeded determinism RNG, built here at the wiring seam and
	# injected on ctx (identical two lines as the legacy arm above — BOTH arms migrate,
	# because the oracle drives the legacy arm and would otherwise pass while proving
	# nothing about this one). Same seed resolution as the retired
	# ExecutionHandler._resolve_rng_seed: int(config.rng_seed), default 42.
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
	# 11.1-07 (D-04/D-17): the FACTORY arm registers the paper venue plugin with the
	# seeded, RUN-DERIVED ExchangeConfig (spec.exchange, complete symbol set already
	# folded in above) and passes a REAL, EMPTY ConnectorProvider — the backtest has
	# no venue sessions, and an empty collection is that fact, never None (D-04).
	# Identical two blocks in both arms; see the legacy arm for why both migrate.
	exec_registry = ExecutionVenueRegistry()
	exec_registry.register('paper', PaperVenuePlugin(spec.exchange))
	connectors = ConnectorProvider({})
	venue_bundles = VenueBundles(exec_registry, connectors, ctx)
	# 06.1-01 (D-04): spec-free compose — pass venue_bundles + the OPTIONAL
	# results_store explicitly. The e2e ScenarioSpec is the SystemSpec alias and
	# carries results_store; getattr keeps a duck-typed spec absent-field safe
	# (-> None -> store-free/byte-exact).
	engine = compose_engine(
		ctx,
		venue_bundles=venue_bundles,
		results_store=getattr(spec, 'results_store', None))
	runner = BacktestRunner(engine)

	# 4. Add strategies/portfolios in SPEC ORDER (Trap 6 — get_active_portfolios
	#    is dict-insertion order; preserve it). Then wire subscriptions: each
	#    strategy subscribes to every spec portfolio (the e2e harness convention).
	for strategy in spec.strategies:
		engine.strategies_handler.add_strategy(strategy)

	portfolio_ids = []
	for portfolio_spec in spec.portfolios:
		# D-05/D-19: backtest portfolios name the ``'paper'`` venue — the ONE
		# name for the simulated fill engine across backtest and live-paper —
		# and pass ``venue_name`` EXPLICITLY as well as ``exchange``, so a
		# backtest portfolio and a live portfolio are structurally identical at
		# creation. ``portfolio.py`` derives ``self.exchange`` from
		# ``venue_name`` when supplied, so the routing key is
		# ``('paper', DEFAULT_ACCOUNT_ID)`` either way; the explicit field is
		# about honesty of identity, not routing.
		# The portfolio's exchange string is carried onto its orders. Using
		# spec.ticker here would route to an unregistered venue → no fills
		# (byte-exact break); every construction site (oracle/integration/
		# scripts + the e2e scenarios) names the paper venue, so the factory
		# must too.
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
