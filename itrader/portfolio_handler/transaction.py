from enum import Enum
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from itrader import idgen
from itrader.events_handler.event import FillEvent
from itrader.core.enums import TransactionType
from itrader.core.ids import PortfolioId, PositionId, TransactionId
from itrader.core.money import to_money

@dataclass
class Transaction(object):
	"""
	Instance of a Transaction, generated when a FillOrder event
	is recived from the ExecutionHandler.
	"""

	time: datetime
	type: TransactionType
	ticker: str
	price: Decimal
	quantity: Decimal
	commission: Decimal
	# 02-05 carry-over: events carry an int portfolio_id while Portfolio assigns a
	# UUID-backed PortfolioId. Until the portfolio_id migration completes, accept
	# both at this boundary (the full retype is deferred — not mandated by Task 2).
	portfolio_id: "PortfolioId | int"
	id: TransactionId
	position_id: Optional[PositionId] = None

	def __post_init__(self) -> None:
		"""Enter the Decimal money domain at the construction boundary (D-04).

		Callers may still pass int/float money values; ``to_money`` normalises
		them to ``Decimal`` via the string path so the entity stores Decimal
		end-to-end with no float-repr artifact.
		"""
		self.price = to_money(self.price)
		self.quantity = to_money(self.quantity)
		self.commission = to_money(self.commission)

	def __repr__(self) -> str:
		"""
		Provides a representation of the Transaction
		to allow full recreation of the object.
		"""
		return f"Transaction - {self.id} ({self.type.name}, {self.ticker}, {self.quantity}, {self.price}$)"

	@property
	def cost(self) -> Decimal:
		"""
		Calculate the cost of the transaction without including
		any commission costs.
		"""
		return self.quantity * self.price

	@property
	def total_cost(self) -> Decimal:
		"""
		Calculate the cost of the transaction including
		commission costs.

		Returns
		-------
		`Decimal`
			The transaction cost with commission.
		"""
		if self.commission == 0:
			return self.cost
		else:
			return self.cost + self.commission
	
	@classmethod
	def new_transaction(cls, filled_order: FillEvent) -> "Transaction":
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

		transaction_type = TransactionType(filled_order.action)

		return cls(
			filled_order.time,
			transaction_type,
			filled_order.ticker,
			to_money(filled_order.price),
			to_money(filled_order.quantity),
			to_money(filled_order.commission),
			filled_order.portfolio_id,
			TransactionId(idgen.generate_transaction_id())
		)

	def to_dict(self) -> dict[str, object]:
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