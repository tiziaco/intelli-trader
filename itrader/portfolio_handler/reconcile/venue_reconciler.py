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

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from itrader.core.money import to_money
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.logger import get_itrader_logger

from .drift import is_within_single_unit_tolerance

if TYPE_CHECKING:
    from queue import Queue

    from itrader.connectors.base import LiveConnector
    from itrader.order_handler.order import Order
    from itrader.order_handler.storage.cached_sql_storage import CachedSqlOrderStorage
    from itrader.portfolio_handler.account.venue import VenueAccount

# D-07: the machine-readable halt reason for an unresolved reconciliation (matches the
# 05-04 halt vocabulary consumed by LiveTradingSystem.halt / get_status).
_HALT_REASON = "reconciliation-unresolved"

# Conservative precision for the symbol+side+price+qty FALLBACK leg match (D-05). The
# venue-id-first match is the CONFIDENT path (exact id equality); the fallback only fires
# when a leg has no persisted venue id, and a one-least-significant-unit tolerance guards
# the venue-float→Decimal last-digit noise (mirrors drift.py's epsilon rationale). Kept
# generous — an over-tight epsilon would misfire the fallback into a spurious per-bracket halt.
_MATCH_PRICE_PRECISION = 2
_MATCH_QTY_PRECISION = 8

