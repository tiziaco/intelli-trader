"""
Test suite for TransactionManager class.
Tests transaction validation, processing, error handling, and thread safety.
"""

import threading
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from itrader.portfolio_handler.transaction.transaction_manager import (
    TransactionManager,
    TransactionState,
    TransactionContext,
)
from itrader.portfolio_handler.transaction import Transaction
from itrader.core.enums import TransactionType
from itrader.core.exceptions import (
    InvalidTransactionError,
    InsufficientFundsError,
    ConcurrencyError,
)
from itrader import idgen


class MockCashManager:
    """Mock CashManager exposing the precision-preserving transaction primitive.

    CR-03: TransactionManager now routes the cash mutation through
    ``portfolio.cash_manager.apply_transaction_delta(delta)`` instead of the
    quantizing ``cash`` setter. The mock adds the full-precision Decimal delta
    straight to the parent portfolio's ``cash`` (no quantization, no policy gate),
    mirroring the real primitive so the Decimal-exact assertions still hold.
    """

    def __init__(self, portfolio):
        self._portfolio = portfolio

    def apply_transaction_delta(self, delta, description="", reference_id=None):
        self._portfolio.cash = self._portfolio.cash + delta
        return True


class MockPortfolio:
    """Mock portfolio for testing.

    Cash is Decimal end-to-end (M2-02). CR-03: TransactionManager mutates cash
    via ``self.portfolio.cash_manager.apply_transaction_delta(delta)`` with a
    full-precision Decimal delta and NO float() round-trip, so the mock exposes a
    ``cash_manager`` that preserves full Decimal precision on ``cash``.
    """

    def __init__(self, initial_cash=Decimal("100000.0")):
        self.cash = Decimal(str(initial_cash))
        self.portfolio_id = idgen.generate_portfolio_id()
        self.cash_manager = MockCashManager(self)


@pytest.fixture
def env():
    """A TransactionManager on a $100000 mock portfolio + a sample valid BUY."""
    portfolio = MockPortfolio(initial_cash=100000.0)
    transaction_manager = TransactionManager(portfolio)
    valid_transaction = Transaction(
        time=datetime.now(),
        type=TransactionType.BUY,
        ticker="BTCUSDT",
        price=50000.0,
        quantity=1.0,
        commission=25.0,
        portfolio_id=portfolio.portfolio_id,
        id=idgen.generate_transaction_id(),
    )
    return SimpleNamespace(
        portfolio=portfolio,
        transaction_manager=transaction_manager,
        valid_transaction=valid_transaction,
    )


def test_transaction_manager_initialization(env):
    """Test TransactionManager initialization."""
    tm = env.transaction_manager
    assert tm.portfolio is not None
    assert len(tm._storage.get_pending_transactions()) == 0
    assert len(tm._storage.get_transaction_history()) == 0
    assert tm.min_transaction_amount == Decimal("0.01")


def test_valid_buy_transaction_processing(env):
    """Test processing a valid BUY transaction."""
    tm = env.transaction_manager
    initial_cash = env.portfolio.cash

    result = tm.process_transaction(env.valid_transaction)

    assert result
    assert len(tm._storage.get_transaction_history()) == 1

    # Check cash was debited
    expected_cash = initial_cash - (
        env.valid_transaction.price * env.valid_transaction.quantity
        + env.valid_transaction.commission
    )
    assert env.portfolio.cash == expected_cash


def test_valid_sell_transaction_processing(env):
    """Test processing a valid SELL transaction."""
    sell_transaction = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="BTCUSDT",
        price=52000.0, quantity=1.0, commission=26.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    initial_cash = env.portfolio.cash

    result = env.transaction_manager.process_transaction(sell_transaction)

    assert result

    # Check cash was credited
    expected_cash = initial_cash + (
        sell_transaction.price * sell_transaction.quantity - sell_transaction.commission
    )
    assert env.portfolio.cash == expected_cash


def test_invalid_price_validation(env):
    """Test validation fails for negative or zero price."""
    invalid_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=-1000.0, quantity=1.0, commission=25.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.process_transaction(invalid_transaction)

    assert "price must be positive" in str(exc_info.value)


def test_invalid_quantity_validation(env):
    """Test validation fails for negative or zero quantity."""
    invalid_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=50000.0, quantity=0.0, commission=25.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.process_transaction(invalid_transaction)

    assert "quantity must be positive" in str(exc_info.value)


def test_negative_commission_validation(env):
    """Test validation fails for negative commission."""
    invalid_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=50000.0, quantity=1.0, commission=-25.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.process_transaction(invalid_transaction)

    assert "Commission cannot be negative" in str(exc_info.value)


def test_insufficient_funds_error(env):
    """Test insufficient funds error for BUY transaction."""
    # Set portfolio cash to low amount (Decimal end-to-end)
    env.portfolio.cash = Decimal("1000.0")

    large_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=50000.0, quantity=1.0, commission=25.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    with pytest.raises(InsufficientFundsError) as exc_info:
        env.transaction_manager.process_transaction(large_transaction)

    assert exc_info.value.available_cash == 1000.0
    assert exc_info.value.required_cash == 50025.0


