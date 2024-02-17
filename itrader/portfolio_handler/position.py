from enum import Enum
from datetime import datetime

from itrader import idgen
from itrader.portfolio_handler.transaction import Transaction, TransactionType

PositionSide = Enum("PositionSide", "LONG SHORT")
position_side_map = {
	"LONG": PositionSide.LONG,
	"SHORT": PositionSide.SHORT,
}

class Position(object):
	"""
	Handles the accounting of entering a new position in an
	Asset along with subsequent modifications via additional
	trades.

	The approach taken here separates the long and short side
	for accounting purposes. It also includes an unrealised and
	realised running profit & loss of the position.
	"""
	def __init__(
		self,
		entry_date: datetime,
		ticker: str,
		side: PositionSide,
		price: float,
		buy_quantity: float,
		sell_quantity: float,
		avg_bought: float,
		avg_sold: float,
		buy_commission: float,
		sell_commission: float,
		is_open: bool,
		portfolio_id: str
	):
		self.id = idgen.generate_position_id()
		self.ticker = ticker
		self.side = side
		self.current_price = price
		self.current_time = entry_date 
		self.buy_quantity = buy_quantity
		self.sell_quantity = sell_quantity
		self.avg_bought = avg_bought
		self.avg_sold = avg_sold
		self.buy_commission = buy_commission
		self.sell_commission = sell_commission
		self.entry_date = entry_date
		self.exit_date = None
		self.is_open = is_open
		self.portfolio_id = portfolio_id
	
	def __repr__(self):
		rep = ('%s, %s, %s'%(self.ticker, self.side.value, self.net_quantity))
		return rep


	@property
	def market_value(self) -> float:
		"""
		Return the market value (respecting the direction) of the
		Position based on the current price available to the Position.
		"""
		return self.current_price * abs(self.net_quantity)

	@property
	def avg_price(self) -> float:
		"""
		The average price paid for all assets on the long or short side.
		"""
		# if self.net_quantity == 0:
		# 	return 0.0
		if self.side == PositionSide.LONG:
			return (self.avg_bought * self.buy_quantity + self.buy_commission) / self.buy_quantity
		else: # side = 'SHORT'
			return (self.avg_sold * self.sell_quantity - self.sell_commission) / self.sell_quantity

	@property
	def net_quantity(self) -> float:
		"""
		The difference in the quantity of assets bought and sold to date.
		"""
		return abs(self.buy_quantity - self.sell_quantity)

	@property
	def total_bought(self) -> float:
		"""
		Calculates the total average cost of assets bought.
		"""
		return self.avg_bought * self.buy_quantity

	@property
	def total_sold(self) -> float:
		"""
		Calculates the total average cost of assets sold.
		"""
		return self.avg_sold * self.sell_quantity

	@property
	def net_total(self) -> float:
		"""
		Calculates the net total average cost of assets
		bought and sold.
		"""
		if self.is_open == False:
			return self.total_sold - self.total_bought
		else:
			if self.side == PositionSide.LONG:
				return self.market_value - self.total_bought
			else:
				return self.total_sold - self.market_value

	@property
	def commission(self) -> float:
		"""
		Calculates the total commission from assets bought and sold.
		"""
		return self.buy_commission + self.sell_commission

	@property
	def net_incl_commission(self) -> float:
		"""
		Calculates the net total average cost of assets bought
		and sold including the commission.
		"""
		return self.net_total - self.commission

	@property
	def realised_pnl(self) -> float:
		"""
		Calculates the profit & loss (P&L) that has been realised.
		"""
		if self.side == PositionSide.LONG:
			if self.sell_quantity == 0:
				return 0.0
			else:
				return (
					((self.avg_sold - self.avg_bought) * self.sell_quantity) -
					((self.sell_quantity / self.buy_quantity) * self.buy_commission) -
					self.sell_commission
				)
		elif self.side == PositionSide.SHORT:
			if self.buy_quantity == 0:
				return 0.0
			else:
				return (
					((self.avg_sold - self.avg_bought) * self.buy_quantity) -
					((self.buy_quantity / self.sell_quantity) * self.sell_commission) -
					self.buy_commission
				)
		else:
			return self.net_incl_commission

	@property
	def unrealised_pnl(self) -> float:
		"""
		Calculates the profit & loss (P&L) that has yet to be 'realised'
		in the remaining non-zero quantity of assets, due to the current
		market price.
		"""
		if self.side == PositionSide.LONG:
			return (self.current_price - self.avg_price) * self.net_quantity
		elif self.side == PositionSide.SHORT:
			return (self.avg_price - self.current_price) * self.net_quantity

	@property
	def total_pnl(self) -> float:
		"""
		Calculates the sum of the unrealised and realised profit & loss (P&L).
		"""
		return self.realised_pnl + self.unrealised_pnl

	@classmethod
	def open_position(cls, transaction: Transaction):
		"""
		Creates a new position object based on the provided transaction. 
		It determines the position side based on the transaction type (BUY or SELL) 
		and maps it to the corresponding PositionSide enum value. 

		The newly opened position instance is returned.
		"""
		position_side = PositionSide.LONG if transaction.type == TransactionType.BUY else PositionSide.SHORT

		return cls(
			entry_date = transaction.time,
			ticker = transaction.ticker,
			side = position_side,
			price = transaction.price,
			buy_quantity = transaction.quantity if position_side == PositionSide.LONG else 0,
			sell_quantity = transaction.quantity if position_side == PositionSide.SHORT else 0,
			avg_bought = transaction.price if position_side == PositionSide.LONG else 0,
			avg_sold = transaction.price if position_side == PositionSide.SHORT else 0,
			buy_commission = transaction.commission if position_side == PositionSide.LONG else 0,
			sell_commission = transaction.commission if position_side == PositionSide.SHORT else 0,
			is_open = True,
			portfolio_id = transaction.portfolio_id,
		)

	def update_position(self, transaction: Transaction):
		"""
		Updates the average bought/sold price, quantity, and commission
		of the Position based on the transaction details.
		"""
		if transaction.type == TransactionType.BUY:
			self.avg_bought = ((self.avg_bought * self.buy_quantity) + (transaction.quantity * transaction.price)) / (self.buy_quantity + transaction.quantity)
			self.buy_quantity += transaction.quantity
			self.buy_commission += transaction.commission
		elif transaction.type == TransactionType.SELL:
			self.avg_sold = ((self.avg_sold * self.sell_quantity) + (transaction.quantity * transaction.price)) / (self.sell_quantity + (transaction.quantity))
			self.sell_quantity += transaction.quantity
			self.sell_commission += transaction.commission
		self.update_current_price_time(transaction.price, transaction.time)

	def close_position(self, price, time):
		"""
		Close the position.
		"""
		self.is_open = False
		self.exit_date = time
		self.current_price = price

	def update_current_price_time(self, price: float, time: datetime):
		"""
		Updates the Position's awareness of the current market price
		and time.

		Parameters
		----------
		price : `float`
			The current market price.
		time : `datetime`
			The optional timestamp of the current market price.
		"""
		self.current_price = price
		self.current_time = time

	def to_dict(self):
			return {
				'id': self.id,
				'is_open': self.is_open,
				'current_price': self.current_price,
				'entry_date': self.entry_date,
				'exit_date': self.exit_date,
				'pair': self.ticker,
				'side': self.side,
				'avg_price': self.avg_price,
				'net_quantity': self.net_quantity,
				'net_total': self.net_total,
				'realised_pnl': self.realised_pnl,
				'unrealised_pnl': self.unrealised_pnl,
				'avg_bought': self.avg_bought,
				'avg_sold': self.avg_sold,
				'buy_quantity': self.buy_quantity,
				'sell_quantity': self.sell_quantity,
				'total_bought': self.total_bought,
				'total_sold': self.total_sold,
				'market_value': self.market_value
			}