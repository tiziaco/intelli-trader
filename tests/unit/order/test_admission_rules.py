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
from itrader.core.enums import OrderType, OrderStatus, Side, OrderTriggerSource, PositionSide
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

    def open_short(self, quantity, price=40.0, ticker="BTCUSDT"):
        """Open a short position by filling an explicit-quantity SELL.

        Explicit quantity skips the direction gate, so the SELL reaches the
        fill regardless of direction — the resulting position carries
        net_quantity < 0 (the cover-arm fixture, SHORT-02)."""
        sell = self.create_mock_signal(
            "SELL", ticker=ticker, quantity=quantity, price=price,
            direction=TradingDirection.LONG_SHORT,
        )
        self.order_handler.on_signal(sell)
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
    assert last_change.triggered_by is OrderTriggerSource.ADMISSION_DIRECTION
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
    assert last_change.triggered_by is OrderTriggerSource.ADMISSION_DIRECTION
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


def test_short_only_unsized_sell_while_short_is_rejected_when_allow_increase_false(harness):
    """SCALE-01 (D-01): a SHORT_ONLY unsized SELL that ADDS to an open short is
    an audited admission rejection WHEN allow_increase=False — now conditional
    on the SAME flag that gates a long add, byte-symmetrically with the long
    gate (admission_manager.py:577-591). The mock signal defaults
    allow_increase=False, so this still rejects; the reason text now mirrors the
    long arm ("position increase not allowed by strategy") rather than the old
    unconditional "short increase out of v1 scope (D-09)" wording.

    Without the gate the SELL passed the direction gate (SHORT_ONLY+SELL is not
    policed), was not a reduction (SELL vs an open SHORT), and routed into
    resolve_entry — opening a fresh entry-sized lot on top of the short. The
    allow_increase=True admit path is proven in
    test_allow_increase_true_sizes_short_increase_on_remaining_cash_and_reserves."""
    harness.open_short(quantity=2.0, price=40.0)
    position = harness.ptf_handler.get_position(harness.last_ptf_id, "BTCUSDT")
    assert position is not None and position.side is PositionSide.SHORT
    assert harness.queue.empty()

    signal = harness.create_mock_signal(
        "SELL", direction=TradingDirection.SHORT_ONLY, allow_increase=False)
    harness.order_handler.on_signal(signal)

    # No order emitted — the short was NOT scaled by entry sizing.
    assert harness.queue.empty()
    last_change = _get_single_rejection(harness, "BTCUSDT")
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by is OrderTriggerSource.ADMISSION_INCREASE
    # The rejection is now BECAUSE allow_increase=False, not "always".
    assert "position increase not allowed by strategy" in last_change.reason
    assert "allow_increase=False" in last_change.reason
    assert last_change.timestamp == signal.time


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
    assert last_change.triggered_by is OrderTriggerSource.ADMISSION_INCREASE
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


# --- SCALE-01/SCALE-02 short scale-in: admit/reject + D-06 reserve (Plan 05.1-01)


def test_allow_increase_false_unsized_sell_while_short_is_rejected(harness):
    """SCALE-01 (D-01): allow_increase=False + unsized SELL + open short: zero
    emitted orders, ONE stored REJECTED order naming the violation. The exact
    SHORT-side mirror of test_allow_increase_false_unsized_buy_while_long_is_rejected
    — same gate, same reason text, swapping open_long->open_short, BUY->SELL."""
    harness.open_short(quantity=2.5, price=40.0)
    assert harness.queue.empty()

    signal = harness.create_mock_signal(
        "SELL", direction=TradingDirection.LONG_SHORT, allow_increase=False)
    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    last_change = _get_single_rejection(harness, "BTCUSDT")
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by is OrderTriggerSource.ADMISSION_INCREASE
    assert "position increase not allowed by strategy" in last_change.reason
    assert "allow_increase=False" in last_change.reason
    # Event-derived timestamp — never the wall clock (M2-09).
    assert last_change.timestamp == signal.time