def test_transaction_value_limits(env):
    """Test transaction value minimum and maximum limits."""
    tiny_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=0.001, quantity=1.0, commission=0.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.process_transaction(tiny_transaction)

    assert "below minimum" in str(exc_info.value)


def test_high_commission_rate_validation(env):
    """Test validation fails for unreasonably high commission rates."""
    high_commission_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=100.0, quantity=1.0, commission=60.0,  # 60% rate (> 50% limit)
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.process_transaction(high_commission_transaction)

    assert "Commission rate" in str(exc_info.value)


def test_invalid_ticker_validation(env):
    """Test validation fails for invalid ticker."""
    invalid_ticker_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BT",  # Too short
        price=50000.0, quantity=1.0, commission=25.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.process_transaction(invalid_ticker_transaction)

    assert "Invalid ticker format" in str(exc_info.value)


def test_transaction_cost_calculation_buy(env):
    """Test transaction cost calculation for BUY orders."""
    cost = env.transaction_manager._calculate_transaction_cost(env.valid_transaction)
    expected_cost = Decimal("-50025.0")  # -(50000 * 1 + 25)
    assert cost == expected_cost


def test_transaction_cost_calculation_sell(env):
    """Test transaction cost calculation for SELL orders."""
    sell_transaction = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="BTCUSDT",
        price=52000.0, quantity=1.0, commission=26.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    cost = env.transaction_manager._calculate_transaction_cost(sell_transaction)
    expected_cost = Decimal("51974.0")  # 52000 * 1 - 26
    assert cost == expected_cost


def test_transaction_history_tracking(env):
    """Test transaction history is properly tracked."""
    tm = env.transaction_manager
    transaction1 = env.valid_transaction
    transaction2 = Transaction(
        time=datetime.now(), type=TransactionType.SELL, ticker="ETHUSDT",
        price=3000.0, quantity=2.0, commission=15.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    tm.process_transaction(transaction1)
    tm.process_transaction(transaction2)

    history = tm.get_transaction_history()
    assert len(history) == 2
    assert history[0].id == transaction1.id
    assert history[1].id == transaction2.id


def test_transaction_history_limit(env):
    """Test transaction history with limit."""
    tm = env.transaction_manager
    for i in range(5):
        transaction = Transaction(
            time=datetime.now(), type=TransactionType.SELL, ticker=f"TEST{i}USDT",
            price=1000.0, quantity=1.0, commission=5.0,
            portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
        )
        tm.process_transaction(transaction)

    recent_history = tm.get_transaction_history(limit=3)
    assert len(recent_history) == 3


def test_concurrent_transaction_processing(env):
    """Test thread safety with concurrent transaction processing."""
    tm = env.transaction_manager
    results = []
    errors = []

    def process_transaction_thread(transaction_id):
        try:
            transaction = Transaction(
                time=datetime.now(), type=TransactionType.SELL,
                ticker=f"TEST{transaction_id}USDT", price=1000.0, quantity=1.0,
                commission=5.0, portfolio_id=env.portfolio.portfolio_id,
                id=idgen.generate_transaction_id(),
            )
            results.append(tm.process_transaction(transaction))
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(10):
        thread = threading.Thread(target=process_transaction_thread, args=(i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    assert len(errors) == 0, f"Concurrent processing errors: {errors}"
    assert len(results) == 10
    assert all(results)

    history = tm.get_transaction_history()
    assert len(history) == 10


def test_failed_transaction_cleanup(env):
    """Test that failed transactions are properly cleaned up."""
    tm = env.transaction_manager
    invalid_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=-1000.0, quantity=1.0, commission=25.0,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    with pytest.raises(InvalidTransactionError):
        tm.process_transaction(invalid_transaction)

    # Check that pending transactions is cleaned up
    assert len(tm.get_pending_transactions()) == 0
    # Check that failed transaction is not in history
    assert len(tm.get_transaction_history()) == 0


def test_precision_decimal_calculations(env):
    """Test that calculations use proper decimal precision."""
    precise_transaction = Transaction(
        time=datetime.now(), type=TransactionType.BUY, ticker="BTCUSDT",
        price=33333.33, quantity=0.3, commission=5.55,
        portfolio_id=env.portfolio.portfolio_id, id=idgen.generate_transaction_id(),
    )

    initial_cash = env.portfolio.cash
    result = env.transaction_manager.process_transaction(precise_transaction)

    assert result

    # Decimal end-to-end: no float() round-trip — cash stays Decimal on the cash path.
    expected_cost = Decimal("33333.33") * Decimal("0.3") + Decimal("5.55")
    expected_cash = initial_cash - expected_cost

    assert env.portfolio.cash == expected_cash
