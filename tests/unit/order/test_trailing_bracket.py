"""Plan 05-03 Task 1: trailing-SL bracket declaration (D-TRAIL-3 / D-TRAIL-5).

A bracket that declares a trailing stop replaces its FIXED SL leg with a
``TRAILING_STOP`` child seeded from the ENTRY FILL price (D-TRAIL-3) — the TP
limit leg and OCO linkage are unchanged (D-TRAIL-5, EITHER-fixed-OR-trailing).
The trailing intent rides the existing ``PercentFromFill`` fill-anchored
carve-out (a trailing SL has no static price at declaration), so the SL child is
created at the parent's EXECUTED fill via ``_create_fill_anchored_children``.

The function names contain BOTH ``trailing`` and ``bracket`` so the compound
selector ``-k "trailing and bracket"`` (05-03 Task 1) collects these. Both long
and short are covered (shorts were added only in Phase 3 — coverage does NOT
transfer). All expectations are hand-computed Decimals entered via the string
path (Pitfall 1); entirely oracle-dark (the golden run carries no brackets).

The BracketManager only DECLARES (parent_order_id / child_order_ids) and
reconciles its mirror from FillEvents — it NEVER matches (D-18, T-05-07); the
ratchet/trigger logic stays in the execution layer (proven at the unit level in
05-02 and end-to-end in 05-03 Task 2).

Folder-derived ``unit`` marker only (no decorator — --strict-markers).
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import FillEvent, OrderEvent, SignalEvent
from itrader.config import TrailType
from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.exceptions import SizingPolicyViolation
from itrader.core.sizing import (
    FractionOfCash,
    PercentFromFill,
    TradingDirection,
)
from tests.support.venue_wiring import backtest_portfolio_handler


_STRATEGY_ID = 1


class _TrailHarness:
    """OrderHandler harness with a funded portfolio and a trailing-aware signal."""

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = backtest_portfolio_handler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        self.last_ptf_id = self.ptf_handler.add_portfolio("trail_ptf", "default", 100000)

    def create_signal(self, action, ticker="BTCUSDT", quantity=1.0, price=100.0,
                      sltp_policy=None, direction=TradingDirection.LONG_ONLY):
        return SignalEvent(
            time=datetime(2024, 1, 1),
            order_type=OrderType.MARKET,
            ticker=ticker,
            action=Side(action),
            price=price,
            quantity=quantity,
            stop_loss=0.0,
            take_profit=0.0,
            strategy_id=_STRATEGY_ID,
            portfolio_id=self.last_ptf_id,
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=direction,
            sltp_policy=sltp_policy,
        )

    def drain_order_events(self):
        emitted = []
        while not self.queue.empty():
            ev = self.queue.get_nowait()
            if isinstance(ev, OrderEvent):
                emitted.append(ev)
        return emitted

    def fill(self, order_event, status="EXECUTED", price=None):
        fill = FillEvent.new_fill(
            status, order_event,
            price=price if price is not None else order_event.price,
            quantity=order_event.quantity,
            commission=0.0,
        )
        if status == "EXECUTED":
            self.ptf_handler.on_fill(fill)
        self.order_handler.on_fill(fill)
        return fill


@pytest.fixture
def harness():
    h = _TrailHarness()
    yield h
    while not h.queue.empty():
        try:
            h.queue.get_nowait()
        except Exception:
            break


def test_trailing_bracket_child_replaces_fixed_sl(harness):
    """LONG: PercentFromFill carrying trail_type/trail_value builds the SL child
    as a TRAILING_STOP seeded from the ENTRY FILL price (D-TRAIL-3, the engine's
    HWM/LWM anchor) instead of a fixed STOP — the TP LIMIT leg is unchanged
    (D-TRAIL-5 EITHER/OR). Parent fills at 102 (the fill anchor)."""
    signal = harness.create_signal(
        "BUY", quantity=1.0, price=100.0,
        sltp_policy=PercentFromFill(
            sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10"),
            trail_type=TrailType.PERCENT, trail_value=Decimal("0.05"),
        ),
    )

    harness.order_handler.on_signal(signal)
    # Fill-anchored carve-out: assembly emits ONLY the parent.
    order_events = harness.drain_order_events()
    assert len(order_events) == 1
    parent_event = order_events[0]

    # Parent EXECUTED at 102 — the fill is the trailing reference/anchor.
    harness.fill(parent_event, status="EXECUTED", price=Decimal("102"))

    child_events = harness.drain_order_events()
    # D-TRAIL-5: the SL leg is a TRAILING_STOP; the TP leg is an unchanged LIMIT.
    assert [e.order_type for e in child_events] == [
        OrderType.TRAILING_STOP, OrderType.LIMIT
    ]
    sl_event, tp_event = child_events

    # D-TRAIL-3: the trailing child's `price` is the ENTRY FILL price (the
    # engine's _seed_trail anchor = order.price), NOT the computed initial stop.
    assert sl_event.price == Decimal("102")
    assert sl_event.trail_type == TrailType.PERCENT
    assert sl_event.trail_value == Decimal("0.05")
    assert sl_event.action is Side.SELL  # long sell-stop
    # TP leg unchanged: fill-anchored percent limit, 102 * (1 + 0.10) = 112.2.
    assert tp_event.order_type == OrderType.LIMIT
    assert tp_event.price == Decimal("112.2")
    assert tp_event.trail_type is None
    assert tp_event.trail_value is None

    # Two-directional linkage — the manager declares, never matches (D-18).
    assert sl_event.parent_order_id == parent_event.order_id
    assert tp_event.parent_order_id == parent_event.order_id
    stored_parent = harness.order_storage.get_order_by_id(
        parent_event.order_id, harness.last_ptf_id)
    assert set(stored_parent.child_order_ids) == {sl_event.order_id, tp_event.order_id}


def test_trailing_bracket_child_replaces_fixed_sl_short(harness):
    """SHORT: a SELL-to-open with a trailing PercentFromFill builds the cover SL
    as a TRAILING_STOP (BUY) seeded from the fill, TP LIMIT unchanged."""
    signal = harness.create_signal(
        "SELL", quantity=1.0, price=100.0,
        direction=TradingDirection.SHORT_ONLY,
        sltp_policy=PercentFromFill(
            sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10"),
            trail_type=TrailType.PRICE, trail_value=Decimal("8"),
        ),
    )
    # Enable shorts on the order-domain admission path.
    sh = harness.order_handler.order_manager
    sh.admission_manager._enable_margin = True
    harness.order_handler.order_manager.order_validator.enable_margin = True

    harness.order_handler.on_signal(signal)
    order_events = harness.drain_order_events()
    assert len(order_events) == 1
    parent_event = order_events[0]

    harness.fill(parent_event, status="EXECUTED", price=Decimal("98"))

    child_events = harness.drain_order_events()
    assert [e.order_type for e in child_events] == [
        OrderType.TRAILING_STOP, OrderType.LIMIT
    ]
    sl_event, tp_event = child_events

    # D-TRAIL-3: trailing child price = entry fill anchor (98); PRICE trail = 8.
    assert sl_event.price == Decimal("98")
    assert sl_event.trail_type == TrailType.PRICE
    assert sl_event.trail_value == Decimal("8")
    assert sl_event.action is Side.BUY  # short buy-stop (cover)
    # TP unchanged: short cover LIMIT below the fill, 98 * (1 - 0.10) = 88.2.
    assert tp_event.order_type == OrderType.LIMIT
    assert tp_event.price == Decimal("88.2")
    assert sl_event.parent_order_id == parent_event.order_id


def test_trailing_bracket_nonviable_price_trail_rejected_at_fill(harness):
    """CR-01 (PRICE case): a PRICE trail >= the entry-fill anchor would seed a
    NON-POSITIVE stop (anchor - trail <= 0) that can never trigger — a silently
    unprotected position. The PRICE viability gate (D-TRAIL-7) is only knowable
    at fill, so it is enforced in ``_create_fill_anchored_children`` and rejected
    fail-loud (backtest fail-fast: the reconcile path re-raises), NOT silently
    rested as a dead stop. Construction is allowed (the anchor is unknown then)."""
    signal = harness.create_signal(
        "BUY", quantity=1.0, price=100.0,
        sltp_policy=PercentFromFill(
            sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10"),
            # PRICE trail of 120 is fine at construction; only at the fill of
            # 100 does it become non-viable (100 - 120 = -20, a dead stop).
            trail_type=TrailType.PRICE, trail_value=Decimal("120"),
        ),
    )

    harness.order_handler.on_signal(signal)
    order_events = harness.drain_order_events()
    assert len(order_events) == 1
    parent_event = order_events[0]

    # Fill at 100 — the (positive) anchor is BELOW the 120 PRICE trail, so the
    # carve-out must reject the non-viable trail instead of resting stop = -20.
    parent = harness.order_storage.get_order_by_id(
        parent_event.order_id, harness.last_ptf_id)
    pending = harness.order_handler.order_manager._brackets.get(parent_event.order_id)
    fill = FillEvent.new_fill(
        "EXECUTED", parent_event, price=Decimal("100"),
        quantity=parent_event.quantity, commission=0.0,
    )
    with pytest.raises(SizingPolicyViolation, match="trail_value"):
        harness.order_handler.order_manager.bracket_manager._create_fill_anchored_children(
            parent, pending, fill)
