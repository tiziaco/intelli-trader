import queue
from datetime import datetime

from itrader.events_handler.event_handler import EventEngine
from itrader.price_handler.CCXT_data_provider import CCXT_data_provider
from itrader.universe.dynamic import DynamicUniverse
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.trading_system.simulation.ping_generator import PingGenerator
from itrader.reporting.statistics import StatisticsReporting

from itrader import logger
from itrader.events_handler.event import EventType


class TradingSystem(object):
	"""
	Enscapsulates the settings and components for
	carrying out either a backtest or live trading session.
	"""
	def __init__(
		self, exchange='binance', universe = 'static',
		init_cash = None,
		start_date=None, end_date='',
		session_type='backtest',
		price_handler=None,
		to_sql = False,
	):
		"""
		Set up the backtest variables according to
		what has been passed in.
		"""
		self.session_type = session_type
		self.exchange = exchange
		self.uni_type = universe

		self.init_cash = init_cash
		self.start_date = start_date
		self.end_date = end_date
		self.to_sql = to_sql

		self.global_queue = queue.Queue()
		self.price_handler = price_handler
		self.universe = None
		self.strategies_handler = None
		self.screeners_handler = None
		self.engine = None
		self.ping = None
		self.reporting = None
		
		self._initialize_trading_system()
		self.cur_time = None


	def _initialize_trading_system(self):
		"""
		Initialises the necessary modules used
		within the session.
		"""

		# Define  price handler
		if self.price_handler is None:
			self.price_handler = CCXT_data_provider(self.exchange, start_dt= self.start_date, 
													end_dt='', global_queue=self.global_queue)

		# Define trading engine module
		self.engine = EventEngine(self.price_handler, self.global_queue, self.session_type, self.exchange, self.init_cash,
								  to_sql=self.to_sql)

		# Define the Universe module
		self.universe = DynamicUniverse(self.price_handler, self.global_queue, self.uni_type)

		# Define the strategies module
		self.strategies_handler = StrategiesHandler(self.global_queue, self.price_handler)

		# Define the screeners handler
		self.screeners_handler = ScreenersHandler(self.global_queue, self.price_handler)

		# Define ping generator
		self.ping = PingGenerator()

		# Statistical reporting module
		self.reporting = StatisticsReporting(self.engine.engine_logger)

	def _process_ping(self):
		"""
		When a ping is generated from the ping simulator or the live
		price streamer, execute it.
		"""

		while not self.global_queue.empty() :
			
			try:
				event = self.global_queue.get(False)
			except queue.Empty:
				event = None
			if event.type == EventType.PING:
				self.universe.generate_bars(event)
			elif event.type == EventType.BAR:
				logger.info('UNIVERSE - New bar %s', event.time)
				self.engine.portfolio_handler.update_portfolio_value(event)
				self.engine.order_handler.check_pending_orders(event)
				self.engine._process_signal() # Process eventual stop or limit order signal
				if self.uni_type == 'dynamic':
					self.screeners_handler.apply_screeners(event)
					# TEMPORARY: al momento non considera lo screener
					self.strategies_handler.assign_symbol(self.screeners_handler.get_proposed_symbols())
					###
					self.universe.assign_assets(self._get_assets())
					event = self.universe.update_bars(event)

				self.strategies_handler.calculate_signals(event)
			elif event.type == EventType.SIGNAL:
				self.engine.engine_queue.put(event)
				self.engine._process_signal()
			else:
				raise NotImplemented('Unsupported event type %s' % event.type)
			#self.engine.portfolio_handler.record_portfolios_metrics(time)

	def _run_backtest(self):
		"""
		Carries out an for-loop that polls the
		events queue and directs each event to either the
		strategy component of the execution handler. The
		loop continue until the ping series is completed
		"""

		logger.info('    RUNNING BACKTEST   ')

		for ping_event in self.ping:
			self.global_queue.put(ping_event)
			self._process_ping()
			self.engine.portfolio_handler.record_portfolios_metrics(ping_event.time)
			
		logger.info('    BACKTEST COMPLETED   ')
	
	
	def _get_traded_symbols(self):
		sym1 = self.strategies_handler.get_traded_symbols()
		sym2 = self.screeners_handler.get_screener_universe()
		return (sym1+sym2)
	
	def _get_assets(self):
		"""
		Return a list of string with the tickers traded from the 
		strategies and the opened positions in the portfolio
		"""
		sym1 = self.engine._get_opened_positions()
		sym2 = self.strategies_handler.get_traded_symbols()
		unique_assetts = list(set(sym1+sym2))
		return unique_assetts

	def _initialise_backtest_session(self):
		"""
		Load the data in the price handler and define the pings vector
		for the for-loop iteration.
		"""
		logger.info('TRADING SYSTEM: Initialising backtest session')

		self.universe.assign_assets(self.strategies_handler.get_traded_symbols())
		self.price_handler.set_symbols(self._get_traded_symbols())
		self.price_handler.set_timeframe(self.strategies_handler.min_timeframe[1])
		self.price_handler.download_data()
		self.ping.set_dates(next(iter(self.price_handler.prices.items()))[1].index)
		self.reporting.prices = self.price_handler.prices

	def start(self, print_summary=False):
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
