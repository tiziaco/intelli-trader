import uuid

import pandas as pd
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Optional

import uuid_utils.compat as uuid_compat

# EventType relocated to core/enums (class-based, D-05/D-08); the `as` form is
# an explicit re-export (mypy no_implicit_reexport) so `EventType` stays
# importable from this module for existing consumers until the Plan 04-05 cutover.
from ..core.enums import EventType as EventType
from ..core.enums import OrderType, OrderCommand, FillStatus
from ..core.ids import OrderId, StrategyId

@dataclass(frozen=True, slots=True)
class TimeEvent:
	"""
	Signals that the simulation clock advanced to ``time`` ("the clock
	advanced to T"), pairing with the ``itrader.core.clock.Clock`` family
	(D-08). Drives per-tick screening and bar generation.
	"""

	time: datetime
	type = EventType.TIME

	def __str__(self) -> str:
		return f"{self.type}, Time: {self.time}"

	def __repr__(self) -> str:
		return str(self)


@dataclass(frozen=True, slots=True)
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

	def __str__(self) -> str:
		return f"{self.type}, Time: {self.time}"

	def __repr__(self) -> str:
		return str(self)

	def get_last_close(self, ticker: str) -> float:
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

	def get_last_open(self, ticker: str) -> Optional[float]:
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

	def get_last_high(self, ticker: str) -> Optional[float]:
		"""
		Get the high price for the ticker from the current bar.

		Parameters
		----------
		ticker : str
			The ticker symbol

		Returns
		-------
		float
			The high price for the ticker
		"""
		if ticker not in self.bars:
			return None

		high_data = self.bars[ticker]['high']

		# Handle pandas Series or DataFrame column
		if hasattr(high_data, 'iloc'):
			return float(high_data.iloc[-1])
		# Handle numpy arrays
		elif hasattr(high_data, '__getitem__') and hasattr(high_data, '__len__'):
			return float(high_data[-1])
		# Handle scalar values
		else:
			return float(high_data)

	def get_last_low(self, ticker: str) -> Optional[float]:
		"""
		Get the low price for the ticker from the current bar.

		Parameters
		----------
		ticker : str
			The ticker symbol

		Returns
		-------
		float
			The low price for the ticker
		"""
		if ticker not in self.bars:
			return None

		low_data = self.bars[ticker]['low']

		# Handle pandas Series or DataFrame column
		if hasattr(low_data, 'iloc'):
			return float(low_data.iloc[-1])
		# Handle numpy arrays
		elif hasattr(low_data, '__getitem__') and hasattr(low_data, '__len__'):
			return float(low_data[-1])
		# Handle scalar values
		else:
			return float(low_data)

