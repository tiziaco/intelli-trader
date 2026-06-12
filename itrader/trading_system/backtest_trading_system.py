"""Thin backtest holder + the ``build_backtest_system`` factory (D-03/D-04).

D-03: ``TradingSystem`` is renamed ``BacktestTradingSystem`` (symmetry with
``LiveTradingSystem``, matches the filename). A backward-compat ``TradingSystem``
alias is retained so existing import sites (oracle/integration/conftest/scripts)
keep working until Wave 4 (04-05) migrates them.

D-04: the factory builds, the class is a thin holder. ``build_backtest_system(spec)``
selects the mode-specific backends (``OrderStorageFactory.create('backtest')`` +
the backtest signal store, D-14a), derives the COMPLETE symbol set and folds it
into the spec's ``ExchangeConfig`` (D-13/Trap 1), calls ``compose_engine``,
constructs the ``BacktestRunner``, adds strategies/portfolios in spec order
(Trap 6), wires subscriptions, and returns the holder.

The holder keeps a direct-construction ``__init__`` (legacy loose params) that
builds the same engine+runner internally, so the oracle/integration sites work
by renaming the class only (Wave 4 swaps them to the factory). Its ``run()``
delegates to the runner then lifts the metrics printout into ``reporting``
(W4-07).

Indentation: TABS (``trading_system/`` package convention).
"""

from pathlib import Path
from typing import Any, Callable, Optional

from itrader.config import ExchangeConfig, OrderConfig, get_exchange_preset
from itrader.order_handler.storage import OrderStorageFactory
from itrader.reporting.summary import print_metrics_summary
from itrader.strategy_handler.storage import SignalStorageFactory, SignalStore
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.trading_system.backtest_runner import BacktestRunner
from itrader.trading_system.compose import Engine, compose_engine
from itrader.trading_system.system_spec import SystemSpec

from itrader.logger import get_itrader_logger


