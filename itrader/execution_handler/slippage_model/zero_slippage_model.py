"""
Zero slippage model - perfect execution with no slippage.
"""

from typing import Dict, Any
from .base import SlippageModel


class ZeroSlippageModel(SlippageModel):
    """
    Zero slippage model that provides perfect execution with no slippage.
    
    This model always returns a slippage factor of 1.0, meaning orders
    execute at exactly the expected price with no price impact.
    """
    
    def __init__(self):
        """Initialize the zero slippage model."""
        super().__init__()
    
    def calculate_slippage_factor(self, quantity: float, price: float, 
                                side: str, order_type: str = "market") -> float:
        """
        Calculate slippage factor (always 1.0 for zero slippage).
        
        Parameters
        ----------
        quantity : float
            Order quantity (ignored)
        price : float
            Order price (ignored)
        side : str
            Order side (ignored)
        order_type : str
            Order type (ignored)
            
        Returns
        -------
        float
            Always returns 1.0 (no slippage)
        """
        return 1.0
    
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
