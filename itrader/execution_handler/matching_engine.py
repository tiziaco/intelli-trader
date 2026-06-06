"""
Pure order-matching engine for simulated execution.

Holds resting OrderEvents (stop/limit, and next-bar market orders) and decides
which fill on each bar using intrabar high/low, with pessimistic gap fills and
exchange-enforced OCO between bracket siblings.

This module has NO dependency on the event queue, fee/slippage models, or
logging side-effects. It takes OrderEvents and BarEvents in and returns plain
decision objects out, so it is fully deterministic and unit-testable.

Money (D-12/D-14): matching is Decimal end-to-end — order prices and Bar OHLC
are both Decimal, so trigger comparisons and gap-fill min/max run in the
Decimal domain with NO quantization (never-round-prices: rounding happens only
at money boundaries, never inside matching).

DEF-01-C (known limitation, blessed into the M1 oracle): the engine has no
margin/liquidation model. A short position that is never liquidated can drive
total equity negative — this is current-behavior-to-preserve, routed to the
Phase 7 (M5b) risk layer per D-07. Documentation only; no matching behavior
encodes margin.
"""

import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple

from itrader.core.ids import OrderId
from itrader.core.money import to_money
from itrader.events_handler.events import OrderEvent, BarEvent
from itrader.core.enums import OrderType, Side


@dataclass
class FillDecision:
    """One resting order has matched and should be filled.

    Full-quantity contract (D-06): a fill always covers the order's entire
    quantity — partial fills do not exist in the engine, so the decision
    carries no quantity field (the exchange reads ``order_event.quantity``).
    ``fill_price`` is Decimal, the product of Decimal-native trigger/gap math
    against Decimal Bar OHLC (D-12).
    """
    order_event: OrderEvent
    fill_price: Decimal
    reason: str


@dataclass
class CancelDecision:
    """One resting order should be cancelled (OCO sibling of a fill)."""
    order_event: OrderEvent
    reason: str


