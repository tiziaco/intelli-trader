import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime
from ..base import OrderStorage, IdLike

if TYPE_CHECKING:
    from ..order import Order
    from ...core.enums import OrderStatus


class InMemoryOrderStorage(OrderStorage):
    """
    In-memory implementation of OrderStorage.

    Provides fast order operations using Python dictionaries.
    Ideal for backtesting where persistence is not required.

    Now supports comprehensive order lifecycle management including
    order history, state tracking, and advanced querying capabilities.

    Keying is native ``uuid.UUID`` (D-14): order ids are stored as their native
    UUID (no ``str(...)`` coercion). A flat ``self._by_id`` index
    (``Dict[uuid.UUID, Order]``, PERF2) provides O(1) cross-portfolio lookup,
    replacing the previous O(n) scan in ``get_order_by_id``. The nested
    per-portfolio dicts are retained for portfolio-scoped queries; the deeper
    nested-scan elimination is M4-06 (PERF3) and is NOT pulled forward here.
    """

    def __init__(self) -> None:
        """Initialize the in-memory storage."""
        # Active orders (PENDING, PARTIALLY_FILLED)
        self.active_orders: Dict[Any, Dict[Any, 'Order']] = {}

        # All orders (including completed ones for history)
        self.all_orders: Dict[Any, Dict[Any, 'Order']] = {}

        # Archived orders (moved from all_orders for performance)
        self.archived_orders: Dict[Any, Dict[Any, 'Order']] = {}

        # Flat global order index for O(1) cross-portfolio lookup (D-14, PERF2)
        self._by_id: Dict[Any, 'Order'] = {}

    def add_order(self, order: 'Order') -> None:
        """Add a new order to in-memory storage."""
        portfolio_key = order.portfolio_id
        order_key = order.id

        # Add to all orders
        self.all_orders.setdefault(portfolio_key, {})[order_key] = order

        # Index in the flat global order index
        self._by_id[order_key] = order

        # Add to active orders if it's in an active state
        if order.is_active:
            self.active_orders.setdefault(portfolio_key, {})[order_key] = order
    
    def deactivate_order(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> bool:
        """
        Deactivate an order (remove from active but keep in all_orders for audit trail).

        This mimics professional SQL behavior where filled orders remain in the main table
        but are filtered out of active queries.

        Parameters
        ----------
        order_id : uuid.UUID
            The ID of the order to deactivate
        portfolio_id : uuid.UUID, optional
            The portfolio ID containing the order

        Returns
        -------
        bool
            True if order was successfully deactivated
        """
        order_key = order_id
        deactivated = False

        if portfolio_id:
            # Direct access if portfolio_id is provided
            portfolio_key = portfolio_id

            # Remove from active orders only
            if (portfolio_key in self.active_orders and 
                order_key in self.active_orders[portfolio_key]):
                del self.active_orders[portfolio_key][order_key]
                if not self.active_orders[portfolio_key]:
                    del self.active_orders[portfolio_key]
                deactivated = True
        else:
            # Search all portfolios if portfolio_id not provided
            for portfolio_key, orders in list(self.active_orders.items()):
                if order_key in orders:
                    del self.active_orders[portfolio_key][order_key]
                    if not self.active_orders[portfolio_key]:
                        del self.active_orders[portfolio_key]
                    deactivated = True
                    break
        
        return deactivated

    def remove_order(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> bool:
        """Remove an order from in-memory storage."""
        order_key = order_id
        removed = False

        if portfolio_id:
            # Direct access if portfolio_id is provided
            portfolio_key = portfolio_id

            # Remove from active orders
            if (portfolio_key in self.active_orders and
                order_key in self.active_orders[portfolio_key]):
                del self.active_orders[portfolio_key][order_key]
                if not self.active_orders[portfolio_key]:
                    del self.active_orders[portfolio_key]
                removed = True

            # Also remove from all_orders for complete removal
            if (portfolio_key in self.all_orders and
                order_key in self.all_orders[portfolio_key]):
                del self.all_orders[portfolio_key][order_key]
                if not self.all_orders[portfolio_key]:
                    del self.all_orders[portfolio_key]
                removed = True
        else:
            # Search all portfolios if portfolio_id not provided
            removed = self._remove_order_search_all(order_key)

        # Keep the flat index consistent
        if removed:
            self._by_id.pop(order_key, None)

        return removed

    def _remove_order_search_all(self, order_key: IdLike) -> bool:
        """Helper method to search and remove an order across all portfolios."""
        removed = False

        # Remove from active orders
        for portfolio_key, orders in list(self.active_orders.items()):
            if order_key in orders:
                del self.active_orders[portfolio_key][order_key]
                if not self.active_orders[portfolio_key]:
                    del self.active_orders[portfolio_key]
                removed = True
                break

        # Also remove from all_orders for complete removal
        # TODO: Check if i really need to remove everything from all_orders
        for portfolio_key, orders in list(self.all_orders.items()):
            if order_key in orders:
                del self.all_orders[portfolio_key][order_key]
                if not self.all_orders[portfolio_key]:
                    del self.all_orders[portfolio_key]
                removed = True
                break

        # Keep the flat index consistent
        if removed:
            self._by_id.pop(order_key, None)

        return removed
    
    def remove_orders_by_ticker(self, ticker: str, portfolio_id: IdLike) -> int:
        """Remove all active orders for a specific ticker in a portfolio."""
        portfolio_key = portfolio_id
        if portfolio_key not in self.active_orders:
            return 0

        orders_to_remove = []
        for order_key, order in self.active_orders[portfolio_key].items():
            if order.ticker == ticker:
                orders_to_remove.append(order_key)

        for order_key in orders_to_remove:
            del self.active_orders[portfolio_key][order_key]

        # Clean up empty portfolio dict if needed
        if not self.active_orders[portfolio_key]:
            del self.active_orders[portfolio_key]

        return len(orders_to_remove)

    def get_pending_orders(self, portfolio_id: Optional[IdLike] = None) -> Dict[Any, Dict[Any, 'Order']]:
        """Get pending orders (backward compatibility - now returns active orders)."""
        return self.get_active_orders_dict(portfolio_id)

    def get_active_orders_dict(self, portfolio_id: Optional[IdLike] = None) -> Dict[Any, Dict[Any, 'Order']]:
        """Get active orders as nested dictionary structure."""
        if portfolio_id:
            portfolio_key = portfolio_id
            return {portfolio_key: self.active_orders.get(portfolio_key, {})}
        return self.active_orders.copy()

    def get_order_by_id(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> Optional['Order']:
        """Get a specific order by ID."""
        order_key = order_id

        if portfolio_id:
            portfolio_key = portfolio_id
            # Check all_orders first (includes both active and completed)
            return self.all_orders.get(portfolio_key, {}).get(order_key)

        # Cross-portfolio lookup via the flat global index (O(1), PERF2)
        order = self._by_id.get(order_key)
        if order is not None:
            return order

        # Also check archived orders (not tracked in the flat index)
        for orders in self.archived_orders.values():
            if order_key in orders:
                return orders[order_key]

        return None

    def update_order(self, order: 'Order') -> bool:
        """Update an existing order."""
        portfolio_key = order.portfolio_id
        order_key = order.id

        # Update in all_orders
        if (portfolio_key in self.all_orders and
            order_key in self.all_orders[portfolio_key]):
            self.all_orders[portfolio_key][order_key] = order
            self._by_id[order_key] = order

            # Update active orders based on current state
            if order.is_active:
                self.active_orders.setdefault(portfolio_key, {})[order_key] = order
            else:
                # Remove from active orders if no longer active
                if (portfolio_key in self.active_orders and 
                    order_key in self.active_orders[portfolio_key]):
                    del self.active_orders[portfolio_key][order_key]
                    if not self.active_orders[portfolio_key]:
                        del self.active_orders[portfolio_key]
            
            return True
        return False
    
    def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get all orders for a specific ticker."""
        orders: List['Order'] = []

        if portfolio_id:
            portfolio_key = portfolio_id
            portfolio_orders = self.all_orders.get(portfolio_key, {})
            orders.extend([order for order in portfolio_orders.values() 
                          if order.ticker == ticker])
        else:
            for portfolio_orders in self.all_orders.values():
                orders.extend([order for order in portfolio_orders.values() 
                              if order.ticker == ticker])
        
        return orders
    
    def clear_portfolio_orders(self, portfolio_id: IdLike) -> int:
        """Clear all active orders for a portfolio."""
        portfolio_key = portfolio_id
        count = 0
        
        if portfolio_key in self.active_orders:
            count = len(self.active_orders[portfolio_key])
            del self.active_orders[portfolio_key]
        
        # Note: We don't clear all_orders to maintain history
        return count
    
    # Enhanced storage methods implementation
    
    def get_orders_by_status(self, status: 'OrderStatus', portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get orders by status, optionally filtered by portfolio."""
        orders: List['Order'] = []

        search_dict = self.all_orders
        if portfolio_id:
            portfolio_key = portfolio_id
            search_dict = {portfolio_key: self.all_orders.get(portfolio_key, {})}
        
        for portfolio_orders in search_dict.values():
            orders.extend([order for order in portfolio_orders.values() 
                          if order.status == status])
        
        return orders
    
    def get_active_orders(self, portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get all active orders (PENDING and PARTIALLY_FILLED)."""
        orders: List['Order'] = []

        search_dict = self.active_orders
        if portfolio_id:
            portfolio_key = portfolio_id
            search_dict = {portfolio_key: self.active_orders.get(portfolio_key, {})}
        
        for portfolio_orders in search_dict.values():
            orders.extend(portfolio_orders.values())
        
        return orders
    
    def get_orders_by_time_range(self, start_time: datetime, end_time: datetime,
                                portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get orders within a time range."""
        orders: List['Order'] = []

        search_dict = self.all_orders
        if portfolio_id:
            portfolio_key = portfolio_id
            search_dict = {portfolio_key: self.all_orders.get(portfolio_key, {})}
        
        for portfolio_orders in search_dict.values():
            for order in portfolio_orders.values():
                if start_time <= order.created_at <= end_time:
                    orders.append(order)
        
        return orders
    
    def get_order_history(self, order_id: IdLike) -> List[Dict[str, Any]]:
        """Get the state change history for an order."""
        order = self.get_order_by_id(order_id)
        if not order:
            return []
        
        return [
            {
                'from_status': change.from_status.name if change.from_status else None,
                'to_status': change.to_status.name,
                'timestamp': change.timestamp.isoformat(),
                'reason': change.reason,
                'triggered_by': change.triggered_by,
                'additional_data': change.additional_data
            }
            for change in order.state_changes
        ]
    
    def archive_orders(self, cutoff_date: datetime, portfolio_id: Optional[IdLike] = None) -> int:
        """Archive old orders to separate storage."""
        archived_count = 0

        search_dict = self.all_orders
        if portfolio_id:
            portfolio_key = portfolio_id
            search_dict = {portfolio_key: self.all_orders.get(portfolio_key, {})}

        for portfolio_key, portfolio_orders in list(search_dict.items()):
            orders_to_archive = []

            for order_key, order in list(portfolio_orders.items()):
                # Archive terminal orders older than cutoff date
                if order.is_terminal and order.created_at < cutoff_date:
                    orders_to_archive.append((order_key, order))

            for order_key, order in orders_to_archive:
                # Move to archived orders (removed from the flat live index)
                self.archived_orders.setdefault(portfolio_key, {})[order_key] = order
                del self.all_orders[portfolio_key][order_key]
                self._by_id.pop(order_key, None)
                archived_count += 1
            
            # Clean up empty portfolio dict
            if not self.all_orders[portfolio_key]:
                del self.all_orders[portfolio_key]
        
        return archived_count
    
    def search_orders(self, criteria: Dict[str, Any], portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Search orders based on criteria."""
        orders: List['Order'] = []

        search_dict = self.all_orders
        if portfolio_id:
            portfolio_key = portfolio_id
            search_dict = {portfolio_key: self.all_orders.get(portfolio_key, {})}
        
        for portfolio_orders in search_dict.values():
            for order in portfolio_orders.values():
                match = True
                
                for key, value in criteria.items():
                    if hasattr(order, key):
                        order_value = getattr(order, key)
                        if order_value != value:
                            match = False
                            break
                    else:
                        match = False
                        break
                
                if match:
                    orders.append(order)
        
        return orders
    
    def get_orders_count_by_status(self, portfolio_id: Optional[IdLike] = None) -> Dict[str, int]:
        """Get count of orders by status."""
        status_counts: Dict[str, int] = {}

        search_dict = self.all_orders
        if portfolio_id:
            portfolio_key = portfolio_id
            search_dict = {portfolio_key: self.all_orders.get(portfolio_key, {})}
        
        for portfolio_orders in search_dict.values():
            for order in portfolio_orders.values():
                status_name = order.status.name
                status_counts[status_name] = status_counts.get(status_name, 0) + 1
        
        return status_counts
