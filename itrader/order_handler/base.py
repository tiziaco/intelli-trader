from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from .order import Order, OrderStatus


class OrderBase(object):
	"""
	The OrderBase class offer basic order handler functionalities
	like keeping track of the portfolio updates, check the limit
	orders and fill them. 
	"""

	def __init__(self, events_queue, portfolios = {}):
		self.portfolios = portfolios


class OrderStorage(ABC):
    """
    Abstract base class for order storage implementations.
    
    Provides a unified interface for managing orders across different
    storage backends (in-memory for backtesting, PostgreSQL for live trading).
    """
    
    @abstractmethod
    def add_order(self, order) -> None:
        """
        Add a new order to the storage.
        
        Parameters
        ----------
        order : Order
            The order to add
        """
        pass
    
    @abstractmethod
    def remove_order(self, order_id: Union[str, int], portfolio_id: Union[str, int] = None) -> bool:
        """
        Remove an order from the storage.
        
        Parameters
        ----------
        order_id : Union[str, int]
            The ID of the order to remove
        portfolio_id : Union[str, int], optional
            The portfolio ID for direct access (more efficient)
            
        Returns
        -------
        bool
            True if order was found and removed, False otherwise
        """
        pass
    
    @abstractmethod
    def remove_orders_by_ticker(self, ticker: str, portfolio_id: Union[str, int]) -> int:
        """
        Remove all orders for a specific ticker in a portfolio.
        
        Parameters
        ----------
        ticker : str
            The ticker symbol
        portfolio_id : Union[str, int]
            The portfolio ID
            
        Returns
        -------
        int
            Number of orders removed
        """
        pass
    
    @abstractmethod
    def get_pending_orders(self, portfolio_id: Union[str, int] = None) -> Dict[str, Dict[str, 'Order']]:
        """
        Get pending orders, optionally filtered by portfolio.
        
        Parameters
        ----------
        portfolio_id : Union[str, int], optional
            Portfolio ID to filter by. If None, returns all portfolios.
            
        Returns
        -------
        Dict[str, Dict[str, Order]]
            Dictionary keyed by portfolio_id, then by order_id
        """
        pass
    
    @abstractmethod
    def get_order_by_id(self, order_id: Union[str, int], portfolio_id: Union[str, int] = None) -> Optional['Order']:
        """
        Get a specific order by ID.
        
        Parameters
        ----------
        order_id : Union[str, int]
            The order ID
        portfolio_id : Union[str, int], optional
            Portfolio ID for direct access
            
        Returns
        -------
        Optional[Order]
            The order if found, None otherwise
        """
        pass
    
    @abstractmethod
    def update_order(self, order) -> bool:
        """
        Update an existing order.
        
        Parameters
        ----------
        order : Order
            The updated order
            
        Returns
        -------
        bool
            True if order was found and updated, False otherwise
        """
        pass
    
    @abstractmethod
    def get_orders_by_ticker(self, ticker: str, portfolio_id: Union[str, int] = None) -> List['Order']:
        """
        Get all orders for a specific ticker.
        
        Parameters
        ----------
        ticker : str
            The ticker symbol
        portfolio_id : Union[str, int], optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of orders for the ticker
        """
        pass
    
    @abstractmethod
    def clear_portfolio_orders(self, portfolio_id: Union[str, int]) -> int:
        """
        Clear all orders for a portfolio.
        
        Parameters
        ----------
        portfolio_id : Union[str, int]
            The portfolio ID
            
        Returns
        -------
        int
            Number of orders cleared
        """
        pass
    
    # Enhanced storage methods for comprehensive order management
    
    @abstractmethod
    def get_orders_by_status(self, status: 'OrderStatus', portfolio_id: Union[str, int] = None) -> List['Order']:
        """
        Get orders by status, optionally filtered by portfolio.
        
        Parameters
        ----------
        status : OrderStatus
            The order status to filter by
        portfolio_id : Union[str, int], optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of orders with the specified status
        """
        pass
    
    @abstractmethod
    def get_active_orders(self, portfolio_id: Union[str, int] = None) -> List['Order']:
        """
        Get all active orders (PENDING and PARTIALLY_FILLED).
        
        Parameters
        ----------
        portfolio_id : Union[str, int], optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of active orders
        """
        pass
    
    @abstractmethod
    def get_orders_by_time_range(self, start_time: datetime, end_time: datetime, 
                                portfolio_id: Union[str, int] = None) -> List['Order']:
        """
        Get orders within a time range.
        
        Parameters
        ----------
        start_time : datetime
            Start of time range
        end_time : datetime
            End of time range
        portfolio_id : Union[str, int], optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of orders within the time range
        """
        pass
    
    @abstractmethod
    def get_order_history(self, order_id: Union[str, int]) -> List[Dict]:
        """
        Get the state change history for an order.
        
        Parameters
        ----------
        order_id : Union[str, int]
            The order ID
            
        Returns
        -------
        List[Dict]
            List of state changes for the order
        """
        pass
    
    @abstractmethod
    def archive_orders(self, cutoff_date: datetime, portfolio_id: Union[str, int] = None) -> int:
        """
        Archive old orders to separate storage.
        
        Parameters
        ----------
        cutoff_date : datetime
            Orders older than this date will be archived
        portfolio_id : Union[str, int], optional
            Portfolio ID to filter by
            
        Returns
        -------
        int
            Number of orders archived
        """
        pass
    
    @abstractmethod
    def search_orders(self, criteria: Dict, portfolio_id: Union[str, int] = None) -> List['Order']:
        """
        Search orders based on criteria.
        
        Parameters
        ----------
        criteria : Dict
            Search criteria (e.g., {'ticker': 'AAPL', 'action': 'BUY'})
        portfolio_id : Union[str, int], optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of orders matching the criteria
        """
        pass
    
    @abstractmethod
    def get_orders_count_by_status(self, portfolio_id: Union[str, int] = None) -> Dict[str, int]:
        """
        Get count of orders by status.
        
        Parameters
        ----------
        portfolio_id : Union[str, int], optional
            Portfolio ID to filter by
            
        Returns
        -------
        Dict[str, int]
            Dictionary with status names as keys and counts as values
        """
        pass
    
    @abstractmethod
    def deactivate_order(self, order_id: Union[str, int], portfolio_id: Union[str, int] = None) -> bool:
        """
        Deactivate an order (remove from active but keep in all_orders for audit trail).
        
        Professional trading behavior: filled orders remain in historical records
        but are removed from active order queries.
        
        Parameters
        ----------
        order_id : Union[str, int]
            The ID of the order to deactivate
        portfolio_id : Union[str, int], optional
            The portfolio ID for direct access (more efficient)
            
        Returns
        -------
        bool
            True if order was found and deactivated, False otherwise
        """
        pass
