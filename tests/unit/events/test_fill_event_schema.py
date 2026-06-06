import uuid
from datetime import datetime
from decimal import Decimal

import uuid_utils.compat as uuid_compat

from itrader.events_handler.events import OrderEvent, FillEvent
from itrader.core.enums import FillStatus, OrderType, Side
from itrader.core.money import to_money

_STRATEGY_ID = uuid_compat.uuid7()


def _order_event():
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker="BTCUSDT", action=Side.BUY,
        price=40.0, quantity=1.0, exchange="default", strategy_id=_STRATEGY_ID,
        portfolio_id=1, order_type=OrderType.MARKET, order_id=7,
    )


def test_executed_fill_carries_order_id():
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.5)
    assert fill.order_id == 7
    assert fill.status is FillStatus.EXECUTED


def test_cancelled_status_supported():
    order = _order_event()
    fill = FillEvent.new_fill(
        "CANCELLED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert fill.status is FillStatus.CANCELLED
    assert fill.order_id == 7


def test_fill_id_is_uuid7():
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert isinstance(fill.fill_id, uuid.UUID)
    assert fill.fill_id.version == 7


def test_each_fill_gets_a_unique_fill_id():
    order = _order_event()
    fill_a = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    fill_b = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert fill_a.fill_id != fill_b.fill_id


def test_strategy_id_copied_from_order():
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert fill.strategy_id == _STRATEGY_ID


def test_executed_values_land_without_mutation():
    # Construct-complete (D-12): the executed price/quantity are explicit
    # constructor inputs — they land on the fill (normalized via to_money,
    # D-22), and the originating order is left untouched.
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=41.5, quantity=0.75, commission=0.1)
    assert fill.price == Decimal("41.5")
    assert fill.quantity == Decimal("0.75")
    assert fill.commission == Decimal("0.1")
    assert order.price == 40.0
    assert order.quantity == 1.0


def test_float_fill_price_enters_via_to_money():
    # D-22: every float->Decimal crossing enters via to_money (Decimal(str(x)))
    # — numerically inert by construction. 0.1 + 0.2 carries the canonical
    # binary artifact; the fill must equal to_money(that float) exactly,
    # NOT Decimal(0.30000000000000004...) (the forbidden Decimal(float) path).
    order = _order_event()
    float_price = 0.1 + 0.2  # 0.30000000000000004
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=float_price, quantity=0.75, commission=0.0)
    assert isinstance(fill.price, Decimal)
    assert fill.price == to_money(float_price)
    assert str(fill.price) == "0.30000000000000004"


def test_fill_money_fields_are_decimal():
    # D-22: FillEvent price/quantity/commission are Decimal-typed; float
    # constructor inputs are normalized once, at construction, via to_money.
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=41.5, quantity=0.75, commission=0.1)
    assert isinstance(fill.price, Decimal)
    assert isinstance(fill.quantity, Decimal)
    assert isinstance(fill.commission, Decimal)
    assert fill.price == Decimal("41.5")
    assert fill.quantity == Decimal("0.75")
    assert fill.commission == Decimal("0.1")


def test_decimal_inputs_pass_through_identity():
    # to_money on Decimal input is an identity normalization (str round-trips
    # a Decimal exactly) — Decimal callers lose nothing.
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=Decimal("41.50000001"),
        quantity=Decimal("0.75"), commission=Decimal("0"))
    assert fill.price == Decimal("41.50000001")
    assert fill.quantity == Decimal("0.75")
    assert fill.commission == Decimal("0")


def test_frozen_base_fields_and_side_carried():
    # M3-01 base fields: uuid7 event_id + business-time created_at; the
    # Side member is carried from the originating order (D-05).
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert fill.event_id.version == 7
    assert fill.created_at == fill.time
    assert fill.action is Side.BUY
