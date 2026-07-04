"""A5 (D-08 / V17-06) RED gate — a RE-DELIVERED venue trade must NOT double-count.

CONF-A spine (D-19), Wave-1 slice 2. This is an EXPECTED-FAILING regression test: it
pins the V17-06 duplicate-fill-corruption bug and turns GREEN only once the D-08 durable
per-trade dedup lands in Phase 05.2. It MUST be RED against current code — that is the
success condition of a CONF-A spine plan, NOT a broken build.

The bug (V17-06)
----------------
``ReconcileManager._apply_executed`` (reconcile_manager.py:127-216) accumulates each
EXECUTED increment onto ``order.filled_quantity`` and consults NO durable per-trade
idempotency key. The exchange-side de-dup lives only in the in-memory
``VenueCorrelationIndex`` — which is EMPTY after a process restart. So when a partial
trade ``T1`` is re-delivered through the FILL route post-restart (the reconciler's
``fetch_my_trades`` catch-up, or a reconnect replay), the mirror re-accumulates the SAME
trade: ``filled_quantity`` doubles from 0.2 to 0.4. The order mirror is now corrupt.

Offline reproduction
--------------------
Drive the REAL reconcile FILL route (``ReconcileManager.on_fill``) against a real
``Order`` twice with the SAME ``venue_trade_id`` — the second delivery simulates the
post-restart re-emission with a fresh (empty) exchange index. No manual mirror mutation:
the accumulation is the production ``_apply_executed`` path. The two FillEvents carry
distinct ``fill_id`` (a fresh identity per emission) but the SAME ``venue_trade_id`` (the
stable venue TradeID shared across the two live emitters).

Expected today (RED): ``filled_quantity`` doubles to 0.4. Expected after D-08 (Phase
05.2): a durable ``venue_trade_id`` dedup inside ``_apply_executed`` makes the second
delivery a no-op, so ``filled_quantity`` stays 0.2.

Import-clean, fully offline (no network). Folder-derived ``unit`` marker.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from itrader.core.enums import FillStatus, OrderStatus, OrderType, Side
from itrader.core.ids import OrderId, PortfolioId
from itrader.events_handler.events import FillEvent
from itrader.order_handler.order import Order
from itrader.order_handler.reconcile.reconcile_manager import ReconcileManager


class _FixedStorage:
    """Returns a single fixed order and records ``update_order`` calls (the mirror moves)."""

    def __init__(self, order: Order) -> None:
        self._order = order
        self.update_calls = 0

    def get_order_by_id(self, order_id, portfolio_id=None):
        return self._order

    def update_order(self, order) -> bool:
        self.update_calls += 1
        return True

    def get_active_orders(self, portfolio_id):
        return []


def _make_manager(order: Order) -> ReconcileManager:
    """Wire a ReconcileManager around a real Order + a fixed storage.

    A PARTIAL EXECUTED fill never terminalizes, so the reservation-release, bracket
    ``consume`` and portfolio ``get_position`` branches are all skipped — the brackets /
    bracket_manager / cancel_order / portfolio collaborators are unused Mocks.
    """
    return ReconcileManager(
        order_storage=_FixedStorage(order),
        logger=Mock(),
        portfolio_handler=Mock(),
        brackets=Mock(),
        bracket_manager=Mock(),
        cancel_order=Mock(),
    )


def _partial_fill(order: Order, venue_trade_id: str) -> FillEvent:
    """A fresh EXECUTED partial FillEvent for ``order`` carrying ``venue_trade_id``.

    Each emission mints a NEW ``fill_id`` (a distinct fill identity) but reuses the SAME
    ``venue_trade_id`` — modelling a re-delivery of the one underlying venue trade.
    """
    return FillEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        status=FillStatus.EXECUTED,
        ticker=order.ticker,
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("0.2"),
        commission=Decimal("0"),
        portfolio_id=order.portfolio_id,
        fill_id=uuid.uuid4(),
        order_id=order.id,
        strategy_id=order.strategy_id,
        venue_trade_id=venue_trade_id,
    )


def test_redeliver_dedup_leaves_filled_quantity_unchanged() -> None:
    """Re-delivering the SAME venue trade must not re-accumulate ``filled_quantity``.

    RED today: the mirror double-counts (0.2 -> 0.4) because there is no durable
    ``venue_trade_id`` dedup. GREEN after D-08 (Phase 05.2).
    """
    portfolio_id = PortfolioId(uuid.uuid4())
    order_id = OrderId(uuid.uuid4())
    order = Order(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        type=OrderType.LIMIT,
        status=OrderStatus.PENDING,
        ticker="BTC-USDT",
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("1.0"),
        exchange="okx",
        strategy_id=1,
        portfolio_id=portfolio_id,
        id=order_id,
    )
    manager = _make_manager(order)

    # Adopt the partial T1 through the real FILL route -> filled 0.2 (a strict partial
    # against remaining 1.0, so the order stays PARTIALLY_FILLED, reservation HELD).
    manager.on_fill(_partial_fill(order, venue_trade_id="T1"))
    assert order.filled_quantity == Decimal("0.2")
    assert order.status == OrderStatus.PARTIALLY_FILLED

    # Re-deliver the SAME T1 (fresh exchange index / post-restart replay) through the
    # SAME FILL route. A durable per-trade dedup must make this a no-op.
    manager.on_fill(_partial_fill(order, venue_trade_id="T1"))

    assert order.filled_quantity == Decimal("0.2"), (
        "V17-06: the re-delivered venue trade T1 was double-counted — "
        f"filled_quantity={order.filled_quantity} (expected an unchanged 0.2). The "
        "mirror has no durable venue_trade_id dedup; D-08 (Phase 05.2) must add one."
    )
