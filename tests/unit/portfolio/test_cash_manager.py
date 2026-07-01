"""
Test suite for the simulated account cash leaf.

Retargeted from the deleted ``CashManager`` (01-03) to the account leaves: the
cash-only contract is exercised against ``SimulatedCashAccount`` (the ``cm``
fixture), and the margin-only surface (position-keyed locks + borrow carry) is
exercised against its ``SimulatedMarginAccount`` superset (the ``mcm`` fixture) —
those methods live only on the margin leaf after the split, so the same behaviors
are tested against the correct leaf with no coverage loss.

Tests cash operations, precision, single-writer sequencing, and validation.
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from itrader.portfolio_handler.account import (
    SimulatedCashAccount,
    SimulatedMarginAccount,
    CashOperation,
)
from itrader.core.enums import CashOperationType
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
    """A SimulatedCashAccount seeded with $100000 on a mock portfolio."""
    portfolio = MockPortfolio()
    return SimulatedCashAccount(portfolio, 100000.0)


@pytest.fixture
def mcm():
    """A SimulatedMarginAccount (the cash superset) seeded with $100000.

    The margin-only surface (lock_margin / release_margin / locked_margin_total /
    accrue_borrow_interest) lives only on the margin leaf after the 01-02 split,
    so the margin-keyed tests exercise it here.
    """
    portfolio = MockPortfolio()
    return SimulatedMarginAccount(portfolio, 100000.0)


def test_cash_manager_initialization(cm):
    """Test cash account initialization."""
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
    cm.reserve("ORDER_123", 30000.0)

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
        cm.reserve("ORDER_124", 150000.0)


def test_release_cash_reservation(cm):
    """Test releasing a cash reservation by reference (Plan 05-03)."""
    # First, make a reservation
    cm.reserve("ORDER_125", 20000.0)

    # Then release it by reference — the full reserved amount comes back
    cm.release("ORDER_125")

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
    cm.reserve("ORDER_127", 15000.0)

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


def test_interleaved_operations_sequential_single_writer(cm):
    """WR-11: the D-19 single-writer contract deliberately removed the
    cash-leaf locks — ALL mutations happen on the engine thread. The old
    multi-threaded variant of this test asserted a thread-safety property the
    code intentionally no longer provides (a lost-update race). The same
    operation mix, run sequentially on one writer, must be exact."""
    results = []
    for i in range(5):
        results.append(cm.deposit(100.0, f"Sequential deposit {i}"))
        results.append(cm.withdraw(50.0, f"Sequential withdrawal {i}"))

    assert len(results) == 10
    assert all(results)

    # Check final balance consistency
    assert cm.validate_balance_consistency()

    # Expected balance: 100000 + (5 * 100) - (5 * 50) = 100250
    assert cm.balance == Decimal("100250.00")


def test_interleaved_reservation_operations_sequential_single_writer(cm):
    """WR-11: reservation churn under the D-19 single-writer contract —
    overlapping reserve/release cycles run sequentially leave no residue."""
    # Overlap the reservations (all reserved before any release) to exercise
    # the multi-key reservation accounting, then release them all.
    for i in range(5):
        cm.reserve(f"ORDER_{i}", 1000.0)
    assert cm.reserved_balance == Decimal("5000.00")
    for i in range(5):
        cm.release(f"ORDER_{i}")

    # Final state should have no reservations
    assert cm.reserved_balance == Decimal("0.00")
    assert cm.available_balance == cm.balance


# ---------------------------------------------------------------------------
# Per-reference reservations (Plan 05-03 Task 2 — D-13/OQ4 groundwork)
# ---------------------------------------------------------------------------


def test_reservations_sum_per_reference(cm):
    """Two reservations under different refs: reserved_balance is the sum."""
    cm.reserve("ORDER_A", Decimal("10000.00"))
    cm.reserve("ORDER_B", Decimal("25000.00"))

    assert cm.reserved_balance == Decimal("35000.00")
    assert cm.available_balance == Decimal("65000.00")
    assert cm.balance == Decimal("100000.00")  # Total unchanged


def test_reservation_full_precision_round_trip(cm):
    """OQ4: reservations are stored at FULL precision — no 2dp quantize."""
    cm.reserve("ORDER_FP", Decimal("123.45678901"))

    assert cm.reserved_balance == Decimal("123.45678901")
    assert cm.available_balance == Decimal("100000.00") - Decimal("123.45678901")


def test_release_removes_exactly_that_reference(cm):
    """release(ref) pops exactly that reservation, others stay."""
    cm.reserve("ORDER_A", Decimal("10000.00"))
    cm.reserve("ORDER_B", Decimal("5000.00"))

    cm.release("ORDER_A")

    assert cm.reserved_balance == Decimal("5000.00")
    assert cm.available_balance == Decimal("95000.00")

    # Release audit entry recorded only for the existing reservation
    operations = cm.get_cash_operations(
        operation_type=CashOperationType.RELEASE_RESERVATION
    )
    assert len(operations) == 1


def test_release_unknown_reference_is_silent_noop(cm):
    """Releasing an unknown reference is idempotent — no raise, no audit entry."""
    cm.release("NEVER_RESERVED")
    cm.release("NEVER_RESERVED")  # twice — still a no-op

    assert cm.reserved_balance == Decimal("0.00")
    operations = cm.get_cash_operations(
        operation_type=CashOperationType.RELEASE_RESERVATION
    )
    assert len(operations) == 0


def test_release_is_idempotent_after_real_reservation(cm):
    """Releasing the same reference twice releases once, second is a no-op."""
    cm.reserve("ORDER_X", Decimal("1000.00"))
    cm.release("ORDER_X")
    cm.release("ORDER_X")  # idempotent

    assert cm.reserved_balance == Decimal("0.00")
    operations = cm.get_cash_operations(
        operation_type=CashOperationType.RELEASE_RESERVATION
    )
    assert len(operations) == 1


def test_reserve_insufficient_funds_reserves_nothing(cm):
    """A failed reservation raises typed InsufficientFundsError and reserves 0."""
    with pytest.raises(InsufficientFundsError):
        cm.reserve("ORDER_BIG", Decimal("150000.00"))

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


def test_cash_operation_borrow_interest_member_exists():
    """D-03 / CARRY-01: a first-class BORROW_INTEREST op kind makes the
    short-carry financing-cost drag an attributable ledger line."""
    assert CashOperationType.BORROW_INTEREST.value == "BORROW_INTEREST"
    # The duck-typed serializer reads op.operation_type.name.
    assert CashOperationType.BORROW_INTEREST.name == "BORROW_INTEREST"


def test_cash_operation_borrow_interest_parses_case_insensitively():
    """The _missing_ parser resolves lower-case input to the member."""
    assert (
        CashOperationType("borrow_interest")
        is CashOperationType.BORROW_INTEREST
    )


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
    cm.reserve("ORDER_RES", Decimal("95000.00"))
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


# ---------------------------------------------------------------------------
# Position-keyed locked margin (Plan 02-04 Task 1 — D-10/Pitfall 2/Pitfall 6)
# The margin surface lives only on SimulatedMarginAccount (the ``mcm`` fixture).
# ---------------------------------------------------------------------------


def test_locked_margin_total_clean_zero_when_empty(mcm):
    """Pitfall 6: with no locks the total is a CLEAN Decimal('0') and
    available_balance == balance − reserved byte-exact (x − Decimal('0') == x)."""
    assert mcm.locked_margin_total == Decimal("0")
    # Byte-exact spot identity: subtracting the empty container preserves the value.
    assert mcm.available_balance == mcm.balance - mcm.reserved_balance
    assert mcm.available_balance == Decimal("100000.00")


def test_lock_margin_subtracts_from_available_balance(mcm):
    """available_balance == balance − reserved − locked_margin (D-10)."""
    mcm.lock_margin("POS_1", Decimal("12000.00"))

    assert mcm.locked_margin_total == Decimal("12000.00")
    assert mcm.reserved_balance == Decimal("0.00")
    assert mcm.balance == Decimal("100000.00")  # ledger balance unchanged
    assert mcm.available_balance == Decimal("88000.00")


def test_lock_release_round_trips_exactly_full_precision(mcm):
    """OQ4/Pitfall: lock/release at FULL precision — release == lock exactly,
    no 2dp quantize drift; releasing returns the exact locked amount."""
    locked = Decimal("9876.54321098")
    mcm.lock_margin("POS_FP", locked)

    assert mcm.locked_margin_total == locked
    assert mcm.available_balance == Decimal("100000.00") - locked

    released = mcm.release_margin("POS_FP")
    assert released == locked

    # Clean zero again, available restored byte-exact.
    assert mcm.locked_margin_total == Decimal("0")
    assert mcm.available_balance == Decimal("100000.00")


def test_locked_margin_is_position_keyed_distinct_from_reservation(mcm):
    """Pitfall 2: the locked-margin container is keyed by position_id, a
    DISTINCT lifecycle from the order-keyed reservation — locking under a
    position and reserving under an order id are independent."""
    mcm.lock_margin("POS_A", Decimal("10000.00"))
    mcm.reserve("ORDER_A", Decimal("5000.00"))

    assert mcm.locked_margin_total == Decimal("10000.00")
    assert mcm.reserved_balance == Decimal("5000.00")
    # available subtracts BOTH, independently.
    assert mcm.available_balance == Decimal("85000.00")

    # Releasing the reservation leaves the lock intact (distinct lifecycle).
    mcm.release("ORDER_A")
    assert mcm.locked_margin_total == Decimal("10000.00")
    assert mcm.available_balance == Decimal("90000.00")

    # Releasing the margin leaves nothing behind.
    mcm.release_margin("POS_A")
    assert mcm.locked_margin_total == Decimal("0")
    assert mcm.available_balance == Decimal("100000.00")


def test_locked_margin_total_sums_multiple_positions(mcm):
    """Two positions locked: locked_margin_total is the sum (per-position keying)."""
    mcm.lock_margin("POS_1", Decimal("10000.00"))
    mcm.lock_margin("POS_2", Decimal("25000.00"))

    assert mcm.locked_margin_total == Decimal("35000.00")
    assert mcm.available_balance == Decimal("65000.00")


def test_release_unknown_position_margin_is_silent_noop(mcm):
    """Releasing an unknown position id returns Decimal('0') and is a no-op."""
    released = mcm.release_margin("NEVER_LOCKED")
    assert released == Decimal("0")
    assert mcm.locked_margin_total == Decimal("0")
    assert mcm.available_balance == Decimal("100000.00")


# ---------------------------------------------------------------------------
# Phase 3 Wave 0 stubs (CARRY-01 / WR-03) — collectible RED placeholders.
# Seeded by Plan 03-02 so the Plan 03-05 / 03-06 verify selectors
# (`borrow_interest`, `borrow_interest_op`, `release_symmetry`) each select
# >=1 test BEFORE any production code is written (D-10). These assert NOTHING
# yet — the implementing plans turn them green. (Margin surface -> ``mcm``.)
# ---------------------------------------------------------------------------


def test_borrow_interest_debits_cash_by_exact_amount(mcm):
    """CARRY-01/D-03: accrue_borrow_interest debits realized cash by the exact
    Decimal carry amount (a REAL outflow, not a reservation)."""
    amount = Decimal("0.05479452054794520547945205")  # 2×100×0.10/365 full precision
    before = mcm.balance
    mcm.accrue_borrow_interest(
        amount=amount, reference_id="POS_SHORT",
        description="borrow interest", timestamp=_EVENT_TIME,
    )
    assert mcm.balance == before - amount


def test_borrow_interest_records_borrow_interest_op_with_balances_and_time(mcm):
    """CARRY-01/D-03: a BORROW_INTEREST CashOperation is recorded with the
    Decimal amount, balance_before/after, and the caller-supplied bar time."""
    amount = Decimal("12.34")
    before = mcm.balance
    mcm.accrue_borrow_interest(
        amount=amount, reference_id="POS_SHORT",
        description="borrow interest", timestamp=_EVENT_TIME,
    )

    ops = mcm.get_cash_operations(operation_type=CashOperationType.BORROW_INTEREST)
    assert len(ops) == 1
    op = ops[0]
    assert op.operation_type is CashOperationType.BORROW_INTEREST
    assert op.amount == amount
    assert op.balance_before == before
    assert op.balance_after == before - amount
    assert op.timestamp == _EVENT_TIME
    assert op.reference_id == "POS_SHORT"


def test_borrow_interest_zero_amount_is_noop(mcm):
    """A zero carry (rate-0 / no-short) accrues nothing and records no op —
    keeps the SMA_MACD oracle byte-exact under default-off."""
    before = mcm.balance
    mcm.accrue_borrow_interest(
        amount=Decimal("0"), reference_id="POS_SHORT",
        description="borrow interest", timestamp=_EVENT_TIME,
    )
    assert mcm.balance == before
    assert mcm.get_cash_operations(
        operation_type=CashOperationType.BORROW_INTEREST
    ) == []


def test_release_symmetry_returns_exact_locked_amount(mcm):
    """WR-03: release_margin returns EXACTLY the locked amount (full precision,
    no rounding drift) — lock/release are symmetric so a release can never leak
    or short-change a position-keyed margin lock (T-03-16)."""
    amount = Decimal("12345.6789012345678901234567")  # full-precision, > 2dp
    mcm.lock_margin("POS_SHORT", amount)
    assert mcm.locked_margin_total == amount

    released = mcm.release_margin("POS_SHORT")
    assert released == amount  # symmetric — exact round-trip, no quantize drift
    assert mcm.locked_margin_total == Decimal("0")


def test_release_symmetry_unlocked_position_is_clean_zero(mcm):
    """WR-03: releasing a position id that was NEVER locked (the assembly-failure
    site — no fill yet → no position-keyed lock can exist) returns a clean
    Decimal('0') and leaks nothing, never an un-paired release (T-03-16)."""
    before = mcm.available_balance
    released = mcm.release_margin("NEVER_LOCKED")
    assert released == Decimal("0")
    assert mcm.locked_margin_total == Decimal("0")
    assert mcm.available_balance == before
