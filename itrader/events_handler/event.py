import pandas as pd
from enum import Enum
from datetime import datetime
from dataclasses import dataclass

EventType = Enum("EventType", "PING BAR UPDATE SIGNAL ORDER FILL SCREENER")
FillStatus = Enum("FillStatus", "EXECUTED REFUSED")

event_type_map = {
	"PING": EventType.PING,
	"BAR": EventType.BAR,
	"UPDATE": EventType.UPDATE,
	"SIGNAL": EventType.SIGNAL,
	"ORDER": EventType.ORDER,
	"FILL": EventType.FILL
}

fill_status_map = {
	"EXECUTED": FillStatus.EXECUTED,
	"REFUSED": FillStatus.REFUSED,
}

@dataclass
class PingEvent:
	"""
	Handles the event of receiving a new market update tick,
	which is defined as a ticker symbol and associated best
	bid and ask from the top of the order book.
	"""

	time: datetime
	type = EventType.PING

	def __str__(self):
		return f"{self.type}, Time: {self.time}"

	def __repr__(self):
		return str(self)


@dataclass
class BarEvent:
	"""
	Handles the event of receiving a new market
	open-high-low-close-volume bar, as would be generated
	via common data providers.
	"""

	time: datetime
	bars: dict[str, pd.DataFrame]
	# TODO:
	# improvment idea : define a Bar object instead of using a DataFrame
	# to store the bar data
	# e.g. Bar(open, high, low, close, volume)
	# where Bar is a dataclass with the above fields
	type = EventType.BAR

	def __str__(self):
		return f"{self.type}, Time: {self.time}"

	def __repr__(self):
		return str(self)

	def get_last_close(self, ticker) -> float:
		close_data = self.bars[ticker]['close']

		# TODO: check why the close data is not always a Series (from test).
		# This shouldn't be the case after the before mentioned improvement is done.
		
		# Handle pandas Series or DataFrame column
		if hasattr(close_data, 'iloc'):
			return float(close_data.iloc[-1])
		# Handle numpy arrays
		elif hasattr(close_data, '__getitem__') and hasattr(close_data, '__len__'):
			return float(close_data[-1])
		# Handle scalar values
		else:
			return float(close_data)

	def get_last_open(self, ticker) -> float:
		"""
		Get the opening price for the ticker from the current bar.
		
		Parameters
		----------
		ticker : str
			The ticker symbol
			
		Returns
		-------
		float
			The opening price for the ticker
		"""
		if ticker not in self.bars:
			return None
			
		open_data = self.bars[ticker]['open']
		
		# Handle pandas Series or DataFrame column
		if hasattr(open_data, 'iloc'):
			return float(open_data.iloc[-1])
		# Handle numpy arrays
		elif hasattr(open_data, '__getitem__') and hasattr(open_data, '__len__'):
			return float(open_data[-1])
		# Handle scalar values
		else:
			return float(open_data)

@dataclass
class PortfolioUpdateEvent:
	"""
	Handles the event of receiving a new market
	open-high-low-close-volume bar, as would be generated
	via common data providers.
	"""

	time: datetime
	portfolios: dict
	type = EventType.UPDATE

	def __str__(self):
		return f"{self.type}, Time: {self.time}"

	def __repr__(self):
		return str(self)

@dataclass
class SignalEvent:
	"""
	Signal event generated from a Strategy object.
	This is received by the Order handler object that validate and
	send the order to the Execution handler object.

	Parameters
	----------
	time: `timestamp`
		Event time
	order_type: `str`
		Type of order, e.g. 'MARKET', 'LIMIT', 'STOP'
		'MARKET' is the default order type.
	ticker: `str`
		The ticker symbol, e.g. 'BTCUSD'.
	action: `str`
		'BUY' (for long) or 'SELL' (for short)
	price: `float`
		Last close price for the instrument
	quantity: `float`
		Quantity to trade
	stop_loss: `float`
		Stop loss price for the instrument
	take_profit: `float`
		Take profit price for the instrument
	strategy_id: `int`
		The ID of the strategy who generated the signal
	portfolio_id: `int`
		The ID of the portfolio where to transact the position
	strategy_setting: `dict`
		Strategy settings used to generate the signal.
	"""

	time: datetime
	order_type: str
	ticker: str
	action: str
	price: float
	quantity: float
	stop_loss: float
	take_profit: float
	strategy_id: int
	portfolio_id: int
	strategy_setting: dict
	verified: bool = False
	type = EventType.SIGNAL

	def __str__(self):
		return f"{self.type} ({self.ticker}, {self.action}, {round(self.price, 4)} $)"

	def __repr__(self):
		return str(self)

