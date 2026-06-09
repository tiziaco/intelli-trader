"""
Trading-direction vocabulary for the iTrader engine.

``TradingDirection`` is the declared trading direction for a strategy (D-08
admission seam). It lives in ``core/enums/`` — its canonical home — and is
re-exported from ``core/sizing.py`` so the existing
``from itrader.core.sizing import TradingDirection`` call sites keep working.
This module imports stdlib ONLY (the core/enums dependency rule).
"""

from enum import Enum

__all__ = ["TradingDirection", "Timeframe"]


class TradingDirection(Enum):
    """Declared trading direction for a strategy (D-08 admission seam).

    Class-based with explicit string values and a case-insensitive
    ``_missing_`` (the OrderType house pattern) so a boundary parse like
    ``TradingDirection("long_only")`` resolves any casing and raises a clear
    ``ValueError`` on unknown strings instead of silently coercing.
    """

    LONG_ONLY = "LONG_ONLY"
    LONG_SHORT = "LONG_SHORT"
    SHORT_ONLY = "SHORT_ONLY"

    @classmethod
    def _missing_(cls, value: object) -> "TradingDirection":
        """Case-insensitive string parse; raise a clear f-string error."""
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown TradingDirection: {value!r}")


class Timeframe(Enum):
    """Supported fixed-duration strategy timeframe vocabulary (D-06).

    Engine-facing declaration parsed at the config boundary (HARD-01): a
    strategy declares ``timeframe="1d"`` and the pydantic config coerces it to
    a ``Timeframe`` member, rejecting any unsupported string loudly. The
    member values mirror the ``to_timedelta`` d/h/m/w vocabulary; ``1d`` MUST
    be valid (the golden BTCUSD run is daily).

    Class-based with explicit string values and a case-insensitive
    ``_missing_`` (the ``TradingDirection`` house pattern) so a boundary parse
    like ``Timeframe("1D")`` resolves any casing and raises a clear
    ``ValueError`` on unknown strings instead of silently coercing.
    """

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"

    @classmethod
    def _missing_(cls, value: object) -> "Timeframe":
        """Case-insensitive string parse; raise a clear f-string error."""
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown Timeframe: {value!r}")
