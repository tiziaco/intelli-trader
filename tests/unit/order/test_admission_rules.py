"""Direction admission rules (D-08, plan 07-07 — test-with-code, D-24).

The OrderManager enforces the strategy's DECLARED TradingDirection at
admission, as step 0 of process_signal BEFORE sizing. The gate intercepts
exactly the RESEARCH Pitfall-4 fall-through: an unsized LONG_ONLY SELL with
no open long previously fell through to entry sizing and opened a short
(the 2 blessed golden shorts). Now it is an audited REJECTED order with
triggered_by == "admission_direction" — DEF-01-C dies structurally.

Preserved paths the gate must NOT block:
- LONG_ONLY SELL with an open long (the exit sizes and emits, unchanged)
- LONG_ONLY BUY (entries pass)
- LONG_SHORT signals (registration, not admission, polices LONG_SHORT)
- Explicit-quantity signals (the live/manual path skips the gate)
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import FillEvent, OrderEvent, SignalEvent
from itrader.core.enums import OrderType, OrderStatus, Side
from itrader.core.sizing import FractionOfCash, TradingDirection


_STRATEGY_ID = 1


class _AdmissionHarness:
    """OrderHandler harness with a single funded portfolio and a signal factory.

    Mirrors the test_on_signal harness, with a ``direction`` factory
    parameter so every TradingDirection arm of the D-08 gate is reachable.
    """

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        self.last_ptf_id = self.ptf_handler.add_portfolio(1, "test_ptf", "default", 10000)

    def create_mock_signal(
        self, action, ticker="BTCUSDT", quantity=None, price=40.0,
        order_type="MARKET", stop_loss=0.0, take_profit=0.0,
        direction=TradingDirection.LONG_ONLY, exit_fraction=Decimal("1"),
    ):
        """Create a mock signal. ``quantity=None`` means "the order layer
        sizes me" (D-10) — the unsized path the direction gate polices."""
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
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=direction,
            allow_increase=False,
            exit_fraction=exit_fraction,
        )

    def fill_next_order(self):
        """Pop the next OrderEvent off the queue and settle it as EXECUTED."""
        order_event: OrderEvent = self.queue.get(False)
        fill = FillEvent.new_fill(
            "EXECUTED", order_event,
            price=order_event.price, quantity=order_event.quantity,
            commission=0.0,
        )
        # Portfolio settles first (positions/cash), then the order mirror
        # reconciles — the canonical FILL dispatch order.
        self.ptf_handler.on_fill(fill)
        self.order_handler.on_fill(fill)
        return order_event

    def open_long(self, quantity, price=40.0, ticker="BTCUSDT"):
        """Open a long position by filling an explicit-quantity BUY."""
        buy = self.create_mock_signal("BUY", ticker=ticker, quantity=quantity, price=price)
        self.order_handler.on_signal(buy)
        return self.fill_next_order()


@pytest.fixture
def harness():
    h = _AdmissionHarness()
    yield h
    # Drain the queue after each test to prevent cross-test bleed.
    while not h.queue.empty():
        try:
            h.queue.get_nowait()
        except Exception:
            break


def _assert_audited_admission_rejection(harness, signal):
    """The Phase 4 audited-REJECTED template, for the direction gate."""
    stored = harness.order_storage.get_orders_by_ticker(signal.ticker, harness.last_ptf_id)
    assert len(stored) == 1
    rejected = stored[0]
    assert rejected.status == OrderStatus.REJECTED
    # Rejected-at-admission entities never enter the active book.
    assert harness.order_storage.get_active_orders(harness.last_ptf_id) == []
    # Audited state change: PENDING -> REJECTED, by the direction gate,
    # stamped with the signal's event time — never the wall clock (M2-09).
    last_change = rejected.get_latest_state_change()
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by == "admission_direction"
    assert "direction violation" in last_change.reason
    assert last_change.timestamp == signal.time
    return last_change


def test_long_only_unsized_sell_with_no_open_long_is_rejected(harness):
    """LONG_ONLY + unsized SELL + no open long: zero emitted orders, ONE
    stored REJECTED order naming the violation (the Pitfall-4 short-opening
    fall-through is gone — D-08, DEF-01-C dead)."""
    signal = harness.create_mock_signal("SELL")

    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    last_change = _assert_audited_admission_rejection(harness, signal)
    assert "LONG_ONLY" in last_change.reason


def test_long_only_unsized_sell_after_position_closed_is_rejected(harness):
    """LONG_ONLY + unsized SELL once the long is fully closed (net_quantity
    <= 0): rejected — a flat book never re-opens as a short."""
    harness.open_long(quantity=2.5, price=40.0)
    # Close the long completely with an explicit-quantity SELL.
    close = harness.create_mock_signal("SELL", quantity=2.5, price=40.0)
    harness.order_handler.on_signal(close)
    harness.fill_next_order()
    position = harness.ptf_handler.get_position(harness.last_ptf_id, "BTCUSDT")
    assert position is None or position.net_quantity <= 0

    sell = harness.create_mock_signal("SELL")
    harness.order_handler.on_signal(sell)

    assert harness.queue.empty()
    rejected = [
        o for o in harness.order_storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
        if o.status == OrderStatus.REJECTED
    ]
    assert len(rejected) == 1
    last_change = rejected[0].get_latest_state_change()
    assert last_change.triggered_by == "admission_direction"
    assert "LONG_ONLY" in last_change.reason
    assert last_change.timestamp == sell.time


def test_long_only_unsized_sell_with_open_long_sizes_the_exit(harness):
    """LONG_ONLY + unsized SELL + open long: passes the gate and the exit
    sizes to the position's net_quantity (closing behavior unchanged)."""
    harness.open_long(quantity=2.5, price=40.0)
    position = harness.ptf_handler.get_position(harness.last_ptf_id, "BTCUSDT")
    assert position is not None and position.net_quantity > 0

    sell = harness.create_mock_signal("SELL")
    harness.order_handler.on_signal(sell)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.SELL
    assert str(order_event.quantity) == str(position.net_quantity)


def test_long_only_unsized_buy_passes_the_gate(harness):
    """LONG_ONLY + BUY: passes the gate and sizes the entry."""
    signal = harness.create_mock_signal("BUY")

    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    assert order_event.quantity > 0


def test_short_only_unsized_buy_with_no_open_short_is_rejected(harness):
    """SHORT_ONLY + unsized BUY + no open short: rejected symmetrically
    (oracle-dark — the golden strategy is LONG_ONLY)."""
    signal = harness.create_mock_signal("BUY", direction=TradingDirection.SHORT_ONLY)

    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    last_change = _assert_audited_admission_rejection(harness, signal)
    assert "SHORT_ONLY" in last_change.reason


def test_long_short_direction_passes_the_gate(harness):
    """A LONG_SHORT-direction signal (e.g. from TradingInterface) passes the
    gate — registration, not admission, polices LONG_SHORT."""
    signal = harness.create_mock_signal("SELL", direction=TradingDirection.LONG_SHORT)

    harness.order_handler.on_signal(signal)

    # No open long: the SELL falls through to entry sizing — sanctioned for
    # LONG_SHORT — and emits.
    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.SELL
    assert order_event.quantity > 0


def test_explicit_quantity_sell_skips_the_direction_gate(harness):
    """Explicit-quantity signals pass the direction gate untouched — the
    preserved live/manual path (no open long required)."""
    signal = harness.create_mock_signal("SELL", quantity=1.5)

    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.SELL
    assert order_event.quantity == 1.5
