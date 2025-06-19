import numpy as np
from datetime import datetime
from typing import Optional, Dict, List, Any
from decimal import Decimal

from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.position import Position, PositionSide
from itrader.events_handler.event import BarEvent

# Import the new managers
from itrader.portfolio_handler.transaction_manager import TransactionManager
from itrader.portfolio_handler.position_manager import PositionManager
from itrader.portfolio_handler.cash_manager import CashManager
from itrader.portfolio_handler.metrics_manager import MetricsManager

from itrader import logger, idgen

TOLERANCE = 1e-3

class Portfolio(object):
	"""
	Represents a portfolio of assets. It contains a cash
	account with the ability to subscribe and withdraw funds.
	It also contains a list of positions in assets, encapsulated
	by a PositionHandler instance.

	Parameters
	----------
	user_id: str
		An identifier for the user owner of the portfolio.
	name: str
		The human-readable name of the portfolio.
	cash : float
		Starting cash of the portfolio.
	time : datetime
		Portfolio creation datetime. 
	"""

	def __init__(self, user_id: int, name: str, exchange: str, cash: float, time: datetime):
		"""
		Initialise the Portfolio object with a PositionHandler,
		along with cash balance.
		"""
		self.user_id = user_id
		self.portfolio_id = idgen.generate_portfolio_id()
		self.name = name
		self.exchange = exchange
		self.creation_time = time
		self.current_time = time
		
		# Initialize managers with production-ready architecture
		self.cash_manager = CashManager(self, initial_cash=cash)
		self.transaction_manager = TransactionManager(self)
		self.position_manager = PositionManager(self)
		self.metrics_manager = MetricsManager(self)
	
	def __str__(self):
		return f"Portfolio-{self.portfolio_id}"

	def __repr__(self):
		return str(self)

	# Properties that delegate to managers
	@property
	def cash(self) -> float:
		"""Get current cash balance."""
		return float(self.cash_manager.balance)
	
	@cash.setter
	def cash(self, value: float):
		"""Set cash balance."""
		current_balance = self.cash_manager.balance
		difference = Decimal(str(value)) - current_balance
		if difference > 0:
			self.cash_manager.deposit(difference, "Cash balance adjustment")
		elif difference < 0:
			self.cash_manager.withdraw(abs(difference), "Cash balance adjustment")

	@property
	def n_open_positions(self):
		"""
		Obtain the number of open positions present in the portfolio
		"""
		return len(self.position_manager.get_all_positions())

	@property
	def total_market_value(self):
		"""
		Obtain the total market value of the portfolio excluding cash.
		"""
		return float(self.position_manager.get_total_market_value())

	@property
	def total_equity(self):
		"""
		Obtain the total market value of the portfolio including cash.
		"""
		return self.total_market_value + self.cash

	@property
	def total_unrealised_pnl(self):
		"""
		Calculate the sum of all the positions' unrealised P&Ls.
		"""
		return float(self.position_manager.get_total_unrealized_pnl())

	@property
	def total_realised_pnl(self):
		"""
		Calculate the sum of all the positions' realised P&Ls,
		including both open and closed positions.
		"""
		return float(self.position_manager.get_total_realized_pnl())

	@property
	def total_pnl(self):
		"""
		Calculate the sum of all the positions' total P&Ls.
		"""
		return self.total_unrealised_pnl + self.total_realised_pnl
	
	@property
	def positions(self) -> dict[str, Position]:
		"""Get open positions as a dictionary."""
		return self.position_manager.get_all_positions()
	
	@property
	def closed_positions(self) -> list[Position]:
		"""Get closed positions as a list."""
		return self.position_manager.get_closed_positions()
	
	@property
	def transactions(self) -> list[Transaction]:
		"""Get all transactions as a list."""
		return self.transaction_manager.get_transaction_history()

	def process_transaction(self, transaction: Transaction):
		"""
		Process a transaction using the new manager architecture while 
		preserving existing short position logic and behavior.
		"""
		# Update transaction with portfolio information
		transaction.portfolio_id = self.portfolio_id
		
		# Process transaction through the managers in the correct order
		try:
			# Process position changes first (this handles short positions properly)
			position = self.position_manager.process_position_update(transaction)
			transaction.position_id = position.id
			
			# Process the transaction financially (cash flow) - this includes funds validation
			self.transaction_manager.process_transaction(transaction)
			
		except Exception as e:
			logger.error(f"Transaction processing failed: {e}")
			raise

	def update_market_value(self, bar_event: BarEvent):
		"""
		Updates the value of all positions that are currently open.
		"""
		tickers = bar_event.bars.keys()
		current_prices = {}
		
		for ticker in tickers:
			current_price = bar_event.get_last_close(ticker)
			current_prices[ticker] = current_price
		
		# Update all positions with new prices
		self.position_manager.update_position_market_values(current_prices, bar_event.time)

	def to_dict(self):
		return {
				'id' : self.portfolio_id,
				'name' : self.name,
				'exchange' : self.exchange,
				'n_open_positions' : len(self.positions),
				'total_market_value' : self.total_market_value,
				'available_cash' : self.cash,
				'total_equity' : self.total_equity,
				'total_unrealised_pnl' : self.total_unrealised_pnl,
				'total_realised_pnl' : self.total_realised_pnl,
				'total_pnl' : self.total_pnl
			}

	def record_metrics(self, time: datetime):
		"""Record portfolio metrics using the metrics manager."""
		self.metrics_manager.record_snapshot(time)

	def get_open_position(self, ticker):
		"""Get an open position by ticker."""
		return self.position_manager.get_position(ticker)
