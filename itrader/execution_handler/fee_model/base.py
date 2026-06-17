"""
Fee model ABC — Decimal-native fee calculation for trading operations (D-12).

Validation contract (the SURVIVOR pattern, plan 06-04): ``validate_inputs``
raises typed exceptions from the core ``ValidationError`` family and returns
``None`` — there is no boolean contract and no silent fallback anywhere in
the fee/slippage layer.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any

from itrader.core.exceptions import ValidationError

# Known order-type strings (case-insensitive) accepted at the model boundary.
# TRAIL-01/TRAIL-02: a TRAILING_STOP is a taker fill like a STOP once triggered,
# so the fee model accepts it as a known type (is_maker is False for it, matching
# STOP); without this the post-trigger fee call raises a ValidationError.
_KNOWN_ORDER_TYPES = {"market", "limit", "stop", "trailing_stop"}


class FeeModel(ABC):
    """
    Decimal-native fee calculation interface for trading operations.

    Money (D-12): quantities, prices, rates, and returned fees are Decimal
    end-to-end — no float casts inside fee math, no quantization (rounding
    happens only at money boundaries, never in fee models).
    """

    def validate_inputs(
        self,
        quantity: Decimal,
        price: Decimal,
        side: str = "buy",
        order_type: str = "market",
    ) -> None:
        """
        Validate input parameters for fee calculation.

        Raises typed exceptions (returns ``None`` on valid input) — the
        boolean validation contract is dead (plan 06-04, T-06-13).

        Parameters
        ----------
        quantity : Decimal
            Number of units to trade (must be positive)
        price : Decimal
            Price per unit (must be positive)
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

        if side not in ("buy", "sell"):
            raise ValidationError("side", side, "must be 'buy' or 'sell'")

        if not isinstance(order_type, str) or order_type.lower() not in _KNOWN_ORDER_TYPES:
            raise ValidationError(
                "order_type", str(order_type),
                f"must be one of {sorted(_KNOWN_ORDER_TYPES)} (case-insensitive)")

    @abstractmethod
    def calculate_fee(
        self,
        quantity: Decimal,
        price: Decimal,
        side: str = "buy",
        order_type: str = "market",
        is_maker: bool | None = None,
    ) -> Decimal:
        """
        Calculate the total trading fee for an order.

        Parameters
        ----------
        quantity : Decimal
            Number of units/shares to trade (always positive)
        price : Decimal
            Price per unit (always positive)
        side : str, optional
            Order side - "buy" or "sell" (default: "buy")
        order_type : str, optional
            Order type - "market", "limit", "stop" (default: "market")
        is_maker : bool | None, optional
            Real order context (D-11): authoritative maker/taker
            classification when provided; ``None`` lets the model fall back
            to its own order_type-string classification.

        Returns
        -------
        Decimal
            Total fee amount in quote currency (always >= 0)

        Raises
        ------
        ValidationError
            If quantity or price are not positive, or side/order_type unknown
        """
        raise NotImplementedError("Subclasses must implement calculate_fee()")

    @property
    def fee_type(self) -> str:
        """
        Get the type of fee model for identification.

        Returns
        -------
        str
            Fee model type identifier
        """
        return self.__class__.__name__

    def get_fee_info(self) -> Dict[str, Any]:
        """
        Get information about this fee model configuration.

        Returns
        -------
        Dict[str, Any]
            Fee model information and parameters
        """
        return {
            "type": self.fee_type,
            "description": self.__doc__.split('\n')[1].strip() if self.__doc__ else "No description",
            "supports_order_types": True
        }
