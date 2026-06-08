from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import FillEvent, OrderEvent, SignalEvent
from itrader.core.enums import OrderType, OrderStatus, Side
from itrader.core.money import to_money
from itrader.core.sizing import (
    FixedQuantity,
    FractionOfCash,
    RiskPercent,
    TradingDirection,
)


_STRATEGY_ID = 1


class _OnSignalHarness:
    """OrderHandler harness with a single funded portfolio and a signal factory."""

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        # One portfolio per harness instance (per-test, like the legacy setUp).
        self.last_ptf_id = self.ptf_handler.add_portfolio(1, "test_ptf", "default", 10000)

    def create_mock_signal(
        self, action, ticker="BTCUSDT", quantity=100.0, price=40.0,
        order_type="MARKET", stop_loss=0.0, take_profit=0.0,
        sizing_policy=None, exit_fraction=Decimal("1"),
    ):
        """Create a mock signal for testing.

        ``quantity=None`` means "the order layer sizes me" (D-10) — the
        manager's SizingResolver dispatches on ``sizing_policy`` (D-01,
        wired by plan 07-05). The default policy mirrors the golden
        declaration ``FractionOfCash(Decimal("0.95"))`` (D-03).
        """
        return SignalEvent(
            time=datetime.now(),
            order_type=OrderType(order_type),
            ticker=ticker,
            action=Side(action),
            price=price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_id=_STRATEGY_ID,
            portfolio_id=self.last_ptf_id,
            sizing_policy=(
                sizing_policy if sizing_policy is not None
                else FractionOfCash(Decimal("0.95"))
            ),
            direction=TradingDirection.LONG_ONLY,
            allow_increase=False,
            exit_fraction=exit_fraction,
        )

    def open_long(self, quantity, price=40.0, ticker="BTCUSDT"):
        """Open a long position by filling an explicit-quantity BUY."""
        buy = self.create_mock_signal("BUY", ticker=ticker, quantity=quantity, price=price)
        self.order_handler.on_signal(buy)
        order_event: OrderEvent = self.queue.get(False)
        fill = FillEvent.new_fill(
            "EXECUTED", order_event,
            price=order_event.price, quantity=order_event.quantity,
            commission=0.0,
        )
        # Portfolio settles first (positions/cash), then the order mirror
        # reconciles and releases the admission reservation — the canonical
        # FILL dispatch order.
        self.ptf_handler.on_fill(fill)
        self.order_handler.on_fill(fill)
        return order_event


@pytest.fixture
def harness():
    h = _OnSignalHarness()
    yield h
    # Drain the queue after each test to prevent cross-test bleed.
    while not h.queue.empty():
        try:
            h.queue.get_nowait()
        except Exception:
            break


def test_on_signal_buy(harness):
    buy_signal = harness.create_mock_signal("BUY", quantity=100.0, price=40.0)

    harness.order_handler.on_signal(buy_signal)

    order_event: OrderEvent = harness.queue.get(False)

    assert isinstance(order_event, OrderEvent)
    assert order_event.ticker == "BTCUSDT"
    assert order_event.action is Side.BUY
    assert order_event.quantity == 100.0


def test_on_signal_sell(harness):
    sell_signal = harness.create_mock_signal("SELL", quantity=50.0, price=40.0)

    harness.order_handler.on_signal(sell_signal)

    order_event: OrderEvent = harness.queue.get(False)

    assert isinstance(order_event, OrderEvent)
    assert order_event.ticker == "BTCUSDT"
    assert order_event.action is Side.SELL
    assert order_event.quantity == 50.0


def test_on_signal_buy_with_sl_tp(harness):
    buy_signal = harness.create_mock_signal(
        "BUY", quantity=100.0, price=40.0, stop_loss=30.0, take_profit=50.0
    )

    harness.order_handler.on_signal(buy_signal)

    # Drain all 3 order events: MARKET (primary) + STOP (SL) + LIMIT (TP)
    emitted = [harness.queue.get(False) for _ in range(harness.queue.qsize())]
    order_events = [
        e for e in emitted if isinstance(e, OrderEvent) and e.type.name == "ORDER"
    ]
    # Find the primary MARKET order event
    primary_event = next(e for e in order_events if e.order_type == OrderType.MARKET)
    pending_orders = harness.order_storage.get_pending_orders()
    portfolio_orders = pending_orders.get(primary_event.portfolio_id, {})

    assert primary_event.ticker == "BTCUSDT"
    assert primary_event.action is Side.BUY
    assert primary_event.quantity == 100.0
    # All 3 legs emitted
    assert len(order_events) == 3
    # All 3 orders remain pending (market order is filled by execution handler, not self-filled)
    assert isinstance(pending_orders, dict)
    assert len(portfolio_orders) == 3  # MARKET, SL and TP orders all pending


