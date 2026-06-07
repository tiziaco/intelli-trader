"""Admission rules (D-08 direction, D-10 increase, max_positions — D-24 test-with-code).

The OrderManager enforces the strategy's DECLARED constraints at admission,
as step 0 of process_signal BEFORE sizing:

- Direction gate (D-08, plan 07-07): an unsized LONG_ONLY SELL with no open
  long previously fell through to entry sizing and opened a short (the 2
  blessed golden shorts — RESEARCH Pitfall 4). Now it is an audited REJECTED
  order with triggered_by == "admission_direction" — DEF-01-C dies
  structurally.
- Increase gate (D-10, plan 07-08): allow_increase=False + unsized
  BUY-while-long is an audited REJECTED order with
  triggered_by == "admission_increase" — SMA_MACD's declared-but-ignored
  False is finally honest. allow_increase=True sizes the increase by policy
  on CURRENT remaining available cash and flows through the Phase 5
  check-and-reserve gate (the literal M5-06 check_cash requirement).
- max_positions gate (plan 07-08, oracle-dark): an unsized BUY opening a
  NEW position when open_position_count >= max_positions is an audited
  REJECTED order with triggered_by == "admission_max_positions". A BUY for
  an already-open ticker is the increase case, never this one (no
  double-gating).

Preserved paths the gates must NOT block:
- LONG_ONLY SELL with an open long (the exit sizes and emits, unchanged)
- LONG_ONLY BUY first entries (sized exactly as before — byte-exactness of
  the post-07-07 reference depends on it when N=0)
- LONG_SHORT signals (registration, not admission, polices LONG_SHORT)
- Explicit-quantity signals (the live/manual path skips every gate)
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
from itrader.core.money import to_money
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
        allow_increase=False, max_positions=1,
    ):
        """Create a mock signal. ``quantity=None`` means "the order layer
        sizes me" (D-10) — the unsized path the admission gates police."""
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
            allow_increase=allow_increase,
            max_positions=max_positions,
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


# --- D-10 increase gate + max_positions gate (plan 07-08) -------------------


def _get_single_rejection(harness, ticker):
    """Return the latest state change of the ONE REJECTED order for ticker.

    Unlike the direction helper above, the increase/max_positions scenarios
    store prior FILLED orders for the harness positions — filter to the
    REJECTED entity instead of asserting the whole book."""
    rejected = [
        o for o in harness.order_storage.get_orders_by_ticker(ticker, harness.last_ptf_id)
        if o.status == OrderStatus.REJECTED
    ]
    assert len(rejected) == 1
    # Rejected-at-admission entities never enter the active book.
    assert all(
        o.status != OrderStatus.REJECTED
        for o in harness.order_storage.get_active_orders(harness.last_ptf_id)
    )
    return rejected[0].get_latest_state_change()


def test_allow_increase_false_unsized_buy_while_long_is_rejected(harness):
    """allow_increase=False + unsized BUY + open long: zero emitted orders,
    ONE stored REJECTED order naming the violation (D-10 — SMA_MACD's
    declared-but-ignored False is finally honest)."""
    harness.open_long(quantity=2.5, price=40.0)
    assert harness.queue.empty()

    signal = harness.create_mock_signal("BUY", allow_increase=False)
    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    last_change = _get_single_rejection(harness, "BTCUSDT")
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by == "admission_increase"
    assert "position increase not allowed by strategy" in last_change.reason
    # Event-derived timestamp — never the wall clock (M2-09).
    assert last_change.timestamp == signal.time


