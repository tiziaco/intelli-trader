"""
Zero fee model — no fees on any trade (Decimal-native, D-12).
"""

from decimal import Decimal
from typing import Dict, Any

from .base import FeeModel


class ZeroFeeModel(FeeModel):
    """
    Fee model that applies no fees to any trading operations.

    Perfect for backtesting scenarios where you want to test strategy
    performance without fee considerations, or for simulated trading
    environments where fees are not relevant.
    """

    def calculate_fee(
        self,
        quantity: Decimal,
        price: Decimal,
        side: str = "buy",
        order_type: str = "market",
        is_maker: bool | None = None,
    ) -> Decimal:
        """
        Calculate fee for an order (always returns Decimal('0')).

        Parameters
        ----------
        quantity : Decimal
            Number of units to trade
        price : Decimal
            Price per unit
        side : str, optional
            Order side ("buy" or "sell")
        order_type : str, optional
            Order type
        is_maker : bool | None, optional
            Maker/taker context (ignored — zero fees either way)

        Returns
        -------
        Decimal
            Always returns Decimal('0') (no fees)
        """
        # Validate inputs for consistency (raises typed exceptions)
        self.validate_inputs(quantity, price, side, order_type)

        return Decimal('0')

    def get_fee_info(self) -> Dict[str, Any]:
        """Get information about this zero fee model."""
        base_info = super().get_fee_info()
        base_info.update({
            "description": "No fees applied to any trades",
            "fee_rate": 0.0,
            "currency": "N/A"
        })
        return base_info
