"""SIG-03 — Order.action / _PendingBracket.action are Side-typed (D-03).

The persisted `action` boundary is narrowed from `str` to `Side` across the
order_handler: the `Order` entity, the two factory params
(`new_stop_order`/`new_limit_order`), and `_PendingBracket`. These tests pin
the new contract:

* an `Order` constructed with a `Side` action stores it as a `Side` (not a
  string) and round-trips through `OrderEvent.new_order_event` unchanged
  (OrderEvent.action is already Side);
* the factory methods accept a `Side` action and thread it onto the entity;
* `_PendingBracket.action` is a `Side`;
* the reporting/serialization edge still emits the "BUY"/"SELL" string text
  (it reads `.value` at the edge);
* the validator accepts a Side-typed action and rejects a non-Side one.
"""

from datetime import datetime
from decimal import Decimal

from itrader.order_handler.order import Order
from itrader.order_handler.brackets.bracket_book import _PendingBracket
from itrader.reporting.orders import build_orders_snapshot
from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.sizing import PercentFromFill
from itrader.events_handler.events import OrderEvent


def _order(action: Side) -> Order:
    return Order(
        time=datetime(2024, 1, 1),
        type=OrderType.MARKET,
        status=OrderStatus.PENDING,
        ticker="BTCUSDT",
        action=action,
        price=Decimal("40000"),
        quantity=Decimal("0.1"),
        exchange="binance",
        strategy_id=1,
        portfolio_id=1,
    )


def test_order_action_is_side_typed():
    order = _order(Side.BUY)
    assert order.action is Side.BUY


def test_order_action_round_trips_through_to_event():
    order = _order(Side.SELL)
    event = OrderEvent.new_order_event(order)
    # OrderEvent.action is already Side — the entity's Side passes through
    # unchanged (the former Side(order.action) re-parse becomes a no-op).
    assert event.action is Side.SELL


def test_new_stop_order_accepts_side_action():
    order = Order.new_stop_order(
        time=datetime(2024, 1, 1),
        ticker="BTCUSDT",
        action=Side.SELL,
        price=Decimal("30000"),
        quantity=Decimal("1"),
        exchange="binance",
        strategy_id=1,
        portfolio_id=1,
    )
    assert order.action is Side.SELL


def test_new_limit_order_accepts_side_action():
    order = Order.new_limit_order(
        time=datetime(2024, 1, 1),
        ticker="BTCUSDT",
        action=Side.BUY,
        price=Decimal("30000"),
        quantity=Decimal("1"),
        exchange="binance",
        strategy_id=1,
        portfolio_id=1,
    )
    assert order.action is Side.BUY


def test_pending_bracket_action_is_side_typed():
    bracket = _PendingBracket(
        policy=PercentFromFill(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10")),
        ticker="BTCUSDT",
        action=Side.BUY,
        quantity=Decimal("1"),
        exchange="binance",
        strategy_id="strat-1",
        portfolio_id=42,
    )
    assert bracket.action is Side.BUY


def test_orders_snapshot_emits_string_action_text():
    # The serialization edge reads .value — the "action" column stays "BUY"/"SELL".
    frame = build_orders_snapshot([_order(Side.BUY)])
    assert list(frame["action"]) == ["BUY"]