@dataclass
class ScreenerEvent:
	"""
	Screener event generated from a Screener object.
	This is received by the Strategy handler object
	that update the symbol to trade of the subscribed
	strategies.

	Parameters
	----------
	time: `timestamp`
		Event time
	ticker: `str`
		The ticker symbol, e.g. 'BTCUSD'.
	direction: `str`
		Direction of the position.
		'BUY' (for long) or 'SELL' (for short)
	action: `str`
		'ENTRY' (for long) or 'EXIT' (for short)
	price: `float`
		Last close price for the instrument
	strategy_id: `str`
		The ID of the strategy who generated the signal
	"""

	time: datetime
	screener_id: str
	screener_name: str
	subscribed_strategies: list[str]
	tickers : list[str]
	type = EventType.SCREENER

	def __str__(self):
		return f"{self.type} ({self.screener_name})"

	def __repr__(self):
		return str(self)

@dataclass
class OrderEvent:
	"""
	An Order object is generated by the OrderHandler in respons to
	a signal event who has been validated by the the PositionSizer 
	and RiskManager object.

	It is then sent to the ExecutionHandler who send the order
	to the exchange.
	"""

	time: datetime
	ticker: str
	action: str
	price: float
	quantity: float
	exchange: str
	strategy_id: int
	portfolio_id: int
	type = EventType.ORDER

	def __str__(self):
		return f"{self.type} ({self.ticker}, {self.action}, {self.quantity}, {round(self.price, 4)} $)"

	def __repr__(self):
		return str(self)
	
	@classmethod
	def new_order_event(cls, order):
		"""
		Generate a new OrderEvent object when an order is filled.

		Parameters
		----------
		signal : `SignalEvent`
			The object representing the signal
		
		Returns
		-------
		Order : `OrderEvent`
			A new Order object with the specified type.
		"""

		return cls(
			order.time,
			order.ticker,
			order.action,
			order.price,
			order.quantity,
			order.exchange,
			order.strategy_id,
			order.portfolio_id
		)


@dataclass
class FillEvent:
	"""
	This event is generated by the ExecutionHandler in response to
	an executed order. 
	Stores the price and quantity and commission confirmed by 
	the exchange.

	Parameters
	----------
	time: `timestamp`
		Event time
	ticker: `str`
		The ticker symbol, e.g. 'BTCUSD'.
	action: `str`
		'BUY' (for long) or 'SELL' (for short)
	quantity: `float`
		Quantity transacted
	price: `float`
		Last close price for the instrument
	commission: `float`
		Transaction fee
	exchange: `str`
		The exchange where to transact, e.g. 'binance'.
	portfolio_id: `str`
		Portfolio id where transact the position
	"""

	time: datetime
	status: FillStatus
	ticker: str
	action: str
	price: float
	quantity: float
	commission: float
	portfolio_id: str
	type = EventType.FILL

	def __str__(self):
		return f'{self.type} ({self.ticker}, {self.action}, {round(self.quantity, 4)}, {round(self.price, 4)} $)'

	def __repr__(self):
		return str(self)
	
	@classmethod
	def new_fill(cls, status: str, commission: float, order: OrderEvent):
		"""
		Generate a new FillEvent object.

		Parameters
		----------
		status : `str`
			The execution state of the fill order e.g. 'EXECUTED', 'REFUSED'
		order : `OrderEvent`
			The instance of the executed order
		
		Returns
		-------
		fill : `FillEvent`
			Instance of the executed order
		"""

		fill_status = fill_status_map.get(status)
		if fill_status is None:
			raise ValueError('Value %s not supported', status)
		return cls(
			order.time,
			fill_status,
			order.ticker,
			order.action,
			order.price,
			order.quantity,
			commission,
			order.portfolio_id
		)


@dataclass
@dataclass
class PortfolioErrorEvent:
	"""
	Handles portfolio error events for monitoring and alerting.
	"""
	
	time: datetime
	error_type: str
	error_message: str
	portfolio_id: int = None
	operation: str = None
	correlation_id: str = None
	severity: str = "ERROR"  # ERROR, CRITICAL, WARNING
	details: dict = None
	
	type = EventType.UPDATE  # Reuse UPDATE type for now
	
	def __str__(self):
		base = f"PortfolioError: {self.error_type} - {self.error_message}"
		if self.portfolio_id:
			base += f" (Portfolio: {self.portfolio_id})"
		if self.operation:
			base += f" (Operation: {self.operation})"
		return base
	
	def __repr__(self):
		return str(self)
	
	def to_dict(self):
		"""Convert event to dictionary for logging/serialization."""
		return {
			"time": self.time.isoformat(),
			"error_type": self.error_type,
			"error_message": self.error_message,
			"portfolio_id": self.portfolio_id,
			"operation": self.operation,
			"correlation_id": self.correlation_id,
			"severity": self.severity,
			"details": self.details or {}
		}