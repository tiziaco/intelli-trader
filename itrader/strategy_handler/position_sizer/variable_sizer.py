from itrader.events_handler.events import SignalEvent
from typing import cast

from itrader.core.ids import PortfolioId
from itrader.core.portfolio_read_model import PortfolioReadModel

from itrader.logger import get_itrader_logger

class DynamicSizer():
	"""
	Size the order according to the cash available in the
	portfolio and the number of positions already opened.

	By default, it assaign 80% of the available cash at
	each order.

	Parameters
	----------
	integer_size : `boolean`
		Specify if only int size should be calculated
	max_allocation : `float`
		Allocation percentage (default: 80%)
	"""
	def __init__(self, portfolio_handler: PortfolioReadModel) -> None:
		# D-17: the sizer is part of the admission path — it reads through
		# the narrow PortfolioReadModel Protocol, never the concrete handler.
		self.portfolio_handler = portfolio_handler

		self.logger = get_itrader_logger().bind(component="DynamicSizer")
		self.logger.info('   POSITION SIZER: Dynamic Sizer => OK')


	def size_order(self, signal: SignalEvent) -> float:
		"""
		Calculate the size of the order (80% of the available cash).

		Returns the computed quantity; the signal is never mutated (D-03 —
		signals are immutable strategy facts, the order layer owns sizing).
		"""
		ticker = signal.ticker
		# 02-05 carry-over: events declare portfolio_id as int; runtime is UUID.
		portfolio_id = cast(PortfolioId, signal.portfolio_id)
		strategy_setting = signal.strategy_setting
		max_positions = int(strategy_setting.get('max_positions') or 1)
		max_allocation = float(strategy_setting.get('max_allocation') or 0.80)
		# Per-ticker membership composes from get_position (OQ1); the open
		# count backs the allocation split (admission metadata).
		open_position = self.portfolio_handler.get_position(portfolio_id, ticker)
		open_count = self.portfolio_handler.open_position_count(portfolio_id)

		quantity: float
		if open_position is not None:
			# The position is already open and will be closed, assign 100% of
			# the quantity (frozen PositionView snapshot, D-15).
			quantity = float(open_position.net_quantity)
		else:
			# New position, assign 80% of the cash. Sizing stays in float until M4
			# (locked decision); coerce the Decimal cash at this boundary.
			# available_cash is the single trading-decision figure (D-14;
			# available == total until plan 05-06 wires reservations).
			cash = float(self.portfolio_handler.available_cash(portfolio_id))
			last_price = signal.price

			available_pos = (max_positions - open_count)
			quantity = (cash * (max_allocation * (1 / available_pos))) / last_price

		# Define or not an integer value for the position size
		#TODO

		# Return the calculated size (the signal is never mutated, D-03).
		sized_quantity = round(quantity, 5)
		self.logger.debug('Order sized %s %s', sized_quantity, signal.ticker)
		return sized_quantity
