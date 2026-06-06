"""
Test suite for CashManager class.
Tests cash operations, precision, thread safety, and validation.
"""

import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from itrader.portfolio_handler.cash.cash_manager import (
    CashManager,
    CashOperationType,
    CashOperation,
)
from itrader.core.exceptions import (
    InvalidTransactionError,
    InsufficientFundsError,
)


class MockPortfolio:
    """Mock portfolio for testing."""

    def __init__(self):
        self.portfolio_id = 12345


@pytest.fixture
def cm():
    """A CashManager seeded with $100000 on a mock portfolio."""
    portfolio = MockPortfolio()
    return CashManager(portfolio, 100000.0)


def test_cash_manager_initialization(cm):
    """Test CashManager initialization."""
    assert cm.balance == Decimal("100000.00")
    assert cm.available_balance == Decimal("100000.00")
    assert cm.reserved_balance == Decimal("0.00")
    assert len(cm._storage.get_cash_operations()) == 0


def test_deposit_valid_amount(cm):
    """Test valid cash deposit."""
    initial_balance = cm.balance

    result = cm.deposit(5000.0, "Test deposit")

    assert result
    assert cm.balance == initial_balance + Decimal("5000.00")

    # Check operation was recorded
    operations = cm.get_cash_operations()
    assert len(operations) == 1
    assert operations[0].operation_type == CashOperationType.DEPOSIT
    assert operations[0].amount == Decimal("5000.00")


def test_deposit_with_reference_id(cm):
    """Test deposit with reference ID."""
    reference_id = "DEPOSIT_123"

    result = cm.deposit(1000.0, "Test deposit", reference_id)

    assert result
    operations = cm.get_cash_operations()
    assert operations[0].reference_id == reference_id


def test_deposit_exceeds_maximum_balance(cm):
    """Test deposit that would exceed maximum balance."""
    # Set a low maximum balance for testing
    cm.max_balance = Decimal("150000.00")

    with pytest.raises(InvalidTransactionError) as exc_info:
        cm.deposit(60000.0, "Large deposit")

    assert "exceed maximum balance limit" in str(exc_info.value)


def test_deposit_invalid_amount(cm):
    """Test deposit with invalid (negative) amount."""
    with pytest.raises(InvalidTransactionError) as exc_info:
        cm.deposit(-1000.0, "Invalid deposit")

    assert "must be positive" in str(exc_info.value)


def test_withdrawal_valid_amount(cm):
    """Test valid cash withdrawal."""
    initial_balance = cm.balance

    result = cm.withdraw(25000.0, "Test withdrawal")

    assert result
    assert cm.balance == initial_balance - Decimal("25000.00")

    # Check operation was recorded
    operations = cm.get_cash_operations()
    assert len(operations) == 1
    assert operations[0].operation_type == CashOperationType.WITHDRAWAL
    assert operations[0].amount == Decimal("25000.00")


def test_withdrawal_insufficient_funds(cm):
    """Test withdrawal with insufficient funds."""
    with pytest.raises(InsufficientFundsError) as exc_info:
        cm.withdraw(150000.0, "Large withdrawal")

    assert exc_info.value.required_cash == 150000.0
    assert exc_info.value.available_cash == 100000.0


def test_withdrawal_invalid_amount(cm):
    """Test withdrawal with invalid amount."""
    with pytest.raises(InvalidTransactionError) as exc_info:
        cm.withdraw(0.0, "Invalid withdrawal")

    assert "must be positive" in str(exc_info.value)


def test_transaction_cash_flow_debit(cm):
    """Test transaction cash flow debit."""
    initial_balance = cm.balance

    result = cm.process_transaction_cash_flow(5000.0, True, "Buy transaction", "TXN_123")

    assert result
    assert cm.balance == initial_balance - Decimal("5000.00")

    # Check operation was recorded
    operations = cm.get_cash_operations()
    assert len(operations) == 1
    assert operations[0].operation_type == CashOperationType.TRANSACTION_DEBIT


def test_transaction_cash_flow_credit(cm):
    """Test transaction cash flow credit."""
    initial_balance = cm.balance

    result = cm.process_transaction_cash_flow(7500.0, False, "Sell transaction", "TXN_124")

    assert result
    assert cm.balance == initial_balance + Decimal("7500.00")

    # Check operation was recorded
    operations = cm.get_cash_operations()
    assert len(operations) == 1
    assert operations[0].operation_type == CashOperationType.TRANSACTION_CREDIT


def test_transaction_cash_flow_insufficient_funds(cm):
    """Test transaction debit with insufficient funds."""
    with pytest.raises(InsufficientFundsError):
        cm.process_transaction_cash_flow(150000.0, True, "Large buy", "TXN_125")


