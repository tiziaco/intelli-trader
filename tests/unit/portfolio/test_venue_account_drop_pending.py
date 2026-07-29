"""The ORDER-ACK read-model seam: ``stamp_venue_order_id`` -> ``drop_pending``.

What survives here is the SEAM, not a venue-side overlay. ``drop_pending`` is declared on
the ``Account`` ABC, where a compute leaf documents it as a no-op, so the order manager
calls it unconditionally on every venue ack and each leaf decides what that means. Two
things matter: the call is MADE with the right ``(portfolio_id, order_id)`` key, and a
manager with no read-model wired does not blow up on the ack path — a venue ack arriving on
a system without a portfolio read-model is a legitimate wiring, not a crash.

The overlay-mutation tests that used to live here asserted a venue-cached leaf's pending
map, which has no successor: venue truth is read from the venue as an ``AccountSnapshot``
rather than accumulated on a leaf, so there is no overlay to hold or pop.

This directory is package-less (NO ``__init__.py``); the ``unit`` marker is folder-derived.
Indentation: 4-space.
"""

import uuid
from typing import Optional

from itrader.core.ids import OrderId, PortfolioId


class _RecordingReadModel:
    """Minimal ``PortfolioReadModel``-shaped double recording ``drop_pending`` calls."""

    def __init__(self) -> None:
        self.dropped: list[tuple[PortfolioId, OrderId]] = []

    def drop_pending(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        self.dropped.append((portfolio_id, order_id))


class _FakeOrder:
    def __init__(self) -> None:
        self.venue_order_id: Optional[str] = None


class _FakeStorage:
    """Fake ``OrderStorage`` exposing only the two members ``stamp_venue_order_id`` touches."""

    def __init__(self, order: Optional[_FakeOrder]) -> None:
        self._order = order
        self.updated = False

    def get_order_by_id(
        self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None
    ) -> Optional[_FakeOrder]:
        return self._order

    def update_order(self, order: _FakeOrder) -> bool:
        self.updated = True
        return True


def test_stamp_venue_order_id_drops_overlay_via_readmodel_seam() -> None:
    """The ORDER-ACK path drops the overlay through the injected read-model seam (D-15).

    ``stamp_venue_order_id`` must call ``PortfolioReadModel.drop_pending(portfolio_id,
    order_id)`` after stamping — the SAME injected seam the order domain uses for
    reserve/release (queue-only cross-domain contract, not a direct account import).
    """
    import logging

    from itrader.order_handler.order_manager import OrderManager

    read_model = _RecordingReadModel()
    storage = _FakeStorage(_FakeOrder())
    manager = OrderManager(
        storage,  # type: ignore[arg-type]
        logging.getLogger("test"),
        portfolio_handler=read_model,  # type: ignore[arg-type]
    )

    order_id = OrderId(uuid.uuid4())
    portfolio_id = PortfolioId(1)
    result = manager.stamp_venue_order_id(order_id, "venue-123", portfolio_id)

    assert result is True
    assert storage.updated is True
    assert read_model.dropped == [(portfolio_id, order_id)]


def test_stamp_venue_order_id_no_readmodel_is_safe() -> None:
    """Without an injected read-model the ack path stamps but skips the drop (no crash)."""
    import logging

    from itrader.order_handler.order_manager import OrderManager

    storage = _FakeStorage(_FakeOrder())
    manager = OrderManager(storage, logging.getLogger("test"))  # type: ignore[arg-type]

    order_id = OrderId(uuid.uuid4())
    result = manager.stamp_venue_order_id(order_id, "venue-123", PortfolioId(1))
    assert result is True
    assert storage.updated is True
