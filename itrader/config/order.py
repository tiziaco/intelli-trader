"""Order domain configuration (Pydantic v2, D-05).

A thin ``OrderConfig`` model that folds the loose stringly-typed
``OrderManager`` ctor param (``market_execution: str | MarketExecution =
"immediate"``) into the config layer, following the ``config/exchange.py``
convention (``ConfigDict(extra="forbid")`` + a ``default()`` classmethod).

Currently carries the single order-domain knob ``market_execution`` (the
system-level DEFAULT market-order execution timing); extensible later.

Coercion equivalence (D-05, RESEARCH Trap 5 / A1): ``MarketExecution`` is a
plain ``Enum`` (NOT ``str, Enum``) with explicit string values
(``"immediate"`` / ``"next_bar"``). Pydantic v2 validates an ``Enum`` field by
value, so ``model_validate({"market_execution": "immediate"})`` yields the
``MarketExecution.IMMEDIATE`` MEMBER — byte-identical to today's ctor coercion
``MarketExecution(market_execution)``. We do NOT use ``use_enum_values`` (it
would store the raw string instead of the member). Note the config-enum
exception (CONVENTIONS.md): ``MarketExecution`` stays in ``core/enums/``, it is
NOT relocated here.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict

from itrader.core.enums import MarketExecution


class TrailType(str, Enum):
    """How a trailing stop measures its trail distance (TRAIL-01).

    Config-enum exception (CONVENTIONS.md): the order-domain config enum lives
    here in ``config/order.py`` — NOT in ``core/enums/`` — by design (relocating
    it to core would invert the core->config dependency). Placed in the order
    domain (over ``config/exchange.py``) for order-domain cohesion (PATTERNS A3).
    Mirrors the ``FeeModelType`` ``(str, Enum)`` shape so Pydantic validates by
    value.

    - ``PRICE``   — an absolute quote distance below the high-water mark
                    (long) / above the low-water mark (short).
    - ``PERCENT`` — a fraction (0, 1) of the HWM/LWM.
    """

    PRICE = "price"
    PERCENT = "percent"


class OrderConfig(BaseModel):
    """Order-domain configuration (D-05).

    Thin Pydantic model carrying the system-level order defaults. ``extra``
    is forbidden so an unknown key is rejected (mass-assignment defense,
    T-04-01) rather than silently absorbed.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    market_execution: MarketExecution = MarketExecution.IMMEDIATE

    @classmethod
    def default(cls) -> "OrderConfig":
        """The backtest default order config (``market_execution="immediate"``)."""
        return cls()
