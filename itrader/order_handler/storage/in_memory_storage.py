from typing import Dict, List, Optional, Union, TYPE_CHECKING
from ..base import OrderStorage

if TYPE_CHECKING:
    from ..order import Order


class InMemoryOrderStorage(OrderStorage):
    """
    In-memory implementation of OrderStorage.
    
    Provides fast order operations using Python dictionaries.
    Ideal for backtesting where persistence is not required.
    """
    
    def __init__(self):
        """Initialize the in-memory storage."""
        self.pending_orders: Dict[str, Dict[str, 'Order']] = {}
    
    def add_order(self, order) -> None:
        """Add a new order to in-memory storage."""
        portfolio_key = str(order.portfolio_id)
        order_key = str(order.id)
        self.pending_orders.setdefault(portfolio_key, {})[order_key] = order
    
    def remove_order(self, order_id: Union[str, int], portfolio_id: Union[str, int] = None) -> bool:
        """Remove an order from in-memory storage."""
        order_key = str(order_id)
        
        if portfolio_id:
            # Direct access if portfolio_id is provided
            portfolio_key = str(portfolio_id)
            if (portfolio_key in self.pending_orders and 
                order_key in self.pending_orders[portfolio_key]):
                del self.pending_orders[portfolio_key][order_key]
                # Clean up empty portfolio dict if needed
                if not self.pending_orders[portfolio_key]:
                    del self.pending_orders[portfolio_key]
                return True
        else:
            # Search all portfolios if portfolio_id not provided
            return self._remove_order_search_all(order_key)
        return False
    
    def _remove_order_search_all(self, order_key: str) -> bool:
        """Helper method to search and remove an order across all portfolios."""
        for portfolio_key, orders in list(self.pending_orders.items()):
            if order_key in orders:
                del self.pending_orders[portfolio_key][order_key]
                # Clean up empty portfolio dict if needed
                if not self.pending_orders[portfolio_key]:
                    del self.pending_orders[portfolio_key]
                return True
        return False
    
    def remove_orders_by_ticker(self, ticker: str, portfolio_id: Union[str, int]) -> int:
        """Remove all orders for a specific ticker in a portfolio."""
        portfolio_key = str(portfolio_id)
        if portfolio_key not in self.pending_orders:
            return 0
        
        orders_to_remove = []
        for order_key, order in self.pending_orders[portfolio_key].items():
            if order.ticker == ticker:
                orders_to_remove.append(order_key)
        
        for order_key in orders_to_remove:
            del self.pending_orders[portfolio_key][order_key]
        
        # Clean up empty portfolio dict if needed
        if not self.pending_orders[portfolio_key]:
            del self.pending_orders[portfolio_key]
        
        return len(orders_to_remove)
    
    def get_pending_orders(self, portfolio_id: Union[str, int] = None) -> Dict[str, Dict[str, 'Order']]:
        """Get pending orders, optionally filtered by portfolio."""
        if portfolio_id:
            portfolio_key = str(portfolio_id)
            return {portfolio_key: self.pending_orders.get(portfolio_key, {})}
        return self.pending_orders.copy()
    
    def get_order_by_id(self, order_id: Union[str, int], portfolio_id: Union[str, int] = None) -> Optional['Order']:
        """Get a specific order by ID."""
        order_key = str(order_id)
        
        if portfolio_id:
            portfolio_key = str(portfolio_id)
            return self.pending_orders.get(portfolio_key, {}).get(order_key)
        
        # Search all portfolios
        for orders in self.pending_orders.values():
            if order_key in orders:
                return orders[order_key]
        return None
    
    def update_order(self, order) -> bool:
        """Update an existing order."""
        portfolio_key = str(order.portfolio_id)
        order_key = str(order.id)
        
        if (portfolio_key in self.pending_orders and 
            order_key in self.pending_orders[portfolio_key]):
            self.pending_orders[portfolio_key][order_key] = order
            return True
        return False
    
    def get_orders_by_ticker(self, ticker: str, portfolio_id: Union[str, int] = None) -> List['Order']:
        """Get all orders for a specific ticker."""
        orders = []
        
        if portfolio_id:
            portfolio_key = str(portfolio_id)
            portfolio_orders = self.pending_orders.get(portfolio_key, {})
            orders.extend([order for order in portfolio_orders.values() 
                          if order.ticker == ticker])
        else:
            for portfolio_orders in self.pending_orders.values():
                orders.extend([order for order in portfolio_orders.values() 
                              if order.ticker == ticker])
        
        return orders
    
    def clear_portfolio_orders(self, portfolio_id: Union[str, int]) -> int:
        """Clear all orders for a portfolio."""
        portfolio_key = str(portfolio_id)
        if portfolio_key in self.pending_orders:
            count = len(self.pending_orders[portfolio_key])
            del self.pending_orders[portfolio_key]
            return count
        return 0
