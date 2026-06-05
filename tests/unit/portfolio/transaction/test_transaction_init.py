from decimal import Decimal
from datetime import datetime

import pytest

from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.events_handler.event import SignalEvent, OrderEvent, FillEvent
from itrader.order_handler.order import Order


@pytest.fixture
def fill_event():
    """A fresh EXECUTED FillEvent built from a market BUY signal."""
    time = datetime.now()
    signal_event = SignalEvent(
        time=time,
        order_type="MARKET",
        ticker="BTCUSDT",
        action="BUY",
        price=42350.72,
        quantity=1,
        stop_loss=42000,
        take_profit=45000,
        strategy_id="test_strategy",
        portfolio_id="portfolio_id",
        strategy_setting={},
    )
    order = Order.new_order(signal_event, "simulated")
    mkt_order_event = OrderEvent.new_order_event(order)
    return FillEvent.new_fill(
        "EXECUTED", mkt_order_event,
        price=mkt_order_event.price, quantity=mkt_order_event.quantity, commission=1.5)


def test_transaction_initialization(fill_event):
    transaction = Transaction.new_transaction(fill_event)

    assert isinstance(transaction, Transaction)
    assert transaction.type == TransactionType.BUY
    assert type(transaction.time) is datetime
    assert transaction.ticker == "BTCUSDT"
    # Money is Decimal end-to-end (D-02/D-04): entered via to_money(str(x)),
    # so price equals the exact Decimal, not the binary float 42350.72.
    assert isinstance(transaction.price, Decimal)
    assert transaction.price == Decimal("42350.72")
    assert transaction.quantity == 1
    assert transaction.portfolio_id == "portfolio_id"