def test_allow_increase_true_sizes_short_increase_on_remaining_cash_and_reserves(harness):
    """SCALE-01 + SCALE-02/D-06: allow_increase=True + unsized SELL + open short:
    the SELL-add is ADMITTED and sized via the policy on CURRENT remaining
    available_cash (FractionOfCash compounding semantics, D-04), proving it
    reached the direction-agnostic resolve_entry (SCALE-01).

    D-06 reserve-side correctness (criterion 4b): the admission check-and-reserve
    gate reserves ONLY for the cash-DEBITING primary, i.e. a BUY
    (admission_manager.py:259-264, D-03/T-05-15 — "SELLs and bracket SL/TP
    children are exempt: no OCO double-reservation"). A short SELL-add CREDITS
    cash, so it books NO admission-side cash reservation; its margin LOCK is a
    SETTLEMENT-side concern recomputed to aggregate_notional/leverage in
    portfolio.py:423-441 (Plan 05.1-02 owns that settlement-path portion of
    SCALE-02). The reserve-side correctness this admission-gate test proves is
    therefore the EXACT, non-vacuous fact that the admitted SELL-add reserves
    NOTHING extra at admission — available_cash is UNCHANGED across the admit
    (it neither over-reserves the SELL-side notional nor silently debits the
    short proceeds). This is the honest mirror of the long arm: the long BUY
    reserves price*qty because a BUY debits cash; the short SELL reserves zero
    because a SELL credits cash. (Verified against the live reserve path:
    admission_manager.py:264 gates the reservation on `primary.action is Side.BUY`.)"""
    harness.open_short(quantity=100, price=40.0)  # SELL proceeds credit balance
    remaining = harness.ptf_handler.available_cash(harness.last_ptf_id)
    # A short SELL credits proceeds (spot/collateralized basis, margin gate off
    # in this harness), so available_cash RISES above the starting balance —
    # the SELL-side counterpart of the long add's `remaining < 10000`.
    assert remaining > Decimal("10000")
    expected = (Decimal("0.95") * remaining) / to_money(40.0)

    signal = harness.create_mock_signal(
        "SELL", direction=TradingDirection.LONG_SHORT, allow_increase=True)
    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    # The SELL-add reached resolve_entry — it was sized, not rejected (SCALE-01).
    assert order_event.action is Side.SELL
    # The policy expression on REMAINING cash, repr-exact (Pitfall 1 shape) —
    # proves the SELL-add was sized by the SAME FractionOfCash arm as a long add.
    assert str(order_event.quantity) == str(expected)
    # D-06 reserve-side check (criterion 4b): the cash-CREDITING SELL primary
    # books NO admission-side reservation (D-03, admission_manager.py:264 reserves
    # only when `primary.action is Side.BUY`). available_cash is UNCHANGED across
    # the admit — NOT a vacuous >= 0 assert: it pins that the SELL-add neither
    # over-reserves the SELL-side notional nor debits the credited short proceeds.
    # The short's margin LOCK rides settlement (portfolio.py:423-441, Plan 05.1-02).
    reserved_available = harness.ptf_handler.available_cash(harness.last_ptf_id)
    assert reserved_available == remaining


def test_increase_with_insufficient_funds_yields_cash_reservation_rejection(harness):
    """An allowed increase that cannot be funded still produces the existing
    audited cash_reservation rejection — the sized increase is COVERED by the
    check-and-reserve gate, never bypassing it (T-07-21)."""
    harness.open_long(quantity=2.5, price=40.0)
    # Inflate the estimated commission so reserve = price*qty + commission
    # exceeds available cash (FractionOfCash <= 1 alone always fits). The
    # signal→order pipeline (and its _estimate_commission consumer) lives on
    # AdmissionManager since 06-03, so inject the fake estimator at its
    # canonical post-construction home.
    harness.order_handler.order_manager.admission_manager.commission_estimator = (
        lambda quantity, price: Decimal("1000000")
    )

    signal = harness.create_mock_signal("BUY", allow_increase=True)
    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    last_change = _get_single_rejection(harness, "BTCUSDT")
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by is OrderTriggerSource.CASH_RESERVATION


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
    assert last_change.triggered_by is OrderTriggerSource.ADMISSION_MAX_POSITIONS
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
    assert last_change.triggered_by is OrderTriggerSource.ADMISSION_INCREASE


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


