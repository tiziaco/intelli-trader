from datetime import datetime

import pandas as pd
import pytest

from itrader.execution_handler.matching_engine import MatchingEngine
from itrader.events_handler.event import OrderEvent, BarEvent
from itrader.core.enums import OrderType, OrderCommand


def make_order_event(order_type, action, price, order_id,
                     ticker="BTCUSDT", quantity=1.0, parent_order_id=None):
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker=ticker, action=action, price=price,
        quantity=quantity, exchange="default", strategy_id=1, portfolio_id=1,
        order_type=order_type, order_id=order_id, parent_order_id=parent_order_id,
        command=OrderCommand.NEW,
    )


def make_bar(open_, high, low, close, ticker="BTCUSDT"):
    bars = {
        ticker: pd.DataFrame(
            {"open": [open_], "high": [high], "low": [low], "close": [close], "volume": [1]}
        )
    }
    return BarEvent(time=datetime(2024, 1, 1), bars=bars)


@pytest.fixture
def engine():
    return MatchingEngine()


# --- book operations --------------------------------------------------------


def test_submit_then_cancel(engine):
    oe = make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1)
    engine.submit(oe)
    assert engine.has_order(1)
    assert engine.cancel(1)
    assert not engine.has_order(1)


def test_cancel_unknown_returns_false(engine):
    assert not engine.cancel(123)


def test_modify_price_and_quantity(engine):
    oe = make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=2, quantity=1.0)
    engine.submit(oe)
    assert engine.modify(2, new_price=55.0, new_quantity=3.0)
    resting = engine.get_order(2)
    assert resting.price == 55.0
    assert resting.quantity == 3.0


def test_modify_replaces_in_book_without_mutating_original(engine):
    """Replace-in-book: modify stores an updated COPY; the submitted event is untouched."""
    oe = make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=2, quantity=1.0)
    engine.submit(oe)
    assert engine.modify(2, new_price=55.0, new_quantity=3.0)
    resting = engine.get_order(2)
    assert resting is not oe                 # a new object was stored back
    assert oe.price == 50.0                  # original event never mutated
    assert oe.quantity == 1.0
    assert resting.price == 55.0
    assert resting.quantity == 3.0


def test_modify_preserves_order_identity(engine):
    """dataclasses.replace deliberately preserves order_id (and event_id once
    events carry one): a MODIFY amends the order's terms, not its identity."""
    oe = make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=2,
                          parent_order_id=100)
    engine.submit(oe)
    assert engine.modify(2, new_price=60.0)
    resting = engine.get_order(2)
    assert resting.order_id == 2             # same identity, same book key
    assert resting.parent_order_id == 100    # bracket linkage preserved too
    assert engine.has_order(2)


def test_modify_none_guarded_args_leave_other_field_unchanged(engine):
    oe = make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=2, quantity=4.0)
    engine.submit(oe)
    assert engine.modify(2, new_price=52.0)          # quantity not passed
    resting = engine.get_order(2)
    assert resting.price == 52.0
    assert resting.quantity == 4.0                   # untouched
    assert engine.modify(2, new_quantity=7.0)        # price not passed
    resting = engine.get_order(2)
    assert resting.price == 52.0                     # untouched
    assert resting.quantity == 7.0


def test_modify_unknown_returns_false(engine):
    assert not engine.modify(999, new_price=1.0)


# --- stop triggers ----------------------------------------------------------


def test_sell_stop_triggers_when_low_pierces(engine):
    # stop-loss on a long: SELL stop at 30, bar low 20 -> fills
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, cancels = engine.on_bar(make_bar(open_=35, high=36, low=20, close=25))
    assert len(fills) == 1
    assert fills[0].fill_price == 30.0   # filled at stop (no gap)
    assert not engine.has_order(1)       # removed from book


def test_sell_stop_does_not_trigger_when_low_above(engine):
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, cancels = engine.on_bar(make_bar(open_=40, high=45, low=35, close=42))
    assert fills == []
    assert engine.has_order(1)


def test_sell_stop_gap_fills_at_open(engine):
    # bar gaps below the stop: open 25 < stop 30 -> realistic fill at open (worse)
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, cancels = engine.on_bar(make_bar(open_=25, high=27, low=18, close=20))
    assert fills[0].fill_price == 25.0   # min(open, stop)


def test_buy_stop_triggers_when_high_pierces(engine):
    # stop on a short: BUY stop at 50, bar high 60 -> fills at stop
    engine.submit(make_order_event(OrderType.STOP, "BUY", 50.0, order_id=2))
    fills, cancels = engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
    assert fills[0].fill_price == 50.0


def test_buy_stop_gap_fills_at_open(engine):
    # bar gaps above the stop: open 55 > stop 50 -> fill at open (worse)
    engine.submit(make_order_event(OrderType.STOP, "BUY", 50.0, order_id=2))
    fills, cancels = engine.on_bar(make_bar(open_=55, high=62, low=54, close=60))
    assert fills[0].fill_price == 55.0   # max(open, stop)


