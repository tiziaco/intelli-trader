"""
SimulatedExchange ``OrderCommand.EXPIRE`` arm (LIFE-01, Plan 06-03, D-08).

The EXPIRE arm is the parallel peer of the CANCEL arm (simulated.py:274-283):
``matching_engine.cancel(order_id)`` bool guard, then a ``FillEvent(EXPIRED)``
carrying the order's own Decimal price/quantity with commission ``Decimal("0")``.

Two behaviors are pinned:
1. EXPIRE for a RESTING order removes it from the matching engine and emits a
   single ``FillEvent`` with status EXPIRED and commission ``Decimal("0")``.
2. EXPIRE for an order_id NOT resting emits NO fill (the
   ``matching_engine.cancel`` False guard — no spurious fill).

Mirrors the existing ``_RoutingHarness`` (connected SimulatedExchange restricted
to BTCUSDT). Folder-derived ``unit`` marker (no decorator).
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.events_handler.events import OrderEvent, FillEvent
from itrader.core.enums import OrderType, OrderCommand, FillStatus, Side


class _RoutingHarness:
    """Connected SimulatedExchange restricted to BTCUSDT, with event factories."""

    def __init__(self):
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)
        self.exchange.connect()
        self.exchange.update_config({"limits": {"supported_symbols": {"BTCUSDT"}}})

    def oe(self, order_type, action="SELL", price=30.0, order_id=1, command=None):
        return OrderEvent(
            time=datetime(2024, 1, 1), ticker="BTCUSDT",
            action=Side(action), price=Decimal(str(price)), quantity=Decimal("1.0"),
            exchange="default",
            strategy_id=1, portfolio_id=1, order_type=order_type, order_id=order_id,
            command=command or OrderCommand.NEW,
        )


@pytest.fixture
def routing():
    h = _RoutingHarness()
    yield h
    while not h.queue.empty():
        h.queue.get_nowait()


def test_expire_command_removes_resting_and_emits_expired(routing):
    """EXPIRE for a RESTING order removes it from the matching engine and emits
    a single FillEvent(EXPIRED) with commission Decimal("0")."""
    routing.exchange.on_order(routing.oe(OrderType.STOP, price=30.0, order_id=3))
    assert routing.exchange.matching_engine.has_order(3)

    routing.exchange.on_order(
        routing.oe(OrderType.STOP, price=30.0, order_id=3, command=OrderCommand.EXPIRE)
    )

    assert not routing.exchange.matching_engine.has_order(3)
    fills = [routing.queue.get() for _ in range(routing.queue.qsize())]
    assert len(fills) == 1
    assert isinstance(fills[0], FillEvent)
    assert fills[0].status is FillStatus.EXPIRED
    assert fills[0].order_id == 3
    assert fills[0].commission == Decimal("0")


def test_expire_command_for_non_resting_emits_no_fill(routing):
    """EXPIRE for an order_id that is NOT resting emits no FillEvent
    (matching_engine.cancel returns False -> the guard suppresses the fill)."""
    # No order id 42 was ever submitted.
    assert not routing.exchange.matching_engine.has_order(42)

    routing.exchange.on_order(
        routing.oe(OrderType.STOP, price=30.0, order_id=42, command=OrderCommand.EXPIRE)
    )

    assert routing.queue.qsize() == 0
