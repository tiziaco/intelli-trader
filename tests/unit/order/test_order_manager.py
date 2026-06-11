"""
Test suite for OrderManager - Internal order orchestration engine.

Tests the OrderManager's functionality including:
- Market-driven order processing
- Stop/Limit order trigger evaluation
- Market order execution timing
- Order fill processing
- State management and event generation
"""

import datetime as _dt
import uuid
from datetime import datetime
from decimal import Decimal
from queue import Queue
from unittest.mock import Mock

import pytest

from itrader.order_handler.order_manager import OrderManager
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.order import Order
from itrader.order_handler.storage import OrderStorageFactory
from itrader.order_handler.storage.in_memory_storage import InMemoryOrderStorage
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.events import SignalEvent, OrderEvent, FillEvent
from itrader.core.enums import OrderType, OrderCommand, OrderStatus, Side, OrderTriggerSource
from itrader.core.exceptions import InsufficientFundsError
from itrader.core.sizing import FractionOfCash, TradingDirection


# --- OrderManager initialization -------------------------------------------


def test_order_manager_initialization():
    """Test OrderManager initialization.

    D-18: the manager owns the storage and takes NO OrderHandler
    back-reference — layering is one-directional (facade -> manager -> storage).
    """
    order_storage = InMemoryOrderStorage()
    logger = Mock()

    order_manager_immediate = OrderManager(
        order_storage, logger, market_execution="immediate"
    )
    order_manager_next_bar = OrderManager(
        order_storage, logger, market_execution="next_bar"
    )

    assert order_manager_immediate.market_execution == "immediate"
    assert order_manager_next_bar.market_execution == "next_bar"
    assert order_manager_immediate.order_storage == order_storage
    assert order_manager_immediate.logger == logger
    # No back-reference to the handler exists (D-18)
    assert not hasattr(order_manager_immediate, "order_handler")


# --- shared handler harness -------------------------------------------------


class _Harness:
    """OrderHandler + storage + one funded portfolio."""

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.storage = OrderStorageFactory.create("test")
        self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
        self.portfolio_id = self.ptf_handler.add_portfolio(1, "p", "default", 100000)

    def signal(self, stop_loss=0.0, take_profit=0.0):
        return SignalEvent(
            time=_dt.datetime(2024, 1, 1), order_type=OrderType.MARKET,
            ticker="BTCUSDT", action=Side.BUY, price=40.0, quantity=1.0,
            stop_loss=stop_loss, take_profit=take_profit, strategy_id=1,
            portfolio_id=self.portfolio_id,
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
        )

    def rest_a_stop(self):
        order = Order.new_stop_order(
            time=_dt.datetime(2024, 1, 1), ticker="BTCUSDT",
            action="SELL", price=30.0, quantity=1.0, exchange="default",
            strategy_id=1, portfolio_id=self.portfolio_id,
        )
        self.storage.add_order(order)
        return order

    def fill(self, order, status):
        oe = OrderEvent(
            time=_dt.datetime(2024, 1, 1), ticker=order.ticker, action=Side(order.action),
            price=float(order.price), quantity=float(order.quantity), exchange=order.exchange,
            strategy_id=order.strategy_id, portfolio_id=order.portfolio_id,
            order_type=OrderType.STOP, order_id=order.id,
        )
        return FillEvent.new_fill(status, oe, price=oe.price, quantity=oe.quantity, commission=0.0)


@pytest.fixture
def harness():
    h = _Harness()
    yield h
    while not h.queue.empty():
        h.queue.get_nowait()


# --- bracket emission -------------------------------------------------------


def test_bracket_legs_emitted_and_linked(harness):
    harness.handler.on_signal(harness.signal(stop_loss=30.0, take_profit=55.0))
    events = [harness.queue.get() for _ in range(harness.queue.qsize())]
    order_events = [
        e for e in events
        if getattr(e, "order_type", None) is not None and e.type.name == "ORDER"
    ]
    types = sorted(e.order_type.name for e in order_events)
    assert types == ["LIMIT", "MARKET", "STOP"]
    primary = next(e for e in order_events if e.order_type == OrderType.MARKET)
    children = [e for e in order_events if e.order_type != OrderType.MARKET]
    for child in children:
        assert child.parent_order_id == primary.order_id


