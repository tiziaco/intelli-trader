from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

import pandas as pd

from itrader.core.enums import OrderType, Side
from itrader.core.ids import StrategyId
from itrader.core.money import to_money
from itrader.core.sizing import SignalIntent, SizingPolicy, SLTPPolicy, TradingDirection
from itrader.outils.time_parser import to_timedelta
from itrader.strategy_handler.config import BaseStrategyConfig
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
	def __init__(self, name: str, config: BaseStrategyConfig) -> None:
		# D-01: single config object is the source of truth. The strategy
		# DECLARES its engine-facing settings as a frozen pydantic config;
		# the base reads them onto the instance for the engine to query.
		self.config: BaseStrategyConfig = config
		self.strategy_id: StrategyId = StrategyId(idgen.generate_strategy_id())
		self.name = name
		self.is_active = True
		# D-06: Timeframe is an enum on the config — pass its .value alias to
		# the legacy string-based to_timedelta converter.
		self.timeframe = to_timedelta(config.timeframe.value)
		self.tickers = config.tickers
		# D-04 / HARD-03: order_type is the OrderType ENUM end-to-end, read
		# straight off the config — the old stringly-typed seam is gone.
		self.order_type: OrderType = config.order_type
		# The handler reads this for per-portfolio fan-out — the strategy
		# itself never iterates it (D-12).
		self.subscribed_portfolios: list[int] = []
		# Typed declarations (D-01/D-08/D-10): the strategy DECLARES, the
		# engine resolves. sizing_policy is REQUIRED — no default, honest
		# contract (the old max_allocation float kwarg is dead).
		self.sizing_policy: SizingPolicy = config.sizing_policy
		self.direction: TradingDirection = config.direction
		self.allow_increase = config.allow_increase
		self.max_positions = config.max_positions
		# WR-06: typed declaration seam for the engine-side SLTP feature (D-13).
		# Previously the handler reached this via getattr(strategy,
		# 'sltp_policy', None) — a stringly-typed hole mypy could not check and
		# a typo silently turned into "no policy". Now it is read off the typed
		# config. None means the strategy declares no policy (the golden path).
		self.sltp_policy: SLTPPolicy | None = config.sltp_policy
		# MUTABLE runtime state stays on the instance, NEVER on the frozen
		# config (RESEARCH Pitfall 2).
		# Fetch width (bars) a concrete strategy needs available in its window.
		# Concrete strategies (e.g. SMA_MACD) override this in their __init__.
		self.max_window: int = 0
		# D-15: minimum completed bars required before the framework invokes
		# generate_signal — a DEDICATED warmup threshold, distinct from
		# max_window (fetch width). The handler short-circuits on this. Default
		# 0 means no warmup gating; SMA_MACD overrides it to its indicator
		# warmup. Disambiguating warmup from max_window preserves both the
		# SMA byte-exact firing tick (HARD-04) and count-based canaries that
		# need a wide max_window but no warmup gate.
		self.warmup: int = 0

	def to_dict(self) -> dict[str, Any]:
		return {
			"strategy_id" : self.strategy_id,
			"strategy_name": self.name,
			"subscribed_portfolios" : self.subscribed_portfolios,
			# D-04: order_type is the OrderType enum now — serialize its value.
			"order_type": self.order_type.value,
			"is_active" : self.is_active,
			# Typed declarations serialized in place of the dead settings dict.
			"sizing_policy" : repr(self.sizing_policy),
			"direction" : self.direction.value,
			"allow_increase" : self.allow_increase,
			"max_positions" : self.max_positions,
			# WR-06: the SLTP declaration is now a first-class typed kwarg, so it
			# serializes alongside the other declarations (None when undeclared).
			"sltp_policy" : repr(self.sltp_policy) if self.sltp_policy is not None else None,
		}

	def __str__(self) -> str:
		# D-14: generalize the per-strategy shape (was f'{self.name}_{self.timeframe}'
		# on SMA_MACD) onto the base. Use the stable config timeframe alias.
		return f'{self.name}_{self.config.timeframe.value}'

	def __repr__(self) -> str:
		return str(self)

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
