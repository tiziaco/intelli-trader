from decimal import Decimal
from typing import Union, Dict, Any, Optional
from .base import FeeModel


class MakerTakerFeeModel(FeeModel):
    """
    Fee model implementing maker/taker fee structure common in cryptocurrency exchanges.
    
    Maker orders (limit orders that add liquidity) typically have lower fees,
    while taker orders (market orders that remove liquidity) have higher fees.
    This model supports order-type based fee determination.
    """

    def __init__(
        self, 
        maker_rate: float = 0.0005, 
        taker_rate: float = 0.001
    ):
        """
        Initialize the maker/taker fee model.
        
        Parameters
        ----------
        maker_rate : float, optional
            Default maker fee rate as decimal (e.g., 0.0005 = 0.05%)
        taker_rate : float, optional
            Default taker fee rate as decimal (e.g., 0.001 = 0.1%)
            
        Raises
        ------
        ValueError
            If any fee rate is negative
        """
        if maker_rate < 0:
            raise ValueError(f"Maker rate must be non-negative, got {maker_rate}")
        if taker_rate < 0:
            raise ValueError(f"Taker rate must be non-negative, got {taker_rate}")
        
        self.maker_rate = Decimal(str(maker_rate))
        self.taker_rate = Decimal(str(taker_rate))

    def calculate_fee(
        self, 
        quantity: Union[int, float, Decimal], 
        price: Union[float, Decimal], 
        side: str = "buy",
        order_type: str = "market",
        **kwargs
    ) -> Decimal:
        """
        Calculate maker/taker fee for an order.
        
        Parameters
        ----------
        quantity : Union[int, float, Decimal]
            Number of units to trade
        price : Union[float, Decimal]
            Price per unit
        side : str, optional
            Order side ("buy" or "sell")
        order_type : str, optional
            Order type ("market", "limit", etc.)
        **kwargs
            Additional parameters (e.g., is_maker boolean override)
            
        Returns
        -------
        Decimal
            Fee amount based on maker/taker classification
        """
        self.validate_inputs(quantity, price, side, order_type)
        
        # Convert to Decimal for precision
        quantity_decimal = Decimal(str(quantity))
        price_decimal = Decimal(str(price))
        trade_value = abs(quantity_decimal * price_decimal)
        
        # Determine if this is a maker or taker order
        is_maker = self._is_maker_order(order_type, **kwargs)
        
        # Apply appropriate fee
        if is_maker:
            return trade_value * self.maker_rate
        else:
            return trade_value * self.taker_rate

    def _is_maker_order(self, order_type: str, **kwargs) -> bool:
        """
        Determine if an order is a maker order.
        
        Parameters
        ----------
        order_type : str
            Order type
        **kwargs
            Additional parameters (e.g., is_maker override)
            
        Returns
        -------
        bool
            True if this is a maker order
        """
        # Allow explicit override
        if "is_maker" in kwargs:
            return bool(kwargs["is_maker"])
        
        # Default classification based on order type
        order_type_lower = order_type.lower()
        
        # Market orders are typically takers
        if order_type_lower in ("market", "market_order"):
            return False
        
        # Limit orders are typically makers (though not always)
        if order_type_lower in ("limit", "limit_order"):
            return True
        
        # Conservative default: assume taker (higher fee)
        return False

    def calculate_maker_fee(self, quantity: Union[int, float, Decimal], price: Union[float, Decimal]) -> Decimal:
        """Calculate fee for a maker order (limit order)."""
        return self.calculate_fee(quantity, price, order_type="limit", is_maker=True)
    
    def calculate_taker_fee(self, quantity: Union[int, float, Decimal], price: Union[float, Decimal]) -> Decimal:
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
