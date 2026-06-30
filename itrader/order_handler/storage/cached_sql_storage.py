"""``CachedSqlOrderStorage`` — the live-only order-seam decorator (D-04 wrapper topology).

Composes the gate-passed Phase-3 ``SqlOrderStorage`` (system of record) with an in-memory
``InMemoryOrderStorage`` working set, implementing the 14-method ``OrderStorage`` ABC by
forwarding store-first (persist-then-acknowledge, Pitfall 8). The store commit returns BEFORE
the cache is mutated, so the cache is always rebuildable from the store and a cache bug can
never compromise the store's proven correctness (D-04 — the composed ``SqlOrderStorage`` is
never modified).

Retention (D-02): a terminal standalone order is purged from the cache the moment it
terminalizes, behind a mandatory terminal-state gate (``_can_evict``). A bracket PARENT stays
resident until ALL of its children terminalize (bracket-parent-resident). The open set is
served from the cache (hot path); terminal / purged records are served via read-through to the
store. Restart rehydration (D-03) loads open-only (PENDING / PARTIALLY_FILLED) plus the
(possibly terminal) parents of live children — never standalone terminal history.

Research dispositions:
* A1 (cross-method atomicity): per-write store-first, FK-ordered (parent before children). The
  wrapper adds NO ``add_bracket`` method and NO cross-method transaction — within-method
  atomicity is the composed store's ``engine.begin()``; cross-method bracket atomicity is N+4
  reconciliation's job, NOT a Phase-4 failure.
* A4 (thread-safety): read-through is daemon-only as-wired but built API-thread-safe with one
  ``threading.RLock`` taken briefly around cache mutation + read-through lookup.
* A5 (typing): this module enters ``mypy --strict`` (no override).

The module stays SQL-import-light: ``SqlOrderStorage`` / ``Order`` are imported under
``TYPE_CHECKING`` only, so it is NOT re-exported from any package ``__init__`` (GATE-01
quarantine — the backtest import path stays SQL-free). 4-space indentation (matches the
existing ``order_handler/storage`` siblings; Pitfall 12 — a mixed-indent file raises TabError).
"""

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from itrader.core.enums import OrderStatus
from itrader.logger import get_itrader_logger

from ..base import IdLike, OrderStorage
from .in_memory_storage import InMemoryOrderStorage

if TYPE_CHECKING:
    from ..order import Order
    from .sql_storage import SqlOrderStorage   # type-only — keep the module SQL-import-light


# The active predicate (PENDING / PARTIALLY_FILLED), kept in lockstep with ``Order.is_active``.
# A single home for the cache-vs-read-through split on ``get_orders_by_status``.
_ACTIVE_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED}
)


