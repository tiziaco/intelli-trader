import queue
from datetime import datetime

from itrader.core.clock import BacktestClock
from itrader.events_handler.full_event_handler import EventHandler
from itrader.price_handler.data_provider import PriceHandler
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.trading_system.simulation.ping_generator import PingGenerator
from itrader.universe.dynamic import DynamicUniverse
from itrader.reporting.statistics import StatisticsReporting

from itrader.logger import get_itrader_logger
from itrader.events_handler.event import EventType


class TradingSystem(object):
	"""
	Enscapsulates the settings and components for
	carrying out either a backtest session.
	"""
	def __init__(
		self, exchange='binance',
		start_date = None,
		end_date = '',
		to_sql = False,
	):
		"""
		Set up the backtest variables according to
		what has been passed in.
		"""
		self.logger = get_itrader_logger().bind(component="Engine")
		self.exchange = exchange

		self.start_date = start_date
		self.end_date = end_date
		self.to_sql = to_sql

		self.global_queue = queue.Queue()

		# Determinism seam (D-09/D-10): an injected BacktestClock returns the
		# advanced simulation/bar time instead of wall-clock, so any engine-path
		# consumer of "now" reads deterministic simulation time. The run loop
		# advances it (set_time) on every ping/bar. M2a builds + advances the
		# mechanism here; M2b wires it into order/transaction timestamps. The
		# perf-telemetry datetime.now() in _run_backtest stays wall-clock (D-09 —
		# run duration is not a domain fact).
		self.clock = BacktestClock()

		self.price_handler = PriceHandler(self.exchange, [], '', start_date, end_dt = end_date)
		self.universe = DynamicUniverse(self.price_handler, self.global_queue)
		self.strategies_handler = StrategiesHandler(self.global_queue, self.price_handler)
		self.screeners_handler = ScreenersHandler(self.global_queue, self.price_handler)
		self.portfolio_handler = PortfolioHandler(self.global_queue)
		
		# Create order storage for backtesting (in-memory)
		order_storage = OrderStorageFactory.create('backtest')
		self.order_handler = OrderHandler(self.global_queue, self.portfolio_handler, order_storage)
		
		self.execution_handler = ExecutionHandler(self.global_queue)
		self.ping = PingGenerator()
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


	def _initialise_backtest_session(self):
		"""
		Load the data in the price handler and define the pings vector
		for the for-loop iteration.
		"""
		self.logger.info('Initialising backtest session')

		self.universe.init_universe(
			self.strategies_handler.get_strategies_universe(), 
			self.screeners_handler.get_screeners_universe())
		self.price_handler.set_symbols(self.universe.get_full_universe())
		self.price_handler.set_timeframe(self.strategies_handler.min_timeframe,
										self.screeners_handler.min_timeframe)
		self.price_handler.load_data()
		self.ping.set_dates(next(iter(self.price_handler.prices.items()))[1].index)
		#self.reporting.prices = self.price_handler.prices

	def _run_backtest(self):
		"""
		Carries out an for-loop that polls the
		events queue and directs each event to either the
		strategy component of the execution handler. The
		loop continue until the ping series is completed
		"""

		self.logger.info('    RUNNING BACKTEST   ')
		start_time = datetime.now()  # Capture start time

		for ping_event in self.ping:
			# Advance the injected clock to the current simulation/bar time so any
			# engine-path consumer of "now" reads deterministic time (D-09/D-10).
			self.clock.set_time(ping_event.time)
			self.global_queue.put(ping_event)
			self.event_handler.process_events()
			for portfolio in self.portfolio_handler.get_active_portfolios():
				portfolio.record_metrics(ping_event.time)
		self.logger.info('    BACKTEST COMPLETED   ')
		end_time = datetime.now()  # Capture end time
		duration = end_time - start_time
		print("Backtest duration:", duration)

	def run(self, print_summary=False):
		"""
		Runs the backtest and print out the backtest statistics
		at the end of the simulation.
		"""
		self._initialise_backtest_session()
		self._run_backtest()

		if print_summary:
			self.reporting.calculate_statistics()
			self.reporting.print_summary()

		# Close the logger file
		#file_handler.close()
		# Close the SQL connection
		#self.sql_engine.dispose() # Close all checked in sessions