# --- commands ---------------------------------------------------------------


def test_cancel_emits_cancel_command(harness):
    order = harness.rest_a_stop()
    ok = harness.handler.cancel_order(order.id, harness.portfolio_id)
    assert ok
    events = [harness.queue.get() for _ in range(harness.queue.qsize())]
    order_events = [e for e in events if e.type.name == "ORDER"]
    assert len(order_events) == 1
    assert order_events[0].command is OrderCommand.CANCEL
    assert order_events[0].order_id == order.id


def test_modify_emits_modify_command(harness):
    order = harness.rest_a_stop()
    ok = harness.handler.modify_order(order.id, new_price=Decimal("28.0"), portfolio_id=harness.portfolio_id)
    assert ok
    events = [harness.queue.get() for _ in range(harness.queue.qsize())]
    order_events = [e for e in events if e.type.name == "ORDER"]
    assert len(order_events) == 1
    assert order_events[0].command is OrderCommand.MODIFY


def test_modify_quantity_only_succeeds(harness):
    """CR-01 regression: a quantity-only modification (new_price=None) must not
    TypeError inside validate_order_modification's `new_price <= 0` check."""
    order = harness.rest_a_stop()
    ok = harness.handler.modify_order(
        order.id, new_quantity=Decimal("2.0"), portfolio_id=harness.portfolio_id
    )
    assert ok
    events = [harness.queue.get() for _ in range(harness.queue.qsize())]
    order_events = [e for e in events if e.type.name == "ORDER"]
    assert len(order_events) == 1
    assert order_events[0].command is OrderCommand.MODIFY
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.quantity == Decimal("2.0")


def test_modify_price_only_on_partially_filled_order(harness):
    """CR-01 regression: a price-only modification (new_quantity=None) on a
    PARTIALLY_FILLED order must not TypeError on `None < filled_quantity`.

    add_fill is full-quantity-only now (D-06), so the PARTIALLY_FILLED state
    is staged directly — the status remains a valid transition target and the
    modify path must still handle it.
    """
    order = harness.rest_a_stop()
    order.filled_quantity = Decimal("0.5")
    assert order.add_state_change(
        OrderStatus.PARTIALLY_FILLED, "staged partial state", OrderTriggerSource.SYSTEM,
        time=_dt.datetime(2024, 1, 2),
    )
    harness.storage.update_order(order)
    assert order.status == OrderStatus.PARTIALLY_FILLED
    ok = harness.handler.modify_order(
        order.id, new_price=Decimal("28.0"), portfolio_id=harness.portfolio_id
    )
    assert ok
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.price == Decimal("28.0")


# --- reconciliation ---------------------------------------------------------


def test_executed_fill_marks_order_filled(harness):
    order = harness.rest_a_stop()
    harness.handler.on_fill(harness.fill(order, "EXECUTED"))
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.FILLED


def test_cancelled_fill_marks_order_cancelled(harness):
    order = harness.rest_a_stop()
    harness.handler.on_fill(harness.fill(order, "CANCELLED"))
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.CANCELLED


def test_partial_quantity_fill_is_rejected_by_mirror(harness):
    """Full-quantity contract (D-06, plan 06-04): the float-roundtrip clamp is
    deleted — a fill event whose quantity is below the order's remaining is
    rejected by add_fill and the mirror is left unchanged (warning logged)."""
    import dataclasses
    order = harness.rest_a_stop()  # quantity 1.0
    partial = dataclasses.replace(
        harness.fill(order, "EXECUTED"), quantity=Decimal("0.4")
    )
    harness.handler.on_fill(partial)
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.PENDING
    assert stored.filled_quantity == Decimal("0")


def test_full_precision_decimal_quantity_marks_filled(harness):
    """Decimal-native matching (D-12): a full fill carrying the order's own
    full-precision Decimal quantity reconciles to FILLED exactly — no float
    roundtrip exists anywhere on the path anymore."""
    import dataclasses
    order = harness.rest_a_stop()
    order.quantity = Decimal("0.123456789012345678901234567")
    order.filled_quantity = Decimal("0")
    harness.storage.update_order(order)
    full = dataclasses.replace(
        harness.fill(order, "EXECUTED"), quantity=order.quantity
    )
    harness.handler.on_fill(full)
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.FILLED
    assert stored.remaining_quantity == Decimal("0")


