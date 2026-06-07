from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.core.bar import Bar
from itrader.order_handler.order_handler import OrderHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import SignalEvent, BarEvent
from itrader.core.enums import EventType, FillStatus, OrderType, Side
from itrader.core.sizing import FractionOfCash, TradingDirection


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
            time=datetime(2024, 1, 1), order_type=OrderType(order_type), ticker="BTCUSDT",
            action=Side(action), price=price, quantity=1.0, stop_loss=stop_loss,
            take_profit=take_profit, strategy_id=1, portfolio_id=self.pid,
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
        )

    def bar(self, open_, high, low, close, time=datetime(2024, 1, 2)):
        # Defaults to the bar AFTER the signal tick (signals are stamped
        # 2024-01-01): under D-01/D-13 fills come from the NEXT bar.
        bars = {
            "BTCUSDT": Bar(
                time=time, open=Decimal(str(open_)), high=Decimal(str(high)),
                low=Decimal(str(low)), close=Decimal(str(close)), volume=Decimal("1"),
            )
        }
        return BarEvent(time=time, bars=bars)

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


def test_entry_rests_then_fills_at_next_open_and_stop_triggers_same_bar(harness):
    harness.order_handler.on_signal(harness.signal("BUY", stop_loss=30.0))
    harness.route_orders()
    # D-01/D-13: the market entry RESTS — no fill on the same drain as the
    # OrderEvent (the order mirror stays PENDING until exchange truth lands).
    assert harness.drain_fills() == []

    # The follow-up bar fills the entry at ITS OPEN (38, stamped with the
    # bar's time) and the SL child triggers against the SAME bar's low.
    bar = harness.bar(open_=38, high=39, low=20, close=25)
    harness.execution.on_market_data(bar)
    fills = harness.drain_fills()
    executed = [f for f in fills if f.status == FillStatus.EXECUTED]
    buys = [f for f in executed if f.action is Side.BUY]
    assert len(buys) == 1
    assert buys[0].price == Decimal("38")     # next bar's open, exact
    assert buys[0].time == bar.time           # T+1tf fill stamp
    assert any(f.action is Side.SELL for f in executed)  # SL same-bar trigger


def test_take_profit_fill_cancels_stop_via_oco(harness):
    harness.order_handler.on_signal(harness.signal("BUY", stop_loss=30.0, take_profit=55.0))
    harness.route_orders()
    # Entry rests — no same-drain fill (D-01/D-13).
    assert harness.drain_fills() == []
    # The bar fills the entry at its open (50), pierces the TP (high 60 >= 55)
    # but not the SL (low 40 > 30): TP fills, SL is OCO-cancelled.
    harness.execution.on_market_data(harness.bar(open_=50, high=60, low=40, close=58))
    statuses = [(ev.action, ev.status) for ev in harness.drain_fills()]
    assert (Side.BUY, FillStatus.EXECUTED) in statuses
    assert (Side.SELL, FillStatus.EXECUTED) in statuses
    assert (Side.SELL, FillStatus.CANCELLED) in statuses


def test_stop_does_not_fill_when_not_breached(harness):
    harness.order_handler.on_signal(harness.signal("BUY", stop_loss=30.0))
    harness.route_orders()
    # Entry rests — no same-drain fill (D-01/D-13).
    assert harness.drain_fills() == []
    # The bar fills the entry at its open; the SL (30) is never breached
    # (low 35 > 30) so no SELL fill is produced.
    harness.execution.on_market_data(harness.bar(open_=40, high=45, low=35, close=42))
    fills = harness.drain_fills()
    assert any(f.action is Side.BUY and f.status is FillStatus.EXECUTED for f in fills)
    sell_fills = [f for f in fills if f.action is Side.SELL]
    assert sell_fills == []
