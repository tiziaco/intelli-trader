"""
Pure order-matching engine for simulated execution.

Holds resting OrderEvents (stop/limit, and next-bar market orders) and decides
which fill on each bar using intrabar high/low, with pessimistic gap fills and
exchange-enforced OCO between bracket siblings.

This module has NO dependency on the event queue, fee/slippage models, or
logging side-effects. It takes OrderEvents and BarEvents in and returns plain
decision objects out, so it is fully deterministic and unit-testable.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from itrader.events_handler.event import OrderEvent, BarEvent
from itrader.core.enums import OrderType


@dataclass
class FillDecision:
    """One resting order has matched and should be filled."""
    order_event: OrderEvent
    fill_quantity: float
    fill_price: float
    reason: str


@dataclass
class CancelDecision:
    """One resting order should be cancelled (OCO sibling of a fill)."""
    order_event: OrderEvent
    reason: str


class MatchingEngine:
    """Resting-order book + trigger/OCO evaluation."""

    def __init__(self):
        self._resting: Dict[int, OrderEvent] = {}

    # --- book management ---

    def submit(self, order_event: OrderEvent) -> None:
        """Add a resting order (stop/limit, or a next-bar market order)."""
        self._resting[order_event.order_id] = order_event

    def cancel(self, order_id: int) -> bool:
        """Remove a resting order. Returns True if it was present."""
        return self._resting.pop(order_id, None) is not None

    def modify(self, order_id: int, new_price: Optional[float] = None,
               new_quantity: Optional[float] = None) -> bool:
        """Mutate a resting order's price/quantity. Returns True if present."""
        order = self._resting.get(order_id)
        if order is None:
            return False
        if new_price is not None:
            order.price = new_price
        if new_quantity is not None:
            order.quantity = new_quantity
        return True

    def has_order(self, order_id: int) -> bool:
        return order_id in self._resting

    def get_order(self, order_id: int) -> Optional[OrderEvent]:
        return self._resting.get(order_id)

    # --- matching ---

    def _evaluate(self, order: OrderEvent, bar: BarEvent) -> Optional[float]:
        """Return the fill price if `order` triggers on `bar`, else None."""
        ticker = order.ticker
        if ticker not in bar.bars:
            return None
        open_ = bar.get_last_open(ticker)
        high = bar.get_last_high(ticker)
        low = bar.get_last_low(ticker)

        if order.order_type == OrderType.MARKET:
            # next-bar market order: unconditional fill at the open
            return open_

        if order.order_type == OrderType.STOP:
            if order.action == 'SELL':              # stop-loss on a long
                if low <= order.price:
                    return min(open_, order.price)  # pessimistic gap-down
            else:                                   # BUY stop (cover short)
                if high >= order.price:
                    return max(open_, order.price)  # pessimistic gap-up

        elif order.order_type == OrderType.LIMIT:
            # Limits fill at the limit price even on a favorable gap (we never
            # credit a better-than-limit fill to the strategy) — intentionally
            # asymmetric with the pessimistic open-based gap fill used for stops.
            if order.action == 'SELL':              # take-profit on a long
                if high >= order.price:
                    return order.price
            else:                                   # BUY limit (cover short)
                if low <= order.price:
                    return order.price

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
        candidates: Dict[int, float] = {}
        for order in list(self._resting.values()):
            try:
                price = self._evaluate(order, bar)
            except (TypeError, ValueError, KeyError):
                # A single malformed resting order (e.g. price=None, missing bar
                # field) must not drop the whole bar. Programming errors
                # (AttributeError, etc.) are NOT swallowed — they propagate.
                continue
            if price is not None:
                candidates[order.order_id] = price

        if not candidates:
            return [], []

        # 2. Resolve, per bracket, which single order fills.
        chosen: Dict[int, float] = {}   # order_id -> fill_price
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
        cancelled_ids = set()

        for order_id, price in chosen.items():
            order = self._resting[order_id]
            fills.append(FillDecision(
                order_event=order,
                fill_quantity=order.quantity,
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
            self._resting.pop(fill.order_event.order_id, None)
        for cancel in cancels:
            self._resting.pop(cancel.order_event.order_id, None)

        return fills, cancels

    def _pick_bracket_winner(self, bracket: int, candidates: Dict[int, float]) -> int:
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
