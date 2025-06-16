"""
Trading Interface Module

This module provides a high-level interface for trading operations,
acting as a bridge between the web API and the core trading system.
It handles order creation, validation, and other trading-related operations
without cluttering the core LiveTradingSystem class.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from itrader.events_handler.event import OrderEvent
from itrader.logger import get_itrader_logger


class TradingInterface:
    """
    High-level interface for trading operations.
    
    This class provides a clean API for creating orders and managing trading
    operations while keeping the core LiveTradingSystem focused on system
    management (event processing, queue management, etc.).
    """
    
    def __init__(self, live_trading_system):
        """
        Initialize the trading interface.
        
        Parameters
        ----------
        live_trading_system : LiveTradingSystem
            Reference to the live trading system instance
        """
        self.live_trading_system = live_trading_system
        self.logger = get_itrader_logger(__name__)
    
    def create_market_order(self, symbol: str, side: str, quantity: float, 
                          order_type: str = "MARKET", strategy_id: int = 0, 
                          portfolio_id: int = 0) -> bool:
        """
        Create a market order and add it to the processing queue.
        
        Parameters
        ----------
        symbol : str
            Trading symbol (e.g., 'BTCUSDT')
        side : str
            Order side ('BUY' or 'SELL')
        quantity : float
            Order quantity
        order_type : str
            Order type (default: 'MARKET')
        strategy_id : int
            Strategy identifier (default: 0)
        portfolio_id : int
            Portfolio identifier (default: 0)
            
        Returns
        -------
        bool
            True if order was created successfully, False otherwise
        """
        if not self.live_trading_system.is_running():
            self.logger.warning('Cannot create order: Live trading system is not running')
            return False
        
        try:
            # Create order event with the correct parameters
            order_event = OrderEvent(
                time=datetime.now(),
                ticker=symbol,
                action=side,  # 'BUY' or 'SELL'
                price=0.0,    # Market order - price will be determined by execution
                quantity=quantity,
                exchange=self.live_trading_system.exchange,
                strategy_id=strategy_id,
                portfolio_id=portfolio_id
            )
            
            return self.live_trading_system.add_event(order_event)
            
        except Exception as e:
            self.logger.error(f'Failed to create market order: {e}')
            return False
    
    def create_limit_order(self, symbol: str, side: str, quantity: float, 
                         price: float, strategy_id: int = 0, 
                         portfolio_id: int = 0) -> bool:
        """
        Create a limit order and add it to the processing queue.
        
        Parameters
        ----------
        symbol : str
            Trading symbol (e.g., 'BTCUSDT')
        side : str
            Order side ('BUY' or 'SELL')
        quantity : float
            Order quantity
        price : float
            Limit price
        strategy_id : int
            Strategy identifier (default: 0)
        portfolio_id : int
            Portfolio identifier (default: 0)
            
        Returns
        -------
        bool
            True if order was created successfully, False otherwise
        """
        if not self.live_trading_system.is_running():
            self.logger.warning('Cannot create order: Live trading system is not running')
            return False
        
        try:
            # Create order event with the correct parameters
            order_event = OrderEvent(
                time=datetime.now(),
                ticker=symbol,
                action=side,  # 'BUY' or 'SELL'
                price=price,
                quantity=quantity,
                exchange=self.live_trading_system.exchange,
                strategy_id=strategy_id,
                portfolio_id=portfolio_id
            )
            
            return self.live_trading_system.add_event(order_event)
            
        except Exception as e:
            self.logger.error(f'Failed to create limit order: {e}')
            return False
    
    def validate_order_parameters(self, symbol: str, side: str, quantity: float, 
                                price: Optional[float] = None) -> Dict[str, Any]:
        """
        Validate order parameters before creating an order.
        
        Parameters
        ----------
        symbol : str
            Trading symbol
        side : str
            Order side ('BUY' or 'SELL')
        quantity : float
            Order quantity
        price : Optional[float]
            Order price (for limit orders)
            
        Returns
        -------
        Dict[str, Any]
            Validation result with 'valid' boolean and 'errors' list
        """
        errors = []
        
        # Validate symbol
        if not symbol or not isinstance(symbol, str):
            errors.append("Invalid symbol: must be a non-empty string")
        
        # Validate side
        if side not in ['BUY', 'SELL']:
            errors.append("Invalid side: must be 'BUY' or 'SELL'")
        
        # Validate quantity
        try:
            quantity = float(quantity)
            if quantity <= 0:
                errors.append("Invalid quantity: must be greater than 0")
        except (ValueError, TypeError):
            errors.append("Invalid quantity: must be a valid number")
        
        # Validate price if provided
        if price is not None:
            try:
                price = float(price)
                if price <= 0:
                    errors.append("Invalid price: must be greater than 0")
            except (ValueError, TypeError):
                errors.append("Invalid price: must be a valid number")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        Get the current status of the trading system.
        
        Returns
        -------
        Dict[str, Any]
            System status information
        """
        return self.live_trading_system.get_status()
    
    def is_system_ready(self) -> bool:
        """
        Check if the trading system is ready to accept orders.
        
        Returns
        -------
        bool
            True if system is ready, False otherwise
        """
        return self.live_trading_system.is_running()
