"""
Base slippage model for simulating execution slippage (Decimal-native, D-12).

Validation contract (plan 06-04, T-06-13): ``validate_inputs`` raises typed
exceptions from the core ``ValidationError`` family — the old
bool-and-silently-return-1.0 contract is dead. A bad input is LOUD, never a
neutral factor.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any

from itrader.core.exceptions import ValidationError

# Known order-type strings (case-insensitive) accepted at the model boundary.
# TRAIL-01/TRAIL-02: a TRAILING_STOP fills like a STOP once its ratcheted level
# triggers (gap-aware), so the slippage model treats it identically to "stop";
# it must be a known type or the post-trigger fill slippage call raises here.
_KNOWN_ORDER_TYPES = {"market", "limit", "stop", "trailing_stop"}


class SlippageModel(ABC):
    """
    Abstract base class for slippage models.

    Slippage models calculate the price impact of orders during execution,
    simulating realistic market conditions where orders don't execute
    at the exact expected price.

    Money (D-12): the returned factor is Decimal; any RNG float jitter
    enters the Decimal domain exactly once via ``to_money`` (the Phase 2
    D-11 seeded-RNG seam is preserved — deterministic given the seed).
    """

    def __init__(self) -> None:
        """Initialize the slippage model."""
        pass

    @abstractmethod
    def calculate_slippage_factor(self, quantity: Decimal, price: Decimal,
                                  side: str = "buy", order_type: str = "market") -> Decimal:
        """
        Calculate the slippage factor for an order.

        Parameters
        ----------
        quantity : Decimal
            Order quantity
        price : Decimal
            Order price
        side : str
            Order side ('buy' or 'sell')
        order_type : str
            Order type ('market', 'limit', 'stop')

        Returns
        -------
        Decimal
            Slippage factor to multiply with price (Decimal("1") = no slippage)

        Raises
        ------
        ValidationError
            If any input is invalid — there is NO silent neutral-factor
            fallback (plan 06-04)
        """
        pass

    @abstractmethod
    def get_slippage_info(self) -> Dict[str, Any]:
        """
        Get information about the slippage model.

        Returns
        -------
        Dict[str, Any]
            Dictionary with slippage model information
        """
        pass

    def validate_inputs(self, quantity: Decimal, price: Decimal,
                        side: str = "buy", order_type: str = "market") -> None:
        """
        Validate input parameters.

        Raises typed exceptions (returns ``None`` on valid input) — the
        boolean contract that let models silently return a neutral 1.0
        factor on bad input is dead (plan 06-04, T-06-13).

        Parameters
        ----------
        quantity : Decimal
            Order quantity (must be positive)
        price : Decimal
            Order price (must be positive)
        side : str
            Order side ("buy" or "sell")
        order_type : str
            Order type ("market", "limit", "stop" — case-insensitive)

        Raises
        ------
        ValidationError
            If any parameter is invalid
        """
        if not isinstance(quantity, (int, Decimal)) or quantity <= 0:
            raise ValidationError("quantity", str(quantity), "must be a positive Decimal")

        if not isinstance(price, Decimal) or price <= 0:
            raise ValidationError("price", str(price), "must be a positive Decimal")

        if not isinstance(side, str) or side.lower() not in ("buy", "sell"):
            raise ValidationError("side", str(side), "must be 'buy' or 'sell'")

        if not isinstance(order_type, str) or order_type.lower() not in _KNOWN_ORDER_TYPES:
            raise ValidationError(
                "order_type", str(order_type),
                f"must be one of {sorted(_KNOWN_ORDER_TYPES)} (case-insensitive)")
