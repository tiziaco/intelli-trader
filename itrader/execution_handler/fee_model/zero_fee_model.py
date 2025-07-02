from decimal import Decimal
from typing import Union, Dict, Any, Optional
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
        quantity: Union[int, float, Decimal], 
        price: Union[float, Decimal], 
        side: str = "buy",
        order_type: str = "market",
        **kwargs
    ) -> Decimal:
        """
        Calculate fee for an order (always returns Decimal('0')).
        
        Parameters
        ----------
        quantity : Union[int, float, Decimal]
            Number of units to trade
        price : Union[float, Decimal]
            Price per unit
        side : str, optional
            Order side ("buy" or "sell")
        order_type : str, optional
            Order type
        **kwargs
            Additional parameters (ignored)
            
        Returns
        -------
        Decimal
            Always returns Decimal('0') (no fees)
        """
        # Validate inputs for consistency
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
