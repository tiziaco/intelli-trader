"""Effective-leverage plumbing through the run path (Finding B, LEV-03).

The admission-clamped EFFECTIVE leverage
``min(signal.leverage, Instrument.max_leverage, portfolio.max_leverage)``
must flow Order -> OrderEvent -> FillEvent -> Transaction -> Position so the
position-life locked margin (``aggregate_notional / position.leverage``) EQUALS
the admission reservation (``notional / effective_leverage``).

Per-hop RED tests:
  1. OrderEvent.new_order_event carries the Order entity's leverage.
  2. FillEvent.new_fill carries the OrderEvent's leverage.
  3. Transaction.new_transaction carries the FillEvent's leverage; a Position
     opened from that Transaction has Position.leverage == effective and
     locked_margin == aggregate_notional / leverage.
  4. Admission attaches the CLAMPED effective leverage to the built Order (an
     over-cap request is clamped, NOT the raw request).

Defaults stay Decimal("1") (oracle-dark): the spot path never sets leverage.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from itrader.core.enums import OrderStatus, OrderType, Side, PositionSide
from itrader.core.sizing import FractionOfCash, LeveredFraction, TradingDirection
from itrader.events_handler.events import SignalEvent, OrderEvent, FillEvent
from itrader.order_handler.order import Order
from itrader.portfolio_handler.transaction import Transaction
from itrader.portfolio_handler.position.position import Position


def _signal(leverage=Decimal("1"), sizing=None, action=Side.BUY,
            ticker="BTCUSDT", price=100.0):
    return SignalEvent(
        time=datetime.now(),
        order_type=OrderType.MARKET,
        ticker=ticker,
        action=action,
        price=price,
        quantity=Decimal("200"),
        stop_loss=Decimal("0"),
        take_profit=Decimal("0"),
        strategy_id="strat",
        portfolio_id="pf",
        sizing_policy=sizing if sizing is not None else FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        leverage=leverage,
    )


# --- Hop 1: Order -> OrderEvent --------------------------------------------------


def test_order_event_carries_order_leverage():
    """new_order_event reads the effective leverage off the Order entity."""
    order = Order.new_order(_signal(leverage=Decimal("5")), "paper",
                            leverage=Decimal("5"))
    event = OrderEvent.new_order_event(order)
    assert event.leverage == Decimal("5")


def test_order_event_default_leverage_is_one():
    """A default Order (no leverage supplied) yields OrderEvent.leverage == 1."""
    order = Order.new_order(_signal(), "paper")
    event = OrderEvent.new_order_event(order)
    assert event.leverage == Decimal("1")


# --- Hop 2: OrderEvent -> FillEvent ----------------------------------------------


def test_fill_event_carries_order_event_leverage():
    """new_fill carries the OrderEvent's leverage onto the FillEvent."""
    order = Order.new_order(_signal(leverage=Decimal("5")), "paper",
                            leverage=Decimal("5"))
    event = OrderEvent.new_order_event(order)
    fill = FillEvent.new_fill("EXECUTED", event,
                              price=event.price, quantity=event.quantity,
                              commission=0)
    assert fill.leverage == Decimal("5")


def test_fill_event_default_leverage_is_one():
    order = Order.new_order(_signal(), "paper")
    event = OrderEvent.new_order_event(order)
    fill = FillEvent.new_fill("EXECUTED", event,
                              price=event.price, quantity=event.quantity,
                              commission=0)
    assert fill.leverage == Decimal("1")


# --- Hop 3: FillEvent -> Transaction -> Position ---------------------------------


def _fill(leverage):
    order = Order.new_order(_signal(leverage=leverage), "paper",
                            leverage=leverage)
    event = OrderEvent.new_order_event(order)
    return FillEvent.new_fill("EXECUTED", event,
                              price=event.price, quantity=event.quantity,
                              commission=0)


def test_transaction_carries_fill_leverage():
    """new_transaction reads filled_order.leverage."""
    tx = Transaction.new_transaction(_fill(Decimal("5")))
    assert tx.leverage == Decimal("5")


def test_transaction_default_leverage_is_one():
    tx = Transaction.new_transaction(_fill(Decimal("1")))
    assert tx.leverage == Decimal("1")


def test_position_leverage_and_locked_margin_self_consistent():
    """Position opened from a leverage=5 Transaction has Position.leverage == 5,
    and locked_margin == aggregate_notional / 5 (== the admission reservation).

    aggregate_notional = 200 x 100 = 20000; locked = 20000 / 5 = 4000.
    """
    tx = Transaction.new_transaction(_fill(Decimal("5")))
    position = Position.open_position(tx)
    assert position.leverage == Decimal("5")
    assert position.aggregate_notional == Decimal("20000")
    # locked margin == aggregate_notional / leverage == 4000 (== reservation)
    assert position.aggregate_notional / position.leverage == Decimal("4000")
    assert position.side == PositionSide.LONG


# --- Hop 4: Admission attaches the CLAMPED effective leverage --------------------


class _StubLogger:
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...
    def info(self, *a, **k): ...
    def debug(self, *a, **k): ...


def _admission(enable_margin, pf_max_leverage):
    from itrader.order_handler.admission.admission_manager import AdmissionManager
    from itrader.order_handler.brackets.bracket_book import BracketBook
    from itrader.order_handler.brackets.bracket_manager import BracketManager
    from itrader.order_handler.storage import OrderStorageFactory
    storage = OrderStorageFactory.create("test")
    logger = _StubLogger()
    brackets = BracketBook()
    bracket_manager = BracketManager(storage, logger, brackets)
    return AdmissionManager(
        storage, logger,
        None,  # order_validator
        None,  # sizing_resolver
        None,  # portfolio_handler
        None,  # fee_model_provider
        brackets, bracket_manager,
        enable_margin=enable_margin,
        portfolio_max_leverage=pf_max_leverage,
    )


def test_admission_clamps_over_cap_leverage_onto_order():
    """An over-cap request (leverage 20, pf cap 5, no Universe -> instr cap 1...
    actually with no Universe instr_cap=1) is clamped: with margin ON and no
    Universe wired the cap degrades to Decimal('1'); with a pf cap of 5 and a
    requested 20 the effective is the MIN. Verify the built Order carries the
    CLAMPED value, never the raw 20."""
    mgr = _admission(enable_margin=True, pf_max_leverage=Decimal("5"))
    signal = _signal(leverage=Decimal("20"),
                     sizing=LeveredFraction(fraction=Decimal("2")))
    order = mgr._build_primary_order(signal, "paper", Decimal("200"))
    assert isinstance(order, Order)
    # No Universe wired -> instr cap degrades to Decimal("1"); min(20, 1, 5) = 1.
    assert order.leverage == Decimal("1")
    # CRITICAL: never the raw request.
    assert order.leverage != Decimal("20")


def test_admission_spot_path_forces_leverage_one():
    """With enable_margin off the effective leverage is forced to Decimal('1')
    (oracle-dark) even when the signal requests 20."""
    mgr = _admission(enable_margin=False, pf_max_leverage=Decimal("1"))
    signal = _signal(leverage=Decimal("20"))
    order = mgr._build_primary_order(signal, "paper", Decimal("200"))
    assert isinstance(order, Order)
    assert order.leverage == Decimal("1")
