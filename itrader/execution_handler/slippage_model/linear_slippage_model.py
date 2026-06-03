"""
Linear slippage model - slippage increases linearly with order size.
"""

import random
from typing import Dict, Any
from .base import SlippageModel


class LinearSlippageModel(SlippageModel):
    """
    Linear slippage model that simulates slippage proportional to order size.
    
    This model combines base slippage (random market noise) with size impact
    that increases linearly with order value.
    """
    
    def __init__(self, base_slippage_pct: float = 0.01, 
                 size_impact_factor: float = 0.00001, 
                 max_slippage_pct: float = 0.1):
        """
        Initialize the linear slippage model.
        
        Parameters
        ----------
        base_slippage_pct : float
            Base slippage percentage (random component)
        size_impact_factor : float
            Factor for size impact calculation
        max_slippage_pct : float
            Maximum slippage percentage cap
        """
        super().__init__()
        self.base_slippage_pct = base_slippage_pct
        self.size_impact_factor = size_impact_factor
        self.max_slippage_pct = max_slippage_pct
    
    def calculate_slippage_factor(self, quantity: float, price: float, 
                                side: str, order_type: str = "market") -> float:
        """
        Calculate slippage factor based on linear model.
        
        Parameters
        ----------
        quantity : float
            Order quantity
        price : float
            Order price
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
        
        # Base slippage - random market noise
        base_slippage = random.uniform(-self.base_slippage_pct, self.base_slippage_pct) / 100.0
        
        # Size impact - proportional to order value
        order_value = quantity * price
        size_impact = min(
            self.max_slippage_pct / 100.0,
            order_value * self.size_impact_factor / 100.0
        )
        
        # Apply slippage direction based on order side
        # Buy orders get positive slippage (worse price)
        # Sell orders get negative slippage (worse price)
        if side.lower() == 'buy':
            total_slippage = base_slippage + size_impact
        else:  # sell
            total_slippage = base_slippage - size_impact
        
        # Cap total slippage
        total_slippage = max(-self.max_slippage_pct / 100.0, 
                           min(self.max_slippage_pct / 100.0, total_slippage))
        
        return 1.0 + total_slippage
    
    def get_slippage_info(self) -> Dict[str, Any]:
        """
        Get information about the linear slippage model.
        
        Returns
        -------
        Dict[str, Any]
            Model information
        """
        return {
            'model_type': 'linear',
            'name': 'Linear Slippage Model',
            'description': 'Slippage increases linearly with order size',
            'parameters': {
                'base_slippage_pct': self.base_slippage_pct,
                'size_impact_factor': self.size_impact_factor,
                'max_slippage_pct': self.max_slippage_pct
            },
            'supports_order_types': ['market', 'limit'],
            'supports_sides': ['buy', 'sell']
        }