class MatchingEngine:
    """Resting-order book + trigger/OCO evaluation."""

    def __init__(self) -> None:
        # Order ids have been UUIDv7-backed since M2 (D-12) — the book is
        # keyed by OrderId, never by int.
        self._resting: dict[OrderId, OrderEvent] = {}

    # --- book management ---

    def submit(self, order_event: OrderEvent) -> None:
        """Add a resting order (stop/limit, or a next-bar market order)."""
        if order_event.order_id is None:
            raise ValueError("Cannot rest an order with no order_id")
        self._resting[order_event.order_id] = order_event

    def cancel(self, order_id: OrderId) -> bool:
        """Remove a resting order. Returns True if it was present."""
        return self._resting.pop(order_id, None) is not None

    def modify(self, order_id: OrderId, new_price: Optional[Decimal] = None,
               new_quantity: Optional[Decimal] = None) -> bool:
        """Replace a resting order with an updated copy. Returns True if present.

        Replace-in-book: the stored OrderEvent is never mutated in place —
        ``dataclasses.replace`` builds an updated copy from the None-guarded
        changed kwargs and stores it back under the same key. ``replace``
        deliberately PRESERVES ``order_id`` (and ``event_id`` once events
        carry one): a MODIFY changes an order's terms, not its identity —
        it is the same instruction, amended (RESEARCH Open Question 2).

        D-22: the annotation follows the event retype (Decimal money);
        ``to_money`` normalizes so a legacy float caller still stores
        Decimal in the book (identity on Decimal input).
        """
        order = self._resting.get(order_id)
        if order is None:
            return False
        # None-guarded: an omitted kwarg keeps the resting order's own value.
        self._resting[order_id] = dataclasses.replace(
            order,
            price=order.price if new_price is None else to_money(new_price),
            quantity=order.quantity if new_quantity is None else to_money(new_quantity),
        )
        return True

    def has_order(self, order_id: OrderId) -> bool:
        return order_id in self._resting

    def get_order(self, order_id: OrderId) -> Optional[OrderEvent]:
        return self._resting.get(order_id)

    # --- matching ---

    def _evaluate(self, order: OrderEvent, bar: BarEvent) -> Optional[Decimal]:
        """Return the fill price if `order` triggers on `bar`, else None."""
        ticker = order.ticker
        bar_struct = bar.bars.get(ticker)
        if bar_struct is None:
            # No bar for this ticker at T (sparse universe / data gap) —
            # same no-data semantics as the legacy Optional accessors.
            return None
        # D-12: Decimal end-to-end — Bar OHLC is Decimal by construction and
        # order.price is Decimal money, so the trigger comparisons and min/max
        # gap-fill math below run in the Decimal domain. NO quantization here
        # (D-14 never-round-prices): rounding belongs to money boundaries only.
        open_ = bar_struct.open
        high = bar_struct.high
        low = bar_struct.low
        trigger = order.price

        if order.order_type == OrderType.MARKET:
            # next-bar market order: unconditional fill at the open
            return open_

        if order.order_type == OrderType.STOP:
            if order.action is Side.SELL:           # stop-loss on a long
                if low <= trigger:
                    return min(open_, trigger)      # pessimistic gap-down
            else:                                   # BUY stop (cover short)
                if high >= trigger:
                    return max(open_, trigger)      # pessimistic gap-up

        elif order.order_type == OrderType.LIMIT:
            # Limit-or-better (D-03): a limit fill can never be worse than the
            # limit price. On a favorable gap the order fills at the (better)
            # open; an in-bar touch fills at the limit exactly. Asymmetric with
            # the pessimistic open-based gap fill used for stops by design.
            if order.action is Side.SELL:           # take-profit on a long
                if open_ >= trigger:
                    return open_                    # gap-through: better open
                elif high >= trigger:
                    return trigger                  # in-bar touch: at limit
            else:                                   # BUY limit (cover short)
                if open_ <= trigger:
                    return open_                    # gap-through: better open
                elif low <= trigger:
                    return trigger                  # in-bar touch: at limit

        return None

    def on_bar(self, bar: BarEvent) -> Tuple[List[FillDecision], List[CancelDecision]]:
        """
        Evaluate all resting orders against `bar`.

        - Candidates are orders whose trigger price is reached this bar.
        - For bracket siblings (same non-None parent_order_id), at most one
          fills per bar; if both a STOP and a LIMIT are candidates, the STOP
          wins (pessimistic same-bar priority).
        - When a bracket leg fills, all other resting orders in that bracket
          are cancelled (OCO), even if they did not trigger this bar.
        """
        # 1. Collect candidate fills (price reached).
        candidates: dict[OrderId, Decimal] = {}
        for order in list(self._resting.values()):
            try:
                price = self._evaluate(order, bar)
            except (TypeError, ValueError, KeyError):
                # A single malformed resting order (e.g. price=None, missing bar
                # field) must not drop the whole bar. Programming errors
                # (AttributeError, etc.) are NOT swallowed — they propagate.
                continue
            if price is not None and order.order_id is not None:
                candidates[order.order_id] = price

        if not candidates:
            return [], []

        # 2. Resolve, per bracket, which single order fills.
        chosen: dict[OrderId, Decimal] = {}   # order_id -> fill_price
        seen_brackets = set()
        for order_id, price in candidates.items():
            order = self._resting[order_id]
            bracket = order.parent_order_id
            if bracket is None:
                chosen[order_id] = price            # standalone, fills independently
                continue
            if bracket in seen_brackets:
                continue                            # already chose a leg for this bracket
            seen_brackets.add(bracket)
            winner_id = self._pick_bracket_winner(bracket, candidates)
            chosen[winner_id] = candidates[winner_id]

        # 3. Build fills and OCO cancels.
        fills: List[FillDecision] = []
        cancels: List[CancelDecision] = []
        cancelled_ids: set[Optional[OrderId]] = set()

        for order_id, price in chosen.items():
            order = self._resting[order_id]
            fills.append(FillDecision(
                order_event=order,
                fill_price=price,
                reason=self._fill_reason(order),
            ))
            bracket = order.parent_order_id
            if bracket is not None:
                # O(n) sibling scan per filled bracket; negligible at backtest
                # scale (< ~100 resting orders per symbol). Pre-index by
                # parent_order_id if the book ever grows to thousands.
                for sibling in list(self._resting.values()):
                    if (sibling.parent_order_id == bracket
                            and sibling.order_id != order_id
                            and sibling.order_id not in cancelled_ids):
                        cancels.append(CancelDecision(sibling, "OCO - sibling filled"))
                        cancelled_ids.add(sibling.order_id)

        # 4. Remove filled + cancelled orders from the book.
        for fill in fills:
            if fill.order_event.order_id is not None:
                self._resting.pop(fill.order_event.order_id, None)
        for cancel in cancels:
            if cancel.order_event.order_id is not None:
                self._resting.pop(cancel.order_event.order_id, None)

        return fills, cancels

    def _pick_bracket_winner(self, bracket: OrderId,
                             candidates: dict[OrderId, Decimal]) -> OrderId:
        """Among candidate legs of a bracket, prefer a STOP (pessimistic)."""
        leg_ids = [oid for oid in candidates
                   if self._resting[oid].parent_order_id == bracket]
        for oid in leg_ids:
            if self._resting[oid].order_type == OrderType.STOP:
                return oid
        return leg_ids[0]

    @staticmethod
    def _fill_reason(order: OrderEvent) -> str:
        if order.order_type == OrderType.STOP:
            return "stop triggered"
        if order.order_type == OrderType.LIMIT:
            return "limit triggered"
        return "market fill"