def test_allow_increase_true_sizes_increase_on_remaining_cash_and_reserves(harness):
    """allow_increase=True + unsized BUY + open long: sized via the policy on
    CURRENT remaining available_cash (fraction-of-remaining semantics — the
    CONTEXT discretion clause) and reserved through the Phase 5
    check-and-reserve gate (the literal M5-06 check_cash requirement)."""
    harness.open_long(quantity=100, price=40.0)  # 4000 spent of 10000
    remaining = harness.ptf_handler.available_cash(harness.last_ptf_id)
    assert remaining < Decimal("10000")
    expected = (Decimal("0.95") * remaining) / to_money(40.0)

    signal = harness.create_mock_signal("BUY", allow_increase=True)
    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    # The policy expression on REMAINING cash, repr-exact (Pitfall 1 shape).
    assert str(order_event.quantity) == str(expected)
    # The increase flowed through check-and-reserve: buying power dropped by
    # exactly the reservation amount (price x quantity, zero commission).
    reserved_available = harness.ptf_handler.available_cash(harness.last_ptf_id)
    assert reserved_available == remaining - to_money(40.0) * expected


def test_increase_with_insufficient_funds_yields_cash_reservation_rejection(harness):
    """An allowed increase that cannot be funded still produces the existing
    audited cash_reservation rejection — the sized increase is COVERED by the
    check-and-reserve gate, never bypassing it (T-07-21)."""
    harness.open_long(quantity=2.5, price=40.0)
    # Inflate the estimated commission so reserve = price*qty + commission
    # exceeds available cash (FractionOfCash <= 1 alone always fits).
    harness.order_handler.order_manager.commission_estimator = (
        lambda quantity, price: Decimal("1000000")
    )

    signal = harness.create_mock_signal("BUY", allow_increase=True)
    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    last_change = _get_single_rejection(harness, "BTCUSDT")
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by == "cash_reservation"


def test_first_entry_is_untouched_by_the_new_gates(harness):
    """A no-position first entry sizes EXACTLY as before — quantity str-equal
    to the policy expression on available cash (byte-exactness of the
    post-07-07 reference depends on this when N=0)."""
    available = harness.ptf_handler.available_cash(harness.last_ptf_id)
    expected = (Decimal("0.95") * available) / to_money(40.0)

    signal = harness.create_mock_signal("BUY", allow_increase=False, max_positions=1)
    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    assert str(order_event.quantity) == str(expected)


def test_max_positions_rejects_new_ticker_entry_at_the_limit(harness):
    """max_positions=1 + unsized BUY for a NEW ticker while another ticker's
    position is open: audited REJECTED, triggered_by admission_max_positions
    (oracle-dark — the golden run is single-ticker)."""
    harness.open_long(quantity=2.5, price=40.0, ticker="BTCUSDT")
    assert harness.ptf_handler.open_position_count(harness.last_ptf_id) == 1

    signal = harness.create_mock_signal("BUY", ticker="ETHUSDT", max_positions=1)
    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    last_change = _get_single_rejection(harness, "ETHUSDT")
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by == "admission_max_positions"
    assert last_change.timestamp == signal.time


def test_max_positions_allows_new_entry_under_the_limit(harness):
    """max_positions=2 with one open position: a new-ticker entry passes the
    gate and sizes (no over-rejection, T-07-22)."""
    harness.open_long(quantity=2.5, price=40.0, ticker="BTCUSDT")

    signal = harness.create_mock_signal("BUY", ticker="ETHUSDT", max_positions=2)
    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    assert order_event.ticker == "ETHUSDT"
    assert order_event.quantity > 0


def test_buy_for_open_ticker_is_the_increase_case_not_max_positions(harness):
    """A BUY for the already-open ticker trips the increase gate, never the
    max_positions gate — a signal trips at most ONE gate (no double-gating)."""
    harness.open_long(quantity=2.5, price=40.0)
    assert harness.ptf_handler.open_position_count(harness.last_ptf_id) == 1

    signal = harness.create_mock_signal("BUY", allow_increase=False, max_positions=1)
    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    last_change = _get_single_rejection(harness, "BTCUSDT")
    assert last_change.triggered_by == "admission_increase"


def test_explicit_quantity_buy_skips_increase_and_max_positions_gates(harness):
    """Explicit-quantity signals skip BOTH new gates — the preserved
    live/manual path (open long, allow_increase=False, max_positions=1)."""
    harness.open_long(quantity=2.5, price=40.0)

    signal = harness.create_mock_signal(
        "BUY", quantity=1.0, allow_increase=False, max_positions=1)
    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    assert order_event.quantity == 1.0
