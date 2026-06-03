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