def test_on_signal_sell_with_sl_tp(harness):
    sell_signal = harness.create_mock_signal(
        "SELL", quantity=50.0, price=40.0, stop_loss=30.0, take_profit=50.0
    )

    harness.order_handler.on_signal(sell_signal)

    # Drain all 3 order events: MARKET (primary) + STOP (SL) + LIMIT (TP)
    emitted = [harness.queue.get(False) for _ in range(harness.queue.qsize())]
    order_events = [
        e for e in emitted if isinstance(e, OrderEvent) and e.type.name == "ORDER"
    ]
    # Find the primary MARKET order event
    primary_event = next(e for e in order_events if e.order_type == OrderType.MARKET)
    pending_orders = harness.order_storage.get_pending_orders()
    portfolio_orders = pending_orders.get(primary_event.portfolio_id, {})

    assert primary_event.ticker == "BTCUSDT"
    assert primary_event.action is Side.SELL
    assert primary_event.quantity == 50.0
    # All 3 legs emitted
    assert len(order_events) == 3
    # All 3 orders remain pending (market order is filled by execution handler, not self-filled)
    assert isinstance(pending_orders, dict)
    assert len(portfolio_orders) == 3  # MARKET, SL and TP orders all pending


def test_rejected_signal_persists_audited_rejected_order(harness):
    """A signal failing validation leaves exactly one stored REJECTED order (D-13).

    The rejection is an audited FIX/Nautilus-style state change — it transitions
    the PENDING entity to REJECTED through add_state_change (triggered_by
    "validator", event-derived timestamp) and persists it; nothing is emitted.
    """
    # cost = 100 * 200 = 20000 > 10000 portfolio cash → INSUFFICIENT_CASH_COST.
    # SL/TP set: rejection must short-circuit BEFORE any child entity is built.
    signal = harness.create_mock_signal(
        "BUY", quantity=100.0, price=200.0, stop_loss=180.0, take_profit=220.0
    )

    harness.order_handler.on_signal(signal)

    # No OrderEvent reaches the execution handler
    assert harness.queue.empty()

    storage = harness.order_storage
    # Exactly one stored order for the ticker — the rejected primary; the
    # bracket children were never created (create-all-then-emit only runs
    # after acceptance).
    stored = storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
    assert len(stored) == 1
    rejected = stored[0]
    assert rejected.status == OrderStatus.REJECTED
    # Rejected orders never enter the active book
    assert storage.get_active_orders(harness.last_ptf_id) == []

    # Audited state change: PENDING → REJECTED, by the validator, stamped with
    # the signal's event time — never the wall clock (M2-09).
    last_change = rejected.get_latest_state_change()
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by == "validator"
    assert last_change.timestamp == signal.time


def test_bracket_two_directional_linkage_and_parent_first_emission(harness):
    """Brackets carry two-directional linkage and are emitted parent-first (D-11)."""
    signal = harness.create_mock_signal(
        "BUY", quantity=100.0, price=40.0, stop_loss=30.0, take_profit=50.0
    )

    harness.order_handler.on_signal(signal)

    emitted = [harness.queue.get(False) for _ in range(harness.queue.qsize())]
    order_events = [e for e in emitted if isinstance(e, OrderEvent)]
    assert len(order_events) == 3

    # Parent-first queue order: primary MARKET, then stop-loss STOP, then
    # take-profit LIMIT — identical to the pre-D-11 emit-per-creation sequence.
    assert [e.order_type for e in order_events] == [
        OrderType.MARKET, OrderType.STOP, OrderType.LIMIT
    ]

    parent_event, sl_event, tp_event = order_events
    # Children carry parent_order_id
    assert sl_event.parent_order_id == parent_event.order_id
    assert tp_event.parent_order_id == parent_event.order_id
    # The parent event carries both child ids (populated BEFORE emission)
    assert set(parent_event.child_order_ids) == {sl_event.order_id, tp_event.order_id}
    # Non-bracket children carry the empty tuple
    assert sl_event.child_order_ids == ()
    assert tp_event.child_order_ids == ()

    # The stored entities carry the same two-directional linkage
    storage = harness.order_storage
    stored_parent = storage.get_order_by_id(parent_event.order_id, harness.last_ptf_id)
    assert set(stored_parent.child_order_ids) == {sl_event.order_id, tp_event.order_id}
    for child_id in stored_parent.child_order_ids:
        child = storage.get_order_by_id(child_id, harness.last_ptf_id)
        assert child.parent_order_id == stored_parent.id