# --- Plan 02-03 Task 2: leverage cap (D-04/D-05) + f>1 gate (D-07/LEV-02) ----


from itrader.core.instrument import Instrument
from itrader.core.sizing import LeveredFraction
from itrader.universe import Universe


def _make_universe(ticker, max_leverage):
    """Build a one-symbol Universe whose Instrument carries max_leverage.

    Only max_leverage matters here; the other fields are realistic-crypto
    placeholders (oracle-dark — this Universe is never wired into the golden run).
    """
    instr = Instrument(
        symbol=ticker,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=max_leverage,
    )
    return Universe(members=[ticker], instrument_map={ticker: instr})


def _admission(harness):
    return harness.order_handler.order_manager.admission_manager


def test_leverage_forced_one_when_margin_off(harness):
    """enable_margin=False → _effective_leverage returns Decimal("1") with NO
    instrument read (spot byte-exact). Even a Universe present and a high
    signal.leverage cannot lift it above 1."""
    am = _admission(harness)
    # Margin OFF (the harness default). A universe with a high cap is present,
    # but the spot arm must never consult it.
    am.set_universe(_make_universe("BTCUSDT", Decimal("50")))
    assert am._enable_margin is False

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("20"))

    assert am._effective_leverage(signal) == Decimal("1")


def test_leverage_forced_one_no_instrument_read(harness, monkeypatch):
    """Spot arm must NOT call universe.instrument() at all (D-04 no instrument
    read when margin off)."""
    am = _admission(harness)
    universe = _make_universe("BTCUSDT", Decimal("50"))

    def _boom(symbol):
        raise AssertionError("instrument() must not be read on the spot arm")

    monkeypatch.setattr(universe, "instrument", _boom)
    am.set_universe(universe)

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("20"))

    assert am._effective_leverage(signal) == Decimal("1")


def test_leverage_cap_is_min_of_signal_instrument_portfolio(harness):
    """enable_margin=True → effective = min(signal, instr.max_lev, pf.max_lev).
    With {signal 20, instr 10, pf 5} → 5 (D-04)."""
    am = _admission(harness)
    am._enable_margin = True
    am._portfolio_max_leverage = Decimal("5")
    am.set_universe(_make_universe("BTCUSDT", Decimal("10")))

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("20"))

    assert am._effective_leverage(signal) == Decimal("5")


def test_leverage_cap_logs_warning_when_clamped(harness):
    """requested > capped → a warning is logged AND the capped value returned
    (D-05 clamp, NOT reject)."""
    am = _admission(harness)
    am._enable_margin = True
    am._portfolio_max_leverage = Decimal("5")
    am.set_universe(_make_universe("BTCUSDT", Decimal("10")))

    warnings = []
    am.logger.warning = lambda *a, **k: warnings.append((a, k))  # type: ignore[method-assign]

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("20"))

    capped = am._effective_leverage(signal)
    assert capped == Decimal("5")
    assert len(warnings) == 1


def test_leverage_cap_no_warning_when_within_cap(harness):
    """requested <= cap → no clamp warning (D-05)."""
    am = _admission(harness)
    am._enable_margin = True
    am._portfolio_max_leverage = Decimal("10")
    am.set_universe(_make_universe("BTCUSDT", Decimal("10")))

    warnings = []
    am.logger.warning = lambda *a, **k: warnings.append((a, k))  # type: ignore[method-assign]

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("3"))

    assert am._effective_leverage(signal) == Decimal("3")
    assert warnings == []


def test_leverage_cap_instrument_cap_is_one_when_no_universe(harness):
    """enable_margin=True but no Universe → instrument cap degrades to
    Decimal("1") (D-04 None fallback)."""
    am = _admission(harness)
    am._enable_margin = True
    am._portfolio_max_leverage = Decimal("10")
    # No universe injected.
    assert am._universe is None

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("20"))

    assert am._effective_leverage(signal) == Decimal("1")


