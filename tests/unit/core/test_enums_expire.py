"""Wave-0 enum coverage for the EXPIRE lifecycle seams (LIFE-01, D-09).

These assert the two first-class enum members the EXPIRE lifecycle is built on —
``OrderCommand.EXPIRE`` (``core/enums/order.py``) and ``FillStatus.EXPIRED``
(``core/enums/execution.py``) — plus the pre-existing ``OrderStatus.EXPIRED``
transition table (regression guard, must stay unchanged). Adding ``FillStatus.EXPIRED``
closes Pitfall 2: ``FillEvent.new_fill('EXPIRED', ...)`` raises ``ValueError`` until the
member exists. Members are inert until Plan 03 wires them — no run-path behavior change.
"""

from datetime import datetime
from decimal import Decimal

import uuid_utils.compat as uuid_compat

from itrader.core.enums import FillStatus, OrderType, Side
from itrader.core.enums.order import (
    OrderCommand,
    OrderStatus,
    VALID_ORDER_TRANSITIONS,
    order_command_map,
)
from itrader.events_handler.events import FillEvent, OrderEvent

_STRATEGY_ID = uuid_compat.uuid7()


def _order_event():
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker="BTCUSDT", action=Side.BUY,
        price=40.0, quantity=1.0, exchange="default", strategy_id=_STRATEGY_ID,
        portfolio_id=1, order_type=OrderType.MARKET, order_id=7,
    )


def test_order_command_expire_value():
    assert OrderCommand.EXPIRE.value == "EXPIRE"


def test_order_command_map_has_expire():
    assert order_command_map["EXPIRE"] is OrderCommand.EXPIRE


def test_order_command_expire_case_insensitive_missing():
    # _missing_ resolves a lowercase string to the EXPIRE member.
    assert OrderCommand("expire") is OrderCommand.EXPIRE


def test_fill_status_expired_value():
    assert FillStatus.EXPIRED.value == "EXPIRED"


def test_fill_status_expired_case_insensitive_missing():
    assert FillStatus("expired") is FillStatus.EXPIRED


def test_new_fill_expired_does_not_raise():
    # Pitfall 2 closed: FillStatus(status) parse in new_fill no longer raises
    # ValueError for the "EXPIRED" string once the member exists.
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXPIRED", order, price=order.price, quantity=order.quantity,
        commission=Decimal("0"),
    )
    assert fill.status is FillStatus.EXPIRED
    assert fill.order_id == 7


def test_order_status_expired_transition_table_unchanged():
    # Regression guard: the pre-existing EXPIRED transition rows are unchanged.
    assert VALID_ORDER_TRANSITIONS[OrderStatus.EXPIRED] == []
    assert OrderStatus.EXPIRED in VALID_ORDER_TRANSITIONS[OrderStatus.PENDING]