def test_unknown_order_id_is_safe(harness):
    # A fill for an order not in storage must not raise.
    import dataclasses
    order = harness.rest_a_stop()
    # Events are frozen (M3-01) — build the unknown-id variant via replace.
    fake = dataclasses.replace(harness.fill(order, "EXECUTED"), order_id=999999)
    harness.handler.on_fill(fake)  # should be a no-op, no exception
    assert harness.storage.get_order_by_id(999999, harness.portfolio_id) is None
    # The real order remains untouched (still active/PENDING).
    assert (
        harness.storage.get_order_by_id(order.id, harness.portfolio_id).status
        == OrderStatus.PENDING
    )


def test_refused_fill_marks_order_rejected(harness):
    # A REFUSED fill marks the order REJECTED (terminal) and removes it from the active book.
    order = harness.rest_a_stop()
    harness.handler.on_fill(harness.fill(order, "REFUSED"))
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.REJECTED
    active_ids = [o.id for o in harness.storage.get_active_orders(harness.portfolio_id)]
    assert order.id not in active_ids


# --- admission reservation gate (Plan 05-06, D-02/D-03/D-04) -----------------


class _FakeReadModel:
    """PortfolioReadModel-shaped fake recording reserve/release calls.

    Satisfies the runtime_checkable Protocol structurally (D-16) so it can
    stand in for PortfolioHandler at the OrderManager admission boundary.
    """

    def __init__(self, cash=Decimal("100000")):
        self._cash = cash
        self.reserve_calls = []
        self.release_calls = []
        self.fail_reserve = False

    def available_cash(self, portfolio_id):
        return self._cash

    def get_position(self, portfolio_id, ticker):
        return None

    def reserve(self, portfolio_id, order_id, amount):
        if self.fail_reserve:
            raise InsufficientFundsError(
                required_cash=float(amount), available_cash=float(self._cash)
            )
        self.reserve_calls.append((portfolio_id, order_id, amount))

    def release(self, portfolio_id, order_id):
        self.release_calls.append((portfolio_id, order_id))

    def exchange_for(self, portfolio_id):
        return "default"

    def open_position_count(self, portfolio_id):
        return 0


def _reserve_manager(read_model, commission_estimator=None):
    """OrderManager wired to the fake read model + its own in-memory storage."""
    storage = InMemoryOrderStorage()
    manager = OrderManager(
        storage,
        Mock(),
        market_execution="immediate",
        portfolio_handler=read_model,
        commission_estimator=commission_estimator,
    )
    return manager, storage


def _reserve_signal(action=Side.BUY, quantity=2.0, price=40.0,
                    stop_loss=0.0, take_profit=0.0):
    return SignalEvent(
        time=_dt.datetime(2024, 1, 1), order_type=OrderType.MARKET,
        ticker="BTCUSDT", action=action, price=price, quantity=quantity,
        stop_loss=stop_loss, take_profit=take_profit, strategy_id=1,
        portfolio_id=uuid.uuid4(),
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
    )


def test_buy_signal_reserves_cost_plus_estimated_commission():
    """A BUY reserves exactly price x quantity + estimated commission (D-02)."""
    read_model = _FakeReadModel()
    manager, storage = _reserve_manager(
        read_model, commission_estimator=lambda quantity, price: Decimal("1.5")
    )

    results = manager.process_signal(_reserve_signal())

    assert all(r.success for r in results)
    assert len(read_model.reserve_calls) == 1
    _, order_id, amount = read_model.reserve_calls[0]
    primary = storage.get_order_by_id(order_id)
    assert primary is not None
    assert amount == primary.price * primary.quantity + Decimal("1.5")
    # The order WAS emitted (OperationResult carries the OrderEvent).
    assert any(r.order_events for r in results)


def test_buy_reserve_failure_is_audited_rejected_and_emits_nothing():
    """Reserve failure -> stored PENDING->REJECTED audit, nothing emitted (D-02)."""
    read_model = _FakeReadModel()
    read_model.fail_reserve = True
    manager, storage = _reserve_manager(read_model)

    results = manager.process_signal(_reserve_signal())

    assert len(results) == 1
    assert not results[0].success
    assert not results[0].order_events  # nothing emitted
    rejected = storage.get_orders_by_status(OrderStatus.REJECTED)
    assert len(rejected) == 1
    last_change = rejected[0].get_latest_state_change()
    assert last_change is not None
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by is OrderTriggerSource.CASH_RESERVATION


