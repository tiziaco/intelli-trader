import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from datetime import datetime

# Order/portfolio ids may arrive as UUID (native scheme, D-14) or legacy str/int.
IdLike = Union[str, int, uuid.UUID]

if TYPE_CHECKING:
    from .order import Order
    from ..core.enums import OrderStatus


class OrderStorage(ABC):
    """
    Abstract base class for order storage implementations.
    
    Provides a unified interface for managing orders across different
    storage backends (in-memory for backtesting, PostgreSQL for live trading).
    """
    
    @abstractmethod
    def add_order(self, order: 'Order') -> None:
        """
        Add a new order to the storage.
        
        Parameters
        ----------
        order : Order
            The order to add
        """
        pass
    
    @abstractmethod
    def remove_order(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> bool:
        """
        Remove an order from the storage.
        
        Parameters
        ----------
        order_id : IdLike
            The ID of the order to remove
        portfolio_id : IdLike, optional
            The portfolio ID for direct access (more efficient)
            
        Returns
        -------
        bool
            True if order was found and removed, False otherwise
        """
        pass
    
    @abstractmethod
    def remove_orders_by_ticker(self, ticker: str, portfolio_id: IdLike) -> int:
        """
        Remove all orders for a specific ticker in a portfolio.
        
        Parameters
        ----------
        ticker : str
            The ticker symbol
        portfolio_id : IdLike
            The portfolio ID
            
        Returns
        -------
        int
            Number of orders removed
        """
        pass
    
    @abstractmethod
    def get_pending_orders(self, portfolio_id: Optional[IdLike] = None) -> Dict[Any, Dict[Any, 'Order']]:
        """
        Get pending orders, optionally filtered by portfolio.
        
        Parameters
        ----------
        portfolio_id : IdLike, optional
            Portfolio ID to filter by. If None, returns all portfolios.
            
        Returns
        -------
        Dict[str, Dict[str, Order]]
            Dictionary keyed by portfolio_id, then by order_id
        """
        pass
    
    @abstractmethod
    def get_order_by_id(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> Optional['Order']:
        """
        Get a specific order by ID.
        
        Parameters
        ----------
        order_id : IdLike
            The order ID
        portfolio_id : IdLike, optional
            Portfolio ID for direct access
            
        Returns
        -------
        Optional[Order]
            The order if found, None otherwise
        """
        pass
    
    @abstractmethod
    def update_order(self, order: 'Order') -> bool:
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
    def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """
        Get all orders for a specific ticker.
        
        Parameters
        ----------
        ticker : str
            The ticker symbol
        portfolio_id : IdLike, optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of orders for the ticker
        """
        pass
    
    @abstractmethod
    def clear_portfolio_orders(self, portfolio_id: IdLike) -> int:
        """
        Clear all orders for a portfolio.
        
        Parameters
        ----------
        portfolio_id : IdLike
            The portfolio ID
            
        Returns
        -------
        int
            Number of orders cleared
        """
        pass
    
    # Enhanced storage methods for comprehensive order management
    
    @abstractmethod
    def get_orders_by_status(self, status: 'OrderStatus', portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """
        Get orders by status, optionally filtered by portfolio.
        
        Parameters
        ----------
        status : OrderStatus
            The order status to filter by
        portfolio_id : IdLike, optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of orders with the specified status
        """
        pass
    
    @abstractmethod
    def get_active_orders(self, portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """
        Get all active orders (PENDING and PARTIALLY_FILLED).
        
        Parameters
        ----------
        portfolio_id : IdLike, optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of active orders
        """
        pass
    
    @abstractmethod
    def get_orders_by_time_range(self, start_time: datetime, end_time: datetime, 
                                portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """
        Get orders within a time range.
        
        Parameters
        ----------
        start_time : datetime
            Start of time range
        end_time : datetime
            End of time range
        portfolio_id : IdLike, optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of orders within the time range
        """
        pass
    
    @abstractmethod
    def get_order_history(self, order_id: IdLike) -> List[Dict[str, Any]]:
        """
        Get the state change history for an order.
        
        Parameters
        ----------
        order_id : IdLike
            The order ID
            
        Returns
        -------
        List[Dict]
            List of state changes for the order
        """
        pass
    
    @abstractmethod
    def search_orders(self, criteria: Dict[str, Any], portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """
        Search orders based on criteria.
        
        Parameters
        ----------
        criteria : Dict
            Search criteria (e.g., {'ticker': 'AAPL', 'action': 'BUY'})
        portfolio_id : IdLike, optional
            Portfolio ID to filter by
            
        Returns
        -------
        List[Order]
            List of orders matching the criteria
        """
        pass
    
    @abstractmethod
    def count_orders_by_status(self, portfolio_id: Optional[IdLike] = None) -> Dict[str, int]:
        """
        Count orders by status (status name -> count).
        
        Parameters
        ----------
        portfolio_id : IdLike, optional
            Portfolio ID to filter by
            
        Returns
        -------
        Dict[str, int]
            Dictionary with status names as keys and counts as values
        """
        pass

    # -- Runtime config (order scope — global singleton, D-21/D-25) -----------

    @abstractmethod
    def save_config(self, config: Dict[str, Any], at: datetime) -> None:
        """Persist the GLOBAL order-scope config singleton (D-25 — order owns its config).

        The order scope is a single global config record (not per-portfolio); the SQL
        backend rides a dedicated cardinality-1 ``order_config`` table, the in-memory
        backend a plain dict, the cached wrapper delegates. Overwrites any prior record.

        Parameters
        ----------
        config : Dict[str, Any]
            The order-scope config blob (JSON-serializable; Decimal-safe at the money edge).
        at : datetime
            The business ``time`` stamped as ``updated_at`` (clock-free, caller-supplied).
        """
        pass

    @abstractmethod
    def load_config(self) -> Optional[Dict[str, Any]]:
        """Return the persisted global order-scope config, or ``None`` when none saved.

        Read on restart layering so a persisted order override re-applies on boot from the
        ORDER store (NOT SystemStore — D-21/D-25).
        """
        pass
