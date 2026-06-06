"""
Test suite for TransactionManager class (Plan 05-05 D-11/D-12 surface).

The manager is validation + recording + history queries ONLY: settlement
orchestration lives in ``Portfolio.process_transaction`` (D-12) and the cash
math on the ``Transaction`` entity (``net_cash_delta``). The saga machinery
(in-flight context / transaction-state enum / pending dict) is deleted (D-11).
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.transaction.transaction_manager import TransactionManager
from itrader.portfolio_handler.transaction import Transaction
from itrader.core.enums import TransactionType
from itrader.core.exceptions import InvalidTransactionError
from itrader import idgen


class MockPortfolio:
    """Lightweight portfolio stand-in — the manager only needs the seam hook."""

    def __init__(self):
        self.portfolio_id = idgen.generate_portfolio_id()


def _txn(type_=TransactionType.BUY, ticker="BTCUSDT", price=50000.0,
         quantity=1.0, commission=25.0, portfolio_id=None):
    return Transaction(
        time=datetime(2021, 3, 14, 9, 26, 53), type=type_, ticker=ticker,
        price=price, quantity=quantity, commission=commission,
        portfolio_id=portfolio_id, id=idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )


@pytest.fixture
def env():
    """A TransactionManager on a mock portfolio + a sample valid BUY."""
    portfolio = MockPortfolio()
    transaction_manager = TransactionManager(portfolio)
    valid_transaction = _txn(portfolio_id=portfolio.portfolio_id)
    return SimpleNamespace(
        portfolio=portfolio,
        transaction_manager=transaction_manager,
        valid_transaction=valid_transaction,
    )


def test_transaction_manager_initialization(env):
    """Test TransactionManager initialization."""
    tm = env.transaction_manager
    assert tm.portfolio is not None
    assert len(tm._storage.get_transaction_history()) == 0
    assert tm.min_transaction_amount == Decimal("0.01")


# ---------------------------------------------------------------------------
# validate() — pure checks, raise typed / return None (D-09/D-10)
# ---------------------------------------------------------------------------


def test_validate_returns_none_for_valid_transaction(env):
    """D-10 one-channel contract: validate returns None on success."""
    assert env.transaction_manager.validate(env.valid_transaction) is None


def test_validate_mutates_nothing(env):
    """validate is PURE — no history append, no transaction mutation."""
    txn = env.valid_transaction
    env.transaction_manager.validate(txn)

    assert len(env.transaction_manager.get_transaction_history()) == 0
    assert txn.position_id is None


def test_invalid_price_validation(env):
    """Validation fails for negative or zero price."""
    invalid = _txn(price=-1000.0, portfolio_id=env.portfolio.portfolio_id)

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.validate(invalid)

    assert "price must be positive" in str(exc_info.value)


def test_invalid_quantity_validation(env):
    """Validation fails for negative or zero quantity."""
    invalid = _txn(quantity=0.0, portfolio_id=env.portfolio.portfolio_id)

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.validate(invalid)

    assert "quantity must be positive" in str(exc_info.value)


def test_negative_commission_validation(env):
    """Validation fails for negative commission."""
    invalid = _txn(commission=-25.0, portfolio_id=env.portfolio.portfolio_id)

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.validate(invalid)

    assert "Commission cannot be negative" in str(exc_info.value)


def test_transaction_value_limits(env):
    """Validation enforces the minimum transaction value."""
    tiny = _txn(price=0.001, quantity=1.0, commission=0.0,
                portfolio_id=env.portfolio.portfolio_id)

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.validate(tiny)

    assert "below minimum" in str(exc_info.value)


def test_transaction_value_maximum_limit(env):
    """Validation enforces the maximum transaction value."""
    huge = _txn(price=2000000.0, quantity=1.0, commission=0.0,
                portfolio_id=env.portfolio.portfolio_id)

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.validate(huge)

    assert "exceeds maximum" in str(exc_info.value)


def test_high_commission_rate_validation(env):
    """Validation fails for unreasonably high commission rates."""
    high_commission = _txn(price=100.0, quantity=1.0, commission=60.0,  # 60% > 50%
                           portfolio_id=env.portfolio.portfolio_id)

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.validate(high_commission)

    assert "Commission rate" in str(exc_info.value)


def test_invalid_ticker_validation(env):
    """Validation fails for invalid ticker."""
    invalid_ticker = _txn(ticker="BT", portfolio_id=env.portfolio.portfolio_id)

    with pytest.raises(InvalidTransactionError) as exc_info:
        env.transaction_manager.validate(invalid_ticker)

    assert "Invalid ticker format" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Transaction.net_cash_delta — the entity owns its cash math (D-12)
# ---------------------------------------------------------------------------


def test_net_cash_delta_buy(env):
    """BUY: -(price * quantity + commission) — the exact interim-seam math."""
    assert env.valid_transaction.net_cash_delta == Decimal("-50025.0")


def test_net_cash_delta_sell(env):
    """SELL: price * quantity - commission."""
    sell = _txn(type_=TransactionType.SELL, price=52000.0, quantity=1.0,
                commission=26.0, portfolio_id=env.portfolio.portfolio_id)

    assert sell.net_cash_delta == Decimal("51974.0")


def test_net_cash_delta_full_precision():
    """No quantization — full Decimal precision survives (Pitfall 1)."""
    precise = _txn(price=33333.33, quantity=0.3, commission=5.55)

    expected = -(Decimal("33333.33") * Decimal("0.3") + Decimal("5.55"))
    assert precise.net_cash_delta == expected


# ---------------------------------------------------------------------------
# record() + history queries
# ---------------------------------------------------------------------------


def test_record_returns_none_and_appends_history(env):
    """record appends to the seam history and returns None (D-10)."""
    assert env.transaction_manager.record(env.valid_transaction) is None

    history = env.transaction_manager.get_transaction_history()
    assert len(history) == 1
    assert history[0] is env.valid_transaction


def test_transaction_history_tracking(env):
    """Transaction history is properly tracked, in record order."""
    tm = env.transaction_manager
    transaction1 = env.valid_transaction
    transaction2 = _txn(type_=TransactionType.SELL, ticker="ETHUSDT",
                        price=3000.0, quantity=2.0, commission=15.0,
                        portfolio_id=env.portfolio.portfolio_id)

    tm.record(transaction1)
    tm.record(transaction2)

    history = tm.get_transaction_history()
    assert len(history) == 2
    assert history[0].id == transaction1.id
    assert history[1].id == transaction2.id


def test_transaction_history_limit(env):
    """Transaction history with limit returns the most recent entries."""
    tm = env.transaction_manager
    for i in range(5):
        tm.record(_txn(type_=TransactionType.SELL, ticker=f"TEST{i}USDT",
                       price=1000.0, quantity=1.0, commission=5.0,
                       portfolio_id=env.portfolio.portfolio_id))

    recent_history = tm.get_transaction_history(limit=3)
    assert len(recent_history) == 3


# ---------------------------------------------------------------------------
# Saga machinery is GONE (D-11 regression lock)
# ---------------------------------------------------------------------------


def test_saga_machinery_deleted(env):
    """D-11: no pending dict, no process_transaction, no cancel/rollback."""
    tm = env.transaction_manager
    assert not hasattr(tm, "process_transaction")
    assert not hasattr(tm, "_handle_transaction_error")
    assert not hasattr(tm, "_check_funds_availability")
    assert not hasattr(tm, "_execute_transaction")
    assert not hasattr(tm, "_calculate_transaction_cost")
    # No pending/cancel surface survives anywhere on the manager.
    assert not [a for a in dir(tm) if "pending" in a.lower() or "cancel" in a.lower()]


def test_transaction_state_enum_deleted():
    """D-11: the transaction-state enum no longer exists in core enums."""
    import itrader.core.enums as enums
    state_enums = [name for name in enums.__all__ if name.endswith("State")]
    assert state_enums == ["PortfolioState"]
