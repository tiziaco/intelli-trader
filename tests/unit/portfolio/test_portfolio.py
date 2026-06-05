from datetime import datetime

import pytest

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader import idgen


@pytest.fixture
def portfolio():
    """A fresh simulated portfolio funded with $150000."""
    return Portfolio(1, "test_pf", "simulated", 150000, datetime.now())


def test_long_position(portfolio):
    """
    Purchase/sell multiple lots of BTC and ETH at various prices/commissions to
    check the logic handling of the portfolio.
    """
    # Buy 1 of BTC over one transactions
    buy_txn = Transaction(datetime.now(), TransactionType.BUY,
                          "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn)

    # Sell 1 of BTC over one transactions
    sell_txn = Transaction(datetime.now(), TransactionType.SELL,
                           "BTCUSDT", 42000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_txn)

    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 1
    assert portfolio.cash == 152000
    assert portfolio.total_equity == 152000
    assert portfolio.total_unrealised_pnl == 0


def test_short_position(portfolio):
    """Sell then buy back a single BTC unit (short round-trip)."""
    # Sell 1 of BTC over one transactions
    sell_txn = Transaction(datetime.now(), TransactionType.SELL,
                           "BTCUSDT", 42000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_txn)

    # Buy 1 of BTC over one transactions
    buy_txn = Transaction(datetime.now(), TransactionType.BUY,
                          "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn)

    assert len(portfolio.positions) == 0
    assert len(portfolio.closed_positions) == 1
    assert portfolio.cash == 152000
    assert portfolio.total_equity == 152000
    assert portfolio.total_unrealised_pnl == 0


def test_multiple_buys_followed_by_sell(portfolio):
    # Buy 2 units of BTC at $38000
    buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 38000, 2, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn1)

    # Buy 1 unit of BTC at $40000
    buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn2)

    # Sell 1 unit of BTC at $45000
    sell_txn = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 45000, 3, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_txn)

    assert len(portfolio.positions) == 0  # No position remaining
    assert len(portfolio.closed_positions) == 1  # One position (BTCUSDT) closed
    assert portfolio.cash == 169000  # Cash after transactions
    assert portfolio.total_equity == 169000  # Total equity after transactions
    assert portfolio.total_unrealised_pnl == 0  # Total unrealized P&L
    assert portfolio.total_realised_pnl == pytest.approx(19000, abs=0.01)  # Total realized P&L


def test_sell_followed_by_multiple_buys(portfolio):
    # Sell 3 unit of BTC at $45000
    sell_txn = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 45000, 3, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_txn)

    # Buy 1 units of BTC at $40000
    buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn1)

    # Buy 2 unit of BTC at $38000
    buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 38000, 2, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn2)

    assert len(portfolio.positions) == 0  # No positions remaining
    assert len(portfolio.closed_positions) == 1  # One position (BTCUSDT) closed
    assert portfolio.cash == 169000  # Cash after transactions
    assert portfolio.total_equity == 169000  # Total equity after transactions
    assert portfolio.total_unrealised_pnl == 0  # Total unrealized P&L
    assert portfolio.total_realised_pnl == pytest.approx(19000, abs=0.01)  # Total realized P&L


def test_transaction_with_commission(portfolio):
    # Buy 2 units of BTC at $38000 with $100 commission
    buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 38000, 2, 100, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn1)

    # Sell 2 units of BTC at $40000 with $100 commission
    sell_txn = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 40000, 2, 100, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_txn)

    assert len(portfolio.positions) == 0  # No position remaining
    assert len(portfolio.closed_positions) == 1  # One position (BTCUSDT) closed
    assert portfolio.cash == 154000 - 200  # Cash after transactions considering commissions
    assert portfolio.total_realised_pnl == 4000 - 200  # Realized P&L after commissions


def test_partial_closure(portfolio):
    # Buy 3 units of BTC at $40000 (total: $120,000 - within $150,000 budget)
    buy_txn = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 40000, 3, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn)

    # Sell 2 units of BTC at $45000 (partial closure)
    sell_txn = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 45000, 2, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_txn)

    assert len(portfolio.positions) == 1  # One position remaining
    assert portfolio.positions["BTCUSDT"].net_quantity == 1  # 1 unit remaining
    assert portfolio.cash == 150000 - (40000 * 3) + (45000 * 2)  # Cash after transactions
    assert portfolio.total_realised_pnl == 10000  # Realized P&L for the closed portion (2 * $5000)


def test_multiple_assets(portfolio):
    # Buy 1 unit of BTC at $40000
    buy_btc = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_btc)

    # Buy 2 units of ETH at $2500
    buy_eth = Transaction(datetime.now(), TransactionType.BUY, "ETHUSDT", 2500, 2, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_eth)

    # Sell 1 unit of BTC at $42000
    sell_btc = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 42000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_btc)

    assert len(portfolio.positions) == 1  # One position remaining (ETH)
    assert len(portfolio.closed_positions) == 1  # One position (BTC) closed
    assert portfolio.positions["ETHUSDT"].net_quantity == 2  # 2 units of ETH remaining
    assert portfolio.cash == 150000 - 40000 + 42000 - 2500 * 2  # Cash after transactions
    assert portfolio.total_realised_pnl == 2000  # Realized P&L for BTC


def test_mixed_buy_sell_transactions(portfolio):
    # Buy 2 units of BTC at $38000
    buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 38000, 2, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn1)

    # Sell 1 unit of BTC at $40000
    sell_txn1 = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 40000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_txn1)

    # Buy 1 unit of BTC at $37000
    buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, "BTCUSDT", 37000, 1, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(buy_txn2)

    # Sell 2 units of BTC at $39000
    sell_txn2 = Transaction(datetime.now(), TransactionType.SELL, "BTCUSDT", 39000, 2, 0, None, idgen.generate_transaction_id())
    portfolio.process_transaction(sell_txn2)

    assert len(portfolio.positions) == 0  # No position remaining
    assert len(portfolio.closed_positions) == 1  # One position (BTCUSDT) closed
    assert portfolio.cash == 155000  # Cash after transactions
    assert portfolio.total_realised_pnl == pytest.approx(5000, abs=0.01)  # Realized P&L