def test_cash_reservation(cm):
    """Test cash reservation for pending orders."""
    cm.reserve_cash(30000.0, "Order reservation", "ORDER_123")

    assert cm.reserved_balance == Decimal("30000.00")
    assert cm.available_balance == Decimal("70000.00")
    assert cm.balance == Decimal("100000.00")  # Total unchanged

    # Check operation was recorded
    operations = cm.get_cash_operations()
    assert len(operations) == 1
    assert operations[0].operation_type == CashOperationType.RESERVATION


def test_cash_reservation_insufficient_funds(cm):
    """Test cash reservation with insufficient available funds."""
    with pytest.raises(InsufficientFundsError):
        cm.reserve_cash(150000.0, "Large reservation", "ORDER_124")


def test_release_cash_reservation(cm):
    """Test releasing a cash reservation by reference (Plan 05-03)."""
    # First, make a reservation
    cm.reserve_cash(20000.0, "Initial reservation", "ORDER_125")

    # Then release it by reference — the full reserved amount comes back
    cm.release_reservation("ORDER_125")

    assert cm.reserved_balance == Decimal("0.00")
    assert cm.available_balance == Decimal("100000.00")

    # Check operations were recorded
    operations = cm.get_cash_operations()
    assert len(operations) == 2
    assert operations[1].operation_type == CashOperationType.RELEASE_RESERVATION
    assert operations[1].amount == Decimal("20000")


def test_decimal_precision(cm):
    """Test decimal precision in calculations."""
    # Test with amounts that could cause floating point issues
    cm.deposit(33333.33, "Precision test deposit")
    cm.withdraw(11111.11, "Precision test withdrawal")

    # Calculate expected balance
    expected_balance = Decimal("100000.00") + Decimal("33333.33") - Decimal("11111.11")
    assert cm.balance == expected_balance


def test_precision_rounding(cm):
    """Test proper rounding with small amounts."""
    # Amount with more than 2 decimal places
    cm.deposit(1000.999, "Rounding test")  # Should round to 1001.00

    expected_balance = Decimal("100000.00") + Decimal("1001.00")
    assert cm.balance == expected_balance


def test_get_balance_info(cm):
    """Test getting comprehensive balance information."""
    # Make some operations
    cm.deposit(5000.0, "Test deposit")
    cm.reserve_cash(15000.0, "Test reservation", "ORDER_127")

    balance_info = cm.get_balance_info()

    assert balance_info["total_balance"] == 105000.0
    assert balance_info["available_balance"] == 90000.0
    assert balance_info["reserved_balance"] == 15000.0
    assert "min_balance" in balance_info
    assert "max_balance" in balance_info


def test_get_cash_operations_with_filter(cm):
    """Test getting cash operations with type filter."""
    # Perform different types of operations
    cm.deposit(1000.0, "Deposit 1")
    cm.withdraw(500.0, "Withdrawal 1")
    cm.deposit(2000.0, "Deposit 2")

    # Get only deposit operations
    deposit_operations = cm.get_cash_operations(operation_type=CashOperationType.DEPOSIT)

    assert len(deposit_operations) == 2
    assert all(op.operation_type == CashOperationType.DEPOSIT for op in deposit_operations)


def test_get_cash_operations_with_limit(cm):
    """Test getting cash operations with limit."""
    # Perform multiple operations
    for i in range(5):
        cm.deposit(100.0, f"Deposit {i}")

    # Get limited operations
    limited_operations = cm.get_cash_operations(limit=3)

    assert len(limited_operations) == 3


def test_balance_consistency_validation(cm):
    """Test balance consistency validation."""
    # Normal state should be consistent
    assert cm.validate_balance_consistency()

    # Test with manipulated state (simulating corruption): inject a negative
    # reservation directly through the seam (the manager API would reject it).
    cm._storage.add_reservation("CORRUPT", Decimal("-100.00"))

    assert not cm.validate_balance_consistency()

    # Restore state
    cm._storage.pop_reservation("CORRUPT")


def test_concurrent_operations(cm):
    """Test thread safety with concurrent operations."""
    results = []
    errors = []

    def deposit_thread(thread_id):
        try:
            results.append(cm.deposit(100.0, f"Concurrent deposit {thread_id}"))
        except Exception as e:
            errors.append(e)

    def withdraw_thread(thread_id):
        try:
            results.append(cm.withdraw(50.0, f"Concurrent withdrawal {thread_id}"))
        except Exception as e:
            errors.append(e)

    # Start multiple threads
    threads = []
    for i in range(5):
        dep_thread = threading.Thread(target=deposit_thread, args=(i,))
        with_thread = threading.Thread(target=withdraw_thread, args=(i,))
        threads.extend([dep_thread, with_thread])

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Check results
    assert len(errors) == 0, f"Concurrent operation errors: {errors}"
    assert len(results) == 10
    assert all(results)

    # Check final balance consistency
    assert cm.validate_balance_consistency()

    # Expected balance: 100000 + (5 * 100) - (5 * 50) = 100250
    assert cm.balance == Decimal("100250.00")


