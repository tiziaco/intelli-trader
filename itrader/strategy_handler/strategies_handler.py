from datetime import timedelta
from queue import Queue
from typing import Any

from itrader.core.enums import OrderType
from itrader.core.money import to_money
from itrader.core.sizing import TradingDirection
from itrader.price_handler.feed.base import BarFeed
from itrader.strategy_handler.base import Strategy
from itrader.events_handler.events import BarEvent, SignalEvent
from itrader.outils.time_parser import check_timeframe
from itrader.logger import get_itrader_logger


class StrategiesHandler(object):
	"""
	Manage all the strategies of the trading system.
	"""

	def __init__(self, global_queue: "Queue[Any]", feed: BarFeed) -> None:
		"""
		Parameters
		----------
		global_queue: `Queue object`
			The events queue of the trading system
		feed: `BarFeed`
			The look-ahead-safe market-data read model the strategy
			windows are served from (D-20).
		"""
		self.global_queue: "Queue[Any]" = global_queue
		self.feed: BarFeed = feed
		self.min_timeframe: timedelta = timedelta(weeks=100)
		#self.portfolios: dict = {}
		self.strategies: list[Strategy]= []

		self.logger = get_itrader_logger().bind(component="StrategiesHandler")
		self.logger.info('Strategies Handler initialized')

	def calculate_signals(self, event: BarEvent) -> None:
		"""
		Calculate the signal for every strategy to be traded.

		Before generating the signal check if the actual time
		is a multiple of the strategy's timeframe.

		The handler owns everything portfolio-shaped (D-12): it stamps
		time/price from the bar event, attaches the strategy's declared
		policy/direction, fans the intent out per subscribed portfolio,
		and enqueues — the strategy is a pure alpha function.

		Parameters
		----------
		event: `BarEvent object`
			The bar event of the trading system
		"""
		for strategy in self.strategies:
			# Check if the strategy's timeframe is a multiple of the bar event time
			if not check_timeframe(event.time, strategy.timeframe):
				continue
			# Calculate the signal for each ticker traded from the strategy
			for ticker in strategy.tickers:
				# WR-12 sparse-ticker guard (relocated from the legacy
				# Strategy._generate_signal): the ticker is absent from the
				# bar event (sparse universe, data gap) — no price means no
				# signal. The BarEvent payload contract (M5-02) keeps a
				# no-data ticker ABSENT from the dict. The guard precedes
				# generate_signal because the handler stamps price from
				# event.bars[ticker].close below. D-05: the duplicate absence
				# warning was removed — the feed's generate_bar_event is the
				# single span-aware observability owner (D-04); the strategy
				# handler is a pure consumer (missing bar = nothing to do this
				# tick). The skip below is LOAD-BEARING (price is stamped from
				# bar.close).
				bar = event.bars.get(ticker)
				if bar is None:
					continue
				# Push-based window delivery (D-20): asof comes ONLY from the
				# event — strategies never choose the as-of time (T-06-18).
				# Completed bars only; zero resample on this path (M5-03).
				data = self.feed.window(ticker, strategy.timeframe, strategy.max_window, asof=event.time)
				intent = strategy.generate_signal(ticker, data)
				if intent is None:
					continue
				# Relocated SignalEvent construction (D-12): one event per
				# subscribed portfolio. D-05 boundary parse: the strategy
				# string order_type is converted to the enum HERE. D-22 money
				# boundary: prices enter the Decimal domain HERE via to_money
				# (the D-04 string path) — the bar close is ALREADY Decimal
				# via the Bar struct (D-14): to_money(Decimal) is
				# value-identity. Absent SL/TP preserves the legacy default
				# exactly: to_money(0) == Decimal("0").
				for portfolio_id in strategy.subscribed_portfolios:
					signal = SignalEvent(
						time=event.time,
						order_type=OrderType(strategy.order_type),
						ticker=ticker,
						action=intent.action,
						price=to_money(bar.close),
						stop_loss=intent.stop_loss if intent.stop_loss is not None else to_money(0),
						take_profit=intent.take_profit if intent.take_profit is not None else to_money(0),
						strategy_id=strategy.strategy_id,
						portfolio_id=portfolio_id,
						sizing_policy=strategy.sizing_policy,
						direction=strategy.direction,
						allow_increase=strategy.allow_increase,
						max_positions=strategy.max_positions,
						exit_fraction=intent.exit_fraction,
						# WR-01: honor an explicit caller-supplied quantity. The
						# field is already Decimal | None (D-22 money domain) on
						# both SignalIntent and SignalEvent — no boundary parse.
						# None means "resolver decides" (the golden path).
						quantity=intent.quantity,
						# WR-06: read the typed declaration directly — sltp_policy
						# is now a real Strategy attribute, not a getattr hole.
						sltp_policy=strategy.sltp_policy,
					)
					self.global_queue.put(signal)
				self.logger.debug('Strategy signal (%s - %s %s)',
							strategy.strategy_id, ticker, intent.action)

	def get_strategies_universe(self) -> list[str]:
		"""
		Return a list with all the coins traded from the differents strategies.

		Returns
		-------
		traded_tickers: `list`
			List of strings with the traded symbols
		"""
		traded_tickers: list[str] = []
		for strategy in self.strategies:
			# Check if the strategy is trading pairs
			if strategy.tickers and isinstance(strategy.tickers[0], tuple):
				traded_tickers += [value for tuple in strategy.tickers for value in tuple]
			else:
				traded_tickers += strategy.tickers
				
		return list(set(traded_tickers))

	
	def add_strategy(self, strategy: Strategy) -> None:
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

		Raises
		------
		ValueError
			If the strategy declares any direction other than
			``TradingDirection.LONG_ONLY`` (D-08/D-09): shorting (LONG_SHORT
			and SHORT_ONLY alike) requires the margin/liquidation milestone.
			Until it lands, registration rejects the capability loudly instead
			of silently mis-handling un-margined shorts. SHORT_ONLY in
			particular has no cover arm in ``_resolve_signal_quantity`` (CR-01):
			a sanctioned BUY-cover would fall through to entry sizing and could
			net a SHORT_ONLY book LONG — so it must not be reachable yet.
		"""
		# D-08/D-09 registration guard: only LONG_ONLY is admissible until the
		# margin/liquidation milestone lands. This closes the SHORT_ONLY cover
		# hole (CR-01) at the door — the smaller, oracle-dark change: the golden
		# FractionOfCash/LONG_ONLY path is unaffected.
		if strategy.direction is not TradingDirection.LONG_ONLY:
			raise ValueError(
				"Only LONG_ONLY is admissible until the margin/liquidation "
				"milestone — shorting (LONG_SHORT / SHORT_ONLY) requires the "
				"margin model (D-08/D-09)"
			)

		# Add the strategy in the strategies list
		self.strategies.append(strategy)

		# Find the minimum timeframe
		self.min_timeframe = min([self.min_timeframe, strategy.timeframe])

		self.logger.info(f'New strategy added: {strategy.name}')
