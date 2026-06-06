import uuid
from datetime import datetime

import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.position import Position, PositionSide


_TICKER = "BTCUSDT"
_PORTFOLIO_ID = "portfolio_id"


def test_short_position_multiple_sell():
    time = datetime.now()
    sell_transaction = Transaction(
        time, TransactionType.SELL, _TICKER, 42000, 1, 0, _PORTFOLIO_ID, id=1, fill_id=uuid_compat.uuid7()
    )
    position = Position.open_position(sell_transaction)
    # Increase Short position
    time = datetime.now()
    buy_transaction_2 = Transaction(
        time, TransactionType.SELL, _TICKER, 40000, 4, 0, _PORTFOLIO_ID, id=2, fill_id=uuid_compat.uuid7()
    )
    position.update_position(buy_transaction_2)

    assert isinstance(position, Position)
    assert isinstance(position.id, uuid.UUID)  # ids are native UUIDv7
    assert position.ticker == "BTCUSDT"
    assert position.portfolio_id == "portfolio_id"

    assert position.is_open is True
    assert position.side == PositionSide.SHORT
    assert position.buy_quantity == 0
    assert position.sell_quantity == 5
    assert position.avg_bought == 0
    assert position.avg_sold == 40400
    assert position.avg_price == 40400
    assert position.market_value == -200000  # Negative for short positions
    assert position.total_bought == 0
    assert position.total_sold == 202000
    assert position.net_total == 2000
    assert position.realised_pnl == 0
    assert position.unrealised_pnl == 2000
