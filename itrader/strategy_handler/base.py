from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

import pandas as pd

from itrader.core.enums import Side
from itrader.core.ids import StrategyId
from itrader.core.money import to_money
from itrader.core.sizing import SignalIntent, SizingPolicy, TradingDirection
from itrader.outils.time_parser import to_timedelta
from itrader import idgen

class Strategy(ABC):
	"""
	Strategy is the pure-alpha abstract base for all strategies (D-12).

	A concrete strategy is a pure function of market data: it implements
	``generate_signal(ticker, bars) -> SignalIntent | None`` and DECLARES
	its sizing policy, trading direction, and admission settings at
	construction (D-01/D-03/D-08/D-10). It never touches the events queue,
	never stamps time or price, and never knows anything portfolio-shaped —
	``StrategiesHandler`` owns stamping, policy attachment, per-portfolio
	fan-out, and enqueueing (the #24 boundary).
	"""
	def __init__(self, name: str, timeframe: str, tickers: list[str],
				order_type: str = "market", *,
				sizing_policy: SizingPolicy,
				direction: TradingDirection = TradingDirection.LONG_ONLY,
				allow_increase: bool = False,
				max_positions: int = 1) -> None:
		self.strategy_id: StrategyId = StrategyId(idgen.generate_strategy_id())
		self.name = name
		self.is_active = True
		self.timeframe = to_timedelta(timeframe)
		self.tickers = tickers
		self.order_type = order_type
		# The handler reads this for per-portfolio fan-out — the strategy
		# itself never iterates it (D-12).
		self.subscribed_portfolios: list[int] = []
		# Typed declarations (D-01/D-08/D-10): the strategy DECLARES, the
		# engine resolves. sizing_policy is REQUIRED — no default, honest
		# contract (the old max_allocation float kwarg is dead).
		self.sizing_policy: SizingPolicy = sizing_policy
		self.direction: TradingDirection = direction
		self.allow_increase = allow_increase
		self.max_positions = max_positions
		# Lookback window (bars) a concrete strategy needs before it can signal.
		# Concrete strategies (e.g. SMA_MACD) override this in their __init__.
		self.max_window: int = 0

	def to_dict(self) -> dict[str, Any]:
		return {
			"strategy_id" : self.strategy_id,
			"strategy_name": self.name,
			"subscribed_portfolios" : self.subscribed_portfolios,
			"order_type": self.order_type,
			"is_active" : self.is_active,
			# Typed declarations serialized in place of the dead settings dict.
			"sizing_policy" : repr(self.sizing_policy),
			"direction" : self.direction.value,
			"allow_increase" : self.allow_increase,
			"max_positions" : self.max_positions,
		}

	@abstractmethod
	def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
		"""
		Evaluate market data for ``ticker`` and return a trading intent.

		The pure-alpha contract (D-12, M5-06): given the pushed history
		window, return a ``SignalIntent`` (typically via the ``buy()`` /
		``sell()`` sugar) or ``None`` when there is nothing to do. No queue,
		no event construction, no portfolio knowledge.
		"""
		raise NotImplementedError("Should implement generate_signal()")

	def buy(self, ticker: str, sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""
		Thin sugar returning a BUY ``SignalIntent`` for ``ticker``.

		Optional ``sl``/``tp`` enter the Decimal domain via ``to_money``
		(the D-04 string path) — exactly the entry the legacy emit path
		applied; ``None`` means "not declared".
		"""
		return SignalIntent(
			ticker=ticker,
			action=Side.BUY,
			stop_loss=to_money(sl) if sl is not None else None,
			take_profit=to_money(tp) if tp is not None else None,
			exit_fraction=exit_fraction,
		)

	def sell(self, ticker: str, sl: float | Decimal | None = None,
			tp: float | Decimal | None = None,
			exit_fraction: Decimal = Decimal("1")) -> SignalIntent:
		"""
		Thin sugar returning a SELL ``SignalIntent`` for ``ticker``.

		Optional ``sl``/``tp`` enter the Decimal domain via ``to_money``
		(the D-04 string path) — exactly the entry the legacy emit path
		applied; ``None`` means "not declared".
		"""
		return SignalIntent(
			ticker=ticker,
			action=Side.SELL,
			stop_loss=to_money(sl) if sl is not None else None,
			take_profit=to_money(tp) if tp is not None else None,
			exit_fraction=exit_fraction,
		)

	def subscribe_portfolio(self, portfolio_id: int) -> None:
		self.subscribed_portfolios.append(portfolio_id)

	def unsubscribe_portfolio(self, portfolio_id: int) -> None:
		self.subscribed_portfolios.remove(portfolio_id)

	def activate_strategy(self) -> None:
		self.is_active = True

	def deactivate_strategy(self) -> None:
		self.is_active = False
