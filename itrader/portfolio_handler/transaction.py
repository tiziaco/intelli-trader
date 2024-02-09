from enum import Enum

from itrader.events_handler.event import FillEvent

TransactionType = Enum("TransactionType", "BUY SELL")
type_mapping = {
	"BUY": TransactionType.BUY,
	"SELL": TransactionType.SELL,
}

class Transaction(object):
	"""
	Handles the transaction of an asset, as used in the
	Position class.

	Parameters
	----------
	asset : `str`
		The asset symbol of the transaction
	quantity : `int`
		Whole number quantity of shares in the transaction
	dt : `pd.Timestamp`
		The date/time of the transaction
	price : `float`
		The transaction price carried out
	order_id : `int`
		The unique order identifier
	commission : `float`, optional
		The trading commission
	"""

	def __init__(
		self,
		time: str,
		type: TransactionType,
		ticker: str,
		side: str, 
		action: str, 
		price: float,
		quantity: float,
		commission: float,
		portfolio_id: int
	):
		self.id = None		#TODO da implementare
		self.time = time
		self.type = type
		self.ticker = ticker
		self.side = side
		self.action = action
		self.price = price
		self.quantity = quantity
		self.commission = commission
		self.portfolio_id = portfolio_id

	def __repr__(self):
		"""
		Provides a representation of the Transaction
		to allow full recreation of the object.
		"""
		return f"{(self).__name__}(	\
			{self.type.value}		\
			{self.ticker}, 			\
			{self.quantity}"

	@property
	def cost(self) -> float:
		"""
		Calculate the cost of the transaction without including
		any commission costs.
		"""
		return self.quantity * self.price

	@property
	def total_cost(self):
		"""
		Calculate the cost of the transaction including
		commission costs.

		Returns
		-------
		`float`
			The transaction cost with commission.
		"""
		if self.commission == 0.0:
			return self.cost
		else:
			return self.cost + self.commission
	
	@classmethod
	def new_transaction(cls, filled_order: FillEvent):
		"""
		Depending upon whether the action was a buy or sell ("BOT"
		or "SLD") calculate the average bought cost, the total bought
		cost, the average price and the cost basis.

		Finally, calculate the net total with and without commission.
		"""

		transaction_type = type_mapping.get(filled_order.action)
		if transaction_type is None:
			raise ValueError('Value %s not supported', filled_order.action)

		return cls(
			filled_order.time,
			filled_order.type,
			filled_order.ticker,
			filled_order.side,
			filled_order.action,
			filled_order.price,
			filled_order.quantity,
			filled_order.commission,
			filled_order.portfolio_id
		)