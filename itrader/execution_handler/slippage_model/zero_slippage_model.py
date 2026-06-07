"""
Zero slippage model - perfect execution with no slippage (Decimal-native, D-12).
"""

from decimal import Decimal
from typing import Dict, Any

from .base import SlippageModel


class ZeroSlippageModel(SlippageModel):
    """
    Zero slippage model that provides perfect execution with no slippage.

    This model always returns a slippage factor of Decimal("1"), meaning
    orders execute at exactly the expected price with no price impact.
    """

    def __init__(self) -> None:
        """Initialize the zero slippage model."""
        super().__init__()

    def calculate_slippage_factor(self, quantity: Decimal, price: Decimal,
                                  side: str = "buy", order_type: str = "market") -> Decimal:
        """
        Calculate slippage factor (always Decimal("1") for zero slippage).

        Parameters
        ----------
        quantity : Decimal
            Order quantity (ignored)
        price : Decimal
            Order price (ignored)
        side : str
            Order side (ignored)
        order_type : str
            Order type (ignored)

        Returns
        -------
        Decimal
            Always returns Decimal("1") (no slippage)
        """
        return Decimal("1")

    def get_slippage_info(self) -> Dict[str, Any]:
        """
        Get information about the zero slippage model.

        Returns
        -------
        Dict[str, Any]
            Model information
        """
        return {
            'model_type': 'zero',
            'name': 'Zero Slippage Model',
            'description': 'Perfect execution with no slippage',
            'parameters': {},
            'supports_order_types': ['market', 'limit'],
            'supports_sides': ['buy', 'sell']
        }