def test_concurrent_reservation_operations(cm):
    """Test thread safety with concurrent reservation operations."""
    results = []
    errors = []

    def reserve_release_thread(thread_id):
        try:
            cm.reserve_cash(1000.0, f"Reservation {thread_id}", f"ORDER_{thread_id}")
            # Small delay to increase chance of race conditions
            time.sleep(0.01)
            cm.release_reservation(f"ORDER_{thread_id}")
            results.append(True)
        except Exception as e:
            errors.append(e)

    # Start multiple threads
    threads = []
    for i in range(5):
        thread = threading.Thread(target=reserve_release_thread, args=(i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    # Check results
    assert len(errors) == 0, f"Concurrent reservation errors: {errors}"
    assert len(results) == 5
    assert all(results)

    # Final state should have no reservations
    assert cm.reserved_balance == Decimal("0.00")
    assert cm.available_balance == cm.balance


# ---------------------------------------------------------------------------
# Per-reference reservations (Plan 05-03 Task 2 — D-13/OQ4 groundwork)
# ---------------------------------------------------------------------------


def test_reservations_sum_per_reference(cm):
    """Two reservations under different refs: reserved_balance is the sum."""
    cm.reserve_cash(Decimal("10000.00"), "order A", "ORDER_A")
    cm.reserve_cash(Decimal("25000.00"), "order B", "ORDER_B")

    assert cm.reserved_balance == Decimal("35000.00")
    assert cm.available_balance == Decimal("65000.00")
    assert cm.balance == Decimal("100000.00")  # Total unchanged


def test_reservation_full_precision_round_trip(cm):
    """OQ4: reservations are stored at FULL precision — no 2dp quantize."""
    cm.reserve_cash(Decimal("123.45678901"), "full precision", "ORDER_FP")

    assert cm.reserved_balance == Decimal("123.45678901")
    assert cm.available_balance == Decimal("100000.00") - Decimal("123.45678901")


def test_release_reservation_removes_exactly_that_reference(cm):
    """release_reservation(ref) pops exactly that reservation, others stay."""
    cm.reserve_cash(Decimal("10000.00"), "order A", "ORDER_A")
    cm.reserve_cash(Decimal("5000.00"), "order B", "ORDER_B")

    cm.release_reservation("ORDER_A")

    assert cm.reserved_balance == Decimal("5000.00")
    assert cm.available_balance == Decimal("95000.00")

    # Release audit entry recorded only for the existing reservation
    operations = cm.get_cash_operations(
        operation_type=CashOperationType.RELEASE_RESERVATION
    )
    assert len(operations) == 1


def test_release_unknown_reference_is_silent_noop(cm):
    """Releasing an unknown reference is idempotent — no raise, no audit entry."""
    cm.release_reservation("NEVER_RESERVED")
    cm.release_reservation("NEVER_RESERVED")  # twice — still a no-op

    assert cm.reserved_balance == Decimal("0.00")
    operations = cm.get_cash_operations(
        operation_type=CashOperationType.RELEASE_RESERVATION
    )
    assert len(operations) == 0


def test_release_is_idempotent_after_real_reservation(cm):
    """Releasing the same reference twice releases once, second is a no-op."""
    cm.reserve_cash(Decimal("1000.00"), "order", "ORDER_X")
    cm.release_reservation("ORDER_X")
    cm.release_reservation("ORDER_X")  # idempotent

    assert cm.reserved_balance == Decimal("0.00")
    operations = cm.get_cash_operations(
        operation_type=CashOperationType.RELEASE_RESERVATION
    )
    assert len(operations) == 1


def test_reserve_insufficient_funds_reserves_nothing(cm):
    """A failed reservation raises typed InsufficientFundsError and reserves 0."""
    with pytest.raises(InsufficientFundsError):
        cm.reserve_cash(Decimal("150000.00"), "too large", "ORDER_BIG")

    assert cm.reserved_balance == Decimal("0.00")
    assert cm.available_balance == cm.balance


# ---------------------------------------------------------------------------
# Fill-flow primitives (Plan 05-05 Task 1 — D-05/D-06/D-10, Pitfalls 1/2/5)
# ---------------------------------------------------------------------------

_EVENT_TIME = datetime(2021, 3, 14, 9, 26, 53)


def test_apply_fill_cash_flow_full_precision_no_quantize(cm):
    """Pitfall 1: an 8dp signed delta moves balance by EXACTLY that delta."""
    delta = Decimal("-9543.21987654")

    cm.apply_fill_cash_flow(
        amount=delta,
        fee=Decimal("0"),
        description="BUY BTCUSD fill",
        reference_id="txn-1",
        timestamp=_EVENT_TIME,
    )

    # No 2dp quantization — the full 8dp precision survives on the ledger.
    assert cm.balance == Decimal("100000.00") + delta
    assert cm.balance == Decimal("90456.78012346")


def test_apply_fill_cash_flow_one_ledger_entry_with_fee(cm):
    """D-06: exactly one CashOperation per fill — amount = signed net delta,
    fee = commission portion; balance reconstruction holds."""
    buy_delta = Decimal("-50025.00")   # -(50000 * 1 + 25 commission)
    sell_delta = Decimal("51974.00")   # 52000 * 1 - 26 commission

    cm.apply_fill_cash_flow(
        amount=buy_delta, fee=Decimal("25"),
        description="BUY", reference_id="txn-buy", timestamp=_EVENT_TIME,
    )
    cm.apply_fill_cash_flow(
        amount=sell_delta, fee=Decimal("26"),
        description="SELL", reference_id="txn-sell", timestamp=_EVENT_TIME,
    )

    operations = cm.get_cash_operations()
    assert len(operations) == 2

    buy_op, sell_op = operations
    assert buy_op.operation_type == CashOperationType.TRANSACTION_DEBIT
    assert buy_op.amount == buy_delta          # SIGNED net delta, not abs
    assert buy_op.fee == Decimal("25")
    assert buy_op.reference_id == "txn-buy"

    assert sell_op.operation_type == CashOperationType.TRANSACTION_CREDIT
    assert sell_op.amount == sell_delta
    assert sell_op.fee == Decimal("26")

    # Balance reconstruction: balance = initial + Σ amounts.
    assert cm.balance == Decimal("100000.00") + buy_delta + sell_delta


def test_cash_operation_event_time_and_uuid_id(cm):
    """Pitfall 5: ledger records are deterministic — caller-supplied event
    time (never wall clock) + UUID operation id."""
    cm.apply_fill_cash_flow(
        amount=Decimal("-100.00"), fee=Decimal("0"),
        description="BUY", reference_id="txn-2", timestamp=_EVENT_TIME,
    )

    operation = cm.get_cash_operations()[0]
    assert operation.timestamp == _EVENT_TIME
    assert isinstance(operation.operation_id, uuid.UUID)


def test_assert_funds_invariant_raises_when_required_exceeds_balance(cm):
    """D-10: required > balance raises typed InsufficientFundsError."""
    with pytest.raises(InsufficientFundsError):
        cm.assert_funds_invariant(Decimal("100000.01"))


def test_assert_funds_invariant_passes_when_required_within_balance(cm):
    """required <= balance passes (returns None)."""
    assert cm.assert_funds_invariant(Decimal("100000.00")) is None
    assert cm.assert_funds_invariant(Decimal("0.01")) is None


def test_assert_funds_invariant_ignores_reservations(cm):
    """Pitfall 2: the invariant guard checks BALANCE, never the
    reservation-adjusted buying power — an order's own un-released
    reservation must NOT false-positive under portfolio-first FILL dispatch."""
    cm.reserve_cash(Decimal("95000.00"), "pending order", "ORDER_RES")
    assert cm.available_balance == Decimal("5000.00")

    # required > available_balance but <= balance — must NOT raise.
    assert cm.assert_funds_invariant(Decimal("50000.00")) is None


def test_fill_flow_primitives_return_none(cm):
    """D-10 one-channel contract: both primitives return None."""
    result = cm.apply_fill_cash_flow(
        amount=Decimal("10.00"), fee=Decimal("0"),
        description="credit", reference_id="txn-3", timestamp=_EVENT_TIME,
    )
    assert result is None
    assert cm.assert_funds_invariant(Decimal("1.00")) is None


def test_operation_id_uniqueness(cm):
    """Test that operation IDs are unique."""
    operation_ids = set()

    for i in range(100):
        cm.deposit(1.0, f"Test deposit {i}")

    operations = cm.get_cash_operations()

    for operation in operations:
        assert operation.operation_id not in operation_ids
        operation_ids.add(operation.operation_id)

    assert len(operation_ids) == 100
