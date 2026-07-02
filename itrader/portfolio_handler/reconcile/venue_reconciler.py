"""VenueReconciler — the venue side of two-sided restart rehydration (RECON-05, D-03/D-05).

Restart rehydration is TWO-SIDED. The store side already exists
(``CachedSqlOrderStorage.rehydrate()`` — INTENT truth: the working set the engine
submitted before it went down). This module adds the VENUE side: on startup, BEFORE
``status=RUNNING``, it reconciles the rehydrated working set against the live venue's
balance / position / fill truth (REST snapshot) and resolves any disagreement that
accrued during downtime SAFELY before the engine trades again.

Authority split (D-03): the store owns INTENT (which orders exist); the venue owns
balances / positions / fills. When they disagree at restart:

* a venue fill/position DELTA that maps to a stored order is ADOPTED in-band — the
  reconciler synthesizes a reconciling ``FillEvent`` (``last_qty = venue.filled_qty −
  order.filled_qty``, ported in concept from nautilus
  ``create_inferred_order_filled_event`` — NEVER imported) and ``global_queue.put``s it
  so it flows through the SAME idempotent fill path the live stream uses. The delta is
  computed from the rehydrated (persisted) ``filled_quantity``, so a second restart
  re-reads the now-updated filled and computes a zero delta — adopt-once by
  construction (the 05-05 fill-ID dedup covers the concurrent-stream case). Portfolio
  state is NEVER mutated directly (T-05-20).
* a venue POSITION with NO matching stored intent (a hand-opened position) HALTS-and-
  alerts — never silently adopted (D-03 / T-05-21). Adopt is deliberately broader at
  restart than steady-state, but an unexplained position is always a halt.

Bracket re-adoption (D-05) extends this class in a sibling method (``_relink_brackets``)
— re-link stored parent/child legs against the venue resting set, per-bracket halt on an
unconfident leg.

Runs on the ENGINE thread at startup before RUNNING. Backtest-inert: lazy-imported at
the live composition root only (no async / connector / SQL import on the backtest path);
``LiveConnector`` / ``VenueAccount`` / ``CachedSqlOrderStorage`` are ``TYPE_CHECKING``-only.
4-space indentation (matches ``core/`` + the ``reconcile/`` siblings ``drift.py``).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from itrader.core.money import to_money
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from queue import Queue

    from itrader.connectors.base import LiveConnector
    from itrader.order_handler.order import Order
    from itrader.order_handler.storage.cached_sql_storage import CachedSqlOrderStorage
    from itrader.portfolio_handler.account.venue import VenueAccount

# D-07: the machine-readable halt reason for an unresolved reconciliation (matches the
# 05-04 halt vocabulary consumed by LiveTradingSystem.halt / get_status).
_HALT_REASON = "reconciliation-unresolved"


class VenueReconciler:
    """Venue-side restart reconcile: store-vs-venue → reconciling events / halt (D-03/D-05).

    Parameters
    ----------
    store:
        The rehydratable order working set (``CachedSqlOrderStorage``) — the INTENT
        truth. ``reconcile`` calls ``rehydrate()`` on it (store side) before comparing.
    venue_account:
        The cached ``VenueAccount`` (05-03) — ``snapshot()`` takes the REST venue truth;
        ``positions`` exposes the signed per-symbol quantities.
    connector:
        The injected ``LiveConnector`` session — the reconciler reads
        ``fetch_my_trades`` / ``fetch_open_orders`` through ``connector.call`` (D-04 seam).
    global_queue:
        The shared event queue — reconciling ``FillEvent``s are ``put`` here so they
        flow through the SAME idempotent fill path (D-03; NEVER mutate state directly).
    halt_signal:
        The 05-04 freeze-in-place halt entrypoint (``LiveTradingSystem.halt``) — called
        with ``reason='reconciliation-unresolved'`` on an unexplained venue position or
        an unconfident bracket leg.
    quote_currency:
        The quote currency for the venue balance reads (default ``"USDT"``).
    """

    def __init__(
        self,
        *,
        store: "CachedSqlOrderStorage",
        venue_account: "VenueAccount",
        connector: "LiveConnector",
        global_queue: "Queue[Any]",
        halt_signal: Callable[[str], None],
        quote_currency: str = "USDT",
    ) -> None:
        self._store = store
        self._venue_account = venue_account
        self._connector = connector
        self._global_queue = global_queue
        self._halt_signal = halt_signal
        self._quote = quote_currency
        self.logger = get_itrader_logger().bind(component="VenueReconciler")

    # ------------------------------------------------------------------ entrypoint
    def reconcile(self) -> None:
        """Two-sided restart reconcile on the engine thread, BEFORE RUNNING (D-03).

        (1) rehydrate the working set from the store (INTENT truth); (2) take the REST
        venue snapshot (balance/position/fill truth); (3) adopt each in-band venue delta
        as a reconciling ``FillEvent`` through the idempotent fill path; (4) halt-and-alert
        on any venue position with no stored intent.
        """
        # 1. store side — reconstruct the INTENT working set (open orders + bracket parents).
        self._store.rehydrate()
        working = self._working_set()

        # 2. venue side — REST snapshot (balances/positions) + the venue fill history.
        self._venue_account.snapshot()
        venue_trades = self._fetch("fetch_my_trades")

        # 3. adopt in-band fill deltas as reconciling events (never mutate state directly).
        self._adopt_fill_deltas(working, venue_trades)

        # 4. halt-and-alert on a venue position with no stored intent (hand-opened).
        self._halt_on_orphan_positions(working)

    # ------------------------------------------------------------------ working set
    def _working_set(self) -> List["Order"]:
        """Return the rehydrated working set: active orders + their (resident) bracket parents.

        A live child's (possibly terminal) bracket parent is pulled in so a bracket is
        re-adoptable as a whole and its symbol counts as stored intent for the
        orphan-position check.
        """
        orders: Dict[Any, "Order"] = {}
        for order in self._store.get_active_orders(None):
            orders[order.id] = order
            parent_id = order.parent_order_id
            if parent_id is not None and parent_id not in orders:
                parent = self._store.get_order_by_id(parent_id)
                if parent is not None:
                    orders[parent.id] = parent
        return list(orders.values())

    # ------------------------------------------------------------------ fill adoption
    def _adopt_fill_deltas(
        self, working: List["Order"], venue_trades: Any
    ) -> None:
        """Adopt each in-band venue fill delta as a reconciling ``FillEvent`` (D-03).

        Groups the venue trades by venue order id, matches each stored order by its
        persisted ``venue_order_id``, and for a positive ``venue_filled − order.filled``
        delta synthesizes an EXECUTED reconciling fill driven through the idempotent fill
        path. A zero/negative delta (already applied) emits nothing — adopt-once.
        """
        by_venue_id = self._group_trades_by_venue_id(venue_trades)
        for order in working:
            venue_id = order.venue_order_id
            if venue_id is None:
                continue
            trades = by_venue_id.get(str(venue_id))
            if not trades:
                continue
            venue_filled, avg_price, total_commission, last_ts = self._aggregate(trades)
            delta = venue_filled - to_money(order.filled_quantity)
            if delta <= 0:
                # Already applied (or nothing new) — no phantom fill (idempotent, T-05-20).
                continue
            commission = (
                total_commission * (delta / venue_filled)
                if venue_filled > 0
                else Decimal("0")
            )
            self._emit_reconciling_fill(order, delta, avg_price, commission, last_ts)
            self.logger.info(
                "Adopted venue fill delta for order %s (venue_id=%s): +%s @ %s",
                order.id, venue_id, delta, avg_price)

    @staticmethod
    def _group_trades_by_venue_id(venue_trades: Any) -> Dict[str, List[Dict[str, Any]]]:
        """Group ccxt-unified venue trades by their ``order`` (venue order id)."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        if not isinstance(venue_trades, list):
            return grouped
        for trade in venue_trades:
            if not isinstance(trade, dict):
                continue
            venue_id = trade.get("order")
            if venue_id is None:
                continue
            grouped.setdefault(str(venue_id), []).append(trade)
        return grouped

    @staticmethod
    def _aggregate(
        trades: List[Dict[str, Any]]
    ) -> tuple[Decimal, Decimal, Decimal, Optional[Any]]:
        """Aggregate a venue order's trades → (filled_qty, avg_price, commission, last_ts).

        Every venue float crosses the Decimal edge via ``to_money(str(x))``; a missing
        price/amount is skipped. Commission is the non-negative magnitude sum (WR-01),
        stamped-time is the last trade's venue timestamp (business time).
        """
        total_qty = Decimal("0")
        weighted = Decimal("0")
        total_commission = Decimal("0")
        last_ts: Optional[Any] = None
        for trade in trades:
            amount = trade.get("amount")
            price = trade.get("price")
            if amount is None or price is None:
                continue
            qty = to_money(str(amount))
            px = to_money(str(price))
            total_qty += qty
            weighted += qty * px
            fee_obj = trade.get("fee")
            fee: Dict[str, Any] = fee_obj if isinstance(fee_obj, dict) else {}
            fee_cost = fee.get("cost")
            if fee_cost is not None:
                total_commission += abs(to_money(str(fee_cost)))
            ts = trade.get("timestamp")
            if ts is not None:
                last_ts = ts
        avg_price = (weighted / total_qty) if total_qty > 0 else Decimal("0")
        return total_qty, avg_price, total_commission, last_ts

    def _emit_reconciling_fill(
        self,
        order: "Order",
        quantity: Decimal,
        price: Decimal,
        commission: Decimal,
        venue_ts: Optional[Any],
    ) -> None:
        """Mint an EXECUTED reconciling ``FillEvent`` and put it on the queue (D-03).

        Ported in concept from nautilus ``create_inferred_order_filled_event`` (NEVER
        imported): the fill drives the SAME idempotent fill path the live stream uses, so
        state is never mutated directly. ``FillEvent.time`` is stamped from the venue
        trade timestamp (business time), never wall-clock.
        """
        order_event = OrderEvent.new_order_event(order)
        fill_time = self._venue_ts_to_dt(venue_ts) if venue_ts is not None else None
        fill = FillEvent.new_fill(
            "EXECUTED", order_event,
            price=price, quantity=quantity, commission=commission,
            time=fill_time)
        self._global_queue.put(fill)

    @staticmethod
    def _venue_ts_to_dt(ts: Any) -> datetime:
        """Convert a venue millisecond timestamp to a tz-aware UTC datetime (business time)."""
        return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)

    # ------------------------------------------------------------------ orphan positions
    def _halt_on_orphan_positions(self, working: List["Order"]) -> None:
        """Halt-and-alert on any venue position with no matching stored intent (D-03).

        A venue position whose symbol is referenced by NO stored order is a hand-opened
        position — never auto-adopted (T-05-21). Escalates to the freeze-in-place halt
        (reason='reconciliation-unresolved'); the first orphan halts.
        """
        stored_symbols = {order.ticker for order in working}
        for symbol, qty in self._venue_account.positions.items():
            if qty == 0:
                continue
            if symbol not in stored_symbols:
                self.logger.error(
                    "Venue position %s (%s) has no stored intent — halting", symbol, qty)
                self._halt_signal(_HALT_REASON)
                return

    def _fetch(self, method_name: str) -> Any:
        """Run a venue REST read (``fetch_my_trades`` / ``fetch_open_orders``) via the connector."""
        client_method = getattr(self._connector.client, method_name)
        return self._connector.call(client_method())
