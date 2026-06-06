import uuid
from datetime import datetime

import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.position import Position, PositionSide


_TICKER = "BTCUSDT"
_PORTFOLIO_ID = "portfolio_id"


def test_open_long_position():
    time = datetime.now()
    buy_transaction = Transaction(
        time, TransactionType.BUY, _TICKER, 42000, 1, 0, _PORTFOLIO_ID, id=1, fill_id=uuid_compat.uuid7()
    )
    position = Position.open_position(buy_transaction)

    assert isinstance(position, Position)
    assert isinstance(position.id, uuid.UUID)  # ids are native UUIDv7
    assert position.ticker == "BTCUSDT"
    assert position.portfolio_id == "portfolio_id"

    assert position.is_open is True
    assert position.side == PositionSide.LONG
    assert position.buy_quantity == 1
    assert position.sell_quantity == 0
    assert position.avg_bought == 42000
    assert position.avg_sold == 0
    assert position.avg_price == 42000
    assert position.market_value == 42000
    assert position.total_bought == 42000
    assert position.total_sold == 0
    assert position.net_total == 0
    assert position.realised_pnl == 0
    assert position.unrealised_pnl == 0


def test_open_short_position():
    time = datetime.now()
    sell_transaction = Transaction(
        time, TransactionType.SELL, _TICKER, 42000, 1, 0, _PORTFOLIO_ID, id=2, fill_id=uuid_compat.uuid7()
    )
    position = Position.open_position(sell_transaction)

    assert isinstance(position, Position)
    assert isinstance(position.id, uuid.UUID)  # ids are native UUIDv7
    assert position.ticker == "BTCUSDT"
    assert position.portfolio_id == "portfolio_id"

    assert position.is_open is True
    assert position.side == PositionSide.SHORT
    assert position.buy_quantity == 0
    assert position.sell_quantity == 1
    assert position.avg_bought == 0
    assert position.avg_sold == 42000
    assert position.avg_price == 42000
    assert position.total_bought == 0
    assert position.total_sold == 42000
    assert position.net_total == 0
    assert position.realised_pnl == 0
    assert position.unrealised_pnl == 0


def test_update_price_time_long_position():
    time = datetime.now()
    buy_transaction = Transaction(
        time, TransactionType.BUY, _TICKER, 42000, 1, 0, _PORTFOLIO_ID, id=3, fill_id=uuid_compat.uuid7()
    )
    position = Position.open_position(buy_transaction)
    # Update price and time
    time = datetime.now()
    position.update_current_price_time(50000, time)

    assert isinstance(position, Position)
    assert isinstance(position.id, uuid.UUID)  # ids are native UUIDv7
    assert position.ticker == "BTCUSDT"
    assert position.portfolio_id == "portfolio_id"

    assert position.is_open is True
    assert position.side == PositionSide.LONG
    assert position.buy_quantity == 1
    assert position.sell_quantity == 0
    assert position.avg_bought == 42000
    assert position.avg_sold == 0
    assert position.avg_price == 42000
    assert position.market_value == 50000
    assert position.total_bought == 42000
    assert position.total_sold == 0
    assert position.net_total == 8000
    assert position.realised_pnl == 0
    assert position.unrealised_pnl == 8000


def test_update_price_time_short_position():
    time = datetime.now()
    sell_transaction = Transaction(
        time, TransactionType.SELL, _TICKER, 42000, 1, 0, _PORTFOLIO_ID, id=4, fill_id=uuid_compat.uuid7()
    )
    position = Position.open_position(sell_transaction)
    # Update price and time
    time = datetime.now()
    position.update_current_price_time(50000, time)

    assert isinstance(position, Position)
    assert isinstance(position.id, uuid.UUID)  # ids are native UUIDv7
    assert position.ticker == "BTCUSDT"
    assert position.portfolio_id == "portfolio_id"

    assert position.is_open is True
    assert position.side == PositionSide.SHORT
    assert position.buy_quantity == 0
    assert position.sell_quantity == 1
    assert position.avg_bought == 0
    assert position.avg_sold == 42000
    assert position.avg_price == 42000
    assert position.market_value == -50000  # Negative for short positions
    assert position.total_bought == 0
    assert position.total_sold == 42000
    assert position.net_total == -8000
    assert position.realised_pnl == 0
    assert position.unrealised_pnl == -8000
