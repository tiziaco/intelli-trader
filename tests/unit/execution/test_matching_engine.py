from datetime import datetime
from decimal import Decimal

import pytest

from itrader.execution_handler.matching_engine import MatchingEngine
from itrader.events_handler.events import OrderEvent
from itrader.core.enums import OrderType, OrderCommand, Side


def make_order_event(order_type, action, price, order_id,
                     ticker="BTCUSDT", quantity=1.0, parent_order_id=None):
    # D-12: order money is Decimal end-to-end — enter via Decimal(str(x))
    # exactly as the production OrderEvent path does.
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker=ticker, action=Side(action),
        price=Decimal(str(price)), quantity=Decimal(str(quantity)),
        exchange="default", strategy_id=1, portfolio_id=1,
        order_type=order_type, order_id=order_id, parent_order_id=parent_order_id,
        command=OrderCommand.NEW,
    )


# The bar payload comes from the shared `make_bar` factory fixture in
# tests/conftest.py (M5-02: dict[str, Bar] Decimal payload) — same positional
# (open_, high, low, close) signature as the legacy per-file helper.


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


def test_sell_stop_triggers_when_low_pierces(engine, make_bar):
    # stop-loss on a long: SELL stop at 30, bar low 20 -> fills
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, cancels = engine.on_bar(make_bar(open_=35, high=36, low=20, close=25))
    assert len(fills) == 1
    assert fills[0].fill_price == 30.0   # filled at stop (no gap)
    assert not engine.has_order(1)       # removed from book


def test_sell_stop_does_not_trigger_when_low_above(engine, make_bar):
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, cancels = engine.on_bar(make_bar(open_=40, high=45, low=35, close=42))
    assert fills == []
    assert engine.has_order(1)


def test_sell_stop_gap_fills_at_open(engine, make_bar):
    # bar gaps below the stop: open 25 < stop 30 -> realistic fill at open (worse)
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, cancels = engine.on_bar(make_bar(open_=25, high=27, low=18, close=20))
    assert fills[0].fill_price == 25.0   # min(open, stop)


def test_buy_stop_triggers_when_high_pierces(engine, make_bar):
    # stop on a short: BUY stop at 50, bar high 60 -> fills at stop
    engine.submit(make_order_event(OrderType.STOP, "BUY", 50.0, order_id=2))
    fills, cancels = engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
    assert fills[0].fill_price == 50.0


def test_buy_stop_gap_fills_at_open(engine, make_bar):
    # bar gaps above the stop: open 55 > stop 50 -> fill at open (worse)
    engine.submit(make_order_event(OrderType.STOP, "BUY", 50.0, order_id=2))
    fills, cancels = engine.on_bar(make_bar(open_=55, high=62, low=54, close=60))
    assert fills[0].fill_price == 55.0   # max(open, stop)


# --- limit triggers ---------------------------------------------------------


def test_sell_limit_triggers_when_high_pierces(engine, make_bar):
    # take-profit on a long: SELL limit at 50, bar high 60 -> fills at limit
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
    assert fills[0].fill_price == 50.0


def test_sell_limit_does_not_trigger_when_high_below(engine, make_bar):
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=40, high=48, low=39, close=47))
    assert fills == []


def test_buy_limit_triggers_when_low_pierces(engine, make_bar):
    engine.submit(make_order_event(OrderType.LIMIT, "BUY", 30.0, order_id=2))
    fills, _ = engine.on_bar(make_bar(open_=35, high=36, low=25, close=28))
    assert fills[0].fill_price == 30.0


# --- limit-or-better (D-03) -------------------------------------------------


def test_sell_limit_gap_through_fills_at_better_open(engine, make_bar):
    # SELL limit 110, bar opens 115 (favorable gap-up) -> fill at the BETTER
    # open, never below the limit (limit-or-better, D-03).
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", 110.0, order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=115, high=120, low=112, close=118))
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("115")
    assert fills[0].fill_price >= Decimal("110")   # never slips past the limit