def test_levered_fraction_gate_rejects_f_gt_one_without_margin(harness):
    """A LeveredFraction(fraction>1) reaching admission with enable_margin=False
    → audited REJECTED via the existing audited path; NO order emitted, the
    audited entity is stored (LEV-02 / D-07)."""
    am = _admission(harness)
    assert am._enable_margin is False

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "sizing_policy", LeveredFraction(fraction=Decimal("2")))

    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    rejected = [
        o for o in harness.order_storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
        if o.status == OrderStatus.REJECTED
    ]
    assert len(rejected) == 1
    last_change = rejected[0].get_latest_state_change()
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by is OrderTriggerSource.ADMISSION_LEVERAGE
    assert harness.order_storage.get_active_orders(harness.last_ptf_id) == []


def test_levered_fraction_f_le_one_passes_the_gate_without_margin(harness):
    """A LeveredFraction(fraction<=1) is NOT blocked by the f>1 gate even with
    margin off — it sizes off total_equity and emits (the gate is f>1-only)."""
    am = _admission(harness)
    assert am._enable_margin is False

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "sizing_policy", LeveredFraction(fraction=Decimal("0.5")))

    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    assert order_event.quantity > 0


# --- Plan 02-03 Task 3: margin reservation branch (D-08/D-09) + over-margin ---


def _enable_margin(harness, max_leverage):
    """Flip the admission gate into margin mode with a Universe carrying the
    instrument cap, mirroring the compose-root wiring (which threads
    enable_margin into BOTH the admission reservation gate AND the validator so
    the validator defers its full-notional cash check to the reservation gate)."""
    am = _admission(harness)
    am._enable_margin = True
    am._portfolio_max_leverage = max_leverage
    # Mirror construction: the validator the AdmissionManager holds must also see
    # margin mode (compose threads enable_margin into both at construction).
    if am.order_validator is not None:
        am.order_validator.enable_margin = True
    am.set_universe(_make_universe("BTCUSDT", max_leverage))
    return am


def test_margin_reservation_is_notional_over_leverage(harness):
    """enable_margin=True → the admission reservation reserves
    notional / effective_leverage + commission (D-08 initial_margin), NOT the
    full notional. available_cash drops by exactly notional/L (commission 0)."""
    _enable_margin(harness, Decimal("5"))
    before = harness.ptf_handler.available_cash(harness.last_ptf_id)

    # Explicit quantity so notional is exact: 100 @ 40 = 4000; margin = 4000/5 = 800.
    signal = harness.create_mock_signal("BUY", quantity=100, price=40.0)
    object.__setattr__(signal, "leverage", Decimal("5"))
    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    after = harness.ptf_handler.available_cash(harness.last_ptf_id)
    notional = to_money(40.0) * to_money(100)
    expected_margin = notional / Decimal("5")
    assert before - after == expected_margin


def test_spot_reservation_reserves_full_notional(harness):
    """enable_margin=False (spot) → reservation == price*qty + commission, the
    full notional with NO division (Pitfall 4 — byte-exact)."""
    am = _admission(harness)
    assert am._enable_margin is False
    before = harness.ptf_handler.available_cash(harness.last_ptf_id)

    signal = harness.create_mock_signal("BUY", quantity=100, price=40.0)
    harness.order_handler.on_signal(signal)

    harness.queue.get(False)
    after = harness.ptf_handler.available_cash(harness.last_ptf_id)
    assert before - after == to_money(40.0) * to_money(100)


def test_over_margin_order_is_rejected_via_audited_path(harness):
    """enable_margin=True with initial_margin > free margin → audited REJECTED
    via the existing InsufficientFundsError path (MARGIN-02/D-01): no order
    emitted, no reservation recorded, audited REJECTED entity stored."""
    _enable_margin(harness, Decimal("2"))
    before = harness.ptf_handler.available_cash(harness.last_ptf_id)

    # notional = 1000 @ 40 = 40000; margin = 40000/2 = 20000 > 10000 free.
    signal = harness.create_mock_signal("BUY", quantity=1000, price=40.0)
    object.__setattr__(signal, "leverage", Decimal("2"))
    harness.order_handler.on_signal(signal)

    assert harness.queue.empty()
    rejected = [
        o for o in harness.order_storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
        if o.status == OrderStatus.REJECTED
    ]
    assert len(rejected) == 1
    last_change = rejected[0].get_latest_state_change()
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by is OrderTriggerSource.CASH_RESERVATION
    # No reservation recorded — free cash intact.
    assert harness.ptf_handler.available_cash(harness.last_ptf_id) == before