#: The default preset exchange symbols (the *USDT set) the complete supported-set
#: union starts from (D-13/Trap 1). BTCUSD (the golden ticker) is always unioned.
_DEFAULT_PRESET_SYMBOLS: frozenset[str] = frozenset(
	get_exchange_preset('default').limits.supported_symbols)


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
		self, exchange: str = 'binance',
		start_date: Optional[str] = None,
		end_date: str = '',
		to_sql: bool = False,
		timeframe: str = '1d',
		csv_paths: dict[str, "str | Path"] | None = None,
		*,
		engine: Optional[Engine] = None,
		runner: Optional[BacktestRunner] = None,
		signal_store: Optional[SignalStore] = None,
	) -> None:
		"""Construct the holder.

		Two construction modes:

		* **Factory mode (D-04):** ``build_backtest_system`` passes a pre-built
		  ``engine`` + ``runner`` (+ ``signal_store``); the holder is a dumb
		  wrapper.
		* **Legacy direct-construction mode:** the oracle/integration sites pass
		  the loose params; the holder builds the engine+runner internally via the
		  same ``compose_engine`` seam (byte-identical wiring) so they work by
		  renaming the class only (Wave 4 swaps them to the factory).
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
			self._signal_store = signal_store or engine.signal_store
		else:
			# Legacy direct-construction mode: build the engine+runner here using
			# the shared seam. exchange_config=None lets the ExecutionHandler build
			# the TEMPORARY default-preset ∪ {BTCUSD} backward-compat config so the
			# direct-construction symbol set stays byte-exact (Trap 1).
			order_storage = OrderStorageFactory.create('backtest')
			self._signal_store = SignalStorageFactory.create('backtest')
			self.engine = compose_engine(
				order_storage=order_storage,
				signal_store=self._signal_store,
				csv_paths=csv_paths,
				start_date=start_date,
				end_date=end_date or None,
				timeframe=timeframe,
				exchange_config=None,
				order_config=OrderConfig.default(),
			)
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
			on_tick: Optional[Callable[["BacktestTradingSystem", Any], None]] = None) -> None:
		"""Run the backtest, then optionally print the lifted metrics summary.

		Delegates the session setup + for-loop to the ``BacktestRunner`` (the
		byte-exact ordering lives there, Trap 4). When ``print_summary`` is True
		(the default) it calls ``reporting.print_metrics_summary`` after the run
		(W4-07 — display only, no artifact bytes change; oracle-inert).

		``on_tick`` (Phase 6, D-06) is an OPTIONAL per-bar operator hook. It is
		wrapped so the callback receives THIS holder (``system``) as its first
		argument — preserving the e2e ``on_tick(system, time_event)`` contract
		(the harness reaches ``system.order_handler`` from it). Default ``None`` is
		byte-exact (oracle-dark).
		"""
		wrapped: Optional[Callable[[Any, Any], None]] = None
		if on_tick is not None:
			def wrapped(_runner: Any, time_event: Any) -> None:
				on_tick(self, time_event)

		self.runner.run(on_tick=wrapped)

		if print_summary:
			print_metrics_summary(
				self.portfolio_handler.get_active_portfolios(), self.logger)

	def get_signal_records(self) -> list[SignalRecord]:
		"""Return the signals captured during the run (Plan 05-03, SIG-02).

		Post-run read-model accessor (D-12): reads the injected signal-store sink
		AFTER the run completes. A sink read, NOT a cross-domain handler call — the
		queue-only contract is preserved.
		"""
		return self._signal_store.get_all()

	def get_signal_store(self) -> SignalStore:
		"""Return the signal-store itself for post-run filtered queries (SIG-02)."""
		return self._signal_store


def build_backtest_system(spec: SystemSpec) -> BacktestTradingSystem:
	"""Build a backtest system from a declarative ``SystemSpec`` (D-04).

	The FACTORY (D-14a): selects the mode-specific backends
	(``OrderStorageFactory.create('backtest')`` + the backtest signal store),
	derives the COMPLETE supported-symbol set from the spec data keys (∪ default
	preset ∪ {BTCUSD}) and folds it into the spec's ``ExchangeConfig``
	(D-13/Trap 1), calls the shared ``compose_engine`` seam with those concretes,
	constructs the ``BacktestRunner``, adds strategies/portfolios in SPEC ORDER
	(Trap 6 — preserve ``get_active_portfolios`` insertion order), wires the
	portfolio subscriptions, and returns the thin holder.
	"""
	# 1. Mode-specific backend selection (D-14a) — lives in the FACTORY.
	order_storage = OrderStorageFactory.create('backtest')
	signal_store = SignalStorageFactory.create('backtest')

	# 2. Complete symbol-set seeding (D-13/Trap 1): default preset ∪ {BTCUSD} ∪
	#    spec data tickers, folded into the spec's ExchangeConfig BEFORE the
	#    exchange reads it (replacement-safe construction-time seeding).
	exchange_config = spec.exchange if spec.exchange is not None else get_exchange_preset('default')
	tickers = {str(t) for t in spec.data.keys()}
	exchange_config = _seed_supported_symbols(exchange_config, tickers)

	# 3. Wire the graph mode-agnostically through the shared seam.
	engine = compose_engine(
		order_storage=order_storage,
		signal_store=signal_store,
		csv_paths=spec.data,
		start_date=spec.start,
		end_date=spec.end or None,
		timeframe=spec.timeframe,
		exchange_config=exchange_config,
		order_config=OrderConfig.default(),
	)
	runner = BacktestRunner(engine)

	# 4. Add strategies/portfolios in SPEC ORDER (Trap 6 — get_active_portfolios
	#    is dict-insertion order; preserve it). Then wire subscriptions: each
	#    strategy subscribes to every spec portfolio (the e2e harness convention).
	for strategy in spec.strategies:
		engine.strategies_handler.add_strategy(strategy)

	portfolio_ids = []
	for portfolio_spec in spec.portfolios:
		pid = engine.portfolio_handler.add_portfolio(
			user_id=portfolio_spec.user_id,
			name=portfolio_spec.name,
			exchange=spec.ticker if spec.ticker else 'csv',
			cash=portfolio_spec.cash,
		)
		portfolio_ids.append(pid)

	for strategy in spec.strategies:
		for pid in portfolio_ids:
			strategy.subscribe_portfolio(pid)

	return BacktestTradingSystem(
		engine=engine, runner=runner, signal_store=signal_store)


#: Backward-compat alias (D-03). Existing import sites
#: (``from ...backtest_trading_system import TradingSystem``) keep working until
#: Wave 4 (04-05) migrates them to ``BacktestTradingSystem`` /
#: ``build_backtest_system``.
TradingSystem = BacktestTradingSystem
