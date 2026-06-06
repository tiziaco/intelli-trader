import uuid
from datetime import datetime

import uuid_utils.compat as uuid_compat

import pytest

from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.position import Position, PositionSide


_TICKER = "BTCUSDT"
_PORTFOLIO_ID = "portfolio_id"


def test_long_position_multiple_buy():
    # Open position
    time = datetime.now()
    # TODO: use Transaction.new_transaction() or implement an auto generate ID method
    buy_transaction_1 = Transaction(
        time, TransactionType.BUY, _TICKER, 42000, 1, 0, _PORTFOLIO_ID, id=1, fill_id=uuid_compat.uuid7()
    )
    position = Position.open_position(buy_transaction_1)
    # Increase Long position
    time = datetime.now()
    buy_transaction_2 = Transaction(
        time, TransactionType.BUY, _TICKER, 50000, 2, 0, _PORTFOLIO_ID, id=2, fill_id=uuid_compat.uuid7()
    )
    position.update_position(buy_transaction_2)

    assert isinstance(position, Position)
    assert isinstance(position.id, uuid.UUID)  # ids are native UUIDv7
    assert position.ticker == "BTCUSDT"
    assert position.portfolio_id == "portfolio_id"

    assert position.is_open is True
    assert position.side == PositionSide.LONG
    assert position.buy_quantity == 3
    assert position.sell_quantity == 0
    # Money is Decimal end-to-end (M2a): coerce the computed Decimal to float
    # for the tolerance comparison (approx cannot mix Decimal/float).
    assert float(position.avg_bought) == pytest.approx(47333.33, abs=0.01)
    assert position.avg_sold == 0
    assert float(position.avg_price) == pytest.approx(47333.33, abs=0.01)
    assert position.market_value == 150000
    assert position.total_bought == 142000
    assert position.total_sold == 0
    assert float(position.net_total) == pytest.approx(8000, abs=0.01)
    assert position.realised_pnl == 0
    assert float(position.unrealised_pnl) == pytest.approx(8000, abs=0.01)
