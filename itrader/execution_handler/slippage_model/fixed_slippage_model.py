"""
Fixed slippage model - constant slippage percentage regardless of order size.
"""

import random
from typing import Dict, Any
from .base import SlippageModel


class FixedSlippageModel(SlippageModel):
    """
    Fixed slippage model that applies a constant slippage percentage.
    
    This model applies the same slippage percentage to all orders
    regardless of size, with optional random variation.
    """
    
    def __init__(self, slippage_pct: float = 0.01, 
                 random_variation: bool = True):
        """
        Initialize the fixed slippage model.
        
        Parameters
        ----------
        slippage_pct : float
            Fixed slippage percentage to apply
        random_variation : bool
            Whether to apply random variation around the fixed rate
        """
        super().__init__()
        self.slippage_pct = slippage_pct
        self.random_variation = random_variation
    
    def calculate_slippage_factor(self, quantity: float, price: float, 
                                side: str, order_type: str = "market") -> float:
        """
        Calculate slippage factor based on fixed percentage.
        
        Parameters
        ----------
        quantity : float
            Order quantity (ignored for fixed model)
        price : float
            Order price (ignored for fixed model)
        side : str
            Order side ('buy' or 'sell')
        order_type : str
            Order type
            
        Returns
        -------
        float
            Slippage factor to multiply with price
        """
        if not self.validate_inputs(quantity, price, side, order_type):
            return 1.0
        
        # Calculate slippage
        if self.random_variation:
            # Apply random variation around the fixed rate
            slippage = random.uniform(-self.slippage_pct, self.slippage_pct) / 100.0
        else:
            # Use fixed rate with direction based on order side
            if side.lower() == 'buy':
                slippage = self.slippage_pct / 100.0  # Positive slippage for buys
            else:  # sell
                slippage = -self.slippage_pct / 100.0  # Negative slippage for sells
        
        return 1.0 + slippage
    
    def get_slippage_info(self) -> Dict[str, Any]:
        """
        Get information about the fixed slippage model.
        
        Returns
        -------
        Dict[str, Any]
            Model information
        """
        return {
            'model_type': 'fixed',
            'name': 'Fixed Slippage Model',
            'description': 'Constant slippage percentage for all orders',
            'parameters': {
                'slippage_pct': self.slippage_pct,
                'random_variation': self.random_variation
            },
            'supports_order_types': ['market', 'limit'],
            'supports_sides': ['buy', 'sell']
        }