# ---------------------------------------------------------------------------
# Plan 07-05: typed sizing-policy resolution in the order layer (M5-06).
# The manager's SizingResolver dispatches on signal.sizing_policy; failures
# are audited REJECTED orders (D-06); the FractionOfCash arm is repr-exact
# against the legacy M1 expression (Pitfall 1, D-03).
# ---------------------------------------------------------------------------


def test_risk_percent_without_stop_is_audited_sizing_rejection(harness):
    """RiskPercent with no stop_loss: zero emitted orders, ONE stored REJECTED
    order with triggered_by == "sizing_policy" and a reason naming the policy
    (D-06 — sizing failures are loud, audited facts, never silent drops)."""
    signal = harness.create_mock_signal(
        "BUY", quantity=None, price=40.0,
        sizing_policy=RiskPercent(Decimal("0.01")),
    )

    harness.order_handler.on_signal(signal)

    # Nothing reaches the execution handler
    assert harness.queue.empty()

    stored = harness.order_storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
    assert len(stored) == 1
    rejected = stored[0]
    assert rejected.status == OrderStatus.REJECTED
    # Rejected-at-admission entities never enter the active book
    assert harness.order_storage.get_active_orders(harness.last_ptf_id) == []

    # Audited state change: PENDING -> REJECTED, by the sizing policy gate,
    # stamped with the signal's event time — never the wall clock (M2-09).
    last_change = rejected.get_latest_state_change()
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by == "sizing_policy"
    assert "RiskPercent" in last_change.reason
    assert last_change.timestamp == signal.time


def test_fraction_of_cash_quantity_is_repr_exact_against_legacy_expression(harness):
    """FractionOfCash(Decimal("0.95")) reproduces the legacy M1 expression
    (fraction * available_cash) / to_money(price) operand-for-operand —
    str() repr equality, not just numeric equality (Pitfall 1, D-03)."""
    price = 40.0
    # Read available cash through the read model BEFORE the signal is
    # processed (the BUY's admission reservation reduces it afterwards),
    # then compute the expected expression with the SAME operands.
    available = harness.ptf_handler.available_cash(harness.last_ptf_id)
    expected = (Decimal("0.95") * available) / to_money(price)

    signal = harness.create_mock_signal("BUY", quantity=None, price=price)
    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert str(order_event.quantity) == str(expected)


def test_fixed_quantity_policy_produces_declared_quantity(harness):
    """FixedQuantity(Decimal("2")) sizes the entry to exactly 2."""
    signal = harness.create_mock_signal(
        "BUY", quantity=None, price=40.0,
        sizing_policy=FixedQuantity(Decimal("2")),
    )

    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.quantity == Decimal("2")


def test_explicit_quantity_bypasses_policy_sizing(harness):
    """An explicit caller-supplied quantity is used as-is regardless of the
    declared policy (the preserved explicit-quantity path, D-07)."""
    signal = harness.create_mock_signal(
        "BUY", quantity=3.0, price=40.0,
        sizing_policy=FixedQuantity(Decimal("2")),
    )

    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.quantity == to_money(3.0)


def test_full_exit_sizes_to_position_net_quantity_repr_exact(harness):
    """SELL with an open long and exit_fraction Decimal("1") produces a
    quantity str-equal to the position's net_quantity — the D-07 structural
    no-op (no multiplication artifact, identical bytes to the M1 seam)."""
    harness.open_long(quantity=2.5, price=40.0)
    position = harness.ptf_handler.get_position(harness.last_ptf_id, "BTCUSDT")
    assert position is not None and position.net_quantity > 0

    sell = harness.create_mock_signal("SELL", quantity=None, price=40.0)
    harness.order_handler.on_signal(sell)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.SELL
    assert str(order_event.quantity) == str(position.net_quantity)


def test_partial_exit_sizes_to_exit_fraction_of_position(harness):
    """SELL with exit_fraction Decimal("0.5") closes exactly half the open
    position (resolver-sized partial exit, step_size None — no quantize)."""
    harness.open_long(quantity=2.5, price=40.0)
    position = harness.ptf_handler.get_position(harness.last_ptf_id, "BTCUSDT")
    assert position is not None and position.net_quantity > 0

    sell = harness.create_mock_signal(
        "SELL", quantity=None, price=40.0, exit_fraction=Decimal("0.5"),
    )
    harness.order_handler.on_signal(sell)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.SELL
    assert order_event.quantity == position.net_quantity * Decimal("0.5")
