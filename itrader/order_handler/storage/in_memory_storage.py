import uuid
from typing import Any, Dict, Iterator, List, Optional, TYPE_CHECKING
from datetime import datetime
from ..base import OrderStorage, IdLike
# OrderStatus is needed at RUNTIME (as a dict key for the active-only
# by_status index and the shadow registry, and to build the module-level
# _ACTIVE_STATUSES frozenset). A TYPE_CHECKING-only import would NameError at
# runtime — keep this a real top-level import. ``Order`` stays under
# TYPE_CHECKING (string forward refs only); no ``from __future__``.
from ...core.enums import OrderStatus

if TYPE_CHECKING:
    from ..order import Order


# The single source of the active predicate, kept in lockstep with
# ``Order.is_active`` (PENDING / PARTIALLY_FILLED). Never re-derive the active
# set per call site — index logic reads this frozenset.
_ACTIVE_STATUSES: frozenset['OrderStatus'] = frozenset(
    {OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED}
)


class InMemoryOrderStorage(OrderStorage):
    """
    In-memory implementation of OrderStorage.

    Flat-dict-only design: a single ``self._by_id: Dict[uuid.UUID, Order]``
    is the SOLE container. Keying is native ``uuid.UUID`` so lookup and
    removal are O(1).

    Order classification is a *predicate filter* over the entity, evaluated
    at query time:

    - "active"        -> ``order.is_active`` (PENDING / PARTIALLY_FILLED)
    - per-portfolio   -> ``order.portfolio_id == portfolio_id``
    - per-ticker      -> ``order.ticker == ticker``
    - per-status      -> ``order.status == status``

    A status change on the entity alone moves it across query classes — no
    dual-write, no deactivate step. Terminal (filled/cancelled/rejected)
    orders stay in the flat dict, preserving the "all orders" audit/history
    semantics.
    """

    def __init__(self) -> None:
        """Initialize the in-memory storage.

        The flat ``{order_id: order}`` dict is the only source of truth. The
        three structures below are derived caches over it, never a second
        source of truth. They are kept consistent at every one of the five
        write seams (add_order / update_order / remove_order /
        remove_orders_by_ticker / clear_portfolio_orders) via the shared
        ``_index_apply`` / ``_index_remove`` helpers — mirroring the
        MatchingEngine ``_resting`` (truth) / ``_trails`` (parallel cache)
        discipline, where the side-table is touched at every site the truth
        dict is touched so no entry ever leaks or drifts.
        """
        self._by_id: Dict[uuid.UUID, 'Order'] = {}                          # source of truth
        # CACHE-CLASS: (b) storage-index lookup — solved by Phase-3 SQL WHERE/indexes — see docs/CACHE-CLASSIFICATION.md
        self._active_by_portfolio: Dict[uuid.UUID, Dict[uuid.UUID, None]] = {}   # derived cache
        self._by_status: Dict['OrderStatus', Dict[uuid.UUID, None]] = {}         # derived cache, active-only
        self._last_indexed_status: Dict[uuid.UUID, 'OrderStatus'] = {}           # shadow registry: one entry per LIVE order (active OR terminal)
        # The GLOBAL order-scope config singleton (trivial dict impl; backtest-dark).
        self._config: Optional[Dict[str, Any]] = None

    # --- index maintenance (derived caches over the flat dict) --------------

    def _index_apply(self, order: 'Order') -> None:
        """Reconcile both caches + the shadow registry for one order.

        Diff-on-write: the order mutates status IN PLACE before the storage
        write, so the stored object already shows the new status. We diff the
        registry's ``old`` (None for a brand-new id — never pre-seed it)
        against ``order.status``. Called by BOTH add_order and update_order
        (one shared path — no divergence). Idempotent.
        """
        oid = order.id
        pid = order.portfolio_id                          # immutable per order
        old_status = self._last_indexed_status.get(oid)   # None => brand-new id
        new_status = order.status
        if old_status == new_status:
            return                                        # PENDING->PENDING modify / EXPIRED no-op: no bucket move
        was_active = old_status in _ACTIVE_STATUSES       # None => was absent
        is_active = new_status in _ACTIVE_STATUSES
        # active_by_portfolio: maintain only on an active-boundary crossing.
        if is_active and not was_active:
            self._active_by_portfolio.setdefault(pid, {})[oid] = None   # insertion-ordered append
        elif was_active and not is_active:
            bucket = self._active_by_portfolio.get(pid)
            if bucket is not None:
                bucket.pop(oid, None)
                if not bucket:
                    del self._active_by_portfolio[pid]    # keep get_active_orders(None) clean
        # by_status: active-only — drop on terminal, add on active.
        # ``was_active`` implies ``old_status`` is a non-None active member;
        # test it directly so mypy narrows ``OrderStatus | None`` -> ``OrderStatus``.
        if old_status is not None and old_status in _ACTIVE_STATUSES:
            self._by_status[old_status].pop(oid, None)
        if is_active:
            self._by_status.setdefault(new_status, {})[oid] = None
        self._last_indexed_status[oid] = new_status

    def _index_remove(self, order: 'Order') -> None:
        """Drop one order from both caches + the registry (delete paths).

        Every remove pops the registry entry too, so the registry holds
        exactly one entry per LIVE _by_id order (active OR terminal) and never
        leaks a stale status after the order is deleted. (The registry is NOT
        active-only — _index_apply records terminal statuses as well, which
        the old_status diff for a later re-add/update of the same id relies on.)
        """
        oid = order.id
        pid = order.portfolio_id
        bucket = self._active_by_portfolio.get(pid)
        if bucket is not None:
            bucket.pop(oid, None)
            if not bucket:
                del self._active_by_portfolio[pid]
        registered = self._last_indexed_status.get(oid)
        if registered in _ACTIVE_STATUSES:
            status_bucket = self._by_status.get(registered)
            if status_bucket is not None:
                status_bucket.pop(oid, None)
        self._last_indexed_status.pop(oid, None)

    def _orders(self, portfolio_id: Optional[IdLike] = None) -> Iterator['Order']:
        """Iterate stored orders, optionally filtered by portfolio predicate."""
        for order in self._by_id.values():
            if portfolio_id is None or order.portfolio_id == portfolio_id:
                yield order

    def add_order(self, order: 'Order') -> None:
        """Add a new order to in-memory storage (flat-dict write).

        Routes through the same ``_index_apply`` diff as update_order so a
        re-add of an existing id is idempotent and a reject-then-add (REJECTED
        at add time) never enters the active book.
        """
        self._by_id[order.id] = order
        self._index_apply(order)

    def remove_order(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> bool:
        """Remove an order from in-memory storage (O(1) flat-dict delete)."""
        # Native-UUID keying: a non-UUID id can never be a stored key.
        if not isinstance(order_id, uuid.UUID):
            return False
        order = self._by_id.get(order_id)
        if order is None:
            return False
        if portfolio_id is not None and order.portfolio_id != portfolio_id:
            return False
        del self._by_id[order_id]
        self._index_remove(order)
        return True

    def remove_orders_by_ticker(self, ticker: str, portfolio_id: IdLike) -> int:
        """Remove all active orders for a specific ticker in a portfolio.

        Sources candidate ids from the active index: this method only ever
        removes active orders, so the active bucket is the exact equivalent
        set. Terminal orders stay in ``_by_id`` (history) — they were never in
        the active index.
        """
        # The index is UUID-keyed; a non-UUID IdLike can never be a key, so
        # fail closed here rather than falling through to an empty bucket.
        if not isinstance(portfolio_id, uuid.UUID):
            return 0
        bucket = self._active_by_portfolio.get(portfolio_id, {})
        to_remove = [
            oid for oid in bucket if self._by_id[oid].ticker == ticker
        ]
        for order_id in to_remove:
            order = self._by_id[order_id]
            del self._by_id[order_id]
            self._index_remove(order)
        return len(to_remove)

    def get_pending_orders(self, portfolio_id: Optional[IdLike] = None) -> Dict[Any, Dict[Any, 'Order']]:
        """Get active orders grouped by portfolio (derived nested view).

        The nested ``{portfolio_id: {order_id: order}}`` shape is built
        on-the-fly from the flat dict — it is a return-shape convenience, not
        a stored structure.
        """
        if portfolio_id is not None:
            # Index is UUID-keyed; fail closed on a non-UUID IdLike.
            if not isinstance(portfolio_id, uuid.UUID):
                return {portfolio_id: {}}
            bucket = self._active_by_portfolio.get(portfolio_id, {})
            return {portfolio_id: {oid: self._by_id[oid] for oid in bucket}}
        # None path: scan _by_id filtered by active membership so the nested
        # shape keeps the SAME first-seen-portfolio + within-portfolio GLOBAL
        # add_order order an equivalent flat scan would (a per-portfolio index
        # union would re-group and change the sequence).
        result: Dict[Any, Dict[Any, 'Order']] = {}
        for order in self._by_id.values():
            if order.status in _ACTIVE_STATUSES:
                result.setdefault(order.portfolio_id, {})[order.id] = order
        return result

    def get_order_by_id(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> Optional['Order']:
        """Get a specific order by ID — O(1) flat-dict lookup."""
        # Native-UUID keying: a non-UUID id can never be a stored key.
        if not isinstance(order_id, uuid.UUID):
            return None
        order = self._by_id.get(order_id)
        if order is None:
            return None
        if portfolio_id is not None and order.portfolio_id != portfolio_id:
            return None
        return order

    def update_order(self, order: 'Order') -> bool:
        """Update an existing order (flat-dict write + index reconcile)."""
        if order.id in self._by_id:
            self._by_id[order.id] = order
            self._index_apply(order)
            return True
        return False

    def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get all orders for a specific ticker (predicate filter)."""
        return [order for order in self._orders(portfolio_id) if order.ticker == ticker]

    def clear_portfolio_orders(self, portfolio_id: IdLike) -> int:
        """Clear all active orders for a portfolio (sourced from the active index).

        Terminal orders are kept in the flat dict to preserve history — they
        were never in the active index, so sourcing from it is exactly
        equivalent.
        """
        # Index is UUID-keyed; fail closed on a non-UUID IdLike.
        if not isinstance(portfolio_id, uuid.UUID):
            return 0
        bucket = self._active_by_portfolio.get(portfolio_id, {})
        to_remove = list(bucket)
        for order_id in to_remove:
            order = self._by_id[order_id]
            del self._by_id[order_id]
            self._index_remove(order)
        return len(to_remove)

    # Enhanced storage methods implementation
    #
    # The OrderStorage ABC stays query-shaped: the indexes below are a private
    # cache of InMemoryOrderStorage only, and no in-memory-only assumption may
    # leak into the seam. Every ABC method is SQL-expressible, as
    # ``sql_storage.py::SqlOrderStorage`` does — insertion order maps
    # to ``ORDER BY created_at, id``; get_order_history implies a state-change
    # child table; search_orders needs a column whitelist; the active vs terminal
    # split here is an in-memory caching detail (SQL covers both with one
    # ``WHERE status=?``). No in-memory-only assumption leaks into the seam.

    def get_orders_by_status(self, status: 'OrderStatus', portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get orders by status, optionally filtered by portfolio.

        Active statuses resolve membership via the by_status index; terminal
        statuses keep scanning the flat dict (no hot caller, so the unbounded
        bucket growth of an active-style index is avoided).

        Ordering: the by_status bucket is kept in status-transition order (an
        order is popped from PENDING and appended to PARTIALLY_FILLED at fill
        time), which diverges from add-order. To keep output byte-identical
        across every active status (not just PENDING, where transition order
        equals add-order), we yield in _by_id add-order and use the bucket
        only as the membership filter. This method has no per-bar hot caller
        (the hot active-set path is get_active_orders / get_pending_orders via
        _active_by_portfolio), so the _by_id walk here is not on the measured
        path.
        """
        if status in _ACTIVE_STATUSES:
            bucket = self._by_status.get(status, {})
            return [order for order in self._orders(portfolio_id) if order.id in bucket]
        return [order for order in self._orders(portfolio_id) if order.status == status]

    def get_active_orders(self, portfolio_id: Optional[IdLike] = None) -> List['Order']:
        """Get all active orders via the active index.

        Per-portfolio: a single bucket lookup. None: a ``_by_id`` scan filtered
        by active membership — preserves GLOBAL add_order insertion order
        byte-identically (a per-portfolio union would re-group). The None path
        has no production hot caller (reconcile passes a concrete pid,
        lifecycle iterates per concrete pid), so the scan costs nothing
        measured.
        """
        if portfolio_id is not None:
            # Index is UUID-keyed; fail closed on a non-UUID IdLike.
            if not isinstance(portfolio_id, uuid.UUID):
                return []
            bucket = self._active_by_portfolio.get(portfolio_id, {})
            return [self._by_id[oid] for oid in bucket]
        # Route the None scan through the centralized _orders() predicate for a
        # single iteration source, matching add-order byte-identically.
        return [o for o in self._orders() if o.status in _ACTIVE_STATUSES]

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

    # -- Runtime config (order scope — global singleton) ---------------

    def save_config(self, config: Dict[str, Any], at: datetime) -> None:
        """Store the GLOBAL order-scope config singleton (trivial dict; ``at`` unused)."""
        self._config = config

    def load_config(self) -> Optional[Dict[str, Any]]:
        """Return the stored global order-scope config, or ``None`` if never saved."""
        return self._config
