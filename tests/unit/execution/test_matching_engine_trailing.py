"""Phase 5 (05-02) — MatchingEngine TRAILING_STOP ratchet unit tests.

Implements the Wave-0 stubs created in 05-00. Covers the locked behavioral
decisions for engine-native trailing stops, LONG and SHORT (Phase-3 short
coverage does not transfer — VALIDATION.md):

* ratchet favorably-only (D-TRAIL-1, the ratchet invariant)        long + short
* closed-bar / next-bar activation, the "tall bar" case (D-TRAIL-2)  next_bar
* gap-through fill at the OPEN, reusing the STOP rule (D-TRAIL-4)   long + short
* trailing-SL vs TP-limit same-bar OCO priority (D-TRAIL-5)         oco

The active stop level lives in the engine side-table (D-TRAIL-6); the tests read
``engine._trails[oid].current_stop`` to assert the ratchet invariant directly,
and assert fill TIMING/price for the look-ahead and gap decisions.

Folder-derived ``unit`` marker only (tests/conftest.py auto-applies it; no
decorator — ``--strict-markers``). No ``backtesting``/``backtrader`` import
(Pitfall 3 — ``filterwarnings=["error"]``).
"""

from datetime import datetime
from decimal import Decimal

import pytest

from itrader.execution_handler.matching_engine import MatchingEngine
from itrader.events_handler.events import OrderEvent
from itrader.core.enums import OrderType, OrderCommand, Side
from itrader.config import TrailType


def make_order_event(order_type, action, price, order_id,
                     ticker="BTCUSDT", quantity=1.0, parent_order_id=None,
                     trail_type=None, trail_value=None):
    # D-12: order money is Decimal end-to-end — enter via Decimal(str(x)).
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker=ticker, action=Side(action),
        price=Decimal(str(price)), quantity=Decimal(str(quantity)),
        exchange="default", strategy_id=1, portfolio_id=1,
        order_type=order_type, order_id=order_id, parent_order_id=parent_order_id,
        trail_type=trail_type,
        trail_value=None if trail_value is None else Decimal(str(trail_value)),
        command=OrderCommand.NEW,
    )


def make_trailing_order_event(action, price, order_id, *, trail_type, trail_value,
                              parent_order_id=None, ticker="BTCUSDT", quantity=1.0):
    """A resting TRAILING_STOP. ``price`` is the fill-anchored REFERENCE price
    (the D-TRAIL-7 reference the engine seeds HWM/LWM from), NOT the stop level —
    the initial stop is computed from it on submit."""
    return make_order_event(
        OrderType.TRAILING_STOP, action, price, order_id,
        ticker=ticker, quantity=quantity, parent_order_id=parent_order_id,
        trail_type=trail_type, trail_value=trail_value,
    )


@pytest.fixture
def engine():
    return MatchingEngine()


# --- ratchet favorably-only (D-TRAIL-1) -------------------------------------


def test_trailing_long_ratchet_favorable_only(engine, make_bar):
    """LONG sell-stop: as closed-bar highs rise the stop ratchets UP; on a
    lower-high bar the stop does NOT move down (non-decreasing invariant)."""
    # anchor 100, PRICE trail 10 -> initial stop 90
    engine.submit(make_trailing_order_event(
        "SELL", 100.0, 1, trail_type=TrailType.PRICE, trail_value=10.0))
    assert engine._trails[1].current_stop == Decimal("90")

    # bar1 high 120 (no pierce of 90) -> ratchet to 120-10 = 110
    engine.on_bar(make_bar(open_=105, high=120, low=101, close=118))
    assert engine._trails[1].current_stop == Decimal("110")

    # bar2 LOWER high 115 (no pierce of 110) -> candidate 105 < 110, stop HOLDS
    engine.on_bar(make_bar(open_=116, high=118, low=112, close=114))
    assert engine._trails[1].current_stop == Decimal("110")   # never loosens

    # bar3 higher high 130 -> ratchets UP again to 120
    engine.on_bar(make_bar(open_=119, high=130, low=118, close=128))
    assert engine._trails[1].current_stop == Decimal("120")
    assert engine.has_order(1)                                # never triggered


