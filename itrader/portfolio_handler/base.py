from abc import ABC, abstractmethod
from typing import Any

class AbstractPortfolioHandler(ABC):
	"""
	AbstractPortfolioHandler is a base class providing an interface for
	all subsequent (inherited) portfolio handlers.

	The goal of a derived PortfolioHandler is to provide a standardized
	interface for managing and interacting with portfolios. 
	Subclasses should implement specific functionality for
	managing portfolios, such as adding assets, adjusting positions,
	calculating portfolio metrics, and handling transactions.
	"""

	@abstractmethod
	def get_last_close(self, ticker: str) -> Any:
		raise NotImplementedError("Should implement get_last_close()")


class AbstractPortfolio(ABC):
	"""
	AbstractPortfolioHandler is a base class providing an interface for
	all subsequent (inherited) portfolio handlers.

	The goal of a derived PortfolioHandler is to provide a standardized
	interface for managing and interacting with portfolios. 
	Subclasses should implement specific functionality for
	managing portfolios, such as adding assets, adjusting positions,
	calculating portfolio metrics, and handling transactions.
	"""

	@abstractmethod
	def create(self, user_id: Any, name: str, exchange: str, initial_cash: Any) -> Any:
		raise NotImplementedError("Should implement create()")

	@abstractmethod
	def deposit(self, cash: Any) -> Any:
		"""
		Deposit money in the portfolio.
		"""
		raise NotImplementedError("Should implement deposit()")

	@abstractmethod
	def withdraw(self, cash: Any) -> Any:
		"""
		Withdraw money from the portfolio.
		"""
		raise NotImplementedError("Should implement withdraw()")

	@abstractmethod
	def process_transaction(self, transaction: Any) -> Any:
		"""
		Calculate the transaction cost and update the portfolio balance.
		Process the transaction updating or opening a new position.
		"""
		raise NotImplementedError("Should implement process_transaction()")

class AbstractPosition(ABC):

	@abstractmethod
	def create(self, date: Any, symbol: str, side: Any, quantity: Any, price: Any) -> Any:
		"""
		Create a new instance of the Position object.
		"""
		raise NotImplementedError("Should implement create()")

	@abstractmethod
	def transact_buy(self, date: Any, symbol: str, side: Any, quantity: Any, price: Any) -> Any:
		"""
		Update the position attributes after a buy transaction.
		"""
		raise NotImplementedError("Should implement transact_buy()")

	@abstractmethod
	def transact_sell(self, date: Any, symbol: str, side: Any, quantity: Any, price: Any) -> Any:
		"""
		Update the position attributes after a sell transaction.
		"""
		raise NotImplementedError("Should implement transact_sell()")
	
