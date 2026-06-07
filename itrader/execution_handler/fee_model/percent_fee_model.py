"""
Percentage fee model — fixed rate on trade value (Decimal-native, D-12).
"""

from decimal import Decimal
from typing import Dict, Any, Optional

from itrader.core.money import to_money

from .base import FeeModel


class PercentFeeModel(FeeModel):
    """
    Fee model that applies a fixed percentage fee to all trading operations.

    Commonly used for traditional brokers and some exchanges that charge
    a simple percentage of trade value. Supports different rates for
    buy and sell orders if needed.

    Money (D-12): rates are held as Decimal — constructor floats convert
    ONCE via ``to_money``; the fee arithmetic is pure Decimal.
    """

    def __init__(self, fee_rate: float | Decimal = 0.001,
                 buy_rate: Optional[float | Decimal] = None,
                 sell_rate: Optional[float | Decimal] = None):
        """
        Initialize the percentage fee model.

        Parameters
        ----------
        fee_rate : float | Decimal, optional
            Default fee rate as decimal fraction (e.g., 0.001 = 0.1%);
            converted once to Decimal via ``to_money``
        buy_rate : float | Decimal, optional
            Specific fee rate for buy orders. If None, uses fee_rate
        sell_rate : float | Decimal, optional
            Specific fee rate for sell orders. If None, uses fee_rate

        Raises
        ------
        ValueError
            If any fee rate is negative
        """
        self.fee_rate = to_money(fee_rate)
        self.buy_rate = to_money(buy_rate) if buy_rate is not None else self.fee_rate
        self.sell_rate = to_money(sell_rate) if sell_rate is not None else self.fee_rate

        if self.fee_rate < 0:
            raise ValueError(f"Fee rate must be non-negative, got {self.fee_rate}")
        if self.buy_rate < 0:
            raise ValueError(f"Buy rate must be non-negative, got {self.buy_rate}")
        if self.sell_rate < 0:
            raise ValueError(f"Sell rate must be non-negative, got {self.sell_rate}")

    def calculate_fee(
        self,
        quantity: Decimal,
        price: Decimal,
        side: str = "buy",
        order_type: str = "market",
        is_maker: bool | None = None,
    ) -> Decimal:
        """
        Calculate percentage-based fee for an order.

        Parameters
        ----------
        quantity : Decimal
            Number of units to trade
        price : Decimal
            Price per unit
        side : str, optional
            Order side ("buy" or "sell")
        order_type : str, optional
            Order type (ignored in this model)
        is_maker : bool | None, optional
            Maker/taker context (ignored — flat percentage either way)

        Returns
        -------
        Decimal
            Fee amount (percentage of trade value)
        """
        self.validate_inputs(quantity, price, side, order_type)

        # Pure Decimal arithmetic — no float casts, no quantization (D-12/D-14)
        trade_value = abs(quantity * price)

        # Apply appropriate rate based on side
        if side == "buy":
            return trade_value * self.buy_rate
        else:  # sell
            return trade_value * self.sell_rate

    def get_fee_info(self) -> Dict[str, Any]:
        """Get information about this percentage fee model."""
        base_info = super().get_fee_info()
        base_info.update({
            "description": "Percentage-based fee on trade value",
            "default_rate": float(self.fee_rate),
            "buy_rate": float(self.buy_rate),
            "sell_rate": float(self.sell_rate),
            "buy_rate_pct": f"{float(self.buy_rate) * 100:.4f}%",
            "sell_rate_pct": f"{float(self.sell_rate) * 100:.4f}%"
        })
        return base_info
