from enum import Enum
from datetime import datetime

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

	Parameters
	----------
	ticker: `str`
		The Asset symbol string.
	action : `str`
		The market direction of the position e.g. 'BOT' or 'SLD' .
	current_price : `float`
		The initial price of the Position.
	current_time : `pd.Timestamp`
		The time at which the Position was created.
	buy_quantity : `int`
		The amount of the asset bought.
	sell_quantity : `int`
		The amount of the asset sold.
	avg_bought : `float`
		The initial price paid for buying assets.
	avg_sold : `float`
		The initial price paid for selling assets.
	buy_commission : `float`
		The commission spent on buying assets for this position.
	sell_commission : `float`
		The commission spent on selling assets for this position.
	"""
	def __init__(
		self,
		entry_date: datetime,
		ticker: str,
		side: str,
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
		rep = ('%s, %s, %s'%(self.ticker, self.action, self.net_quantity))
		return rep


	@property
	def market_value(self):
		"""
		Return the market value (respecting the direction) of the
		Position based on the current price available to the Position.

		Returns
		-------
		`float`
			The current market value of the Position.
		"""
		return self.current_price * abs(self.net_quantity)

	@property
	def avg_price(self):
		"""
		The average price paid for all assets on the long or short side.

		Returns
		-------
		`float`
			The average price on either the long or short side.
		"""
		if self.net_quantity == 0:
			return 0.0
		elif self.action =='BOT':
			return (self.avg_bought * self.buy_quantity + self.buy_commission) / self.buy_quantity
		else: # action == "SLD"
			return (self.avg_sold * self.sell_quantity - self.sell_commission) / self.sell_quantity

	@property
	def net_quantity(self):
		"""
		The difference in the quantity of assets bought and sold to date.

		Returns
		-------
		`int`
			The net quantity of assets.
		"""
		return abs(self.buy_quantity - self.sell_quantity)

	@property
	def total_bought(self):
		"""
		Calculates the total average cost of assets bought.

		Returns
		-------
		`float`
			The total average cost of assets bought.
		"""
		return self.avg_bought * self.buy_quantity

	@property
	def total_sold(self):
		"""
		Calculates the total average cost of assets sold.

		Returns
		-------
		`float`
			The total average cost of assets solds.
		"""
		return self.avg_sold * self.sell_quantity

	@property
	def net_total(self):
		"""
		Calculates the net total average cost of assets
		bought and sold.

		Returns
		-------
		`float`
			The net total average cost of assets bought
			and sold.
		"""
		return self.total_sold - self.total_bought

	@property
	def commission(self):
		"""
		Calculates the total commission from assets bought and sold.

		Returns
		-------
		`float`
			The total commission from assets bought and sold.
		"""
		return self.buy_commission + self.sell_commission

	@property
	def net_incl_commission(self):
		"""
		Calculates the net total average cost of assets bought
		and sold including the commission.

		Returns
		-------
		`float`
			The net total average cost of assets bought and
			sold including the commission.
		"""
		return self.net_total - self.commission

	@property
	def realised_pnl(self):
		"""
		Calculates the profit & loss (P&L) that has been realised.

		Returns
		-------
		`float`
			The calculated realised P&L.
		"""
		if self.action == 'BOT':
			if self.sell_quantity == 0:
				return 0.0
			else:
				return (
					((self.avg_sold - self.avg_bought) * self.sell_quantity) -
					((self.sell_quantity / self.buy_quantity) * self.buy_commission) -
					self.sell_commission
				)
		elif self.action == 'SLD':
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
	def unrealised_pnl(self):
		"""
		Calculates the profit & loss (P&L) that has yet to be 'realised'
		in the remaining non-zero quantity of assets, due to the current
		market price.

		Returns
		-------
		`float`
			The calculated unrealised P&L.
		"""
		return (self.current_price - self.avg_price) * self.net_quantity

	@property
	def total_pnl(self):
		"""
		Calculates the sum of the unrealised and realised profit & loss (P&L).

		Returns
		-------
		`float`
			The sum of the unrealised and realised P&L.
		"""
		return self.realised_pnl + self.unrealised_pnl

	@classmethod
	def open_position(cls, transaction: Transaction):
		"""
		Depending upon whether the action was a buy or sell ("BOT"
		or "SLD") calculate the average bought cost, the total bought
		cost, the average price and the cost basis.

		Finally, calculate the net total with and without commission.
		"""
		position_side = position_side_map.get(transaction.side)
		if position_side is None:
			raise ValueError('Value %s not supported', transaction.side)
		return cls(
			entry_date = transaction.time,
			ticker = transaction.ticker,
			side = position_side,
			current_price = transaction.price,
			buy_quantity = transaction.quantity if transaction.side == 'long' else 0,
			sell_quantity = transaction.quantity if transaction.side == 'short' else 0,
			avg_bought = transaction.price if transaction.side == 'long' else 0,
			avg_sold = transaction.price if transaction.side == 'short' else 0,
			buy_commission = transaction.commission if transaction.side == 'long' else 0,
			sell_commission = transaction.commission if transaction.side == 'short' else 0,
			is_open = True,
			portfolio_id = transaction.portfolio_id,
		)

	def update_position(self, transaction: Transaction):
		if transaction.action == TransactionType.BUY:
			self.avg_bought = ((self.avg_bought * self.buy_quantity) + (transaction.quantity * transaction.price)) / (self.buy_quantity + transaction.quantity)
			self.buy_quantity += transaction.quantity
			self.buy_commission += transaction.commission
		elif transaction.action == TransactionType.SELL:
			self.avg_sold = ((self.avg_sold * self.sell_quantity) + (-transaction.quantity * transaction.price)) / (self.sell_quantity + (-transaction.quantity))
			self.sell_quantity += -1 * transaction.quantity
			self.sell_commission += transaction.commission

		self.update_current_price_time(transaction.time, transaction.price)

	def close_position(self, price, time):
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