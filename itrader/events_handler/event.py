from enum import Enum
from datetime import datetime
from dataclasses import dataclass

EventType = Enum("EventType", "PING BAR SIGNAL ORDER FILL")
OrderType = Enum("OrderType", "MARKET STOP LIMIT")
OrderStatus = Enum("OrderStatus", "PENDING FILLED CANCELLED")
FillStatus = Enum("FillStatus", "EXECUTED REFUSED")

event_type_map = {
	"PING": EventType.PING,
	"BAR": EventType.BAR,
	"SIGNAL": EventType.SIGNAL,
	"ORDER": EventType.ORDER,
	"FILL": EventType.FILL
}
order_type_map = {
	"MARKET": OrderType.MARKET,
	"STOP": OrderType.STOP,
	"LIMIT": OrderType.LIMIT
}
order_status_map = {
	"PENDING": OrderStatus.PENDING,
	"FILLED": OrderStatus.FILLED,
	"CANCELLED": OrderStatus.CANCELLED
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
		return f"Type: {self.type}, Time: {self.time}"

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
	bars: dict
	type = EventType.BAR

	def __str__(self):
		return f"Type: {self.type}, Time: {self.time}"

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
	ticker: `str`
		The ticker symbol, e.g. 'BTCUSD'.
	direction: `str`
		Direction of the position.
		'BOT' (for long) or 'SLD' (for short)
	action: `str`
		'ENTRY' (for long) or 'EXIT' (for short)
	price: `float`
		Last close price for the instrument
	strategy_id: `str`
		The ID of the strategy who generated the signal
	"""

	time: datetime
	order_type: str
	ticker: str
	side: str
	action: str
	price: float
	quantity: float
	stop_loss: float
	take_profit: float
	strategy_id: int
	portfolio_id: int
	verified: bool = False
	type = EventType.SIGNAL

	def __str__(self):
		return f"{self.type.value} ({self.ticker}, {self.side}, {self.action}, \
			{round(self.price, 4)} $)"

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
	order_type: OrderType
	status: OrderStatus
	ticker: str
	side: str
	action: str
	price: float
	quantity: float
	strategy_id: int
	portfolio_id: int
	type = EventType.ORDER

	def __str__(self):
		return f"Order-{self.type.value} ({self.ticker}, {self.action}, {self.quantity})"

	def __repr__(self):
		return str(self)
	
	@classmethod
	def new_order(cls, signal: SignalEvent):
		"""
		Generate a new Order object with the specified type.

		Parameters
		----------
		signal : `SignalEvent`
			The object representing the signal
		
		Returns
		-------
		Order : `OrderEvent`
			A new Order object with the specified type.
		"""

		order_type = order_type_map.get(signal.order_type)
		if order_type is None:
			raise ValueError(f'OrderType {type} not supported')

		return cls(
			signal.time,
			order_type,
			OrderStatus.PENDING,
			signal.ticker,
			signal.side,
			signal.action,
			signal.price,
			signal.quantity,
			signal.strategy_id,
			signal.portfolio_id
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
	side:
		'LONG' or 'SHORT'
	action: `str`
		'BOT' (for long) or 'SLD' (for short)
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
	side: str
	action: str
	price: float
	quantity: float
	commission: float
	portfolio_id: str
	type = EventType.FILL

	def __str__(self):
		return f"{self.type.value} ({self.ticker}, {self.side}, {self.action}, \
			{round(self.quantity, 4)}, {round(self.price, 4)} $)"

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
			order.side,
			order.action,
			order.price,
			order.quantity,
			commission,
			order.portfolio_id
		)