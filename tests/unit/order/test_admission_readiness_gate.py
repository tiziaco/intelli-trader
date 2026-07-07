"""PRIMARY WR-02 readiness admission gate (D-01 — block trading a non-READY symbol).

Plan 07-08 Task 1. The PRIMARY readiness gate (`_enforce_readiness_admission`,
the SECOND admission gate — after leaving, before direction) reads
`Universe.is_ready(ticker)` and:

- BLOCKS a NEW unsized entry for a still-PENDING / FAILED symbol (audited
  REJECTED, triggered_by == ADMISSION_READINESS) so an externally-injected
  signal that BYPASSES the strategy-loop SECONDARY check (Plan 07-04) can never
  size a live order for an unwarmed symbol, and
- PASSES a sanctioned EXIT (SELL against an open LONG / BUY against an open
  SHORT) so a winding-down orphan with stale readiness can still go flat.

Preserved no-op paths the gate must not touch:
- A READY ticker (normal admission).
- An explicit-quantity signal (the live/manual path skips every gate).
- A construction with no injected universe (backtest / no-universe): oracle-dark.

This mirrors ``test_leaving_symbol_admission.py``: build an ``OrderHandler`` with
a funded portfolio and inject a REAL ``Universe`` (a construction READY member +
an ``apply``-added PENDING symbol) via ``OrderHandler.set_universe``. The PENDING
signal is injected DIRECTLY into ``on_signal`` (bypassing the strategy loop) to
prove the PRIMARY gate stops a strategy-loop-bypassing injection.
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import FillEvent, OrderEvent, SignalEvent
from itrader.core.enums import OrderType, OrderStatus, Side, OrderTriggerSource
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.universe.universe import Universe

pytestmark = pytest.mark.unit


_STRATEGY_ID = 1
_READY_TICKER = "BTCUSDT"
_PENDING_TICKER = "ETHUSDT"


class _ReadinessHarness:
    """OrderHandler harness with a funded portfolio + an injectable Universe.

    Mirrors ``test_leaving_symbol_admission._LeavingHarness`` but the injected
    ``Universe`` carries a construction-time READY member plus an ``apply``-added
    PENDING symbol, so ``is_ready`` is live through the
    ``OrderHandler.set_universe`` → ``OrderManager`` → ``AdmissionManager`` seam.
    """

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        self.last_ptf_id = self.ptf_handler.add_portfolio("test_ptf", "default", 10000)
        # A real Universe: BTCUSDT is a construction member (READY); ETHUSDT is
        # apply-added and therefore PENDING until an explicit mark_ready.
        self.universe = Universe(members=[_READY_TICKER], instrument_map={})
        self.universe.apply({_READY_TICKER, _PENDING_TICKER})

    def inject_universe(self) -> None:
        """Wire the Universe into the admission gate (Trap-4 late seam)."""
        self.order_handler.set_universe(self.universe)

    def create_mock_signal(
        self, action, ticker=_READY_TICKER, quantity=None, price=40.0,
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


@pytest.fixture
def harness():
    h = _ReadinessHarness()
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


def test_admission_readiness_enum_parses_case_insensitive():
    """OrderTriggerSource('admission_readiness') resolves to ADMISSION_READINESS."""
    assert OrderTriggerSource("admission_readiness") is OrderTriggerSource.ADMISSION_READINESS
    assert OrderTriggerSource("ADMISSION_READINESS") is OrderTriggerSource.ADMISSION_READINESS


# --- behavior 2 (PRIMARY GATE): a PENDING symbol injected DIRECTLY is rejected ---


def test_pending_symbol_direct_injection_rejected(harness):
    """A PENDING symbol's unsized signal injected DIRECTLY into on_signal
    (bypassing the strategy loop) is audited-REJECTED (ADMISSION_READINESS) and
    NO OrderEvent reaches the queue — the PRIMARY-gate proof."""
    harness.inject_universe()  # ETHUSDT is PENDING

    harness.order_handler.on_signal(
        harness.create_mock_signal("BUY", ticker=_PENDING_TICKER)
    )

    assert harness.queue.empty()  # no OrderEvent emitted for the unwarmed symbol
    rejected = _stored_rejection(harness, _PENDING_TICKER)
    change = rejected.get_latest_state_change()
    assert change.to_status is OrderStatus.REJECTED
    assert change.triggered_by is OrderTriggerSource.ADMISSION_READINESS
    assert "not ready" in change.reason


# --- behavior 3: after mark_ready the identical signal is admitted -----------


def test_pending_symbol_admitted_after_mark_ready(harness):
    """Once the PENDING symbol is marked READY, the identical signal sizes to an
    OrderEvent (the gate no longer fires)."""
    harness.inject_universe()
    harness.universe.mark_ready(_PENDING_TICKER)

    harness.order_handler.on_signal(
        harness.create_mock_signal("BUY", ticker=_PENDING_TICKER)
    )

    order = harness.queue.get(False)
    assert isinstance(order, OrderEvent)
    assert order.action is Side.BUY
    assert order.ticker == _PENDING_TICKER


# --- behavior 4: a READY construction member is admitted unchanged -----------


def test_ready_construction_member_admitted(harness):
    """An unsized signal for a READY construction member is admitted normally."""
    harness.inject_universe()

    harness.order_handler.on_signal(
        harness.create_mock_signal("BUY", ticker=_READY_TICKER)
    )

    order = harness.queue.get(False)
    assert isinstance(order, OrderEvent)
    assert order.action is Side.BUY
    assert order.ticker == _READY_TICKER


# --- behavior 5: no injected universe is a no-op (oracle-dark) ---------------


def test_no_universe_is_noop(harness):
    """With no injected universe the readiness gate is a no-op — a BUY entry for
    ANY symbol emits (backtest / no-universe oracle-dark path)."""
    # Deliberately DO NOT call inject_universe().
    harness.order_handler.on_signal(
        harness.create_mock_signal("BUY", ticker=_PENDING_TICKER)
    )
    order = harness.queue.get(False)
    assert isinstance(order, OrderEvent)
    assert order.action is Side.BUY


# --- behavior 6: an explicit-quantity signal skips the gate ------------------


def test_pending_symbol_explicit_quantity_skips_gate(harness):
    """An explicit-quantity BUY for a PENDING symbol skips the gate (manual path)."""
    harness.inject_universe()

    harness.order_handler.on_signal(
        harness.create_mock_signal("BUY", ticker=_PENDING_TICKER, quantity=Decimal("5"))
    )

    order = harness.queue.get(False)
    assert isinstance(order, OrderEvent)
    assert order.action is Side.BUY
