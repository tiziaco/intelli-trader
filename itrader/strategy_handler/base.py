import queue
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from itrader.core.enums import OrderType, Side
from itrader.core.ids import StrategyId
from itrader.events_handler.events import SignalEvent, BarEvent
from itrader.outils.time_parser import to_timedelta
from itrader import logger, idgen

class Strategy(ABC):
	"""
	BaseStrategy is a base class providing an interface for
	all subsequent (inherited) strategy objects.

	The goal of a (derived) Strategy object is to generate Signal
	objects for particular symbols based on the inputs of ticks
	generated from a PriceHandler (derived) object.
	"""
	def __init__(self, name: str, timeframe: str, tickers: list[str], order_type: str = "market",
			  	max_positions: int = 1, max_allocation: float = 0.80, allow_increase: bool = False,
				global_queue: "Optional[queue.Queue[Any]]" = None) -> None:
		self.strategy_id: StrategyId = StrategyId(idgen.generate_strategy_id())
		self.name = name
		self.is_active = True
		self.timeframe = to_timedelta(timeframe)
		self.tickers = tickers
		self.order_type = order_type
		#self.portfolios = {}
		self.subscribed_portfolios: list[int] = []
		self.last_event: Optional[BarEvent] = None
		self.global_queue = global_queue
		# Risk management settings
		self.max_positions = max_positions
		self.max_allocation = max_allocation
		self.allow_increase = allow_increase
		# Lookback window (bars) a concrete strategy needs before it can signal.
		# Concrete strategies (e.g. SMA_MACD) override this in their __init__.
		self.max_window: int = 0
	
	def setting_to_dict(self) -> dict[str, Any]:
		return {
			'max_positions' : self.max_positions,
			'max_allocation' : self.max_allocation,
			'allow_increase' : self.allow_increase,
		}

	def to_dict(self) -> dict[str, Any]:
		return {
			"strategy_id" : self.strategy_id,
			"strategy_name": self.name,
			"subscribed_portfolios" : self.subscribed_portfolios,
			"order_type": self.order_type,
			"is_active" : self.is_active,
			'strategy_setting' : self.setting_to_dict()
		}

	@abstractmethod
	def calculate_signal(self, ticker: str, bars: pd.DataFrame) -> None:
		"""
		Evaluate market data for `ticker` and emit signals via `buy`/`sell`.

		Concrete strategies must implement their signal logic here. The richer
		calculate_signal contract (return-typed signals) is deferred to M5b #24 —
		this is the minimal abstract seam only.
		"""
		raise NotImplementedError("Should implement calculate_signal()")

	def _generate_signal(self, ticker: str, action: str, sl: float = 0, tp: float = 0) -> None:
		"""
		Generate a signal for the given `ticker`, `action`, `stop_loss`, and `take_profit`.
		"""
		if self.last_event is None:
			return
		last_close = self.last_event.get_last_close(ticker)
		for portfolio_id in self.subscribed_portfolios:
			# quantity is omitted (defaults to None, D-10): the order/risk layer
			# sizes the signal — the 0 sentinel is gone.
			# D-05 boundary parse: the strategy string contract ('BUY'/'SELL',
			# 'market'/...) is converted to enum members HERE — the case-insensitive
			# `_missing_` classmethods raise ValueError on unknown strings.
			signal = SignalEvent(
							time = self.last_event.time,
							order_type = OrderType(self.order_type),
							ticker = ticker,
							action = Side(action),
							price = last_close,
							stop_loss = sl,
							take_profit = tp,
							strategy_id = self.strategy_id,
							portfolio_id = portfolio_id,
							strategy_setting=self.setting_to_dict()
						)
			if self.global_queue is not None:
				self.global_queue.put(signal)
		logger.debug('Strategy signal (%s - %s %s, %s $)', self.strategy_id,
					ticker, action, round(last_close, 4))

	def buy(self, ticker: str, sl: float = 0, tp: float = 0) -> None:
		"""
		Add a buy signal from the strategy to the global queue
		of the trading system.
		"""
		self._generate_signal(ticker, 'BUY', sl, tp)

	def sell(self, ticker: str, sl: float = 0, tp: float = 0) -> None:
		"""
		Add a sell signal from the strategy to the global queue
		of the trading system.
		"""
		self._generate_signal(ticker, 'SELL', sl, tp)

	def last_time(self) -> Optional[datetime]:
		if self.last_event is not None:
			return self.last_event.time
		return None

	def subscribe_portfolio(self, portfolio_id: int) -> None:
		self.subscribed_portfolios.append(portfolio_id)

	def unsubscribe_portfolio(self, portfolio_id: int) -> None:
		self.subscribed_portfolios.remove(portfolio_id)

	def activate_strategy(self) -> None:
		self.is_active = True

	def deactivate_strategy(self) -> None:
		self.is_active = False