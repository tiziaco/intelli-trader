from enum import Enum
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Union

from itrader import idgen
from itrader.portfolio_handler.transaction import Transaction
from itrader.core.enums import PositionSide, TransactionType
from itrader.core.ids import PortfolioId, PositionId
from itrader.core.money import to_money

# Money values accepted at construction boundaries (D-04): to_money normalises
# int/float/Decimal to Decimal, so accept the wider input type on the seams.
MoneyInput = Union[Decimal, int, float]

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
		price: MoneyInput,
		buy_quantity: MoneyInput,
		sell_quantity: MoneyInput,
		avg_bought: MoneyInput,
		avg_sold: MoneyInput,
		buy_commission: MoneyInput,
		sell_commission: MoneyInput,
		is_open: bool,
		portfolio_id: "PortfolioId | int",
		leverage: MoneyInput = Decimal("1"),
	) -> None:
		self.id: PositionId = PositionId(idgen.generate_position_id())
		self.ticker = ticker
		self.side = side
		# D-06: one effective leverage per position (isolated margin), set at
		# open. Enters the Decimal domain via to_money (string path). Default
		# Decimal("1") keeps spot positions byte-exact — the spot path never
		# sets it. A scale-in CLAMPS a differing signal leverage to this value
		# (the position's leverage is immutable after open); see
		# PositionManager._update_existing_position.
		self.leverage = to_money(leverage)
		# Money fields enter the Decimal domain at the construction boundary (D-04):
		# callers may pass int/float (e.g. the opposite-side 0 in open_position).
		self.current_price = to_money(price)
		self.current_time = entry_date
		self.buy_quantity = to_money(buy_quantity)
		self.sell_quantity = to_money(sell_quantity)
		self.avg_bought = to_money(avg_bought)
		self.avg_sold = to_money(avg_sold)
		self.buy_commission = to_money(buy_commission)
		self.sell_commission = to_money(sell_commission)
		self.entry_date = entry_date
		self.exit_date: Optional[datetime] = None
		self.is_open = is_open
		self.portfolio_id = portfolio_id
		# CARRY-01/D-04: per-short borrow-interest accrual marker. The carry days
		# basis is (bar_time − _last_accrual_time); seeded at the position entry
		# and advanced to the bar's business time after each per-bar accrual. None
		# until the carry hook first reads it (then it falls back to entry_date).
		# Decimal carry never folds into realised_pnl (D-08).
		self._last_accrual_time: Optional[datetime] = None
		# D-05 (PERF-08): explicit fill-invalidated caches for the two fill-derived
		# hot properties. net_quantity / avg_price recompute Decimal arithmetic on
		# every access and are hit repeatedly per bar (market_value /
		# aggregate_notional / unrealised_pnl). They depend ONLY on the six
		# fill-mutated inputs (buy_quantity / sell_quantity / commissions /
		# avg_bought / avg_sold), so an explicit None-until-first-read field
		# (mirroring _last_accrual_time, CARRY-01) is safe: it is reset to None at
		# the single input mutator (update_position). NOT functools.cached_property
		# (D-05 rejected the descriptor route on this hand-written class). Cached
		# values stay Decimal (Decimal end-to-end). current_price is NOT an input
		# here, so market_value / aggregate_notional stay live on the per-bar price.
		self._net_quantity_cache: Optional[Decimal] = None
		self._avg_price_cache: Optional[Decimal] = None

	def __repr__(self) -> str:
		rep = ('%s, %s, %s'%(self.ticker, self.side.name, self.net_quantity))
		return rep


	@property
	def market_value(self) -> Decimal:
		"""
		Return the market value (respecting the direction) of the
		Position based on the current price available to the Position.
		For short positions, this returns a negative value representing the liability.
		"""
		if self.side == PositionSide.SHORT:
			return -self.current_price * abs(self.net_quantity)
		else:
			return self.current_price * abs(self.net_quantity)

	@property
	def aggregate_notional(self) -> Decimal:
		"""
		Direction-agnostic notional magnitude of the open position (D-11).

		``|net_quantity| × avg_price`` — the POSITIVE magnitude mirroring
		``abs(market_value)`` (the SHORT side of market_value is negative; this
		basis is always positive). It is the basis for the margin lock
		(``locked_margin = aggregate_notional / leverage``), recomputed as fills
		aggregate. NOT stored on the Position — the lock lives in CashManager
		(D-13); this property exposes the magnitude the lock is computed from.
		"""
		return abs(self.net_quantity) * self.avg_price

	@property
	def avg_price(self) -> Decimal:
		"""
		The average price paid for all assets on the long or short side.
		"""
		# DEF-01-A reconciled here (M2a #17/#22): commissions are now Decimal
		# end-to-end, so the former float(self.*_commission) coercion is removed —
		# the whole expression stays in the Decimal domain.
		# D-05 (PERF-08): serve from the fill-invalidated cache; the expression
		# below is byte-unchanged from the pre-cache property. Reset in
		# update_position (the only input mutator).
		if self._avg_price_cache is None:
			if self.side == PositionSide.LONG:
				self._avg_price_cache = (self.avg_bought * self.buy_quantity + self.buy_commission) / self.buy_quantity
			else: # side = 'SHORT'
				self._avg_price_cache = (self.avg_sold * self.sell_quantity - self.sell_commission) / self.sell_quantity
		return self._avg_price_cache

	@property
	def net_quantity(self) -> Decimal:
		"""
		The difference in the quantity of assets bought and sold to date.
		"""
		# D-05 (PERF-08): fill-invalidated cache; abs(buy-sell) is byte-unchanged.
		if self._net_quantity_cache is None:
			self._net_quantity_cache = abs(self.buy_quantity - self.sell_quantity)
		return self._net_quantity_cache

	@property
	def total_bought(self) -> Decimal:
		"""
		Calculates the total average cost of assets bought.
		"""
		return self.avg_bought * self.buy_quantity

	@property
	def total_sold(self) -> Decimal:
		"""
		Calculates the total average cost of assets sold.
		"""
		return self.avg_sold * self.sell_quantity

	@property
	def net_total(self) -> Decimal:
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
				# For short positions, use absolute value of market_value 
				# since market_value is now negative (representing liability)
				return self.total_sold - abs(self.market_value)

	@property
	def commission(self) -> Decimal:
		"""
		Calculates the total commission from assets bought and sold.
		"""
		return self.buy_commission + self.sell_commission

	@property
	def net_incl_commission(self) -> Decimal:
		"""
		Calculates the net total average cost of assets bought
		and sold including the commission.
		"""
		return self.net_total - self.commission

	@property
	def realised_pnl(self) -> Decimal:
		"""
		Calculates the profit & loss (P&L) that has been realised.
		"""
		if self.side == PositionSide.LONG:
			if self.sell_quantity == 0:
				return Decimal("0")
			else:
				return (
					((self.avg_sold - self.avg_bought) * self.sell_quantity) -
					((self.sell_quantity / self.buy_quantity) * self.buy_commission) -
					self.sell_commission
				)
		elif self.side == PositionSide.SHORT:
			if self.buy_quantity == 0:
				return Decimal("0")
			else:
				return (
					((self.avg_sold - self.avg_bought) * self.buy_quantity) -
					((self.buy_quantity / self.sell_quantity) * self.sell_commission) -
					self.buy_commission
				)
		else:
			return self.net_incl_commission

	@property
	def unrealised_pnl(self) -> Decimal:
		"""
		Calculates the profit & loss (P&L) that has yet to be 'realised'
		in the remaining non-zero quantity of assets, due to the current
		market price.
		"""
		if self.side == PositionSide.LONG:
			return (self.current_price - self.avg_price) * self.net_quantity
		elif self.side == PositionSide.SHORT:
			return (self.avg_price - self.current_price) * self.net_quantity
		return Decimal("0")

	@property
	def total_pnl(self) -> Decimal:
		"""
		Calculates the sum of the unrealised and realised profit & loss (P&L).
		"""
		return self.realised_pnl + self.unrealised_pnl

	@classmethod
	def open_position(cls, transaction: Transaction) -> "Position":
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
			# D-06: the one effective leverage, taken from the opening fill's
			# signal leverage. The spot path's Transaction has no leverage
			# attribute → default Decimal("1") (byte-exact, oracle-dark).
			leverage = getattr(transaction, "leverage", Decimal("1")),
		)

	def update_position(self, transaction: Transaction) -> None:
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
		# D-05 (PERF-08): this is the ONLY site that mutates the six fill-derived
		# inputs (buy/sell_quantity, buy/sell_commission, avg_bought/avg_sold), so
		# both caches are invalidated here. A grep audit confirms no other mutator
		# exists outside __init__ construction.
		self._net_quantity_cache = None
		self._avg_price_cache = None
		self.update_current_price_time(transaction.price, transaction.time)

	def close_position(self, price: MoneyInput, time: datetime) -> None:
		"""
		Close the position.
		"""
		self.is_open = False
		self.exit_date = time
		self.current_price = to_money(price)

	def update_current_price_time(self, price: MoneyInput, time: datetime) -> None:
		"""
		Updates the Position's awareness of the current market price
		and time.

		Parameters
		----------
		price : `Decimal`
			The current market price.
		time : `datetime`
			The optional timestamp of the current market price.
		"""
		self.current_price = to_money(price)
		self.current_time = time

	def to_dict(self) -> dict[str, Any]:
			return {
				'position_id': self.id,
				'portfolio_id': self.portfolio_id,
				'is_open': self.is_open,
				'current_price': self.current_price,
				'entry_date': self.entry_date,
				'exit_date': self.exit_date,
				'pair': self.ticker,
				'side': self.side.name,
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