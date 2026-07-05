"""
Order-ack event: the venue's acknowledgement of a submitted order (D-06 / V17-02).

When ``OkxExchange._submit_order`` submits an order the venue returns the exchange
order id in ``response["id"]``. That id must be STAMPED + PERSISTED on the stored
order's ``venue_order_id`` field so a post-restart reconciler can match its
working-set orders to venue resting orders / fills by id (the in-memory
``VenueCorrelationIndex`` alone is lost across a process restart).

Cross-domain rule: the exchange must NOT write the order store directly. Instead it
emits this small frozen fact onto ``global_queue``; ``OrderHandler.on_order_ack``
consumes it and ``OrderManager.stamp_venue_order_id`` persists the stamp via
``order_storage.update_order`` (queue-only cross-domain write, D-19).

V5: bind ONLY the declared fields (``order_id -> venue_order_id`` + routing) — the
raw venue payload never rides onto the event (information-disclosure guard).
"""

from typing import Any, ClassVar

from itrader.core.enums import EventType
from itrader.core.ids import OrderId, PortfolioId

from .base import Event


class OrderAckEvent(Event, frozen=True, kw_only=True, gc=False):
    """
    The venue's acknowledgement that a submitted order was accepted, carrying the
    venue-assigned order id back to the order domain.

    Emitted by ``OkxExchange._submit_order`` once the venue id lands and consumed by
    ``OrderHandler.on_order_ack`` to stamp + persist the mirror's ``venue_order_id``.
    The simulated exchange never emits it (oracle-dark on the backtest path).
    """

    type: ClassVar[EventType] = EventType.ORDER_ACK
    order_id: OrderId
    venue_order_id: str
    portfolio_id: PortfolioId

    def __str__(self) -> str:
        return (f"{self.type} (order_id: {self.order_id}, "
                f"venue_order_id: {self.venue_order_id})")

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def new_order_ack(cls, event: Any, venue_order_id: str) -> 'OrderAckEvent':
        """
        Build an OrderAckEvent from the originating ``OrderEvent`` and the venue id.

        Reads ``order_id``/``portfolio_id``/``time`` off the submitted OrderEvent so
        the ack traces to its entity (D-12) and inherits the order's business time
        (never wall clock, D-02).
        """
        return cls(
            time=event.time,
            order_id=event.order_id,
            venue_order_id=venue_order_id,
            portfolio_id=event.portfolio_id,
        )
