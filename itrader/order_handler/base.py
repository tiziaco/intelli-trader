from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .order import Order


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
