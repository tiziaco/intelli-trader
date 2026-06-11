import uuid
from typing import Any, Dict, Iterator, List, Optional, TYPE_CHECKING
from datetime import datetime
from ..base import OrderStorage, IdLike

if TYPE_CHECKING:
    from ..order import Order
    from ...core.enums import OrderStatus


class InMemoryOrderStorage(OrderStorage):
    """
    In-memory implementation of OrderStorage.

    Flat-dict-only design (D-20, closes PERF3 / M4-06): a single
    ``self._by_id: Dict[uuid.UUID, Order]`` is the SOLE container. Keying is
    native ``uuid.UUID`` (D-14) so lookup and removal are O(1).

    The previous nested per-portfolio dicts (the active / all / archived order
    classes) are deleted. Order classification is a *predicate filter* over
    the entity, evaluated at query time:

    - "active"        -> ``order.is_active`` (PENDING / PARTIALLY_FILLED)
    - per-portfolio   -> ``order.portfolio_id == portfolio_id``
    - per-ticker      -> ``order.ticker == ticker``
    - per-status      -> ``order.status == status``

    A status change on the entity alone moves it across query classes — no
    dual-write, no deactivate step. Terminal (filled/cancelled/rejected)
    orders stay in the flat dict, preserving the "all orders" audit/history
    semantics (T-05-02).
    """

    def __init__(self) -> None:
        """Initialize the in-memory storage.

        D-20: the flat ``{order_id: order}`` dict is the ONLY instance
        container.
        """
        self._by_id: Dict[uuid.UUID, 'Order'] = {}

    def _orders(self, portfolio_id: Optional[IdLike] = None) -> Iterator['Order']:
        """Iterate stored orders, optionally filtered by portfolio predicate."""
        for order in self._by_id.values():
            if portfolio_id is None or order.portfolio_id == portfolio_id:
                yield order

    def add_order(self, order: 'Order') -> None:
        """Add a new order to in-memory storage (single flat-dict write, D-20)."""
        self._by_id[order.id] = order

    def remove_order(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> bool:
        """Remove an order from in-memory storage (O(1) flat-dict delete)."""
        # Native-UUID keying (D-14): a non-UUID id can never be a stored key.
        if not isinstance(order_id, uuid.UUID):
            return False
        order = self._by_id.get(order_id)
        if order is None:
            return False
        if portfolio_id is not None and order.portfolio_id != portfolio_id:
            return False
        del self._by_id[order_id]
        return True

    def remove_orders_by_ticker(self, ticker: str, portfolio_id: IdLike) -> int:
        """Remove all active orders for a specific ticker in a portfolio."""
        to_remove = [
            order.id for order in self._orders(portfolio_id)
            if order.is_active and order.ticker == ticker
        ]
        for order_id in to_remove:
            del self._by_id[order_id]
        return len(to_remove)

    def get_pending_orders(self, portfolio_id: Optional[IdLike] = None) -> Dict[Any, Dict[Any, 'Order']]:
        """Get active orders grouped by portfolio (derived nested view).

        The nested ``{portfolio_id: {order_id: order}}`` shape is built
        on-the-fly from the flat dict — it is a return-shape convenience, not
        a stored structure (D-20).
        """
        if portfolio_id is not None:
            return {portfolio_id: {
                order.id: order for order in self._orders(portfolio_id)
                if order.is_active
            }}
        result: Dict[Any, Dict[Any, 'Order']] = {}
        for order in self._orders():
            if order.is_active:
                result.setdefault(order.portfolio_id, {})[order.id] = order
        return result

    def get_order_by_id(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> Optional['Order']:
        """Get a specific order by ID — O(1) flat-dict lookup (D-20/PERF3)."""
        # Native-UUID keying (D-14): a non-UUID id can never be a stored key.
        if not isinstance(order_id, uuid.UUID):
            return None
        order = self._by_id.get(order_id)
        if order is None:
            return None
        if portfolio_id is not None and order.portfolio_id != portfolio_id:
            return None
        return order

    def update_order(self, order: 'Order') -> bool:
        """Update an existing order (single flat-dict write)."""
        if order.id in self._by_id:
            self._by_id[order.id] = order
            return True
        return False

    def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get all orders for a specific ticker (predicate filter)."""
        return [order for order in self._orders(portfolio_id) if order.ticker == ticker]

    def clear_portfolio_orders(self, portfolio_id: IdLike) -> int:
        """Clear all active orders for a portfolio.

        Terminal orders are kept in the flat dict to preserve history.
        """
        to_remove = [
            order.id for order in self._orders(portfolio_id) if order.is_active
        ]
        for order_id in to_remove:
            del self._by_id[order_id]
        return len(to_remove)

    # Enhanced storage methods implementation

    def get_orders_by_status(self, status: 'OrderStatus', portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get orders by status, optionally filtered by portfolio."""
        return [order for order in self._orders(portfolio_id) if order.status == status]

    def get_active_orders(self, portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get all active orders — pure ``order.is_active`` predicate (D-20)."""
        return [order for order in self._orders(portfolio_id) if order.is_active]

    def get_orders_by_time_range(self, start_time: datetime, end_time: datetime,
                                portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get orders within a time range."""
        return [
            order for order in self._orders(portfolio_id)
            if start_time <= order.created_at <= end_time
        ]

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
                'triggered_by': change.triggered_by.value,
                'additional_data': change.additional_data
            }
            for change in order.state_changes
        ]

    def search_orders(self, criteria: Dict[str, Any], portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Search orders based on criteria."""
        orders: List['Order'] = []
        for order in self._orders(portfolio_id):
            match = True
            for key, value in criteria.items():
                if not hasattr(order, key) or getattr(order, key) != value:
                    match = False
                    break
            if match:
                orders.append(order)
        return orders

    def count_orders_by_status(self, portfolio_id: Optional[IdLike] = None) -> Dict[str, int]:
        """Count orders by status (status name -> count)."""
        status_counts: Dict[str, int] = {}
        for order in self._orders(portfolio_id):
            status_name = order.status.name
            status_counts[status_name] = status_counts.get(status_name, 0) + 1
        return status_counts
