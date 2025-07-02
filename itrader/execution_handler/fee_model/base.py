from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Union, Dict, Any, Optional


class FeeModel(ABC):
    """
    Modern, simplified fee calculation interface for trading operations.
    
    Provides a clean, single-method interface for calculating trading fees
    with support for modern trading patterns including maker/taker fees
    and order-type specific calculations.
    """

    @abstractmethod
    def calculate_fee(
        self, 
        quantity: Union[int, float, Decimal], 
        price: Union[float, Decimal], 
        side: str = "buy",
        order_type: str = "market",
        **kwargs
    ) -> Decimal:
        """
        Calculate the total trading fee for an order.
        
        Parameters
        ----------
        quantity : Union[int, float, Decimal]
            Number of units/shares to trade (always positive)
        price : Union[float, Decimal]
            Price per unit (always positive)
        side : str, optional
            Order side - "buy" or "sell" (default: "buy")
        order_type : str, optional
            Order type - "market", "limit", etc. (default: "market")
        **kwargs
            Additional parameters for specific fee models
            
        Returns
        -------
        Decimal
            Total fee amount in quote currency (always >= 0)
            
        Raises
        ------
        ValueError
            If quantity or price are negative or zero
        """
        raise NotImplementedError("Subclasses must implement calculate_fee()")
    
    def validate_inputs(
        self, 
        quantity: Union[int, float, Decimal], 
        price: Union[float, Decimal], 
        side: str = "buy",
        order_type: str = "market"
    ) -> None:
        """
        Validate input parameters for fee calculation.
        
        Parameters
        ----------
        quantity : Union[int, float, Decimal]
            Number of units to trade
        price : Union[float, Decimal]
            Price per unit
        side : str
            Order side ("buy" or "sell")
        order_type : str
            Order type
            
        Raises
        ------
        ValueError
            If any parameter is invalid
        """
        if not isinstance(quantity, (int, float, Decimal)) or quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")
        
        if not isinstance(price, (float, Decimal)) or price <= 0:
            raise ValueError(f"Price must be positive, got {price}")
        
        if side not in ("buy", "sell"):
            raise ValueError(f"Side must be 'buy' or 'sell', got '{side}'")
            
        if not isinstance(order_type, str) or not order_type.strip():
            raise ValueError(f"Order type must be a non-empty string, got '{order_type}'")
    
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
