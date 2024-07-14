from enum import Enum
from datetime import datetime
from dataclasses import dataclass

from itrader import idgen
from itrader.events_handler.event import FillEvent

TransactionType = Enum("TransactionType", "BUY SELL")
transaction_type_map = {
	"BUY": TransactionType.BUY,
	"SELL": TransactionType.SELL,
}

@dataclass
class Transaction(object):
	"""
	Instance of a Transaction, generated when a FillOrder event
	is recived from the ExecutionHandler.
	"""

	time: datetime
	type: TransactionType
	ticker: str
	price: float
	quantity: float
	commission: float
	portfolio_id: int
	id: int
	position_id: int = None

	def __repr__(self):
		"""
		Provides a representation of the Transaction
		to allow full recreation of the object.
		"""
		return f"Transaction - {self.id} ({self.type.name}, {self.ticker}, {self.quantity}, {self.price}$)"

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
		Generate a new Transaction object from a FillEvent instance.

		Parameters
		----------
		filled_order : `OrderEvent`
			Instance of the order to be executed
		
		Returns
		-------
		fill : `FillEvent`
			Instance of the filled order
		"""

		transaction_type = transaction_type_map.get(filled_order.action)
		if transaction_type is None:
			raise ValueError('Value %s not supported', filled_order.action)

		return cls(
			filled_order.time,
			transaction_type,
			filled_order.ticker,
			filled_order.price,
			filled_order.quantity,
			filled_order.commission,
			filled_order.portfolio_id,
			idgen.generate_transaction_id()
		)

	def to_dict(self):
			return {
				'transaction_id': self.id,
				'portfolio_id' : self.portfolio_id,
				'position_id' : self.position_id,
				'time': self.time,
				'ticker': self.ticker,
				'action' : self.type.name,
				'price': self.price,
				'quantity': self.quantity,
				'commission': self.commission,
			}