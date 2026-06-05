from datetime import datetime
from queue import Queue

import pytest

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.event import OrderEvent, SignalEvent
from itrader.core.enums import OrderType


_STRATEGY_ID = 1


class _OnSignalHarness:
    """OrderHandler harness with a single funded portfolio and a signal factory."""

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        # One portfolio per harness instance (per-test, like the legacy setUp).
        self.last_ptf_id = self.ptf_handler.add_portfolio(1, "test_ptf", "default", 10000)

    def create_mock_signal(
        self, action, ticker="BTCUSDT", quantity=100.0, price=40.0,
        order_type="MARKET", stop_loss=0.0, take_profit=0.0,
    ):
        """Create a mock signal with proper quantity for testing."""
        return SignalEvent(
            time=datetime.now(),
            order_type=order_type,
            ticker=ticker,
            action=action,
            price=price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_id=_STRATEGY_ID,
            portfolio_id=self.last_ptf_id,
            strategy_setting={},
        )


@pytest.fixture
def harness():
    h = _OnSignalHarness()
    yield h
    # Drain the queue after each test to prevent cross-test bleed.
    while not h.queue.empty():
        try:
            h.queue.get_nowait()
        except Exception:
            break


def test_on_signal_buy(harness):
    buy_signal = harness.create_mock_signal("BUY", quantity=100.0, price=40.0)

    harness.order_handler.on_signal(buy_signal)

    order_event: OrderEvent = harness.queue.get(False)

    assert isinstance(order_event, OrderEvent)
    assert order_event.ticker == "BTCUSDT"
    assert order_event.action == "BUY"
    assert order_event.quantity == 100.0


def test_on_signal_sell(harness):
    sell_signal = harness.create_mock_signal("SELL", quantity=50.0, price=40.0)

    harness.order_handler.on_signal(sell_signal)

    order_event: OrderEvent = harness.queue.get(False)

    assert isinstance(order_event, OrderEvent)
    assert order_event.ticker == "BTCUSDT"
    assert order_event.action == "SELL"
    assert order_event.quantity == 50.0


def test_on_signal_buy_with_sl_tp(harness):
    buy_signal = harness.create_mock_signal(
        "BUY", quantity=100.0, price=40.0, stop_loss=30.0, take_profit=50.0
    )

    harness.order_handler.on_signal(buy_signal)

    # Drain all 3 order events: MARKET (primary) + STOP (SL) + LIMIT (TP)
    emitted = [harness.queue.get(False) for _ in range(harness.queue.qsize())]
    order_events = [
        e for e in emitted if isinstance(e, OrderEvent) and e.type.name == "ORDER"
    ]
    # Find the primary MARKET order event
    primary_event = next(e for e in order_events if e.order_type == OrderType.MARKET)
    pending_orders = harness.order_handler.order_storage.get_pending_orders()
    portfolio_orders = pending_orders.get(primary_event.portfolio_id, {})

    assert primary_event.ticker == "BTCUSDT"
    assert primary_event.action == "BUY"
    assert primary_event.quantity == 100.0
    # All 3 legs emitted
    assert len(order_events) == 3
    # All 3 orders remain pending (market order is filled by execution handler, not self-filled)
    assert isinstance(pending_orders, dict)
    assert len(portfolio_orders) == 3  # MARKET, SL and TP orders all pending


def test_on_signal_sell_with_sl_tp(harness):
    sell_signal = harness.create_mock_signal(
        "SELL", quantity=50.0, price=40.0, stop_loss=30.0, take_profit=50.0
    )

    harness.order_handler.on_signal(sell_signal)

    # Drain all 3 order events: MARKET (primary) + STOP (SL) + LIMIT (TP)
    emitted = [harness.queue.get(False) for _ in range(harness.queue.qsize())]
    order_events = [
        e for e in emitted if isinstance(e, OrderEvent) and e.type.name == "ORDER"
    ]
    # Find the primary MARKET order event
    primary_event = next(e for e in order_events if e.order_type == OrderType.MARKET)
    pending_orders = harness.order_handler.order_storage.get_pending_orders()
    portfolio_orders = pending_orders.get(primary_event.portfolio_id, {})

    assert primary_event.ticker == "BTCUSDT"
    assert primary_event.action == "SELL"
    assert primary_event.quantity == 50.0
    # All 3 legs emitted
    assert len(order_events) == 3
    # All 3 orders remain pending (market order is filled by execution handler, not self-filled)
    assert isinstance(pending_orders, dict)
    assert len(portfolio_orders) == 3  # MARKET, SL and TP orders all pending
