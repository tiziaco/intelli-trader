import queue
from datetime import datetime

from itrader.events_handler.full_event_handler import EventHandler
from itrader.price_handler.data_provider import PriceHandler
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.trading_system.simulation.ping_generator import PingGenerator
from itrader.universe.dynamic import DynamicUniverse
from itrader.reporting.statistics import StatisticsReporting

from itrader import logger
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
		self.exchange = exchange

		self.start_date = start_date
		self.end_date = end_date
		self.to_sql = to_sql

		self.global_queue = queue.Queue()
		self.price_handler = PriceHandler(self.exchange, [], '', start_date, end_dt = end_date)
		self.universe = DynamicUniverse(self.price_handler, self.global_queue)
		self.strategies_handler = StrategiesHandler(self.global_queue, self.price_handler)
		self.screeners_handler = ScreenersHandler(self.global_queue, self.price_handler)
		self.portfolio_handler = PortfolioHandler(self.global_queue)
		self.order_handler = OrderHandler(self.global_queue, self.portfolio_handler)
		self.execution_handler = ExecutionHandler(self.global_queue)
		self.ping = PingGenerator()
		#self.reporting = StatisticsReporting()
		self.event_handler = EventHandler(
			self.strategies_handler,
			self.screeners_handler,
			self.portfolio_handler,
			self.order_handler,
			self.execution_handler,
			self.universe,
			self.global_queue
		)


	def _initialise_backtest_session(self):
		"""
		Load the data in the price handler and define the pings vector
		for the for-loop iteration.
		"""
		logger.info('TRADING SYSTEM: Initialising backtest session')

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

		logger.info('    RUNNING BACKTEST   ')
		start_time = datetime.now()  # Capture start time

		for ping_event in self.ping:
			self.global_queue.put(ping_event)
			self.event_handler.process_events()
			self.portfolio_handler.record_metrics(ping_event.time)
		logger.info('    BACKTEST COMPLETED   ')
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
