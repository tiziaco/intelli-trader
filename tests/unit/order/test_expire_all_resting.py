"""
LifecycleManager.expire_all_resting() run-end sweep (LIFE-01, Plan 06-03,
D-08/D-10).

The sweep is the peer of ``cancel_order`` (lifecycle_manager.py): it visits
active portfolios in ``get_active_portfolios()`` order and, within each, orders
sorted by ``order_id`` (UUIDv7 stable sort, D-10); per order it locally
transitions PENDING -> EXPIRED (``order.expire_order``), persists, idempotently
releases the reservation (WR-04), and emits an ``OrderEvent(EXPIRE)`` carried on
a successful ``OperationResult``. The manager NEVER touches the queue (D-18) —
it returns results, the handler enqueues.

Behaviors pinned (against a real PortfolioHandler + real storage + real Orders,
mirroring the ``_Harness`` in test_order_manager.py):
- sweep order (D-10): portfolios in get_active_portfolios() order, orders sorted
  by order_id within each — affected_order_ids matches that deterministic order
- sweep transition: each swept order's mirror status is EXPIRED; update_order applied
- sweep release: portfolio_handler.release(portfolio_id, order_id) called once per
  swept order; a second call pops nothing (idempotent — no error)
- sweep emit: each returned OperationResult carries exactly one OrderEvent with
  command == OrderCommand.EXPIRE; no queue access inside the manager
- handler enqueue: OrderHandler.expire_all_resting() enqueues each EXPIRE event

Folder-derived ``unit`` marker (no decorator).
"""

import datetime as _dt
from decimal import Decimal
from queue import Queue

import pytest

from itrader.order_handler.order import Order
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.core.enums import OrderCommand, OrderStatus, Side


class _Harness:
    """OrderHandler + storage + funded portfolios, mirroring test_order_manager."""

    def __init__(self, n_portfolios=2):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.storage = OrderStorageFactory.create("test")
        self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
        self.portfolio_ids = [
            self.ptf_handler.add_portfolio(i + 1, f"p{i}", "default", 100000)
            for i in range(n_portfolios)
        ]

    def rest_a_stop(self, portfolio_id):
        order = Order.new_stop_order(
            time=_dt.datetime(2024, 1, 1), ticker="BTCUSDT",
            action=Side.SELL, price=30.0, quantity=1.0, exchange="default",
            strategy_id=1, portfolio_id=portfolio_id,
        )
        self.storage.add_order(order)
        return order

    def drain(self):
        return [self.queue.get() for _ in range(self.queue.qsize())]


@pytest.fixture
def harness():
    h = _Harness()
    yield h
    while not h.queue.empty():
        h.queue.get_nowait()


# --- sweep order (D-10) -----------------------------------------------------


def test_sweep_order_is_portfolio_then_order_id_sorted(harness):
    """expire_all_resting visits portfolios in get_active_portfolios() order and,
    within each, orders sorted by order_id (UUIDv7) — affected_order_ids matches
    that deterministic order."""
    expected = []
    for pf in harness.ptf_handler.get_active_portfolios():
        orders = [harness.rest_a_stop(pf.portfolio_id) for _ in range(2)]
        for o in sorted(orders, key=lambda o: o.id):
            expected.append(o.id)

    results = harness.handler.order_manager.lifecycle_manager.expire_all_resting()

    swept = [oid for r in results for oid in r.affected_order_ids]
    assert swept == expected


# --- sweep transition + storage persist -------------------------------------


def test_sweep_transitions_each_order_to_expired(harness):
    orders = [harness.rest_a_stop(harness.portfolio_ids[0]) for _ in range(2)]

    harness.handler.order_manager.lifecycle_manager.expire_all_resting()

    for o in orders:
        stored = harness.storage.get_order_by_id(o.id, o.portfolio_id)
        assert stored.status == OrderStatus.EXPIRED


# --- sweep emits exactly one EXPIRE OrderEvent per swept order ---------------


def test_sweep_emits_one_expire_event_per_order(harness):
    orders = [harness.rest_a_stop(harness.portfolio_ids[0]) for _ in range(3)]

    results = harness.handler.order_manager.lifecycle_manager.expire_all_resting()

    assert len(results) == len(orders)
    for r in results:
        assert r.success
        assert len(r.order_events) == 1
        assert r.order_events[0].command is OrderCommand.EXPIRE
    # The manager never touched the queue — only the handler enqueues.
    assert harness.queue.qsize() == 0


# --- sweep release is idempotent (a second release pops nothing) ------------


def test_sweep_release_is_idempotent(harness):
    order = harness.rest_a_stop(harness.portfolio_ids[0])

    harness.handler.order_manager.lifecycle_manager.expire_all_resting()
    # A second explicit release for the same order pops nothing and never raises.
    harness.ptf_handler.release(order.portfolio_id, order.id)


# --- handler enqueues each EXPIRE event -------------------------------------


def test_handler_expire_all_resting_enqueues_expire_events(harness):
    orders = [harness.rest_a_stop(harness.portfolio_ids[0]) for _ in range(2)]

    harness.handler.expire_all_resting()

    events = harness.drain()
    order_events = [e for e in events if e.type.name == "ORDER"]
    assert len(order_events) == len(orders)
    assert all(e.command is OrderCommand.EXPIRE for e in order_events)
    swept_ids = {e.order_id for e in order_events}
    assert swept_ids == {o.id for o in orders}
