from decimal import Decimal
from typing import Union, Dict, Any, Optional
from .base import FeeModel


class PercentFeeModel(FeeModel):
    """
    Fee model that applies a fixed percentage fee to all trading operations.
    
    Commonly used for traditional brokers and some exchanges that charge
    a simple percentage of trade value. Supports different rates for
    buy and sell orders if needed.
    """

    def __init__(self, fee_rate: float = 0.001, buy_rate: Optional[float] = None, sell_rate: Optional[float] = None):
        """
        Initialize the percentage fee model.
        
        Parameters
        ----------
        fee_rate : float, optional
            Default fee rate as decimal (e.g., 0.001 = 0.1%)
        buy_rate : float, optional
            Specific fee rate for buy orders. If None, uses fee_rate
        sell_rate : float, optional
            Specific fee rate for sell orders. If None, uses fee_rate
            
        Raises
        ------
        ValueError
            If any fee rate is negative
        """
        if fee_rate < 0:
            raise ValueError(f"Fee rate must be non-negative, got {fee_rate}")
        
        self.fee_rate = Decimal(str(fee_rate))
        self.buy_rate = Decimal(str(buy_rate)) if buy_rate is not None else self.fee_rate
        self.sell_rate = Decimal(str(sell_rate)) if sell_rate is not None else self.fee_rate
        
        if self.buy_rate < 0:
            raise ValueError(f"Buy rate must be non-negative, got {self.buy_rate}")
        if self.sell_rate < 0:
            raise ValueError(f"Sell rate must be non-negative, got {self.sell_rate}")

    def calculate_fee(
        self, 
        quantity: Union[int, float, Decimal], 
        price: Union[float, Decimal], 
        side: str = "buy",
        order_type: str = "market",
        **kwargs
    ) -> Decimal:
        """
        Calculate percentage-based fee for an order.
        
        Parameters
        ----------
        quantity : Union[int, float, Decimal]
            Number of units to trade
        price : Union[float, Decimal]
            Price per unit
        side : str, optional
            Order side ("buy" or "sell")
        order_type : str, optional
            Order type (ignored in this model)
        **kwargs
            Additional parameters (ignored)
            
        Returns
        -------
        Decimal
            Fee amount (percentage of trade value)
        """
        self.validate_inputs(quantity, price, side, order_type)
        
        # Convert to Decimal for precision
        quantity_decimal = Decimal(str(quantity))
        price_decimal = Decimal(str(price))
        
        # Calculate trade value
        trade_value = abs(quantity_decimal * price_decimal)
        
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