def test_buy_limit_gap_through_fills_at_better_open(engine, make_bar):
    # BUY limit 100, bar opens 95 (favorable gap-down) -> fill at the BETTER
    # open, never above the limit.
    engine.submit(make_order_event(OrderType.LIMIT, "BUY", 100.0, order_id=2))
    fills, _ = engine.on_bar(make_bar(open_=95, high=98, low=90, close=96))
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("95")
    assert fills[0].fill_price <= Decimal("100")   # never slips past the limit


def test_sell_limit_in_bar_touch_fills_at_trigger_exactly(engine, make_bar):
    # No gap (open below the limit); the in-bar touch fills at the limit exactly.
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", 50.0, order_id=3))
    fills, _ = engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
    assert fills[0].fill_price == Decimal("50.0")


def test_buy_limit_in_bar_touch_fills_at_trigger_exactly(engine, make_bar):
    engine.submit(make_order_event(OrderType.LIMIT, "BUY", 30.0, order_id=4))
    fills, _ = engine.on_bar(make_bar(open_=35, high=36, low=25, close=28))
    assert fills[0].fill_price == Decimal("30.0")


def test_stop_gap_pessimism_unchanged(engine, make_bar):
    # The STOP branch keeps its pessimistic gap fill: SELL stop gap-down fills
    # at min(open, trigger) — limit-or-better does NOT leak into stops.
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=5))
    fills, _ = engine.on_bar(make_bar(open_=25, high=27, low=18, close=20))
    assert fills[0].fill_price == min(Decimal("25"), Decimal("30.0"))
    assert fills[0].fill_price == Decimal("25")


def test_independent_orders_on_same_bar_both_fill(engine, make_bar):
    # two unrelated orders (no bracket link) both trigger -> both fill
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", 55.0, order_id=2))
    fills, cancels = engine.on_bar(make_bar(open_=40, high=60, low=20, close=50))
    assert len(fills) == 2
    assert cancels == []


def test_ignores_ticker_not_in_bar(engine, make_bar):
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1, ticker="ETHUSDT"))
    fills, _ = engine.on_bar(make_bar(open_=40, high=60, low=20, close=50))  # BTCUSDT only
    assert fills == []
    assert engine.has_order(1)


# --- D-12 Decimal-native matching --------------------------------------------


def test_stop_fill_price_is_decimal(engine, make_bar):
    # D-12: matching is Decimal end-to-end — order.price (Decimal) compares
    # directly against Decimal Bar OHLC, and the decision's fill_price is a
    # Decimal instance (no float boundary anywhere in the engine).
    engine.submit(make_order_event(OrderType.STOP, "SELL", Decimal("30.0"), order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=35, high=36, low=20, close=25))
    assert len(fills) == 1
    assert isinstance(fills[0].fill_price, Decimal)
    assert fills[0].fill_price == Decimal("30.0")