def test_sell_signal_reserves_nothing():
    """SELL orders never reserve cash (D-03: cash-debiting orders only)."""
    read_model = _FakeReadModel()
    manager, _ = _reserve_manager(read_model)

    results = manager.process_signal(_reserve_signal(action=Side.SELL))

    assert all(r.success for r in results)
    assert read_model.reserve_calls == []


def test_bracket_children_reserve_nothing():
    """Only the cash-debiting primary reserves — SL/TP legs are exempt (D-03)."""
    read_model = _FakeReadModel()
    manager, storage = _reserve_manager(read_model)

    results = manager.process_signal(
        _reserve_signal(stop_loss=30.0, take_profit=55.0)
    )

    assert sum(1 for r in results if r.success) == 3  # primary + SL + TP
    assert len(read_model.reserve_calls) == 1  # exactly one reservation
    _, reserved_order_id, _ = read_model.reserve_calls[0]
    primary = storage.get_order_by_id(reserved_order_id)
    assert primary is not None
    assert primary.parent_order_id is None  # the reserved order IS the primary


def test_default_zero_commission_estimator_reserves_price_times_quantity():
    """With no estimator wired, reservation == price x quantity exactly (D-04)."""
    read_model = _FakeReadModel()
    manager, storage = _reserve_manager(read_model)  # estimator omitted -> 0

    manager.process_signal(_reserve_signal())

    assert len(read_model.reserve_calls) == 1
    _, order_id, amount = read_model.reserve_calls[0]
    primary = storage.get_order_by_id(order_id)
    assert amount == primary.price * primary.quantity


def test_refused_parent_cancels_orphaned_bracket_children():
    """WR-05 regression: when the parent of a bracket reconciles REFUSED
    without any fill, its SL/TP children are cancelled locally and CANCEL
    OrderEvents for them are returned (and enqueued by the handler) so the
    exchange removes the resting protective orders too."""
    read_model = _FakeReadModel()
    manager, storage = _reserve_manager(read_model)

    manager.process_signal(_reserve_signal(stop_loss=30.0, take_profit=55.0))
    primary = next(
        o for o in storage.get_active_orders() if o.parent_order_id is None
    )
    assert len(primary.child_order_ids) == 2

    cancel_events = manager.on_fill(_fill_for(primary, "REFUSED"))

    # Parent reconciled to REJECTED; both children cancelled locally.
    assert storage.get_order_by_id(primary.id).status == OrderStatus.REJECTED
    for child_id in primary.child_order_ids:
        assert storage.get_order_by_id(child_id).status == OrderStatus.CANCELLED
    # One CANCEL OrderEvent per child is returned for the exchange.
    assert len(cancel_events) == 2
    assert all(e.command is OrderCommand.CANCEL for e in cancel_events)
    assert sorted(e.order_id for e in cancel_events) == sorted(primary.child_order_ids)


def test_filled_parent_keeps_bracket_children_active(harness):
    """WR-05 guard: a parent that actually FILLED must NOT cancel its
    protective children — they are the exit legs of the open position."""
    harness.handler.on_signal(harness.signal(stop_loss=30.0, take_profit=55.0))
    while not harness.queue.empty():
        harness.queue.get_nowait()
    primary = next(
        o for o in harness.storage.get_active_orders(harness.portfolio_id)
        if o.parent_order_id is None
    )
    harness.handler.on_fill(harness.fill(primary, "EXECUTED"))
    assert (
        harness.storage.get_order_by_id(primary.id, harness.portfolio_id).status
        == OrderStatus.FILLED
    )
    for child_id in primary.child_order_ids:
        child = harness.storage.get_order_by_id(child_id, harness.portfolio_id)
        assert child.is_active