def test_trailing_short_ratchet_favorable_only(engine, make_bar):
    """SHORT buy-stop: as closed-bar lows fall the stop ratchets DOWN; on a
    higher-low bar the stop does NOT move up (non-increasing invariant)."""
    # anchor 100, PRICE trail 10 -> initial stop 110
    engine.submit(make_trailing_order_event(
        "BUY", 100.0, 1, trail_type=TrailType.PRICE, trail_value=10.0))
    assert engine._trails[1].current_stop == Decimal("110")

    # bar1 low 80 (no pierce of 110) -> ratchet to 80+10 = 90
    engine.on_bar(make_bar(open_=95, high=99, low=80, close=82))
    assert engine._trails[1].current_stop == Decimal("90")

    # bar2 HIGHER low 85 (no pierce of 90) -> candidate 95 > 90, stop HOLDS
    engine.on_bar(make_bar(open_=84, high=88, low=85, close=86))
    assert engine._trails[1].current_stop == Decimal("90")    # never loosens

    # bar3 lower low 70 -> ratchets DOWN again to 80
    engine.on_bar(make_bar(open_=81, high=83, low=70, close=72))
    assert engine._trails[1].current_stop == Decimal("80")
    assert engine.has_order(1)                                # never triggered


# --- closed-bar / next-bar activation, the "tall bar" (D-TRAIL-2) -----------


def test_trailing_next_bar_activation_not_same_bar(engine, make_bar):
    """The phase-defining look-ahead invariant. A single "tall bar" whose HIGH
    ratchets the stop UP and whose LOW pierces that freshly-ratcheted level does
    NOT fill on that bar — the new level is active only on the NEXT bar."""
    # anchor 100, PRICE trail 10 -> initial active stop 90
    engine.submit(make_trailing_order_event(
        "SELL", 100.0, 1, trail_type=TrailType.PRICE, trail_value=10.0))
    assert engine._trails[1].current_stop == Decimal("90")

    # TALL BAR: high 150 would ratchet the stop to 140; low 130 pierces 140.
    # Under same-bar (forbidden) semantics this would fill at 140. Under the
    # correct D-TRAIL-2 ordering the ACTIVE level is still 90 (low 130 > 90),
    # so NO fill — then the END-of-bar ratchet advances the level to 140.
    fills, cancels = engine.on_bar(make_bar(open_=105, high=150, low=130, close=145))
    assert fills == []                                        # NO same-bar fill
    assert engine.has_order(1)
    assert engine._trails[1].current_stop == Decimal("140")   # ratcheted for NEXT bar

    # NEXT bar pierces the now-active 140 -> fills.
    fills, cancels = engine.on_bar(make_bar(open_=143, high=146, low=135, close=138))
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("140")
    assert fills[0].reason == "trailing stop triggered"
    assert not engine.has_order(1)
    assert 1 not in engine._trails                            # side-table popped


# --- gap-through fill at the OPEN (D-TRAIL-4) -------------------------------


def test_trailing_gap_through_fills_at_open_long(engine, make_bar):
    """LONG: a clean gap-down past the active stop fills at the OPEN (worse),
    not the stop level — the existing STOP min(open, trigger) rule verbatim."""
    engine.submit(make_trailing_order_event(
        "SELL", 100.0, 1, trail_type=TrailType.PRICE, trail_value=10.0))
    # bar1 establishes an active stop of 110 (no fill).
    engine.on_bar(make_bar(open_=105, high=120, low=101, close=118))
    assert engine._trails[1].current_stop == Decimal("110")
    # bar2 gaps DOWN: open 95 < stop 110 -> fill at the worse OPEN, not 110.
    fills, _ = engine.on_bar(make_bar(open_=95, high=98, low=90, close=92))
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("95")               # min(open, stop)
    assert fills[0].fill_price < Decimal("110")