def test_limit_fill_price_is_decimal(engine, make_bar):
    engine.submit(make_order_event(OrderType.LIMIT, "SELL", Decimal("50.0"), order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
    assert len(fills) == 1
    assert isinstance(fills[0].fill_price, Decimal)
    assert fills[0].fill_price == Decimal("50.0")


def test_stop_gap_fill_min_max_stays_decimal(engine, make_bar):
    # Gap-down: min(open, stop) runs in the Decimal domain — the result is
    # Decimal, with no quantization (D-14 never-round-prices).
    engine.submit(make_order_event(OrderType.STOP, "SELL", Decimal("30.0"), order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=25, high=27, low=18, close=20))
    assert isinstance(fills[0].fill_price, Decimal)
    assert fills[0].fill_price == Decimal("25")


def test_market_fill_price_is_decimal_bar_open(engine, make_bar):
    # Next-bar market order fills at the bar's own Decimal open, untouched.
    engine.submit(make_order_event(OrderType.MARKET, "BUY", 40.0, order_id=9))
    fills, _ = engine.on_bar(make_bar(open_=41.5, high=45, low=40, close=44))
    assert isinstance(fills[0].fill_price, Decimal)
    assert fills[0].fill_price == Decimal("41.5")


def test_fill_decision_has_no_fill_quantity(engine, make_bar):
    # Full-quantity contract (D-06): the partial-fill plumbing is deleted —
    # FillDecision carries no quantity field at all.
    from itrader.execution_handler.matching_engine import FillDecision
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, _ = engine.on_bar(make_bar(open_=35, high=36, low=20, close=25))
    assert not hasattr(fills[0], "fill_quantity")
    assert "fill_quantity" not in {f.name for f in __import__("dataclasses").fields(FillDecision)}


def test_modify_accepts_decimal_and_stores_decimal(engine):
    # D-22: modify's annotation follows the event retype — the resting copy
    # carries Decimal money.
    oe = make_order_event(OrderType.LIMIT, "SELL", Decimal("50.0"), order_id=2,
                          quantity=Decimal("1.0"))
    engine.submit(oe)
    assert engine.modify(2, new_price=Decimal("55.0"), new_quantity=Decimal("3.0"))
    resting = engine.get_order(2)
    assert isinstance(resting.price, Decimal)
    assert resting.price == Decimal("55.0")
    assert isinstance(resting.quantity, Decimal)
    assert resting.quantity == Decimal("3.0")


# --- next-bar-open market fills + last-bar edge (D-01/D-13) ------------------


def test_market_order_rests_until_next_bar_then_fills_at_open(engine, make_bar):
    # A market order decided at tick T rests; the NEXT bar fills it at the
    # bar's own open (Decimal equality — never the decision price).
    engine.submit(make_order_event(OrderType.MARKET, "BUY", 40.0, order_id=1))
    assert engine.has_order(1)               # resting, nothing filled yet
    fills, cancels = engine.on_bar(make_bar(open_=41.5, high=45, low=40, close=44))
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("41.5")
    assert not engine.has_order(1)
    assert cancels == []


def test_order_decided_on_last_bar_never_fills(engine, make_bar):
    # Last-bar edge (bar-timing contract rule 7): the final dataset bar has
    # already been matched when the order arrives (signals are computed ON
    # that bar); no further bar ever comes, so the order NEVER fills — the
    # book still holds it when the run ends. Not special-cased.
    fills, _ = engine.on_bar(make_bar(open_=40, high=42, low=39, close=41))
    assert fills == []                       # final bar matched an empty book
    engine.submit(make_order_event(OrderType.MARKET, "BUY", 41.0, order_id=1))
    # dataset exhausted — on_bar is never called again
    assert engine.has_order(1)               # still resting, no fill produced


# --- OCO / brackets ---------------------------------------------------------


@pytest.fixture
def bracket(engine):
    """A bracket: entry id 100; SL and TP are children (parent_order_id=100)."""
    sl = make_order_event(OrderType.STOP, "SELL", 30.0, order_id=11, parent_order_id=100)
    tp = make_order_event(OrderType.LIMIT, "SELL", 55.0, order_id=12, parent_order_id=100)
    return engine, sl, tp


def test_tp_fill_cancels_sl_sibling(bracket, make_bar):
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


def test_same_bar_both_pierced_prefers_stop(bracket, make_bar):
    engine, sl, tp = bracket
    engine.submit(sl)
    engine.submit(tp)
    # wide bar pierces BOTH: low 20 <= 30 (SL) and high 60 >= 55 (TP)
    fills, cancels = engine.on_bar(make_bar(open_=45, high=60, low=20, close=40))
    assert len(fills) == 1
    assert fills[0].order_event.order_id == 11      # pessimistic: STOP fills
    assert len(cancels) == 1
    assert cancels[0].order_event.order_id == 12    # TP cancelled


def test_non_triggered_sibling_still_cancelled(bracket, make_bar):
    engine, sl, tp = bracket
    # Only TP triggers; SL does not, but must be cancelled because its bracket leg filled.
    engine.submit(sl)
    engine.submit(tp)
    fills, cancels = engine.on_bar(make_bar(open_=50, high=56, low=45, close=55))
    assert fills[0].order_event.order_id == 12
    assert [c.order_event.order_id for c in cancels] == [11]


def test_parent_market_fill_and_child_stop_trigger_same_bar(engine, make_bar):
    # Same-bar bracket rule (Open Question 1, accepted): the parent MARKET
    # order fills at the bar's open; its resting SL child triggers against
    # the SAME bar's low; the TP sibling is OCO-cancelled. Parent fill is
    # emitted BEFORE the child fill within one on_bar.
    parent = make_order_event(OrderType.MARKET, "BUY", 100.0, order_id=1)
    sl = make_order_event(OrderType.STOP, "SELL", 95.0, order_id=2, parent_order_id=1)
    tp = make_order_event(OrderType.LIMIT, "SELL", 110.0, order_id=3, parent_order_id=1)
    for order in (parent, sl, tp):
        engine.submit(order)
    fills, cancels = engine.on_bar(make_bar(open_=100, high=105, low=94, close=96))
    assert [f.order_event.order_id for f in fills] == [1, 2]   # parent first
    assert fills[0].fill_price == Decimal("100")               # entry at the open
    assert fills[1].fill_price == Decimal("95")                # SL vs same bar's low
    assert [c.order_event.order_id for c in cancels] == [3]    # TP OCO-cancelled
    for order_id in (1, 2, 3):
        assert not engine.has_order(order_id)


def test_parent_fill_same_bar_double_trigger_prefers_stop(engine, make_bar):
    # Parent fills at the open AND the bar pierces BOTH children: the
    # pessimistic STOP-beats-LIMIT sibling priority arbitrates.
    parent = make_order_event(OrderType.MARKET, "BUY", 100.0, order_id=1)
    sl = make_order_event(OrderType.STOP, "SELL", 95.0, order_id=2, parent_order_id=1)
    tp = make_order_event(OrderType.LIMIT, "SELL", 110.0, order_id=3, parent_order_id=1)
    for order in (parent, sl, tp):
        engine.submit(order)
    fills, cancels = engine.on_bar(make_bar(open_=100, high=112, low=94, close=105))
    assert [f.order_event.order_id for f in fills] == [1, 2]   # parent, then STOP
    assert [c.order_event.order_id for c in cancels] == [3]


def test_parent_market_fill_does_not_disturb_non_triggered_children(engine, make_bar):
    # The parent filling alone neither fills nor cancels its children — they
    # stay resting for later bars (the parent is standalone in arbitration).
    parent = make_order_event(OrderType.MARKET, "BUY", 100.0, order_id=1)
    sl = make_order_event(OrderType.STOP, "SELL", 80.0, order_id=2, parent_order_id=1)
    tp = make_order_event(OrderType.LIMIT, "SELL", 130.0, order_id=3, parent_order_id=1)
    for order in (parent, sl, tp):
        engine.submit(order)
    fills, cancels = engine.on_bar(make_bar(open_=100, high=105, low=95, close=102))
    assert [f.order_event.order_id for f in fills] == [1]
    assert cancels == []
    assert engine.has_order(2)
    assert engine.has_order(3)


def test_two_independent_brackets_both_resolve(engine, make_bar):
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


# --- CR-01 parent-filled gate -------------------------------------------------
# A bracket child (SL/TP) whose parent entry order STILL RESTS in the book is
# dormant: it cannot fill and cannot OCO-cancel its sibling. Only once the
# parent leaves the book (filled this bar in pass 1, filled/cancelled on an
# earlier bar, or never rested) do the children become eligible — same-bar
# market-parent semantics and children-only-book semantics are unchanged.


def test_limit_parent_resting_shields_children(engine, make_bar):
    # Defect lock (CR-01, limit entry): a BUY-LIMIT entry at 95 never touches
    # (low 98 > 95) while the bar rallies through the TP zone (high 112 >= 110).
    # Pre-fix the TP filled — opening a short from flat — and the SL was
    # OCO-cancelled. Post-fix the whole bracket stays resting.
    parent = make_order_event(OrderType.LIMIT, "BUY", 95.0, order_id=1)
    sl = make_order_event(OrderType.STOP, "SELL", 90.0, order_id=2, parent_order_id=1)
    tp = make_order_event(OrderType.LIMIT, "SELL", 110.0, order_id=3, parent_order_id=1)
    for order in (parent, sl, tp):
        engine.submit(order)
    fills, cancels = engine.on_bar(make_bar(open_=100, high=112, low=98, close=111))
    assert fills == []
    assert cancels == []
    for order_id in (1, 2, 3):
        assert engine.has_order(order_id)


def test_limit_parent_fill_same_bar_unlocks_children(engine, make_bar):
    # The entry touches this bar (low 94 <= 95 -> in-bar touch fills at the
    # limit 95) AND the TP zone is pierced (high 112 >= 110): the parent fills
    # in pass 1, leaving the book, so the TP is eligible against the SAME bar.
    # Parent fill precedes the child fill; the SL sibling is OCO-cancelled.
    parent = make_order_event(OrderType.LIMIT, "BUY", 95.0, order_id=1)
    sl = make_order_event(OrderType.STOP, "SELL", 90.0, order_id=2, parent_order_id=1)
    tp = make_order_event(OrderType.LIMIT, "SELL", 110.0, order_id=3, parent_order_id=1)
    for order in (parent, sl, tp):
        engine.submit(order)
    fills, cancels = engine.on_bar(make_bar(open_=100, high=112, low=94, close=105))
    assert [f.order_event.order_id for f in fills] == [1, 3]   # parent first
    assert fills[0].fill_price == Decimal("95")                # entry at the limit
    assert fills[1].fill_price == Decimal("110")               # TP at the limit
    assert [c.order_event.order_id for c in cancels] == [2]    # SL OCO-cancelled
    for order_id in (1, 2, 3):
        assert not engine.has_order(order_id)


def test_children_dormant_until_parent_triggers_then_work_later_bar(engine, make_bar):
    # Multi-bar lifecycle: children stay dormant across bars while the parent
    # rests; once the parent fills, the children work on subsequent bars.
    parent = make_order_event(OrderType.LIMIT, "BUY", 95.0, order_id=1)
    sl = make_order_event(OrderType.STOP, "SELL", 90.0, order_id=2, parent_order_id=1)
    tp = make_order_event(OrderType.LIMIT, "SELL", 110.0, order_id=3, parent_order_id=1)
    for order in (parent, sl, tp):
        engine.submit(order)
    # Bar A: no entry touch (low 96 > 95) — nothing fills, nothing cancels.
    fills, cancels = engine.on_bar(make_bar(open_=100, high=108, low=96, close=104))
    assert fills == []
    assert cancels == []
    for order_id in (1, 2, 3):
        assert engine.has_order(order_id)
    # Bar B: entry touches (low 94 <= 95) -> parent fills at the limit 95;
    # children do not trigger (high 99 < 110, low 94 > 90) and keep resting.
    fills, cancels = engine.on_bar(make_bar(open_=96, high=99, low=94, close=98))
    assert [f.order_event.order_id for f in fills] == [1]
    assert fills[0].fill_price == Decimal("95")
    assert cancels == []
    assert not engine.has_order(1)
    assert engine.has_order(2)
    assert engine.has_order(3)
    # Bar C: TP triggers (high 111 >= 110) — fills at the limit; SL cancelled.
    fills, cancels = engine.on_bar(make_bar(open_=100, high=111, low=99, close=110))
    assert [f.order_event.order_id for f in fills] == [3]
    assert fills[0].fill_price == Decimal("110")
    assert [c.order_event.order_id for c in cancels] == [2]
    assert not engine.has_order(2)
    assert not engine.has_order(3)


def test_stop_parent_resting_shields_children(engine, make_bar):
    # Defect lock (CR-01, stop entry): a BUY-STOP entry at 105 never triggers
    # (high 103 < 105) while the bar pierces the SL zone (low 88 <= 90).
    # Pre-fix the SL filled — opening a short from flat — and OCO-cancelled
    # the TP. Post-fix the whole bracket stays resting.
    parent = make_order_event(OrderType.STOP, "BUY", 105.0, order_id=1)
    sl = make_order_event(OrderType.STOP, "SELL", 90.0, order_id=2, parent_order_id=1)
    tp = make_order_event(OrderType.LIMIT, "SELL", 120.0, order_id=3, parent_order_id=1)
    for order in (parent, sl, tp):
        engine.submit(order)
    fills, cancels = engine.on_bar(make_bar(open_=100, high=103, low=88, close=92))
    assert fills == []
    assert cancels == []
    for order_id in (1, 2, 3):
        assert engine.has_order(order_id)
