"""Strategy configuration base contract (TYPE-05 / SYN-02 relocation).

The relocated home of ``BaseStrategyConfig`` — the engine-facing declaration
contract every strategy subclasses. Moved here from ``strategy_handler/config.py``
so the typed strategy-config base lives alongside the other domain configs
(``PortfolioConfig`` / ``ExchangeConfig`` / ``SystemConfig``), re-exported via
``config/__init__.py``. Pure code-motion — fields/defaults/validators unchanged
(oracle-dark). The concrete configs (``SMA_MACDConfig`` / ``EmptyStrategyConfig``)
are co-located in their strategy modules.

Design decisions carried over from the original module:

- **D-01 — config-object constructor primitives.** The engine-facing fields
  live on ``BaseStrategyConfig``; concrete strategies subclass it with their
  own params.
- **D-03 — frozen config.** ``frozen=True`` — a constructed config is immutable;
  attribute assignment raises ``ValidationError``.
- **D-04 — typed order type.** ``order_type: OrderType`` (default
  ``OrderType.MARKET``) kills the stringly-typed seam.
- **D-05 — arbitrary_types_allowed for the sizing/SLTP unions.** The
  ``core/sizing.py`` frozen dataclasses are held without a pydantic schema
  error; ``model_dump`` still recurses into them (queryable snapshot, SIG-02).
- **D-06 — Timeframe enum at the boundary.** ``timeframe: Timeframe`` coerces a
  ``"1d"`` string to the enum and rejects unsupported strings loudly (HARD-01).

4-space indentation (config/ module house style).
"""

from pydantic import BaseModel, ConfigDict, Field

from itrader.core.enums import OrderType, TradingDirection, Timeframe
from itrader.core.sizing import SizingPolicy, SLTPPolicy


class BaseStrategyConfig(BaseModel):
    """Engine-facing declaration contract shared by every strategy (D-01).

    Frozen (D-03) and ``arbitrary_types_allowed`` (D-05) so the frozen
    ``core/sizing.py`` policy dataclasses are accepted as field values. NOT
    ``extra="forbid"`` — subclasses add their own params.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    timeframe: Timeframe
    tickers: list[str]
    order_type: OrderType = OrderType.MARKET
    direction: TradingDirection = TradingDirection.LONG_ONLY
    allow_increase: bool = False
    max_positions: int = Field(default=1, gt=0)
    sizing_policy: SizingPolicy
    sltp_policy: SLTPPolicy | None = None