class CachedSqlOrderStorage(OrderStorage):
    """Live order-seam wrapper: store-first write-through over a purged working-set cache.

    Parameters
    ----------
    store:
        The composed Phase-3 ``SqlOrderStorage`` (system of record). Each of its mutating
        methods is already one ``engine.begin()`` transaction (within-method atomicity).
    """

    def __init__(self, store: "SqlOrderStorage") -> None:
        self._store: "SqlOrderStorage" = store
        # CACHE-CLASS: (d) live-retention working-set cache (built in Phase 4) — see docs/CACHE-CLASSIFICATION.md
        self._cache = InMemoryOrderStorage()
        # A4 — one RLock guards cache mutation + read-through lookup; uncontended in the
        # daemon-only Phase-4 wiring, API-thread-safe for the imminent FastAPI layer.
        self._lock = threading.RLock()
        self.logger = get_itrader_logger().bind(component="CachedSqlOrderStorage")

    # ------------------------------------------------------------------ eviction gate (D-02)
    def _can_evict(self, order: "Order") -> bool:
        """Whether ``order`` may leave the working set (terminal-state gate, D-02).

        Guard-clause / early-exit: never evict an open order. A bracket PARENT (one with
        ``child_order_ids``) is resident until EVERY child is terminal; a standalone terminal
        order is immediately evictable.
        """
        if not order.is_terminal:
            return False
        if order.child_order_ids:
            return all(self._child_is_terminal(cid) for cid in order.child_order_ids)
        return True

    def _child_is_terminal(self, child_id: IdLike) -> bool:
        """Whether a bracket child is terminal — cache first, read-through to the store on miss.

        A purged child is terminal by definition (it was evicted because it terminalized); a
        store miss therefore counts as terminal.
        """
        cached = self._cache.get_order_by_id(child_id)
        if cached is not None:
            return cached.is_terminal
        stored = self._store.get_order_by_id(child_id)
        if stored is None:
            return True
        return stored.is_terminal

    def _maybe_evict_parent(self, parent_id: IdLike) -> None:
        """Re-evaluate a bracket parent and purge it if all its children are now terminal.

        Sources the parent from the cache (the only place it could still be resident); a parent
        already purged needs no action. Called under ``self._lock``.
        """
        parent = self._cache.get_order_by_id(parent_id)
        if parent is None:
            return
        if self._can_evict(parent):
            self._cache.remove_order(parent.id)

    # ------------------------------------------------------------------ writes (store-first)
    def add_order(self, order: "Order") -> None:
        """Persist store-first, then mirror into the cache (Pitfall 8 persist-then-acknowledge).

        An order that is ALREADY terminal at add time is purged on the same terminal-state
        gate as ``update_order`` (D-02): the admission path persists audited REJECTED records
        straight through ``add_order`` (admission_manager.py — every sizing / direction /
        validator rejection), so without this gate each rejection would leave a resident
        terminal record in the working set forever and break the flat-RSS / purge-on-terminalize
        invariant. A standalone terminal order is evicted immediately; a (terminal) bracket
        parent whose children are all terminal is evicted too, with its own parent re-evaluated.
        """
        self._store.add_order(order)            # one txn (orders row + state_changes)
        with self._lock:
            self._cache.add_order(order)        # mirror into the working set
            # Evict a terminal order added straight through add_order. The gate is restricted
            # to orders with NO children of their own (standalone terminals — e.g. an audited
            # REJECTED admission record, or a terminal bracket child): a bracket PARENT is added
            # ACTIVE (PENDING) in the real flow and only terminalizes later via update_order, so
            # applying the child-aware ``_can_evict`` here would wrongly evict a parent whose
            # children are merely not added yet (FK ordering makes the child store-lookup miss,
            # which ``_child_is_terminal`` reads as terminal). A terminal child still re-evaluates
            # its parent so a now-complete bracket parent is purged.
            if order.is_terminal and not order.child_order_ids:
                self._cache.remove_order(order.id)
                if order.parent_order_id is not None:
                    self._maybe_evict_parent(order.parent_order_id)

    def update_order(self, order: "Order") -> bool:
        """Update store-first; on success mirror to cache and purge if now terminal (D-02)."""
        ok = self._store.update_order(order)
        if not ok:
            return False                        # unknown id — leave the cache untouched
        with self._lock:
            self._cache.update_order(order)
            if self._can_evict(order):
                self._cache.remove_order(order.id)
                if order.parent_order_id is not None:
                    self._maybe_evict_parent(order.parent_order_id)
        return True

    def remove_order(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> bool:
        """Remove store-first, then drop from the cache (a purged entry drops harmlessly)."""
        ok = self._store.remove_order(order_id, portfolio_id)
        with self._lock:
            self._cache.remove_order(order_id, portfolio_id)
        return ok

    def remove_orders_by_ticker(self, ticker: str, portfolio_id: IdLike) -> int:
        """Remove active ticker orders store-first, then mirror the removal into the cache.

        These removals only ever drop ACTIVE orders, so a terminal bracket PARENT held
        resident under the bracket-parent-resident invariant is left behind when its last
        live children are cleared here. Re-evaluate those parents after the removal so an
        orphaned terminal parent is evicted instead of leaking until restart (D-02).
        """
        with self._lock:
            parent_ids = {
                o.parent_order_id
                for o in self._cache.get_active_orders(portfolio_id)
                if o.ticker == ticker and o.parent_order_id is not None
            }
            count = self._store.remove_orders_by_ticker(ticker, portfolio_id)
            self._cache.remove_orders_by_ticker(ticker, portfolio_id)
            for parent_id in parent_ids:
                self._maybe_evict_parent(parent_id)
        return count

    def clear_portfolio_orders(self, portfolio_id: IdLike) -> int:
        """Clear active portfolio orders store-first, then mirror the removal into the cache.

        Mirrors ``remove_orders_by_ticker``: clearing only drops ACTIVE orders, so re-evaluate
        the bracket parents of the cleared children afterward to evict any now-orphaned
        terminal parent (bracket-parent-resident, D-02).
        """
        with self._lock:
            parent_ids = {
                o.parent_order_id
                for o in self._cache.get_active_orders(portfolio_id)
                if o.parent_order_id is not None
            }
            count = self._store.clear_portfolio_orders(portfolio_id)
            self._cache.clear_portfolio_orders(portfolio_id)
            for parent_id in parent_ids:
                self._maybe_evict_parent(parent_id)
        return count

    # ------------------------------------------------------------------ reads (split)
    def get_order_by_id(
        self, order_id: IdLike, portfolio_id: Optional[IdLike] = None
    ) -> Optional["Order"]:
        """Cache hit returns without touching the store; a miss reads through (terminal/purged)."""
        with self._lock:
            hit = self._cache.get_order_by_id(order_id, portfolio_id)
        if hit is not None:
            return hit
        return self._store.get_order_by_id(order_id, portfolio_id)

    def get_pending_orders(
        self, portfolio_id: Optional[IdLike] = None
    ) -> Dict[Any, Dict[Any, "Order"]]:
        """Active orders grouped by portfolio — cache-only (the open set is always resident)."""
        with self._lock:
            return self._cache.get_pending_orders(portfolio_id)

    def get_active_orders(self, portfolio_id: Optional[IdLike] = None) -> List["Order"]:
        """All active orders — cache-only (the open set is always resident)."""
        with self._lock:
            return self._cache.get_active_orders(portfolio_id)

    def get_orders_by_status(
        self, status: "OrderStatus", portfolio_id: Optional[IdLike] = None
    ) -> List["Order"]:
        """Active statuses serve from the cache; terminal statuses read through to the store."""
        if status in _ACTIVE_STATUSES:
            with self._lock:
                return self._cache.get_orders_by_status(status, portfolio_id)
        return self._store.get_orders_by_status(status, portfolio_id)

    def get_orders_by_ticker(
        self, ticker: str, portfolio_id: Optional[IdLike] = None
    ) -> List["Order"]:
        """All orders for a ticker (active + terminal) — read-through to the store."""
        return self._store.get_orders_by_ticker(ticker, portfolio_id)

    def get_orders_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        portfolio_id: Optional[IdLike] = None,
    ) -> List["Order"]:
        """Time-range query (history) — read-through to the store."""
        return self._store.get_orders_by_time_range(start_time, end_time, portfolio_id)

    def get_order_history(self, order_id: IdLike) -> List[Dict[str, Any]]:
        """State-change history (audit trail) — read-through to the store."""
        return self._store.get_order_history(order_id)

    def search_orders(
        self, criteria: Dict[str, Any], portfolio_id: Optional[IdLike] = None
    ) -> List["Order"]:
        """Criteria search (may span terminal history) — read-through to the store."""
        return self._store.search_orders(criteria, portfolio_id)

    def count_orders_by_status(
        self, portfolio_id: Optional[IdLike] = None
    ) -> Dict[str, int]:
        """Status counts (span the full retained history) — read-through to the store."""
        return self._store.count_orders_by_status(portfolio_id)

    # ------------------------------------------------------------------ rehydration (D-03)
    def rehydrate(self) -> None:
        """Load the open set (open-only) plus the parents of live children, on restart.

        Uses the Phase-3 indexed active query (D-08). A live child's (possibly terminal) parent
        is pulled in so the bracket-parent-resident invariant holds post-restart; standalone
        terminal history is NEVER loaded into the working set.
        """
        with self._lock:
            for order in self._store.get_active_orders(None):
                self._cache.add_order(order)
                parent_id = order.parent_order_id
                if parent_id is not None and self._cache.get_order_by_id(parent_id) is None:
                    parent = self._store.get_order_by_id(parent_id)
                    if parent is not None:
                        self._cache.add_order(parent)
