"""Plan 05-01 Task 2 — D-TRAIL-7 non-viable-trail rejection (TRAIL-01).

The EnhancedOrderValidator rejects a non-viable trail BEFORE the order rests
(threat T-05-02): a PERCENT trail >= 1, a PRICE trail >= the reference price, or a
TRAILING_STOP missing trail_value/trail_type. A viable trail passes. The same
disposition is mirrored in SimulatedExchange.validate_order (dual-layer agreement,
D-03a) — a trailing order with a positive initial stop passes the positive-price
gate in BOTH layers.

Folder-derived ``unit`` marker only (tests/conftest.py auto-applies it; no decorator
under --strict-markers). No backtesting/backtrader import (Pitfall 3).
"""

from datetime import datetime
from decimal import Decimal

import pytest

from itrader.config import TrailType
from itrader.core.enums import Side
from itrader.core.enums.order import OrderType, OrderStatus
from itrader.order_handler.order import Order
from itrader.order_handler.order_validator import (
    EnhancedOrderValidator,
    ValidationLevel,
)

_BASE_TIME = datetime(2020, 1, 1)


def _trailing_order(trail_type, trail_value, price=Decimal("100")):
    """Build a TRAILING_STOP Order directly so a non-viable trail can be tested.

    The factory enforces to_money on trail_value; for the None/<=0 cases we
    construct the entity directly to bypass the factory's coercion.
    """
    order = Order(
        _BASE_TIME,
        OrderType.TRAILING_STOP,
        OrderStatus.PENDING,
        "BTCUSD",
        Side.SELL,
        price,
        Decimal("1"),
        "binance",
        1,
        1,
    )
    order.trail_type = trail_type
    order.trail_value = trail_value
    return order


def _has_invalid_trail_error(messages):
    return any(
        m.level == ValidationLevel.ERROR and m.code == "INVALID_TRAIL"
        for m in messages
    )


class TestTrailingReject:
    def setup_method(self):
        self.validator = EnhancedOrderValidator()

    def test_trailing_reject_percent_ge_one(self):
        order = _trailing_order(TrailType.PERCENT, Decimal("1.0"))
        result = self.validator.validate_order_pipeline(order)
        assert not result.success
        assert _has_invalid_trail_error(result.messages)

    def test_trailing_reject_absolute_ge_reference_price(self):
        # PRICE trail_value >= reference price (the initial stop) -> reject.
        order = _trailing_order(TrailType.PRICE, Decimal("100"), price=Decimal("100"))
        result = self.validator.validate_order_pipeline(order)
        assert not result.success
        assert _has_invalid_trail_error(result.messages)

    def test_trailing_reject_missing_trail_value(self):
        order = _trailing_order(None, None)
        result = self.validator.validate_order_pipeline(order)
        assert not result.success
        assert _has_invalid_trail_error(result.messages)

    def test_trailing_reject_nonpositive_trail_value(self):
        order = _trailing_order(TrailType.PRICE, Decimal("0"))
        result = self.validator.validate_order_pipeline(order)
        assert not result.success
        assert _has_invalid_trail_error(result.messages)

    def test_viable_percent_trail_passes(self):
        order = _trailing_order(TrailType.PERCENT, Decimal("0.02"))
        result = self.validator.validate_order_pipeline(order)
        # No INVALID_TRAIL error (other phases may add warnings, but the trail
        # itself is viable).
        assert not _has_invalid_trail_error(result.messages)

    def test_viable_price_trail_passes(self):
        order = _trailing_order(TrailType.PRICE, Decimal("5"), price=Decimal("100"))
        result = self.validator.validate_order_pipeline(order)
        assert not _has_invalid_trail_error(result.messages)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
