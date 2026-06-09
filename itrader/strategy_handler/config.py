"""Strategy configuration models (Plan 05-01, HARD-01/HARD-02, D-01..D-06).

The typed contract surface every later Phase 5 plan builds against. A strategy
declares its engine-facing settings (timeframe, tickers, order type, direction,
sizing policy) plus its per-strategy params as a frozen pydantic model that
validates at construction. None of these are wired into ``base.py`` or the
handler yet (Plan 02) — this module only ADDS the contracts, so the oracle is
dark by construction.

Design decisions:

- **D-01 — config-object constructor primitives.** The engine-facing fields
  live on ``BaseStrategyConfig``; concrete strategies subclass it with their
  own params (``SMA_MACDConfig``).
- **D-02 — per-strategy params subclass.** ``SMA_MACDConfig`` adds the SMA/MACD
  windows; ``EmptyStrategyConfig`` adds nothing.
- **D-03 — frozen config.** ``frozen=True`` — a constructed config is immutable;
  attribute assignment raises ``ValidationError``.
- **D-04 — typed order type.** ``order_type: OrderType`` (default
  ``OrderType.MARKET``) kills the stringly-typed seam.
- **D-05 — arbitrary_types_allowed for the sizing/SLTP unions.** The
  ``core/sizing.py`` frozen dataclasses are held without a pydantic schema
  error; ``model_dump`` still recurses into them (queryable snapshot, SIG-02).
- **D-06 — Timeframe enum at the boundary.** ``timeframe: Timeframe`` coerces a
  ``"1d"`` string to the enum and rejects unsupported strings loudly (HARD-01).

Pydantic v2 decorators ONLY (``@model_validator(mode="after")``, never v1
``@validator``) — ``filterwarnings=["error"]`` fails on the deprecation
(RESEARCH Pitfall 5). 4-space indentation (pydantic module house style).
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class SMA_MACDConfig(BaseStrategyConfig):
    """Per-strategy params for the reference SMA_MACD strategy (D-02).

    Golden defaults mirror ``SMA_MACD_strategy.__init__``: short=50, long=100,
    FAST=6, SLOW=12, WIN=3. The ``_short_lt_long`` cross-field rule (HARD-02)
    rejects ``short_window >= long_window`` at construction.
    """

    short_window: int = Field(default=50, gt=0)
    long_window: int = Field(default=100, gt=0)
    FAST: int = Field(default=6, gt=0)
    SLOW: int = Field(default=12, gt=0)
    WIN: int = Field(default=3, gt=0)

    @model_validator(mode="after")
    def _short_lt_long(self) -> "SMA_MACDConfig":
        """HARD-02 cross-field rule: short_window must be strictly < long_window."""
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be < long_window")
        return self


class EmptyStrategyConfig(BaseStrategyConfig):
    """No-extra-params config for the relocated Empty_strategy (Plan 02)."""
