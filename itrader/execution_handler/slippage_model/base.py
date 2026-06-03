"""
Base slippage model for simulating execution slippage.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from decimal import Decimal


class SlippageModel(ABC):
    """
    Abstract base class for slippage models.
    
    Slippage models calculate the price impact of orders during execution,
    simulating realistic market conditions where orders don't execute 
    at the exact expected price.
    """
    
    def __init__(self):
        """Initialize the slippage model."""
        pass
    
    @abstractmethod
    def calculate_slippage_factor(self, quantity: float, price: float, 
                                side: str, order_type: str = "market") -> float:
        """
        Calculate the slippage factor for an order.
        
        Parameters
        ----------
        quantity : float
            Order quantity
        price : float
            Order price
        side : str
            Order side ('buy' or 'sell')
        order_type : str
            Order type ('market', 'limit', etc.)
            
        Returns
        -------
        float
            Slippage factor to multiply with price (1.0 = no slippage)
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
    
    def validate_inputs(self, quantity: float, price: float, side: str, order_type: str) -> bool:
        """
        Validate input parameters.
        
        Parameters
        ----------
        quantity : float
            Order quantity
        price : float
            Order price
        side : str
            Order side
        order_type : str
            Order type
            
        Returns
        -------
        bool
            True if inputs are valid
        """
        if quantity <= 0:
            return False
        if price <= 0:
            return False
        if side.lower() not in ['buy', 'sell']:
            return False
        return True
