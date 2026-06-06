"""
Maker/taker fee model — real-order-context classification (Decimal-native, D-11/D-12).
"""

from decimal import Decimal
from typing import Dict, Any

from itrader.core.money import to_money

from .base import FeeModel


class MakerTakerFeeModel(FeeModel):
    """
    Fee model implementing maker/taker fee structure common in cryptocurrency exchanges.

    Maker orders (limit orders that add liquidity) typically have lower fees,
    while taker orders (market orders that remove liquidity) have higher fees.

    Classification (D-11): the ``is_maker`` parameter is AUTHORITATIVE when
    provided — the exchange derives it from the real order context (resting
    limit = maker; market and triggered stop = taker). The order_type-string
    fallback survives only for direct callers that pass no context.
    """

    def __init__(
        self,
        maker_rate: float | Decimal = 0.0005,
        taker_rate: float | Decimal = 0.001
    ):
        """
        Initialize the maker/taker fee model.

        Parameters
        ----------
        maker_rate : float | Decimal, optional
            Default maker fee rate as decimal fraction (e.g., 0.0005 = 0.05%);
            converted once to Decimal via ``to_money``
        taker_rate : float | Decimal, optional
            Default taker fee rate as decimal fraction (e.g., 0.001 = 0.1%);
            converted once to Decimal via ``to_money``

        Raises
        ------
        ValueError
            If any fee rate is negative
        """
        self.maker_rate = to_money(maker_rate)
        self.taker_rate = to_money(taker_rate)

        if self.maker_rate < 0:
            raise ValueError(f"Maker rate must be non-negative, got {self.maker_rate}")
        if self.taker_rate < 0:
            raise ValueError(f"Taker rate must be non-negative, got {self.taker_rate}")

    def calculate_fee(
        self,
        quantity: Decimal,
        price: Decimal,
        side: str = "buy",
        order_type: str = "market",
        is_maker: bool | None = None,
    ) -> Decimal:
        """
        Calculate maker/taker fee for an order.

        Parameters
        ----------
        quantity : Decimal
            Number of units to trade
        price : Decimal
            Price per unit
        side : str, optional
            Order side ("buy" or "sell")
        order_type : str, optional
            Order type ("market", "limit", "stop")
        is_maker : bool | None, optional
            Authoritative maker/taker classification from real order context
            (D-11). ``None`` falls back to order_type-string classification.

        Returns
        -------
        Decimal
            Fee amount based on maker/taker classification
        """
        self.validate_inputs(quantity, price, side, order_type)

        # Pure Decimal arithmetic — no float casts, no quantization (D-12/D-14)
        trade_value = abs(quantity * price)

        # D-11: explicit context is authoritative; fall back to the
        # order_type string only when no context was provided.
        maker = is_maker if is_maker is not None else self._is_maker_order(order_type)

        if maker:
            return trade_value * self.maker_rate
        else:
            return trade_value * self.taker_rate

    def _is_maker_order(self, order_type: str) -> bool:
        """
        Classify maker/taker from the order-type string (fallback path).

        Parameters
        ----------
        order_type : str
            Order type

        Returns
        -------
        bool
            True if this is a maker order
        """
        order_type_lower = order_type.lower()

        # Market orders are typically takers
        if order_type_lower in ("market", "market_order"):
            return False

        # Limit orders are typically makers (though not always)
        if order_type_lower in ("limit", "limit_order"):
            return True

        # Conservative default: assume taker (higher fee)
        return False

    def calculate_maker_fee(self, quantity: Decimal, price: Decimal) -> Decimal:
        """Calculate fee for a maker order (limit order)."""
        return self.calculate_fee(quantity, price, order_type="limit", is_maker=True)

    def calculate_taker_fee(self, quantity: Decimal, price: Decimal) -> Decimal:
        """Calculate fee for a taker order (market order)."""
        return self.calculate_fee(quantity, price, order_type="market", is_maker=False)

    def get_fee_info(self) -> Dict[str, Any]:
        """Get information about this maker/taker fee model."""
        base_info = super().get_fee_info()
        base_info.update({
            "description": "Maker/taker fee structure with order-type based rates",
            "maker_rate": float(self.maker_rate),
            "taker_rate": float(self.taker_rate),
            "maker_rate_pct": f"{float(self.maker_rate) * 100:.4f}%",
            "taker_rate_pct": f"{float(self.taker_rate) * 100:.4f}%",
            "savings_pct": f"{((float(self.taker_rate) - float(self.maker_rate)) / float(self.taker_rate) * 100):.1f}%" if self.taker_rate > 0 else "0%"
        })
        return base_info