# --- limit triggers ---------------------------------------------------------


def test_sell_limit_triggers_when_high_pierces(engine):
    # take-profit on a long: SELL limit at 50, bar high 60 -> fills at limit
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
    assert fills[0].fill_price == 50.0


def test_sell_limit_does_not_trigger_when_high_below(engine):
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=40, high=48, low=39, close=47))
    assert fills == []


def test_buy_limit_triggers_when_low_pierces(engine):
    engine.submit(make_order_event(OrderType.LIMIT, "BUY", 30.0, order_id=2))
    fills, _ = engine.on_bar(make_bar(open_=35, high=36, low=25, close=28))
    assert fills[0].fill_price == 30.0


def test_independent_orders_on_same_bar_both_fill(engine):
    # two unrelated orders (no bracket link) both trigger -> both fill
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", 55.0, order_id=2))
    fills, cancels = engine.on_bar(make_bar(open_=40, high=60, low=20, close=50))
    assert len(fills) == 2
    assert cancels == []


def test_ignores_ticker_not_in_bar(engine):
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1, ticker="ETHUSDT"))
    fills, _ = engine.on_bar(make_bar(open_=40, high=60, low=20, close=50))  # BTCUSDT only
    assert fills == []
    assert engine.has_order(1)


# --- OCO / brackets ---------------------------------------------------------


@pytest.fixture
def bracket(engine):
    """A bracket: entry id 100; SL and TP are children (parent_order_id=100)."""
    sl = make_order_event(OrderType.STOP, "SELL", 30.0, order_id=11, parent_order_id=100)
    tp = make_order_event(OrderType.LIMIT, "SELL", 55.0, order_id=12, parent_order_id=100)
    return engine, sl, tp


def test_tp_fill_cancels_sl_sibling(bracket):
    engine, sl, tp = bracket
    engine.submit(sl)
    engine.submit(tp)
    # TP triggers (high 60 >= 55), SL does not (low 40 > 30)
    fills, cancels = engine.on_bar(make_bar(open_=50, high=60, low=40, close=58))
    assert len(fills) == 1
    assert fills[0].order_event.order_id == 12
    assert len(cancels) == 1
    assert cancels[0].order_event.order_id == 11
    assert not engine.has_order(11)
    assert not engine.has_order(12)


def test_same_bar_both_pierced_prefers_stop(bracket):
    engine, sl, tp = bracket
    engine.submit(sl)
    engine.submit(tp)
    # wide bar pierces BOTH: low 20 <= 30 (SL) and high 60 >= 55 (TP)
    fills, cancels = engine.on_bar(make_bar(open_=45, high=60, low=20, close=40))
    assert len(fills) == 1
    assert fills[0].order_event.order_id == 11      # pessimistic: STOP fills
    assert len(cancels) == 1
    assert cancels[0].order_event.order_id == 12    # TP cancelled


def test_non_triggered_sibling_still_cancelled(bracket):
    engine, sl, tp = bracket
    # Only TP triggers; SL does not, but must be cancelled because its bracket leg filled.
    engine.submit(sl)
    engine.submit(tp)
    fills, cancels = engine.on_bar(make_bar(open_=50, high=56, low=45, close=55))
    assert fills[0].order_event.order_id == 12
    assert [c.order_event.order_id for c in cancels] == [11]


def test_two_independent_brackets_both_resolve(engine):
    # Two distinct brackets resolve on the same bar without cross-contamination.
    # Bracket A: SL at 20 (no trigger, low 25 > 20), TP at 55 (fills, high 70 >= 55) -> TP wins.
    sl_a = make_order_event(OrderType.STOP, "SELL", 20.0, order_id=21, parent_order_id=200)
    tp_a = make_order_event(OrderType.LIMIT, "SELL", 55.0, order_id=22, parent_order_id=200)
    # Bracket B: SL at 30 (fills, low 25 <= 30), TP at 80 (no trigger, high 70 < 80) -> SL wins.
    sl_b = make_order_event(OrderType.STOP, "SELL", 30.0, order_id=31, parent_order_id=300)
    tp_b = make_order_event(OrderType.LIMIT, "SELL", 80.0, order_id=32, parent_order_id=300)
    for o in (sl_a, tp_a, sl_b, tp_b):
        engine.submit(o)
    fills, cancels = engine.on_bar(make_bar(open_=40, high=70, low=25, close=45))
    assert len(fills) == 2
    assert len(cancels) == 2
    assert {f.order_event.order_id for f in fills} == {22, 31}    # A's TP, B's SL
    assert {c.order_event.order_id for c in cancels} == {21, 32}  # A's SL, B's TP
