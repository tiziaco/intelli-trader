from datetime import timedelta
from queue import Queue

from itrader.price_handler.data_provider import PriceHandler
from itrader.strategy_handler.base import Strategy
from itrader.events_handler.event import BarEvent, PortfolioUpdateEvent
from itrader.outils.time_parser import check_timeframe
from itrader.logger import get_itrader_logger


class StrategiesHandler(object):
	"""
	Manage all the strategies of the trading system.
	"""

	def __init__(self, global_queue, price_handler):
		"""
		Parameters
		----------
		events_queue: `Queue object`
			The events queue of the trading system
		"""
		self.global_queue: Queue = global_queue
		self.price_handler: PriceHandler = price_handler
		self.min_timeframe: timedelta = timedelta(weeks=100)
		#self.portfolios: dict = {}
		self.strategies: list[Strategy]= []

		self.logger = get_itrader_logger().bind(component="StrategiesHandler")
		self.logger.info('Strategies Handler initialized')

	def calculate_signals(self, event: BarEvent):
		"""
		Calculate the signal for every strategy to be traded.

		Before generating the signal check if the actual time 
		is a multiple of the strategy's timeframe.

		Parameters
		----------
		event: `BarEvent object`
			The bar event of the trading system
		"""
		for strategy in self.strategies:
			# Check if the strategy's timeframe is a multiple of the bar event time
			if not check_timeframe(event.time, strategy.timeframe):
				continue
			# Calculate the signal for each ticker or pair traded from the strategy
			strategy.last_event = event
			for ticker in strategy.tickers:
				data = self.price_handler.get_resampled_bars(event.time, ticker, strategy.timeframe, strategy.max_window)
				strategy.calculate_signal(ticker, data)

	# def on_portfolio_update(self, update_event: PortfolioUpdateEvent):
	# 	"""
	# 	Update the information relative to the active portfolios.
	# 	"""
	# 	self.portfolios = update_event.portfolios

	def assign_symbol(self, signals):
		"""
		Take the proposed symbols from the screener and assign it to the strategy.
		If a proposed symbol is not in the strategy universe, remove it.

		Parameters
		----------
		signals: `list of str`
			List of the proposed symbol from the screener
		"""
		traded = self.strategies[0].tickers
		max_pos = self.strategies[0].settings['max_positions']
		
		# TEMPORARY:
		first_key = list(signals.keys())[0]
		proposed = signals[first_key]

		# Remove the symbols from the traded ones if not proposed by the screener
		new_traded = [elem for elem in traded if elem in proposed]

		# Remove the already traded symbols from the proposed ones
		new_proposed = [elem for elem in proposed if elem not in traded]

		# Assign the symbols to be traded to the strategy
		new_traded.extend(new_proposed[0:(max_pos - len(new_traded))])
		self.strategies[0].tickers = new_traded

		if new_traded:
			self.logger.info('Strategies Handler: new symbols for %s : %s', self.strategies[0].__str__(), str(new_traded))

	
	def get_strategies_universe(self):
		"""
		Return a list with all the coins traded from the differents strategies.

		Returns
		-------
		traded_tickers: `list`
			List of strings with the traded symbols
		"""
		traded_tickers = []
		for strategy in self.strategies:
			# Check if the strategy is trading pairs
			if strategy.tickers and isinstance(strategy.tickers[0], tuple):
				traded_tickers += [value for tuple in strategy.tickers for value in tuple]
			else:
				traded_tickers += strategy.tickers
				
		return list(set(traded_tickers))

	
	def add_strategy(self, strategy: Strategy):
		"""
		Add a new strategy in the list of strategies to trade.
		At the same time, calculate the minimum timeframe among 
		the different strategies to be traded. 
		This timeframe will be used from the price handler to 
		download historical prices
		
		Parameters
		----------
		strategy: `Strategy object`
			Strategy to be executed by the trading system
		"""
		# Add the strategy in the strategies list
		strategy.global_queue = self.global_queue
		self.strategies.append(strategy)

		# Find the minimum timeframe
		self.min_timeframe = min([self.min_timeframe, strategy.timeframe])

		self.logger.info(f'New strategy added: {strategy.name}')