# F/U-13 (D-09) — OKX's ``/trade/fills-history`` REST window is ~3 months (100/page). A
# derived ``since`` older than this bound CANNOT be covered by the single limit=100 call
# (ccxt auto-pagination trips sCode 51000 — A3), so the catch-up would silently miss a
# downtime fill. When ``since`` predates ``now − this window`` the reconciler logs loudly
# (T-05.2-04) so an operator sees the incomplete catch-up. Deep pagination is deliberately
# NOT built; this loud-log is the guard for the single-limit=100 call.
_FILLS_HISTORY_WINDOW_DAYS = 90


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
    exchange:
        The order-arm venue exchange (``OkxExchange``) whose in-memory correlation
        maps must be repopulated for rehydrated orders (WR-02 / RECON-05). ``None``
        on the paper/backtest/test paths — a clean skip (the seam is live-only).
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
        exchange: Optional[Any] = None,
    ) -> None:
        self._store = store
        self._venue_account = venue_account
        self._connector = connector
        self._global_queue = global_queue
        self._halt_signal = halt_signal
        self._quote = quote_currency
        self._exchange = exchange
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
        venue_trades = self._fetch_trades(working)

        # 3. adopt in-band fill deltas as reconciling events (never mutate state directly).
        self._adopt_fill_deltas(working, venue_trades)

        # 4. halt-and-alert on a venue position with no stored intent (hand-opened).
        self._halt_on_orphan_positions(working)

        # 5. re-adopt brackets from the venue resting set (D-05): re-link stored
        #    parent/child legs, per-bracket halt on an unconfidently-linked leg.
        venue_open_orders = self._fetch("fetch_open_orders")
        self._relink_brackets(working, venue_open_orders)

        # 6. WR-02 / RECON-05: repopulate the order-arm venue correlation maps for
        #    every rehydrated order carrying a venue id. Runs AFTER _relink_brackets
        #    so freshly re-linked bracket legs (their venue ids just stamped) are
        #    included via the working set. Without this a post-restart fill for a
        #    rehydrated resting order is buffered and never drained, and its cancel is
        #    a silent no-op — the maps are otherwise written ONLY by
        #    OkxExchange._submit_order, which never ran for a pre-restart order.
        self._adopt_venue_correlation(working)

    # ------------------------------------------------------------------ correlation adopt
    def _adopt_venue_correlation(self, working: List["Order"]) -> None:
        """Repopulate the order-arm venue correlation maps for rehydrated orders (WR-02).

        Calls the injected order-arm seam (``OkxExchange.adopt_venue_correlation``)
        for each working-set order (including re-linked bracket legs) carrying a
        persisted ``venue_order_id``. A ``None`` exchange (paper/backtest/test paths)
        is a clean skip — the seam is live-only.
        """
        if self._exchange is None:
            return
        for order in working:
            if order.venue_order_id is not None:
                self._exchange.adopt_venue_correlation(order)

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
        """Adopt each in-band venue fill as a per-trade reconciling ``FillEvent`` (D-03/CR-01).

        Groups the venue trades by venue order id, matches each stored order by its
        persisted ``venue_order_id``, and emits ONE reconciling fill PER not-yet-applied
        venue trade — each carrying its OWN ``venue_trade_id`` (CR-01). Per-trade emission
        (matching the live stream's granularity) is what lets the portfolio settlement
        chokepoint dedup a reconciler-adopted trade against a stream re-delivery of the
        SAME ``trade['id']`` — an aggregated summed-delta fill has no single venue key and
        cannot dedup, so it double-counts (the CR-01 defect).
        """
        by_venue_id = self._group_trades_by_venue_id(venue_trades)
        for order in working:
            venue_id = order.venue_order_id
            if venue_id is None:
                continue
            trades = by_venue_id.get(str(venue_id))
            if not trades:
                continue
            self._adopt_order_trades(order, venue_id, trades)

    def _adopt_order_trades(
        self, order: "Order", venue_id: Any, trades: List[Dict[str, Any]]
    ) -> None:
        """Emit one reconciling fill per not-yet-applied venue trade (adopt-once, CR-01).

        Walks the order's venue trades in venue order and skips the leading quantity
        already reflected in the persisted ``filled_quantity`` (the skip budget), then
        emits the remaining trades one-for-one. A second restart re-reads the now-updated
        ``filled_quantity`` and skips every trade — adopt-once by construction (T-05-20).
        A trade that straddles the applied/unapplied boundary emits only its unapplied
        remainder (commission prorated); the far more common whole-trade case emits the
        trade verbatim with its own ``venue_trade_id``.
        """
        skip_budget = to_money(order.filled_quantity)
        for trade in self._order_trades(trades):
            amount = trade.get("amount")
            price = trade.get("price")
            if amount is None or price is None:
                continue
            qty = to_money(str(amount))
            if qty <= 0:
                continue
            if skip_budget >= qty:
                # This whole trade is already reflected in filled_quantity — skip it.
                skip_budget -= qty
                continue
            emit_qty = qty - skip_budget
            skip_budget = Decimal("0")
            px = to_money(str(price))
            commission = self._trade_commission(trade, qty, emit_qty)
            trade_id = trade.get("id")
            venue_trade_id = str(trade_id) if trade_id is not None else None
            self._emit_reconciling_fill(
                order, emit_qty, px, commission, trade.get("timestamp"), venue_trade_id)
            self.logger.info(
                "Adopted venue trade for order %s (venue_id=%s, trade_id=%s): +%s @ %s",
                order.id, venue_id, venue_trade_id, emit_qty, px)

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
    def _order_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Order an order's venue trades deterministically (timestamp, then trade id).

        The skip-budget adopt-once walk needs a stable order so the SAME trades are
        skipped/emitted on every restart. Timestamp is the venue's fill order; the trade
        id breaks ties for same-millisecond fills.
        """
        return sorted(
            trades,
            key=lambda t: (t.get("timestamp") or 0, str(t.get("id") or "")),
        )

    @staticmethod
    def _trade_commission(
        trade: Dict[str, Any], full_qty: Decimal, emit_qty: Decimal
    ) -> Decimal:
        """The non-negative commission magnitude for the emitted portion of a trade (WR-01).

        Uses the trade's own fee; for a boundary-straddling trade it prorates the fee by
        the emitted fraction (``emit_qty / full_qty``). Every venue float crosses the
        Decimal edge via ``to_money(str(x))``.
        """
        fee_obj = trade.get("fee")
        fee: Dict[str, Any] = fee_obj if isinstance(fee_obj, dict) else {}
        fee_cost = fee.get("cost")
        if fee_cost is None:
            return Decimal("0")
        full_commission = abs(to_money(str(fee_cost)))
        if emit_qty >= full_qty or full_qty <= 0:
            return full_commission
        return full_commission * (emit_qty / full_qty)

    def _emit_reconciling_fill(
        self,
        order: "Order",
        quantity: Decimal,
        price: Decimal,
        commission: Decimal,
        venue_ts: Optional[Any],
        venue_trade_id: Optional[str],
    ) -> None:
        """Mint an EXECUTED reconciling ``FillEvent`` and put it on the queue (D-03/CR-01).

        Ported in concept from nautilus ``create_inferred_order_filled_event`` (NEVER
        imported): the fill drives the SAME idempotent fill path the live stream uses, so
        state is never mutated directly. ``FillEvent.time`` is stamped from the venue
        trade timestamp (business time), never wall-clock. ``venue_trade_id`` carries the
        venue's own trade id so the settlement chokepoint dedups a stream re-delivery of
        the same economic trade (CR-01).
        """
        order_event = OrderEvent.new_order_event(order)
        fill_time = self._venue_ts_to_dt(venue_ts) if venue_ts is not None else None
        fill = FillEvent.new_fill(
            "EXECUTED", order_event,
            price=price, quantity=quantity, commission=commission,
            time=fill_time, venue_trade_id=venue_trade_id)
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

    # ------------------------------------------------------------------ bracket re-link (D-05)
    def _relink_brackets(
        self, working: List["Order"], venue_open_orders: Any
    ) -> None:
        """Re-adopt brackets from the venue resting set; per-bracket halt on an unconfident leg.

        For each rehydrated bracket parent (an order carrying ``child_order_ids``), re-link
        its still-resting legs against the venue open orders — match by the persisted
        ``venue_order_id`` FIRST, then fall back to symbol+side+price+qty. A confident match
        stamps the venue id onto the leg and persists it (so a subsequent restart re-links
        by id — the Open Question 3 population path) and resumes OCO. A leg that cannot be
        confidently re-linked escalates THAT bracket to halt-and-alert (D-05) — a per-bracket
        halt, never a guess (T-05-22).
        """
        resting, resting_by_id = self._index_resting_orders(venue_open_orders)
        for parent in working:
            if not parent.child_order_ids:
                continue
            if not self._relink_bracket(parent, resting, resting_by_id):
                self.logger.error(
                    "Bracket %s has an unconfidently-linked leg — halting", parent.id)
                self._halt_signal(_HALT_REASON)

    @staticmethod
    def _index_resting_orders(
        venue_open_orders: Any,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Return (resting-order list, {venue_id: resting_order}) from the venue open orders."""
        resting: List[Dict[str, Any]] = []
        by_id: Dict[str, Dict[str, Any]] = {}
        if not isinstance(venue_open_orders, list):
            return resting, by_id
        for order in venue_open_orders:
            if not isinstance(order, dict):
                continue
            resting.append(order)
            venue_id = order.get("id")
            if venue_id is not None:
                by_id[str(venue_id)] = order
        return resting, by_id

    def _relink_bracket(
        self,
        parent: "Order",
        resting: List[Dict[str, Any]],
        resting_by_id: Dict[str, Dict[str, Any]],
    ) -> bool:
        """Re-link every still-resting leg of ``parent``; return False on an unconfident leg."""
        for child_id in parent.child_order_ids:
            child = self._store.get_order_by_id(child_id)
            if child is None or not child.is_active:
                # A terminalized / absent leg has nothing resting to re-link.
                continue
            matched = self._match_leg(child, resting, resting_by_id)
            if matched is None:
                return False
            # Confident re-link: persist the venue id onto the leg (Open Question 3
            # population) so the next restart re-links by id, and resume OCO.
            venue_id = str(matched["id"])
            if child.venue_order_id != venue_id:
                child.venue_order_id = venue_id
                self._store.update_order(child)
        return True

    def _match_leg(
        self,
        child: "Order",
        resting: List[Dict[str, Any]],
        resting_by_id: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Match a stored leg to a venue resting order — venue-id first, then attributes.

        Returns the matched resting order, or ``None`` when the match is absent OR ambiguous
        (more than one attribute-candidate) — an unconfident leg the caller must halt on.
        """
        # Venue-id-first (the confident path): an exact persisted-id equality.
        if child.venue_order_id is not None:
            by_id = resting_by_id.get(str(child.venue_order_id))
            if by_id is not None:
                return by_id
        # Fallback: symbol + side + price + qty. Confident ONLY when exactly one candidate.
        candidates = [order for order in resting if self._leg_attributes_match(child, order)]
        if len(candidates) == 1:
            return candidates[0]
        return None

    @staticmethod
    def _leg_attributes_match(child: "Order", resting_order: Dict[str, Any]) -> bool:
        """Whether a venue resting order matches a stored leg on symbol+side+price+qty."""
        if resting_order.get("symbol") != child.ticker:
            return False
        side = resting_order.get("side")
        if side is None or str(side).lower() != child.action.value.lower():
            return False
        price = resting_order.get("price")
        amount = resting_order.get("amount")
        if price is None or amount is None:
            return False
        price_ok = is_within_single_unit_tolerance(
            to_money(str(price)), to_money(child.price), _MATCH_PRICE_PRECISION)
        qty_ok = is_within_single_unit_tolerance(
            to_money(str(amount)), to_money(child.quantity), _MATCH_QTY_PRECISION)
        return price_ok and qty_ok

    def _fetch_trades(self, working: List["Order"]) -> List[Dict[str, Any]]:
        """Fetch venue trades per working-set symbol (CONF-B: since + explicit limit=100).

        D-09 / V17-10: the old arg-less ``fetch_my_trades()`` returned only the venue's
        default recent window — it could NOT cover the working set's oldest active order
        after downtime. For each distinct active-order symbol, derive ``since`` from that
        symbol's oldest active order business ``time`` (epoch-ms) and fetch with an explicit
        ``limit=100``. The ccxt auto-pagination param is deliberately NOT passed — OKX
        rejects it with sCode 51000 'Parameter limit error' (CONF-B online run 2026-07-05;
        the working shape hits ``/trade/fills-history``, ~3-month window, 100/page). Trades
        are aggregated into ONE list so the downstream per-venue-id grouping
        (``_adopt_fill_deltas``) is unchanged.
        """
        active = [order for order in working if order.is_active]
        trades: List[Dict[str, Any]] = []
        for symbol in sorted({order.ticker for order in active}):
            since_ms = self._oldest_active_since_ms(active, symbol)
            self._warn_if_window_uncovered(symbol, since_ms)
            fetched = self._connector.call(
                self._connector.client.fetch_my_trades(symbol, since=since_ms, limit=100))
            if isinstance(fetched, list):
                trades.extend(fetched)
        return trades

    def _warn_if_window_uncovered(self, symbol: str, since_ms: int) -> None:
        """Loud-log when ``since`` predates the venue's ~3-month fills-history window (F/U-13).

        The single ``limit=100`` fetch reaches back only ~``_FILLS_HISTORY_WINDOW_DAYS``
        (OKX ``/trade/fills-history``); ccxt auto-pagination is not built (it trips sCode
        51000 — A3). When the oldest active order's ``since`` is older than that bound the
        catch-up cannot cover it, so a downtime fill could be missed — emit a WARNING naming
        the symbol and the uncovered bound (T-05.2-04) rather than fail silently. The window
        lower bound is a real-time operational bound (the venue's wall-clock window), not a
        business-time comparison, so ``datetime.now`` is legitimate here.
        """
        window_start = datetime.now(timezone.utc) - timedelta(days=_FILLS_HISTORY_WINDOW_DAYS)
        window_start_ms = int(window_start.timestamp() * 1000)
        if since_ms < window_start_ms:
            self.logger.warning(
                "Venue fills-history window (~%d days) cannot cover the oldest active order "
                "for %s (since=%s predates window_start=%s) — restart catch-up may be "
                "INCOMPLETE (deep pagination not built; A3/F/U-13)",
                _FILLS_HISTORY_WINDOW_DAYS, symbol, since_ms, window_start_ms)

    @staticmethod
    def _oldest_active_since_ms(active: List["Order"], symbol: str) -> int:
        """The oldest active-order business ``time`` for ``symbol`` as an epoch-ms ``since``.

        Business ``time`` only (never wall-clock, Pitfall 3) — the venue fill fetch must
        reach back to the working set's oldest still-open order for this symbol so a
        downtime fill is not missed.
        """
        oldest = min(order.time for order in active if order.ticker == symbol)
        return int(oldest.timestamp() * 1000)

    def _fetch(self, method_name: str) -> Any:
        """Run a venue REST read (``fetch_open_orders``) via the connector.

        Arg-less read still used for ``fetch_open_orders`` (the resting-order snapshot);
        the trade read is per-symbol / since / limit=100 via ``_fetch_trades`` (D-09).
        """
        client_method = getattr(self._connector.client, method_name)
        return self._connector.call(client_method())
