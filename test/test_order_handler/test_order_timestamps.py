"""M2-09 tests: order timestamps are event-derived; modify_order routes the validated path.

Phase 3 (M2b) Plan 03-07, Task 2. These pin the determinism behaviors the wave delivers:

  1. ``Order.add_state_change(..., time=event_time)`` records the EVENT time (not
     ``datetime.now()``) — for the recorded ``OrderStateChange.timestamp`` and for
     ``updated_at`` / ``filled_at`` / ``cancelled_at`` / ``expired_at``.
  2. ``add_fill`` threads its ``fill_time`` INTO the recorded transition timestamp
     (not only into ``additional_data["fill_time"]``).
  3. ``modify_order`` routes through ``add_state_change`` — no direct
     ``self.state_changes.append(...)`` — and stamps the modification with an
     event-derived time.
  4. No bare ``datetime.now()`` remains on the add_state_change / modify_order path.

Order-audit timestamps are excluded from the oracle (Phase-1 D-12), so this is oracle-safe.

NOTE (03-08): this file MOVES with the test tree into ``tests/unit/test_order_handler/``
during the 03-08 type-split — 03-08 reconciles it there without duplication.
"""

import inspect
from datetime import datetime
from decimal import Decimal

from itrader.order_handler import order as order_module
from itrader.order_handler.order import Order
from itrader.core.enums import OrderType, OrderStatus


EVENT_TIME = datetime(2020, 1, 1, 12, 0, 0)
FILL_TIME = datetime(2021, 6, 15, 9, 30, 0)
MODIFY_TIME = datetime(2022, 3, 3, 3, 3, 3)


def _make_order(status=OrderStatus.PENDING, quantity=10):
    return Order(
        EVENT_TIME,
        OrderType.LIMIT,
        status,
        "BTCUSDT",
        "BUY",
        Decimal("100"),
        Decimal(str(quantity)),
        "binance",
        1,
        1,
    )


def test_add_state_change_records_event_time():
    """M2-09: add_state_change(time=event_time) stamps the recorded transition with event_time."""
    order = _make_order()
    assert order.add_state_change(OrderStatus.CANCELLED, "cancel", time=EVENT_TIME)
    change = order.get_latest_state_change()
    assert change is not None
    assert change.timestamp == EVENT_TIME


def test_add_state_change_stamps_specific_timestamp_fields_with_event_time():
    """M2-09: updated_at and the terminal-status field use the passed event time."""
    order = _make_order()
    order.add_state_change(OrderStatus.FILLED, "fill", time=FILL_TIME)
    assert order.updated_at == FILL_TIME
    assert order.filled_at == FILL_TIME


def test_add_state_change_cancelled_and_expired_use_event_time():
    """M2-09: cancelled_at / expired_at are event-derived."""
    order_c = _make_order()
    order_c.add_state_change(OrderStatus.CANCELLED, "cancel", time=EVENT_TIME)
    assert order_c.cancelled_at == EVENT_TIME

    order_e = _make_order()
    order_e.add_state_change(OrderStatus.EXPIRED, "expire", time=EVENT_TIME)
    assert order_e.expired_at == EVENT_TIME


def test_add_state_change_defaults_to_order_event_time():
    """M2-09: when no time is passed, the recorded timestamp defaults to the order's event time."""
    order = _make_order()
    order.add_state_change(OrderStatus.CANCELLED, "cancel")
    change = order.get_latest_state_change()
    assert change is not None
    assert change.timestamp == EVENT_TIME  # order.time, not wall-clock


def test_add_fill_threads_fill_time_into_recorded_timestamp():
    """M2-09: add_fill routes fill_time into the recorded transition timestamp."""
    order = _make_order(quantity=10)
    assert order.add_fill(Decimal("10"), Decimal("100"), FILL_TIME, "exchange fill")
    change = order.get_latest_state_change()
    assert change is not None
    # The state-change record timestamp equals the fill time (not wall-clock / not just
    # additional_data["fill_time"]).
    assert change.timestamp == FILL_TIME
    assert order.filled_at == FILL_TIME


def test_modify_order_routes_through_add_state_change():
    """M2-09: modify_order records its transition via add_state_change (no direct append)."""
    order = _make_order(quantity=10)
    before = len(order.state_changes)
    assert order.modify_order(new_price=Decimal("105"), reason="reprice", time=MODIFY_TIME)
    after = len(order.state_changes)
    assert after == before + 1
    change = order.get_latest_state_change()
    assert change is not None
    # Modification keeps the same status but is recorded as a tracked transition.
    assert change.from_status == change.to_status == order.status
    assert change.additional_data is not None and "new_price" in change.additional_data
    assert change.timestamp == MODIFY_TIME
    assert order.updated_at == MODIFY_TIME
    assert order.last_modification_time == MODIFY_TIME


def test_no_bare_datetime_now_in_add_state_change_or_modify_order():
    """M2-09: add_state_change / modify_order no longer call bare datetime.now()."""
    add_src = inspect.getsource(Order.add_state_change)
    modify_src = inspect.getsource(Order.modify_order)
    assert "datetime.now()" not in add_src
    assert "datetime.now()" not in modify_src
    # modify_order must not directly append to the state-change history.
    assert "self.state_changes.append" not in modify_src