@dataclass(frozen=True, slots=True)
class PortfolioUpdateEvent:
	"""
	Handles the event of receiving a new market
	open-high-low-close-volume bar, as would be generated
	via common data providers.
	"""

	time: datetime
	portfolios: dict[str, Any]
	type = EventType.UPDATE

	def __str__(self) -> str:
		return f"{self.type}, Time: {self.time}"

	def __repr__(self) -> str:
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
	stop_loss: `float`
		Stop loss price for the instrument
	take_profit: `float`
		Take profit price for the instrument
	strategy_id: `StrategyId`
		The ID of the strategy who generated the signal
	portfolio_id: `int`
		The ID of the portfolio where to transact the position
	strategy_setting: `dict`
		Strategy settings used to generate the signal.
	quantity: `float | None`
		Quantity to trade. ``None`` (the default) means "the order/risk
		layer sizes me" (D-10 — the 0 sentinel is gone); an explicit
		caller-supplied positive quantity is used as-is.
	"""

	time: datetime
	order_type: str
	ticker: str
	action: str
	price: float
	stop_loss: float
	take_profit: float
	# 02-05 carry-over: strategy_id carries a UUIDv7-backed StrategyId, not a raw int.
	strategy_id: StrategyId
	portfolio_id: int
	strategy_setting: dict[str, Any]
	quantity: float | None = None
	type = EventType.SIGNAL

	def __str__(self) -> str:
		return f"{self.type} ({self.ticker}, {self.action}, {round(self.price, 4)} $)"

	def __repr__(self) -> str:
		return str(self)

@dataclass(frozen=True, slots=True)
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

	def __str__(self) -> str:
		return f"{self.type} ({self.screener_name})"

	def __repr__(self) -> str:
		return str(self)

@dataclass
class OrderEvent:
	"""
	An Order object is generated by the OrderHandler in response to
	a signal event who has been validated by the PositionSizer 
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
	strategy_id: StrategyId
	portfolio_id: int
	order_type: OrderType
	stop_price: Optional[float] = None
	order_id: Optional[int] = None
	parent_order_id: Optional[int] = None
	# D-11: two-directional bracket linkage — a bracket parent carries its
	# children's ids; non-bracket orders carry the empty tuple.
	child_order_ids: tuple[OrderId, ...] = ()
	command: 'OrderCommand' = OrderCommand.NEW
	type = EventType.ORDER

	def __str__(self) -> str:
		base = f"{self.type} ({self.ticker}, {self.action}, {self.order_type.name}, {self.quantity}, {round(self.price, 4)} $"
		if self.stop_price:
			base += f", stop: {round(self.stop_price, 4)}"
		return base + f", ID: {self.order_id})"

	def __repr__(self) -> str:
		return str(self)

	@classmethod
	def new_order_event(cls, order: Any, command: 'OrderCommand' = OrderCommand.NEW) -> 'OrderEvent':
		"""
		Generate a new OrderEvent from an Order.

		Reads the order's real type (`order.type`) and id (`order.id`),
		and optional bracket linkage / command intent.
		"""
		# Boundary coercion (M2a): the Order entity carries Decimal money, but the
		# OrderEvent + execution/matching/fee layer remain float until M4. Coerce
		# here so the float execution layer stays consistent; the cash path
		# re-enters Decimal at Transaction.new_transaction via to_money().
		return cls(
			order.time,
			order.ticker,
			order.action,
			float(order.price),
			float(order.quantity),
			order.exchange,
			order.strategy_id,
			order.portfolio_id,
			order_type=getattr(order, 'type', OrderType.MARKET),
			stop_price=getattr(order, 'stop_price', None),
			order_id=getattr(order, 'id', None),
			parent_order_id=getattr(order, 'parent_order_id', None),
			child_order_ids=tuple(getattr(order, 'child_order_ids', ()) or ()),
			command=command,
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
	order_id: `int | None`
		Id of the originating order, carried for mirror reconciliation.
	fill_id: `uuid.UUID`
		Unique UUIDv7 identity of this fill, generated by the exchange at
		fill construction (D-12).
	strategy_id: `StrategyId | None`
		The originating strategy, carried from the order for the full
		fill -> order -> strategy audit chain (D-12).
	"""

	time: datetime
	status: FillStatus
	ticker: str
	action: str
	price: float
	quantity: float
	commission: float
	portfolio_id: int
	order_id: Optional[int] = None
	fill_id: uuid.UUID = field(default_factory=uuid_compat.uuid7)
	strategy_id: Optional[StrategyId] = None
	type = EventType.FILL

	def __str__(self) -> str:
		return f'{self.type} ({self.ticker}, {self.action}, {round(self.quantity, 4)}, {round(self.price, 4)} $)'

	def __repr__(self) -> str:
		return str(self)

	@classmethod
	def new_fill(cls, status: str, order: OrderEvent, *,
			price: float, quantity: float, commission: float) -> 'FillEvent':
		"""
		Generate a complete FillEvent from the originating order.

		Construct-complete (D-12): the exchange passes the executed values
		explicitly as keyword-only arguments — a FillEvent is never mutated
		after construction. ``fill_id`` is a fresh UUIDv7 generated here, at
		fill construction; ``strategy_id`` and ``order_id`` are carried from
		the originating order for the fill -> order -> strategy audit chain.
		REFUSED/CANCELLED fills pass the order's own price/quantity with
		commission 0.0.

		Parameters
		----------
		status : `str`
			The execution state of the fill order e.g. 'EXECUTED', 'REFUSED', 'CANCELLED'
		order : `OrderEvent`
			The instance of the originating order
		price : `float`
			Executed price confirmed by the exchange (keyword-only)
		quantity : `float`
			Executed quantity confirmed by the exchange (keyword-only)
		commission : `float`
			Transaction fee charged by the exchange (keyword-only)

		Returns
		-------
		fill : `FillEvent`
			Complete fill — no field is rewritten after this returns
		"""

		fill_status = FillStatus(status)
		return cls(
			order.time,
			fill_status,
			order.ticker,
			order.action,
			price,
			quantity,
			commission,
			order.portfolio_id,
			order_id=order.order_id,
			fill_id=uuid_compat.uuid7(),
			strategy_id=order.strategy_id,
		)


@dataclass
class PortfolioErrorEvent:
	"""
	Handles portfolio error events for monitoring and alerting.
	"""
	
	time: datetime
	error_type: str
	error_message: str
	portfolio_id: Optional[int] = None
	operation: Optional[str] = None
	correlation_id: Optional[str] = None
	severity: str = "ERROR"  # ERROR, CRITICAL, WARNING
	details: Optional[dict[str, Any]] = None

	type = EventType.UPDATE  # Reuse UPDATE type for now

	def __str__(self) -> str:
		base = f"PortfolioError: {self.error_type} - {self.error_message}"
		if self.portfolio_id:
			base += f" (Portfolio: {self.portfolio_id})"
		if self.operation:
			base += f" (Operation: {self.operation})"
		return base

	def __repr__(self) -> str:
		return str(self)

	def to_dict(self) -> dict[str, Any]:
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