def test_trailing_gap_through_fills_at_open_short(engine, make_bar):
    """SHORT: a clean gap-up past the active stop fills at the OPEN (worse),
    via the existing STOP max(open, trigger) rule verbatim."""
    engine.submit(make_trailing_order_event(
        "BUY", 100.0, 1, trail_type=TrailType.PRICE, trail_value=10.0))
    # bar1 establishes an active stop of 90 (no fill).
    engine.on_bar(make_bar(open_=95, high=99, low=80, close=82))
    assert engine._trails[1].current_stop == Decimal("90")
    # bar2 gaps UP: open 105 > stop 90 -> fill at the worse OPEN, not 90.
    fills, _ = engine.on_bar(make_bar(open_=105, high=110, low=102, close=108))
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("105")              # max(open, stop)
    assert fills[0].fill_price > Decimal("90")


# --- trailing-SL vs TP-limit same-bar OCO priority (D-TRAIL-5) --------------


def test_trailing_oco_sl_vs_tp_limit(engine, make_bar):
    """A bracket with a TRAILING SL and a TP limit: when BOTH qualify on the
    same bar, the trailing SL wins (STOP-beats-LIMIT priority) and the TP is
    OCO-cancelled. The parent fills first and unlocks the children same bar."""
    parent = make_order_event(OrderType.MARKET, "BUY", 100.0, order_id=1)
    # Trailing SL child: reference 100, trail 5 -> initial active stop 95.
    sl = make_trailing_order_event(
        "SELL", 100.0, 2, trail_type=TrailType.PRICE, trail_value=5.0,
        parent_order_id=1)
    tp = make_order_event(OrderType.LIMIT, "SELL", 110.0, order_id=3,
                          parent_order_id=1)
    for order in (parent, sl, tp):
        engine.submit(order)

    # Bar pierces BOTH the trailing SL (low 94 <= 95) and the TP (high 112 >= 110).
    fills, cancels = engine.on_bar(make_bar(open_=100, high=112, low=94, close=105))
    assert [f.order_event.order_id for f in fills] == [1, 2]  # parent, then trailing SL
    assert fills[1].reason == "trailing stop triggered"
    assert [c.order_event.order_id for c in cancels] == [3]   # TP OCO-cancelled
    assert not engine.has_order(2)
    assert not engine.has_order(3)
    assert 2 not in engine._trails                            # side-table popped


# --- WR-01: MODIFY on a resting trailing stop reseeds the side-table --------


def test_trailing_modify_price_reseeds_trail_state(engine, make_bar):
    """WR-01: a MODIFY that changes a resting TRAILING_STOP's reference price
    must NOT leave the ratchet side-table seeded from the ORIGINAL price. The
    TrailState (hwm/lwm/current_stop) is re-seeded from the new reference so the
    dynamic trigger reflects the modified order — not the stale original level."""
    # anchor 100, PRICE trail 10 -> initial stop 90 (long sell-stop).
    engine.submit(make_trailing_order_event(
        "SELL", 100.0, 1, trail_type=TrailType.PRICE, trail_value=10.0))
    assert engine._trails[1].current_stop == Decimal("90")
    assert engine._trails[1].hwm == Decimal("100")

    # MODIFY the reference up to 150 -> the trail must re-seed: hwm 150, stop 140.
    assert engine.modify(1, new_price=Decimal("150"))
    assert engine._trails[1].hwm == Decimal("150")            # not the stale 100
    assert engine._trails[1].lwm == Decimal("150")
    assert engine._trails[1].current_stop == Decimal("140")  # 150 - 10, not 90

    # The modified order triggers against the NEW level: a bar piercing 140
    # (but not the stale 90) fills.
    fills, _ = engine.on_bar(make_bar(open_=145, high=146, low=139, close=141))
    assert [f.order_event.order_id for f in fills] == [1]
    assert fills[0].fill_price == Decimal("140")             # min(open 145, stop 140)


def test_modify_non_trailing_order_leaves_no_trail_state(engine, make_bar):
    """A MODIFY on a plain STOP must not spuriously create a TrailState entry
    (the reseed path is TRAILING_STOP-only)."""
    engine.submit(make_order_event(OrderType.STOP, "SELL", 90.0, order_id=7))
    assert engine.modify(7, new_price=Decimal("85"))
    assert 7 not in engine._trails
    assert engine.get_order(7).price == Decimal("85")