def test_margin_makes_otherwise_unaffordable_order_affordable(harness):
    """An order whose FULL notional exceeds free cash is fundable under leverage
    because only notional/L is reserved (the point of margin)."""
    _enable_margin(harness, Decimal("10"))

    # notional = 500 @ 40 = 20000 > 10000 free; margin = 20000/10 = 2000 <= 10000.
    signal = harness.create_mock_signal("BUY", quantity=500, price=40.0)
    object.__setattr__(signal, "leverage", Decimal("10"))
    harness.order_handler.on_signal(signal)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    assert order_event.quantity == 500


# --- Plan 02-08 (CR-01 / LEV-03): LIMIT/STOP arms thread effective leverage ---


def test_build_primary_market_order_carries_clamped_leverage(harness):
    """Baseline: the MARKET arm already threads the CLAMPED effective leverage
    onto the Order (signal 20, instr/pf cap 5 → 5)."""
    am = _enable_margin(harness, Decimal("5"))
    signal = harness.create_mock_signal("BUY", quantity=100, price=40.0,
                                        order_type="MARKET")
    object.__setattr__(signal, "leverage", Decimal("20"))

    order = am._build_primary_order(signal, "binance", Decimal("100"))
    assert order.type is OrderType.MARKET
    assert order.leverage == Decimal("5")


def test_build_primary_limit_order_carries_clamped_leverage(harness):
    """CR-01: the LIMIT arm must thread the CLAMPED effective leverage onto the
    Order entity (so position-life locked margin == admission reservation), not
    silently default to Decimal('1')."""
    am = _enable_margin(harness, Decimal("5"))
    signal = harness.create_mock_signal("BUY", quantity=100, price=40.0,
                                        order_type="LIMIT")
    object.__setattr__(signal, "leverage", Decimal("20"))

    order = am._build_primary_order(signal, "binance", Decimal("100"))
    assert order.type is OrderType.LIMIT
    assert order.leverage == Decimal("5")


def test_build_primary_stop_order_carries_clamped_leverage(harness):
    """CR-01: the STOP arm must thread the CLAMPED effective leverage onto the
    Order entity, mirroring the MARKET/LIMIT arms."""
    am = _enable_margin(harness, Decimal("5"))
    signal = harness.create_mock_signal("BUY", quantity=100, price=40.0,
                                        order_type="STOP")
    object.__setattr__(signal, "leverage", Decimal("20"))

    order = am._build_primary_order(signal, "binance", Decimal("100"))
    assert order.type is OrderType.STOP
    assert order.leverage == Decimal("5")


# ---------------------------------------------------------------------------
# Phase 3 Wave 0 stubs (SHORT-02 / WR-04) — collectible RED placeholders.
# Seeded by Plan 03-02 so the Plan 03-04 verify selectors
# (`cover_arm`, `over_cover_clamp`, `leverage_floor`) each select >=1 test
# BEFORE any production code is written (the Nyquist contract, D-10). These
# assert NOTHING yet — Plan 03-04 turns them green.
# ---------------------------------------------------------------------------


def test_cover_arm_buy_on_open_short_routes_through_resolve_exit(harness):
    """SHORT-02/D-05: a BUY-to-cover on an open short (net_quantity < 0) routes
    through the side-agnostic exit and sizes the reduction to the position
    magnitude — it does NOT fall into entry sizing and flip the book long.

    Before the fix the cover BUY failed the `SELL and net>0` predicate and fell
    into entry sizing, sizing 0.95*available_cash / price (a NEW long) — the
    CR-01 hole. After the fix it returns abs(net_quantity) = 2.0."""
    harness.open_short(quantity=2.0, price=40.0)
    position = harness.ptf_handler.get_position(harness.last_ptf_id, "BTCUSDT")
    # The order-boundary read-model carries an UNSIGNED magnitude + a `side`
    # discriminator (PositionView.net_quantity == abs(...) >= 0); SHORT is in
    # `side`, never a negative net_quantity.
    assert position is not None and position.side is PositionSide.SHORT
    assert position.net_quantity == Decimal("2.0")

    cover = harness.create_mock_signal(
        "BUY", direction=TradingDirection.LONG_SHORT, exit_fraction=Decimal("1"),
    )
    harness.order_handler.on_signal(cover)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    # The cover sizes to the FULL short magnitude (clamp-to-flat at fraction 1),
    # not the entry-sizing fraction-of-cash quantity.
    assert order_event.quantity == abs(position.net_quantity)
    assert order_event.quantity == Decimal("2")


