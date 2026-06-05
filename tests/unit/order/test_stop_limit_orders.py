from datetime import datetime
from queue import Queue

import pandas as pd
import pytest

from itrader.order_handler.order_handler import OrderHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.event import SignalEvent, BarEvent, FillStatus, EventType


class _StopLimitHarness:
    """Order-handler + simulated-exchange harness for resting stop/limit flows."""

    def __init__(self):
        self.queue = Queue()
        self.ptf = PortfolioHandler(self.queue)
        self.storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf, self.storage)
        self.execution = ExecutionHandler(self.queue)
        exchange = self.execution.exchanges["simulated"]
        exchange.connect()
        exchange.update_config(supported_symbols={"BTCUSDT"})
        self.pid = self.ptf.add_portfolio(1, "p", "simulated", 100000)

    def signal(self, action, order_type="MARKET", price=40.0, stop_loss=0.0, take_profit=0.0):
        return SignalEvent(
            time=datetime(2024, 1, 1), order_type=order_type, ticker="BTCUSDT",
            action=action, price=price, quantity=1.0, stop_loss=stop_loss,
            take_profit=take_profit, strategy_id=1, portfolio_id=self.pid,
            strategy_setting={},
        )

    def bar(self, open_, high, low, close):
        bars = {
            "BTCUSDT": pd.DataFrame(
                {"open": [open_], "high": [high], "low": [low], "close": [close], "volume": [1]}
            )
        }
        return BarEvent(time=datetime(2024, 1, 1), bars=bars)

    def route_orders(self):
        """Drain ORDER events from the queue into the execution handler."""
        pending = []
        while not self.queue.empty():
            pending.append(self.queue.get())
        for ev in pending:
            if ev.type == EventType.ORDER:
                self.execution.on_order(ev)

    def drain_fills(self):
        fills = []
        while not self.queue.empty():
            ev = self.queue.get()
            if ev.type == EventType.FILL:
                fills.append(ev)
        return fills


@pytest.fixture
def harness():
    h = _StopLimitHarness()
    yield h
    while not h.queue.empty():
        h.queue.get_nowait()


def test_stop_loss_rests_then_fills_on_breach(harness):
    harness.order_handler.on_signal(harness.signal("BUY", stop_loss=30.0))
    harness.route_orders()
    # Drain the BUY entry fill before processing the bar
    harness.drain_fills()
    harness.execution.on_market_data(harness.bar(open_=38, high=39, low=20, close=25))
    executed = [f for f in harness.drain_fills() if f.status == FillStatus.EXECUTED]
    assert any(f.action == "SELL" for f in executed)


def test_take_profit_fill_cancels_stop_via_oco(harness):
    harness.order_handler.on_signal(harness.signal("BUY", stop_loss=30.0, take_profit=55.0))
    harness.route_orders()
    # Drain the BUY entry fill before processing the bar
    harness.drain_fills()
    # Bar pierces the TP (high 60 >= 55) but not the SL (low 40 > 30).
    harness.execution.on_market_data(harness.bar(open_=50, high=60, low=40, close=58))
    statuses = [(ev.action, ev.status) for ev in harness.drain_fills()]
    assert ("SELL", FillStatus.EXECUTED) in statuses
    assert ("SELL", FillStatus.CANCELLED) in statuses


def test_stop_does_not_fill_when_not_breached(harness):
    harness.order_handler.on_signal(harness.signal("BUY", stop_loss=30.0))
    harness.route_orders()
    # Drain the BUY entry fill before processing the bar
    harness.drain_fills()
    harness.execution.on_market_data(harness.bar(open_=40, high=45, low=35, close=42))
    sell_fills = [f for f in harness.drain_fills() if f.action == "SELL"]
    assert sell_fills == []