def test_local_cancel_releases_reservation():
    """WR-04 regression: cancel_order's local terminal transition releases the
    reservation directly — it must not depend on an exchange FillEvent(CANCELLED)
    that only arrives for orders actually resting in the matching engine."""
    read_model = _FakeReadModel()
    manager, storage = _reserve_manager(read_model)
    order = _rest_order(storage)

    result = manager.cancel_order(order.id, order.portfolio_id)

    assert result.success
    assert read_model.release_calls == [(order.portfolio_id, order.id)]


def test_failed_assembly_after_reserve_releases_reservation():
    """WR-03 regression: when bracket assembly/storage fails AFTER the
    admission reserve, no OrderEvent is emitted and no fill will ever arrive —
    the reservation must be released immediately or it leaks forever."""
    read_model = _FakeReadModel()
    manager, storage = _reserve_manager(read_model)

    def _boom(order):
        raise RuntimeError("storage write failed")

    storage.add_order = _boom  # assembly's add_order raises -> failure result

    results = manager.process_signal(_reserve_signal())

    assert len(read_model.reserve_calls) == 1
    _, reserved_order_id, _ = read_model.reserve_calls[0]
    # Nothing was emitted...
    assert not any(r.success and r.order_events for r in results)
    # ...and the orphaned reservation was released.
    assert read_model.release_calls == [
        (read_model.reserve_calls[0][0], reserved_order_id)
    ]


# --- terminal-state reservation release (Plan 05-06, D-01/OQ2) ---------------


def _rest_order(storage):
    order = Order.new_stop_order(
        time=_dt.datetime(2024, 1, 1), ticker="BTCUSDT", action="SELL",
        price=30.0, quantity=1.0, exchange="default", strategy_id=1,
        portfolio_id=uuid.uuid4(),
    )
    storage.add_order(order)
    return order


def _fill_for(order, status):
    oe = OrderEvent(
        time=_dt.datetime(2024, 1, 1), ticker=order.ticker, action=Side(order.action),
        price=float(order.price), quantity=float(order.quantity), exchange=order.exchange,
        strategy_id=order.strategy_id, portfolio_id=order.portfolio_id,
        order_type=OrderType.STOP, order_id=order.id,
    )
    return FillEvent.new_fill(status, oe, price=oe.price, quantity=oe.quantity, commission=0.0)


@pytest.mark.parametrize("status", ["EXECUTED", "CANCELLED", "REFUSED"])
def test_terminal_fill_releases_reservation(status):
    """Every terminal reconciliation releases the order's reservation (OQ2:
    the reserver owns the release — uniform across FILLED/CANCELLED/REJECTED)."""
    read_model = _FakeReadModel()
    manager, storage = _reserve_manager(read_model)
    order = _rest_order(storage)

    manager.on_fill(_fill_for(order, status))

    assert read_model.release_calls == [(order.portfolio_id, order.id)]


def test_rejected_add_fill_still_releases_reservation():
    """WR-02 regression: when the mirror transition is rejected (e.g. an
    EXECUTED fill arriving for an order already locally CANCELLED), the
    terminal release MUST still run — the portfolio has already settled the
    fill, so skipping the release would leave the reservation stuck forever."""
    read_model = _FakeReadModel()
    manager, storage = _reserve_manager(read_model)
    order = _rest_order(storage)
    assert order.cancel_order("local cancel before exchange ack")
    storage.update_order(order)

    manager.on_fill(_fill_for(order, "EXECUTED"))

    # add_fill was rejected (order already terminal) — mirror unchanged...
    stored = storage.get_order_by_id(order.id)
    assert stored.status == OrderStatus.CANCELLED
    # ...but the reservation release still happened.
    assert read_model.release_calls == [(order.portfolio_id, order.id)]


def test_release_on_never_reserved_sell_is_silent_noop(harness):
    """Releasing a never-reserved order (a SELL) is a silent idempotent no-op:
    no exception, no audit noise (CashManager records nothing for the no-op)."""
    order = harness.rest_a_stop()  # SELL stop — never reserved
    harness.handler.on_fill(harness.fill(order, "EXECUTED"))  # must not raise

    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.FILLED
    portfolio = harness.ptf_handler.get_portfolio(harness.portfolio_id)
    assert portfolio.cash_manager.reserved_balance == 0
    release_ops = [
        op for op in portfolio.cash_manager.get_cash_operations()
        if op.operation_type.name == "RELEASE_RESERVATION"
    ]
    assert release_ops == []
