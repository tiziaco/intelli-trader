"""
Cash Manager for portfolio operations.
Handles cash balance management, precision, and cash flow operations.
"""

import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, UTC
from typing import Any, Optional, List, Dict, Tuple
from dataclasses import dataclass

import uuid_utils.compat as uuid_compat

from itrader.core.enums import CashOperationType
from itrader.core.exceptions import (
    InsufficientFundsError,
    InvalidTransactionError
)
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger


@dataclass
class CashOperation:
    """Record of a cash operation for audit trail.

    Deterministic ledger record (Pitfall 5): ``operation_id`` is a UUIDv7
    generated at record construction; ``timestamp`` is supplied by the caller
    (event-derived on the fill path — NEVER wall clock there). D-06: for fill
    settlements ``amount`` is the SIGNED net cash delta (principal ± commission)
    and ``fee`` carries the commission portion included in ``amount``, so
    balance reconstruction holds: balance = initial + Σ amounts.
    """
    operation_id: uuid.UUID
    operation_type: CashOperationType
    amount: Decimal
    timestamp: datetime
    description: str
    fee: Decimal = Decimal("0")
    reference_id: Optional[str] = None
    balance_before: Optional[Decimal] = None
    balance_after: Optional[Decimal] = None


class CashManager:
    """
    Manages portfolio cash operations with high precision.

    Features:
    - Decimal precision for financial calculations
    - Cash reservations for pending orders
    - Overdraft protection
    - Complete audit trail
    - Balance validation and consistency checks
    """

    def __init__(self, portfolio: Any, initial_cash: float | Decimal = 0.0) -> None:
        self.portfolio = portfolio
        # D-19: lock removed — single-writer contract, see Portfolio docstring.
        self.logger = get_itrader_logger().bind(component="CashManager")
        
        # Cash balance with high precision (D-04 string entry via to_money;
        # quantize to the cash scale at this ledger boundary, D-03 HALF_UP).
        self._balance = to_money(initial_cash).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # M2-08: reserved cash (working state) + cash operations (audit trail) now
        # live in the injected state-storage seam. This manager no longer owns
        # those containers — it routes reads/writes through self._storage. The
        # cash *balance* (self._balance) stays on the manager: it is not one of the
        # four relocated containers (positions / transactions / cash-ops+reserved /
        # snapshots) — reserved cash is the working-state container, the running
        # balance is intrinsic ledger state. A real Portfolio always injects a
        # shared seam; a manager constructed standalone (e.g. with a lightweight
        # test portfolio) falls back to its own in-memory backend.
        from itrader.portfolio_handler.base import PortfolioStateStorage
        from itrader.portfolio_handler.storage import PortfolioStateStorageFactory
        storage = getattr(portfolio, "state_storage", None)
        if storage is None:
            storage = PortfolioStateStorageFactory.create("backtest")
            # WR-02: share the fabricated seam with sibling managers so a
            # standalone-constructed portfolio does not end up with disjoint
            # per-manager backends (which would silently break cross-manager
            # invariants). A real Portfolio always sets state_storage first.
            try:
                portfolio.state_storage = storage
            except AttributeError:
                pass
        self._storage: PortfolioStateStorage = storage

        # Configuration
        self.min_balance = Decimal('0.00')  # Minimum allowed balance
        self.max_balance = Decimal('10000000.00')  # Maximum allowed balance
        self.precision = Decimal('0.01')  # Precision for rounding

        self.logger.info("CashManager initialized",
            initial_balance=str(self._balance),
            min_balance=str(self.min_balance),
            max_balance=str(self.max_balance)
        )
    
    @property
    def balance(self) -> Decimal:
        """Get current cash balance."""
        return self._balance
    
    @property
    def available_balance(self) -> Decimal:
        """Get available cash balance (total - reserved)."""
        return self._balance - self._storage.get_reserved_cash()

    @property
    def reserved_balance(self) -> Decimal:
        """Get reserved cash balance."""
        return self._storage.get_reserved_cash()
    
    def deposit(self, amount: float | Decimal, description: str = "Cash deposit", reference_id: Optional[str] = None) -> bool:
        """
        Deposit cash to the portfolio.
        
        Args:
            amount: Amount to deposit
            description: Description of the deposit
            reference_id: Optional reference ID for tracking
            
        Returns:
            bool: True if successful
            
        Raises:
            InvalidTransactionError: If amount is invalid
        """
        amount_decimal = self._validate_and_convert_amount(amount, "deposit")
        
        old_balance = self._balance
        new_balance = old_balance + amount_decimal
            
        # Check maximum balance limit
        if new_balance > self.max_balance:
            raise InvalidTransactionError(
                f"Deposit would exceed maximum balance limit of ${self.max_balance}",
                {"amount": float(amount_decimal), "current_balance": float(old_balance)}
            )
            
        # Execute deposit
        self._balance = new_balance
            
        # Record operation
        operation = self._create_operation(
            CashOperationType.DEPOSIT,
            amount_decimal,
            description,
            reference_id,
            old_balance,
            new_balance,
            timestamp=datetime.now(UTC)  # admin path — wall clock, not oracle-serialized
        )
            
        self.logger.info("Cash deposit completed",
            amount=str(amount_decimal),
            old_balance=str(old_balance),
            new_balance=str(new_balance),
            reference_id=reference_id
        )
            
        return True
    
    def withdraw(self, amount: float | Decimal, description: str = "Cash withdrawal", reference_id: Optional[str] = None) -> bool:
        """
        Withdraw cash from the portfolio.
        
        Args:
            amount: Amount to withdraw
            description: Description of the withdrawal
            reference_id: Optional reference ID for tracking
            
        Returns:
            bool: True if successful
            
        Raises:
            InvalidTransactionError: If amount is invalid
            InsufficientFundsError: If insufficient funds
        """
        amount_decimal = self._validate_and_convert_amount(amount, "withdrawal")
        
        old_balance = self._balance
        available = self.available_balance
            
        # Check sufficient funds
        if available < amount_decimal:
            raise InsufficientFundsError(
                required_cash=float(amount_decimal),
                available_cash=float(available)
            )
            
        new_balance = old_balance - amount_decimal
            
        # Check minimum balance
        if new_balance < self.min_balance:
            raise InvalidTransactionError(
                f"Withdrawal would breach minimum balance of ${self.min_balance}",
                {"amount": float(amount_decimal), "resulting_balance": float(new_balance)}
            )
            
        # Execute withdrawal
        self._balance = new_balance
            
        # Record operation
        operation = self._create_operation(
            CashOperationType.WITHDRAWAL,
            amount_decimal,
            description,
            reference_id,
            old_balance,
            new_balance,
            timestamp=datetime.now(UTC)  # admin path — wall clock, not oracle-serialized
        )
            
        self.logger.info("Cash withdrawal completed",
            amount=str(amount_decimal),
            old_balance=str(old_balance),
            new_balance=str(new_balance),
            reference_id=reference_id
        )
            
        return True
    
    def process_transaction_cash_flow(self, amount: float | Decimal, is_debit: bool, description: str, transaction_id: str) -> bool:
        """
        Process cash flow from a transaction.
        
        Args:
            amount: Amount of cash flow
            is_debit: True for debit (outflow), False for credit (inflow)
            description: Description of the transaction
            transaction_id: Transaction ID for reference
            
        Returns:
            bool: True if successful
            
        Raises:
            InvalidTransactionError: If amount is invalid
            InsufficientFundsError: If insufficient funds for debit
        """
        abs_amount = abs(to_money(amount))
        amount_decimal = self._validate_and_convert_amount(abs_amount, "transaction")
        
        old_balance = self._balance
            
        if is_debit:
            # Debit (outflow)
            available = self.available_balance
            if available < amount_decimal:
                raise InsufficientFundsError(
                    required_cash=float(amount_decimal),
                    available_cash=float(available)
                )
                
            new_balance = old_balance - amount_decimal
            operation_type = CashOperationType.TRANSACTION_DEBIT
        else:
            # Credit (inflow)
            new_balance = old_balance + amount_decimal
            operation_type = CashOperationType.TRANSACTION_CREDIT
            
        # Execute cash flow
        self._balance = new_balance
            
        # Record operation
        operation = self._create_operation(
            operation_type,
            amount_decimal,
            description,
            transaction_id,
            old_balance,
            new_balance,
            timestamp=datetime.now(UTC)  # legacy path — wall clock, not oracle-serialized
        )
            
        self.logger.debug("Transaction cash flow processed",
            amount=str(amount_decimal),
            is_debit=is_debit,
            old_balance=str(old_balance),
            new_balance=str(new_balance),
            transaction_id=transaction_id
        )
            
        return True
    
    def apply_fill_cash_flow(self, amount: Decimal, fee: Decimal, description: str,
                             reference_id: str, timestamp: datetime) -> None:
        """Apply a fill settlement's signed, full-precision cash delta (D-05/D-06).

        The ONE trade-path cash primitive. Deliberately does NOT route through
        ``_validate_and_convert_amount`` (Pitfall 1: its 2dp HALF_UP quantize
        would silently shift the balance → equity curve → byte-exact oracle
        FAIL on 8dp instrument costs) and does NOT enforce the deposit/withdraw
        min/max-balance policy gates (solvency was enforced pre-trade by the
        reservation gate; the settlement-side check is the separate
        ``assert_funds_invariant`` guard).

        Records exactly ONE ``CashOperation`` per fill (D-06): ``amount`` is
        the SIGNED net cash delta (principal ± commission, full precision),
        ``fee`` the commission portion included in it, ``timestamp`` the
        caller-supplied event-derived time (Pitfall 5 — never wall clock).

        Args:
            amount: Signed full-precision net cash delta — negative for a BUY
                outflow, positive for a SELL inflow. No quantization.
            fee: Commission portion already included in ``amount``.
            description: Audit description.
            reference_id: Reference ID (e.g. transaction id).
            timestamp: Event-derived time (transaction/fill time).
        """
        old_balance = self._balance
        new_balance = old_balance + amount

        self._balance = new_balance

        operation_type = (
            CashOperationType.TRANSACTION_DEBIT
            if amount < 0
            else CashOperationType.TRANSACTION_CREDIT
        )
        self._create_operation(
            operation_type,
            amount,
            description,
            reference_id,
            old_balance,
            new_balance,
            timestamp=timestamp,
            fee=fee,
        )

        self.logger.debug("Fill cash flow applied",
            amount=str(amount),
            fee=str(fee),
            old_balance=str(old_balance),
            new_balance=str(new_balance),
            reference_id=reference_id
        )

    def assert_funds_invariant(self, required: Decimal) -> None:
        """D-10 engine-bug guard: raise when a settlement debit exceeds balance.

        Compares against ``self._balance`` — NEVER the reservation-adjusted
        buying power (Pitfall 2): FILL dispatches portfolio-first, so the
        order's own un-released reservation would false-positive here. The
        D-02 reservation gate should have prevented this state; if it fires,
        it is an engine bug and the backtest stops loudly via the Phase 4
        ``_on_handler_error`` re-raise seam.

        Args:
            required: The actual net cash cost of the settlement debit.

        Raises:
            InsufficientFundsError: When ``required`` exceeds the ledger
                balance.
        """
        if required > self._balance:
            raise InsufficientFundsError(
                required_cash=float(required),
                available_cash=float(self._balance),
            )

    def reserve_cash(self, amount: float | Decimal, description: str, reference_id: str) -> None:
        """Reserve cash for a pending order, keyed by reference id (Plan 05-03).

        Reservations are tracked per ``reference_id`` at FULL precision (OQ4:
        the released amount must equal the reserved amount exactly, so this
        deliberately skips ``_validate_and_convert_amount``'s 2dp quantize).
        The audit entry records balance_before == balance_after — only the
        reservation changes, never the ledger balance.

        Args:
            amount: Amount to reserve (full precision, no quantization)
            description: Description of the reservation
            reference_id: Reference ID (e.g. order id) keying the reservation

        Raises:
            InvalidTransactionError: If amount is not positive
            InsufficientFundsError: If amount exceeds available balance
                (nothing is reserved in that case)
        """
        amount_decimal = to_money(amount)
        if amount_decimal <= 0:
            raise InvalidTransactionError(
                "Amount for reservation must be positive",
                {"amount": float(amount_decimal)}
            )

        available = self.available_balance

        if available < amount_decimal:
            raise InsufficientFundsError(
                required_cash=float(amount_decimal),
                available_cash=float(available)
            )

        self._storage.add_reservation(reference_id, amount_decimal)

        # Record operation (balance unchanged — reservation only)
        self._create_operation(
            CashOperationType.RESERVATION,
            amount_decimal,
            description,
            reference_id,
            self._balance,
            self._balance,
            timestamp=datetime.now(UTC)  # admission audit — wall clock, not oracle-serialized
        )

        self.logger.debug("Cash reserved",
            amount=str(amount_decimal),
            reserved_total=str(self._storage.get_reserved_cash()),
            reference_id=reference_id
        )

    def release_reservation(self, reference_id: str) -> None:
        """Release the cash reservation keyed by a reference id (Plan 05-03).

        Idempotent: releasing an unknown or already-released reference is a
        silent no-op — no exception, no audit entry. When a reservation
        existed, the exact reserved amount (full precision, OQ4) is released
        and a RELEASE_RESERVATION audit entry is recorded.

        Args:
            reference_id: Reference ID the reservation was keyed by
        """
        released = self._storage.pop_reservation(reference_id)
        if released is None:
            return

        # Record operation (balance unchanged — reservation only)
        self._create_operation(
            CashOperationType.RELEASE_RESERVATION,
            released,
            "Cash reservation released",
            reference_id,
            self._balance,
            self._balance,
            timestamp=datetime.now(UTC)  # admission audit — wall clock, not oracle-serialized
        )

        self.logger.debug("Cash reservation released",
            amount=str(released),
            reserved_total=str(self._storage.get_reserved_cash()),
            reference_id=reference_id
        )
    
    def get_balance_info(self) -> Dict[str, float]:
        """Get comprehensive balance information."""
        return {
            "total_balance": float(self._balance),
            "available_balance": float(self.available_balance),
            "reserved_balance": float(self._storage.get_reserved_cash()),
            "min_balance": float(self.min_balance),
            "max_balance": float(self.max_balance)
        }
    
    def get_cash_operations(self, limit: Optional[int] = None, operation_type: Optional[CashOperationType] = None) -> List[CashOperation]:
        """Get cash operations history."""
        operations = self._storage.get_cash_operations()

        if operation_type:
            operations = [op for op in operations if op.operation_type == operation_type]
            
        if limit:
            operations = operations[-limit:]
            
        return operations.copy()
    
    def validate_balance_consistency(self) -> bool:
        """Validate balance consistency and integrity."""
        # Check if balance is within valid range
        if self._balance < 0:
            self.logger.error("Negative balance detected", balance=str(self._balance))
            return False
            
        reserved = self._storage.get_reserved_cash()
        if reserved < 0:
            self.logger.error("Negative reserved cash detected", reserved=str(reserved))
            return False

        if reserved > self._balance:
            self.logger.error("Reserved cash exceeds total balance",
                reserved=str(reserved),
                balance=str(self._balance)
            )
            return False
            
        return True
    
    def _validate_and_convert_amount(self, amount: float | Decimal, operation_type: str) -> Decimal:
        """Validate and convert amount to Decimal with proper precision."""
        if amount <= 0:
            raise InvalidTransactionError(
                f"Amount for {operation_type} must be positive",
                {"amount": amount}
            )
        
        # Convert to Decimal with proper precision (D-04 string entry).
        amount_decimal = to_money(amount).quantize(self.precision, rounding=ROUND_HALF_UP)
        
        if amount_decimal <= 0:
            raise InvalidTransactionError(
                f"Amount for {operation_type} too small after precision rounding",
                {"amount": amount, "rounded_amount": float(amount_decimal)}
            )
        
        return amount_decimal
    
    def _create_operation(self, operation_type: CashOperationType, amount: Decimal,
                         description: str, reference_id: Optional[str],
                         balance_before: Decimal, balance_after: Decimal,
                         timestamp: datetime,
                         fee: Decimal = Decimal("0")) -> CashOperation:
        """Create a cash operation record.

        Deterministic (Pitfall 5): ``operation_id`` is a UUIDv7 (the
        ``uuid_utils.compat`` scheme used at fill construction) and
        ``timestamp`` is CALLER-supplied — the fill path always passes the
        transaction's event-derived time; admin paths (deposit/withdraw/
        reservations, not on the oracle-serialized path) pass their own
        wall-clock source explicitly at their call sites.
        """
        operation = CashOperation(
            operation_id=uuid_compat.uuid7(),
            operation_type=operation_type,
            amount=amount,
            timestamp=timestamp,
            description=description,
            fee=fee,
            reference_id=reference_id,
            balance_before=balance_before,
            balance_after=balance_after
        )

        self._storage.add_cash_operation(operation)
        return operation
