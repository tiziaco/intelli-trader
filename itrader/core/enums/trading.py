"""
Trading-direction vocabulary for the iTrader engine.

``TradingDirection`` is the declared trading direction for a strategy (D-08
admission seam). It lives in ``core/enums/`` — its canonical home — and is
re-exported from ``core/sizing.py`` so the existing
``from itrader.core.sizing import TradingDirection`` call sites keep working.
This module imports stdlib ONLY (the core/enums dependency rule).
"""

from enum import Enum

__all__ = ["TradingDirection"]


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
