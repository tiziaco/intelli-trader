from abc import ABCMeta, abstractmethod

class AbstractPortfolioHandler(object):
	"""
	AbstractPortfolioHandler is a base class providing an interface for
	all subsequent (inherited) portfolio handlers.

	The goal of a derived PortfolioHandler is to provide a standardized
	interface for managing and interacting with portfolios. 
	Subclasses should implement specific functionality for
	managing portfolios, such as adding assets, adjusting positions,
	calculating portfolio metrics, and handling transactions.
	"""

	__metaclass__ = ABCMeta

	@abstractmethod
	def get_last_close(self, ticker):
		raise NotImplementedError("Should implement get_last_close()")
	

class AbstractPortfolio(object):
	"""
	AbstractPortfolioHandler is a base class providing an interface for
	all subsequent (inherited) portfolio handlers.

	The goal of a derived PortfolioHandler is to provide a standardized
	interface for managing and interacting with portfolios. 
	Subclasses should implement specific functionality for
	managing portfolios, such as adding assets, adjusting positions,
	calculating portfolio metrics, and handling transactions.
	"""

	__metaclass__ = ABCMeta

	@abstractmethod
	def create(self, user_id, name, exchange, initial_cash):
		raise NotImplementedError("Should implement create()")
	
	@abstractmethod
	def deposit(self, cash):
		"""
		Deposit money in the portfolio.
		"""
		raise NotImplementedError("Should implement get_last_close()")
	
	@abstractmethod
	def withdraw(self, cash):
		"""
		Withdraw money from the portfolio.
		"""
		raise NotImplementedError("Should implement get_last_close()")
	
	@abstractmethod
	def process_transaction(self, transaction):
		"""
		Calculate the transaction cost and update the portfolio balance.
		Process the transaction updating or opening a new position.
		"""
		raise NotImplementedError("Should implement get_last_close()")

class AbstractPosition(object):

	@abstractmethod
	def create(self, date, symbol, side, quantity, price):
		"""
		Create a new instance of the Position object.
		"""
		raise NotImplementedError("Should implement create()")
	
	@abstractmethod
	def transact_buy(self, date, symbol, side, quantity, price):
		"""
		Update the position attributes after a buy transaction.
		"""
		raise NotImplementedError("Should implement transact_buy()")
	
	@abstractmethod
	def transact_sell(self, date, symbol, side, quantity, price):
		"""
		Update the position attributes after a sell transaction.
		"""
		raise NotImplementedError("Should implement transact_sell()")
	