def test_cover_arm_sell_on_open_long_is_byte_exact(harness):
    """SHORT-02/A2: the long-exit path stays byte-exact under the generalized
    predicate — a SELL on an open long sizes to the SAME net_quantity it did
    before the change (abs() is identity for net>0)."""
    harness.open_long(quantity=2.5, price=40.0)
    position = harness.ptf_handler.get_position(harness.last_ptf_id, "BTCUSDT")
    assert position is not None and position.net_quantity > 0

    sell = harness.create_mock_signal("SELL")
    harness.order_handler.on_signal(sell)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.SELL
    # Byte-exact: the SELL-on-long exit quantity is the position net_quantity,
    # repr-identical (str compare, not just ==).
    assert str(order_event.quantity) == str(position.net_quantity)


def test_over_cover_clamp_buy_clamps_to_short_magnitude(harness):
    """SHORT-02/D-06: a BUY-cover with exit_fraction == 1 on an open short
    clamps to EXACTLY abs(net_quantity) — the cover closes to flat and the
    excess does NOT auto-open a long. resolve_exit returns at most the full
    magnitude, so a full-close cover can never exceed the open short."""
    harness.open_short(quantity=1.5, price=40.0)
    position = harness.ptf_handler.get_position(harness.last_ptf_id, "BTCUSDT")
    assert position is not None and position.side is PositionSide.SHORT
    assert position.net_quantity == Decimal("1.5")

    cover = harness.create_mock_signal(
        "BUY", direction=TradingDirection.LONG_SHORT, exit_fraction=Decimal("1"),
    )
    harness.order_handler.on_signal(cover)

    order_event: OrderEvent = harness.queue.get(False)
    assert order_event.action is Side.BUY
    # Clamped to flat: the cover quantity equals the short magnitude exactly,
    # never more (no auto-opened long from the excess).
    assert order_event.quantity == abs(position.net_quantity)
    assert order_event.quantity <= abs(position.net_quantity)


def test_leverage_floor_zero_instrument_cap_floors_at_one(harness):
    """WR-04/D-09: a misconfigured Instrument.max_leverage of Decimal("0")
    yields an effective leverage floored at Decimal("1") — never sub-1, never
    a downstream divide-by-zero."""
    am = _admission(harness)
    am._enable_margin = True
    am._portfolio_max_leverage = Decimal("10")
    am.set_universe(_make_universe("BTCUSDT", Decimal("0")))

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("5"))

    assert am._effective_leverage(signal) == Decimal("1")


def test_leverage_floor_sub_one_instrument_cap_floors_at_one(harness):
    """WR-04/D-09: a sub-1 instrument cap (e.g. 0.5) also floors at 1 — the
    floor guards every cap below 1, not just exactly 0."""
    am = _admission(harness)
    am._enable_margin = True
    am._portfolio_max_leverage = Decimal("10")
    am.set_universe(_make_universe("BTCUSDT", Decimal("0.5")))

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("5"))

    assert am._effective_leverage(signal) == Decimal("1")


def test_leverage_floor_normal_cap_unaffected(harness):
    """WR-04: a normal cap is unaffected by the floor — min(signal, instr, pf)
    still applies above 1. {signal 20, instr 5, pf 10} → 5 (the floor never
    lifts a legitimately-capped value)."""
    am = _admission(harness)
    am._enable_margin = True
    am._portfolio_max_leverage = Decimal("10")
    am.set_universe(_make_universe("BTCUSDT", Decimal("5")))

    signal = harness.create_mock_signal("BUY")
    object.__setattr__(signal, "leverage", Decimal("20"))

    assert am._effective_leverage(signal) == Decimal("5")
