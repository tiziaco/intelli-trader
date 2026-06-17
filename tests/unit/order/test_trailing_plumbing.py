"""Plan 05-01 Task 1 — STATIC trailing-stop plumbing (TRAIL-01).

Covers the type/config-enum/event/entity/factory contracts the MatchingEngine
(05-02) and BracketManager (05-03) consume:
  - OrderType.TRAILING_STOP member + order_type_map entry
  - TrailType config-enum (PRICE/PERCENT) importable from itrader.config
  - Order.trail_type/trail_value fields + new_trailing_stop_order factory
  - OrderEvent.trail_type/trail_value carriage via new_order_event getattr read-back
  - non-trailing orders remain trail-field no-op (oracle-dark)

Folder-derived ``unit`` marker only (tests/conftest.py auto-applies it; no decorator
under --strict-markers). No backtesting/backtrader import (Pitfall 3).
"""

from datetime import datetime
from decimal import Decimal

import pytest

from itrader.config import TrailType
from itrader.core.enums import Side
from itrader.core.enums.order import OrderType, order_type_map
from itrader.events_handler.events.order import OrderEvent
from itrader.order_handler.order import Order


class TestTrailingTypePlumbing:
    def test_order_type_trailing_stop_member(self):
        assert OrderType("trailing_stop") is OrderType.TRAILING_STOP
        assert OrderType("TRAILING_STOP") is OrderType.TRAILING_STOP

    def test_order_type_map_entry(self):
        assert order_type_map["TRAILING_STOP"] is OrderType.TRAILING_STOP

    def test_trail_type_values(self):
        assert TrailType("price") is TrailType.PRICE
        assert TrailType("percent") is TrailType.PERCENT


class TestTrailingFactory:
    base_time = datetime(2020, 1, 1)

    def test_new_trailing_stop_order_type_and_fields(self):
        order = Order.new_trailing_stop_order(
            self.base_time, "BTCUSD", Side.SELL, 95.0, 100.0, "binance", 1, 1,
            trail_type=TrailType.PERCENT, trail_value=Decimal("0.02"),
        )
        assert order.type is OrderType.TRAILING_STOP
        assert order.trail_type is TrailType.PERCENT
        assert order.trail_value == Decimal("0.02")

    def test_new_trailing_stop_order_carries_leverage(self):
        order = Order.new_trailing_stop_order(
            self.base_time, "BTCUSD", Side.SELL, 95.0, 100.0, "binance", 1, 1,
            trail_type=TrailType.PRICE, trail_value=Decimal("5"), leverage=Decimal("3"),
        )
        assert order.leverage == Decimal("3")

    def test_trail_value_entered_via_to_money(self):
        # D-TRAIL-8: float trail_value enters Decimal via to_money (never Decimal(float)).
        order = Order.new_trailing_stop_order(
            self.base_time, "BTCUSD", Side.SELL, 95.0, 100.0, "binance", 1, 1,
            trail_type=TrailType.PRICE, trail_value=5.0,
        )
        assert order.trail_value == Decimal("5")


class TestTrailingEventCarriage:
    base_time = datetime(2020, 1, 1)

    def test_trailing_order_event_carries_trail_fields(self):
        order = Order.new_trailing_stop_order(
            self.base_time, "BTCUSD", Side.SELL, 95.0, 100.0, "binance", 1, 1,
            trail_type=TrailType.PERCENT, trail_value=Decimal("0.02"),
        )
        event = OrderEvent.new_order_event(order)
        assert event.trail_type is TrailType.PERCENT
        assert event.trail_value == Decimal("0.02")

    def test_non_trailing_order_event_trail_fields_none(self):
        order = Order.new_stop_order(
            self.base_time, "BTCUSD", Side.BUY, 40.0, 100.0, "binance", 1, 1,
        )
        event = OrderEvent.new_order_event(order)
        assert event.trail_type is None
        assert event.trail_value is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
