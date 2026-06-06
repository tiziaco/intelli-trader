import queue
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from itrader.core.clock import BacktestClock
from itrader.events_handler.full_event_handler import EventHandler
from itrader.price_handler.data_provider import PriceHandler
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.trading_system.simulation.time_generator import TimeGenerator
from itrader.universe.dynamic import DynamicUniverse
from itrader.reporting.statistics import StatisticsReporting

from itrader.logger import get_itrader_logger
from itrader.events_handler.events import EventType


class TradingSystem(object):
	"""
	Enscapsulates the settings and components for
	carrying out either a backtest session.
	"""
	def __init__(
		self, exchange: str = 'binance',
		start_date: Optional[str] = None,
		end_date: str = '',
		to_sql: bool = False,
	) -> None:
		"""
		Set up the backtest variables according to
		what has been passed in.
		"""
		self.logger = get_itrader_logger().bind(component="Engine")
		self.exchange = exchange

		self.start_date = start_date
		self.end_date = end_date
		self.to_sql = to_sql

		self.global_queue: "queue.Queue[Any]" = queue.Queue()

		# Determinism seam (D-09/D-10): an injected BacktestClock that returns the
		# advanced simulation/bar time instead of wall-clock. M2a STAGES the seam —
		# it is constructed here and advanced (set_time) on every ping in the run
		# loop — but it currently has NO domain consumer: clock.now() is read
		# nowhere, and every domain timestamp (order audit, transaction, cash,
		# metrics) still uses wall-clock. Wiring domain "now" reads onto this clock
		# is Phase 3 / M2b (D-09/D-10). Backtest RESULT determinism holds today
		# because the result-bearing path is fed ping_event.time explicitly (see
		# record_metrics in _run_backtest), not via clock.now(). The perf-telemetry
		# datetime.now() in _run_backtest stays wall-clock (D-09 — run duration is
		# not a domain fact).
		self.clock = BacktestClock()

		self.price_handler = PriceHandler(self.exchange, [], '', start_date or '', end_dt = end_date)
		self.universe = DynamicUniverse(self.price_handler, self.global_queue)
		self.strategies_handler = StrategiesHandler(self.global_queue, self.price_handler)
		# ScreenersHandler is a deferred subsystem (D-screener, ignore_errors override)
		# so its constructor is untyped to the gate.
		self.screeners_handler = ScreenersHandler(self.global_queue, self.price_handler)  # type: ignore[no-untyped-call]
		self.portfolio_handler = PortfolioHandler(self.global_queue)

		# Execution handler is constructed BEFORE the order handler so the
		# admission gate's commission estimator can adapt the simulated
		# exchange's fee model (Plan 05-06, D-04). Construction-order only —
		# runtime communication stays queue-mediated.
		self.execution_handler = ExecutionHandler(self.global_queue)

		# Commission estimator for the admission cash-reservation gate
		# (Plan 05-06, D-04): an adapter shaped (quantity, price) -> Decimal
		# over the simulated exchange's fee model, INJECTED so order_manager
		# never imports across the execution boundary (RESEARCH Pattern 1).
		# fee_model is read at call time — update_config may rebuild it. The
		# golden run pins fees 0 (ZeroFeeModel default), so the estimate is 0
		# and the reservation equals price x quantity exactly (value-preserving).
		simulated_exchange = self.execution_handler.exchanges.get('simulated')

		def _estimate_commission(quantity: Decimal, price: Decimal) -> Decimal:
			if not isinstance(simulated_exchange, SimulatedExchange):
				return Decimal("0")
			return simulated_exchange.fee_model.calculate_fee(
				quantity, price, side="buy", order_type="market")

		# Create order storage for backtesting (in-memory)
		order_storage = OrderStorageFactory.create('backtest')
		self.order_handler = OrderHandler(self.global_queue, self.portfolio_handler, order_storage,
		                                  commission_estimator=_estimate_commission)
		self.time_generator = TimeGenerator()
		self.reporting = StatisticsReporting(
			self.portfolio_handler,
			self.price_handler)
		self.event_handler = EventHandler(
			self.strategies_handler,
			self.screeners_handler,
			self.portfolio_handler,
			self.order_handler,
			self.execution_handler,
			self.universe,
			self.global_queue
		)

		self.logger.info('Trading system initialised')


	def _initialise_backtest_session(self) -> None:
		"""
		Load the data in the price handler and define the pings vector
		for the for-loop iteration.
		"""
		self.logger.info('Initialising backtest session')

		self.universe.init_universe(
			self.strategies_handler.get_strategies_universe(),
			# D-screener deferred subsystem (ignore_errors override) — untyped to the gate.
			self.screeners_handler.get_screeners_universe())  # type: ignore[no-untyped-call]
		self.price_handler.set_symbols(self.universe.get_full_universe())
		self.price_handler.set_timeframe(self.strategies_handler.min_timeframe,
										self.screeners_handler.min_timeframe)
		self.price_handler.load_data()
		self.time_generator.set_dates(next(iter(self.price_handler.prices.items()))[1].index)
		#self.reporting.prices = self.price_handler.prices

	def _run_backtest(self) -> None:
		"""
		Carries out an for-loop that polls the
		events queue and directs each event to either the
		strategy component of the execution handler. The
		loop continue until the time series is completed
		"""

		self.logger.info('    RUNNING BACKTEST   ')
		start_time = datetime.now()  # Capture start time

		for time_event in self.time_generator:
			# Advance the injected clock to the current simulation/bar time to keep
			# the determinism seam staged. NOTE: the clock has no domain consumer
			# yet — clock.now() is read nowhere; consumer-wiring is Phase 3 / M2b
			# (D-09/D-10). Result determinism comes from passing time_event.time
			# explicitly to record_metrics below, not from clock.now().
			self.clock.set_time(time_event.time)
			self.global_queue.put(time_event)
			self.event_handler.process_events()
			for portfolio in self.portfolio_handler.get_active_portfolios():
				portfolio.record_metrics(time_event.time)
		self.logger.info('    BACKTEST COMPLETED   ')
		end_time = datetime.now()  # Capture end time
		duration = end_time - start_time
		print("Backtest duration:", duration)

	def run(self, print_summary: bool = False) -> None:
		"""
		Runs the backtest and print out the backtest statistics
		at the end of the simulation.
		"""
		self._initialise_backtest_session()
		self._run_backtest()

		if print_summary:
			# Dormant summary path: StatisticsReporting is a deferred D-sql/reporting
			# subsystem (ignore_errors override) with the known-broken _prepare_data
			# path (STATE.md 01-04); the working backtest runs print_summary=False.
			self.reporting.calculate_statistics()  # type: ignore[no-untyped-call,call-arg]
			self.reporting.print_summary()

		# Close the logger file
		#file_handler.close()
		# Close the SQL connection
		#self.sql_engine.dispose() # Close all checked in sessions
