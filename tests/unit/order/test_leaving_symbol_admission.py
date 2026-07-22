"""Leaving-symbol admission gate (D-01 remove policy — block new entries).

Plan 06-04 Task 1. The remove-policy consumer marks a removed-but-still-held
symbol as "leaving" on the injected ``Universe``; the FIRST admission gate
(``_enforce_leaving_symbol_admission``, before the direction gate) reads
``Universe.leaving_symbols()`` and:

- BLOCKS a NEW entry (audited REJECTED, triggered_by == ADMISSION_LEAVING) so
  a leaving symbol never opens fresh exposure while it is being wound down, and
- PASSES a sanctioned EXIT (SELL against an open LONG / BUY against an open
  SHORT) so the orphaned position can still go flat (its stop/exit fires).

Preserved no-op paths the gate must not touch:
- A ticker NOT in the leaving set (normal admission).
- An explicit-quantity signal (the live/manual path skips every gate).
- A construction with no injected universe (backtest / no-universe).

The gate runs FIRST, so even a signal that would trip the direction gate is
intercepted with ADMISSION_LEAVING when the symbol is leaving.
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import FillEvent, OrderEvent, SignalEvent
from itrader.core.enums import OrderType, OrderStatus, Side, OrderTriggerSource
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.universe.universe import Universe
from tests.support.venue_wiring import backtest_portfolio_handler

pytestmark = pytest.mark.unit


_STRATEGY_ID = 1


class _LeavingHarness:
    """OrderHandler harness with a funded portfolio + an injectable Universe.

    Mirrors ``test_admission_rules._AdmissionHarness`` but injects a real
    ``Universe`` (so ``leaving_symbols()`` is live) through the
    ``OrderHandler.set_universe`` → ``OrderManager`` → ``AdmissionManager`` seam.
    """

    def __init__(self, ticker: str = "BTCUSDT"):
        self.queue = Queue()
        self.ptf_handler = backtest_portfolio_handler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        self.last_ptf_id = self.ptf_handler.add_portfolio("test_ptf", "default", 10000)
        # A real Universe holding the single ticker — spot, no margin read.
        self.universe = Universe(members=[ticker], instrument_map={})

    def inject_universe(self) -> None:
        """Wire the Universe into the admission gate (Trap-4 late seam)."""
        self.order_handler.set_universe(self.universe)

    def create_mock_signal(
        self, action, ticker="BTCUSDT", quantity=None, price=40.0,
        order_type="MARKET", stop_loss=0.0, take_profit=0.0,
        direction=TradingDirection.LONG_ONLY, exit_fraction=Decimal("1"),
    ):
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
            exit_fraction=exit_fraction,
        )

    def fill_next_order(self):
        order_event: OrderEvent = self.queue.get(False)
        fill = FillEvent.new_fill(
            "EXECUTED", order_event,
            price=order_event.price, quantity=order_event.quantity,
            commission=0.0,
        )
        self.ptf_handler.on_fill(fill)
        self.order_handler.on_fill(fill)
        return order_event

    def open_long(self, quantity, price=40.0, ticker="BTCUSDT"):
        buy = self.create_mock_signal("BUY", ticker=ticker, quantity=quantity, price=price)
        self.order_handler.on_signal(buy)
        return self.fill_next_order()


@pytest.fixture
def harness():
    h = _LeavingHarness()
    yield h
    while not h.queue.empty():
        try:
            h.queue.get_nowait()
        except Exception:
            break


def _stored_rejection(harness, ticker):
    stored = harness.order_storage.get_orders_by_ticker(ticker, harness.last_ptf_id)
    rejected = [o for o in stored if o.status == OrderStatus.REJECTED]
    assert len(rejected) == 1
    return rejected[0]


# --- behavior 1: the enum member exists + parses case-insensitively ---------


def test_admission_leaving_enum_parses_case_insensitive():
    """OrderTriggerSource('admission_leaving') resolves to ADMISSION_LEAVING."""
    assert OrderTriggerSource("admission_leaving") is OrderTriggerSource.ADMISSION_LEAVING
    assert OrderTriggerSource("ADMISSION_LEAVING") is OrderTriggerSource.ADMISSION_LEAVING


# --- behavior 2: a non-leaving ticker passes the gate -----------------------


def test_non_leaving_symbol_new_entry_passes(harness):
    """A BUY entry for a ticker NOT in the leaving set emits normally."""
    harness.inject_universe()  # nothing marked leaving
    harness.order_handler.on_signal(harness.create_mock_signal("BUY"))
    order = harness.queue.get(False)
    assert isinstance(order, OrderEvent)
    assert order.action is Side.BUY


# --- behavior 3: a NEW entry for a leaving symbol is audited-REJECTED --------


def test_leaving_symbol_new_entry_buy_rejected(harness):
    """A BUY entry for a leaving symbol is audited-REJECTED (ADMISSION_LEAVING)."""
    harness.inject_universe()
    harness.universe.mark_leaving("BTCUSDT")

    harness.order_handler.on_signal(harness.create_mock_signal("BUY"))

    assert harness.queue.empty()  # no OrderEvent emitted
    rejected = _stored_rejection(harness, "BTCUSDT")
    change = rejected.get_latest_state_change()
    assert change.to_status is OrderStatus.REJECTED
    assert change.triggered_by is OrderTriggerSource.ADMISSION_LEAVING
    assert "leaving symbol" in change.reason


def test_leaving_symbol_gate_runs_first(harness):
    """A SELL new-entry for a leaving symbol trips ADMISSION_LEAVING, not the
    direction gate — proving the leaving gate runs FIRST."""
    harness.inject_universe()
    harness.universe.mark_leaving("BTCUSDT")

    harness.order_handler.on_signal(harness.create_mock_signal("SELL"))

    rejected = _stored_rejection(harness, "BTCUSDT")
    change = rejected.get_latest_state_change()
    assert change.triggered_by is OrderTriggerSource.ADMISSION_LEAVING


# --- behavior 4: a sanctioned EXIT for a leaving symbol PASSES ---------------


def test_leaving_symbol_exit_sell_passes(harness):
    """A SELL exit against an open LONG for a leaving symbol PASSES (goes flat)."""
    harness.inject_universe()
    harness.open_long(Decimal("10"))
    harness.universe.mark_leaving("BTCUSDT")

    harness.order_handler.on_signal(harness.create_mock_signal("SELL"))

    order = harness.queue.get(False)
    assert isinstance(order, OrderEvent)
    assert order.action is Side.SELL
    # No admission rejection was stored for this exit.
    stored = harness.order_storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
    assert not any(
        o.status == OrderStatus.REJECTED
        and o.get_latest_state_change().triggered_by is OrderTriggerSource.ADMISSION_LEAVING
        for o in stored
    )


# --- behavior 5: an explicit-quantity signal skips the gate -----------------


def test_leaving_symbol_explicit_quantity_skips_gate(harness):
    """An explicit-quantity BUY for a leaving symbol skips the gate (manual path)."""
    harness.inject_universe()
    harness.universe.mark_leaving("BTCUSDT")

    harness.order_handler.on_signal(
        harness.create_mock_signal("BUY", quantity=Decimal("5"))
    )

    order = harness.queue.get(False)
    assert isinstance(order, OrderEvent)
    assert order.action is Side.BUY


# --- behavior 6: no injected universe is a no-op -----------------------------


def test_no_universe_is_noop(harness):
    """With no injected universe the gate is a no-op — a BUY entry emits."""
    # Deliberately DO NOT call inject_universe().
    harness.order_handler.on_signal(harness.create_mock_signal("BUY"))
    order = harness.queue.get(False)
    assert isinstance(order, OrderEvent)
    assert order.action is Side.BUY
