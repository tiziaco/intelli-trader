"""
Cash Manager for portfolio operations.
Handles cash balance management, precision, and cash flow operations.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import Any, Optional, List, Dict, Tuple
from dataclasses import dataclass

from itrader.core.enums import CashOperationType
from itrader.core.exceptions import (
    InsufficientFundsError,
    InvalidTransactionError
)
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger


@dataclass
class CashOperation:
    """Record of a cash operation for audit trail."""
    operation_id: str
    operation_type: CashOperationType
    amount: Decimal
    timestamp: datetime
    description: str
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
        
        # Operation counter for unique IDs
        self._operation_counter = 0
        
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
            new_balance
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
            new_balance
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
            new_balance
        )
            
        self.logger.debug("Transaction cash flow processed",
            amount=str(amount_decimal),
            is_debit=is_debit,
            old_balance=str(old_balance),
            new_balance=str(new_balance),
            transaction_id=transaction_id
        )
            
        return True
    
    def apply_transaction_delta(self, delta: Decimal, description: str = "Transaction cash delta", reference_id: Optional[str] = None) -> bool:
        """Apply a signed, full-precision Decimal delta to the cash ledger.

        Precision-preserving transaction-path primitive (CR-03). Unlike
        ``deposit``/``withdraw``/``process_transaction_cash_flow`` this does NOT
        route through ``_validate_and_convert_amount`` (so it never quantizes the
        delta to 2dp) and does NOT enforce the deposit/withdraw min/max-balance
        policy gates — the transaction layer already ran its own funds check in
        ``TransactionManager._check_funds_availability`` before calling this.

        The full instrument precision of ``delta`` is preserved on ``_balance``.
        A negative delta is an outflow (BUY cost), a positive delta an inflow
        (SELL proceeds). A ``CashOperation`` is recorded for the audit trail.

        Args:
            delta: Signed full-precision Decimal cash delta (no quantization).
            description: Audit description.
            reference_id: Optional reference ID (e.g. transaction id).

        Returns:
            bool: True if applied.
        """
        old_balance = self._balance
        new_balance = old_balance + delta

        self._balance = new_balance

        operation_type = (
            CashOperationType.TRANSACTION_DEBIT
            if delta < 0
            else CashOperationType.TRANSACTION_CREDIT
        )
        self._create_operation(
            operation_type,
            abs(delta),
            description,
            reference_id,
            old_balance,
            new_balance,
        )

        self.logger.debug("Transaction cash delta applied",
            delta=str(delta),
            old_balance=str(old_balance),
            new_balance=str(new_balance),
            reference_id=reference_id
        )

        return True

    def reserve_cash(self, amount: float | Decimal, description: str, reference_id: str) -> bool:
        """
        Reserve cash for pending orders.
        
        Args:
            amount: Amount to reserve
            description: Description of the reservation
            reference_id: Reference ID for tracking
            
        Returns:
            bool: True if successful
            
        Raises:
            InvalidTransactionError: If amount is invalid
            InsufficientFundsError: If insufficient available funds
        """
        amount_decimal = self._validate_and_convert_amount(amount, "reservation")
        
        available = self.available_balance
            
        if available < amount_decimal:
            raise InsufficientFundsError(
                required_cash=float(amount_decimal),
                available_cash=float(available)
            )
            
        old_reserved = self._storage.get_reserved_cash()
        new_reserved = old_reserved + amount_decimal
        self._storage.set_reserved_cash(new_reserved)

        # Record operation
        operation = self._create_operation(
            CashOperationType.RESERVATION,
            amount_decimal,
            description,
            reference_id,
            self._balance,
            self._balance  # Balance doesn't change, only reservation
        )

        self.logger.debug("Cash reserved",
            amount=str(amount_decimal),
            old_reserved=str(old_reserved),
            new_reserved=str(new_reserved),
            reference_id=reference_id
        )
            
        return True
    
    def release_cash_reservation(self, amount: float | Decimal, description: str, reference_id: str) -> bool:
        """
        Release reserved cash.
        
        Args:
            amount: Amount to release
            description: Description of the release
            reference_id: Reference ID for tracking
            
        Returns:
            bool: True if successful
            
        Raises:
            InvalidTransactionError: If amount is invalid or exceeds reserved amount
        """
        amount_decimal = self._validate_and_convert_amount(amount, "release")
        
        reserved = self._storage.get_reserved_cash()
        if amount_decimal > reserved:
            raise InvalidTransactionError(
                f"Cannot release ${amount_decimal}, only ${reserved} is reserved",
                {"amount": float(amount_decimal), "reserved": float(reserved)}
            )

        old_reserved = reserved
        new_reserved = reserved - amount_decimal
        self._storage.set_reserved_cash(new_reserved)

        # Record operation
        operation = self._create_operation(
            CashOperationType.RELEASE_RESERVATION,
            amount_decimal,
            description,
            reference_id,
            self._balance,
            self._balance  # Balance doesn't change, only reservation
        )

        self.logger.debug("Cash reservation released",
            amount=str(amount_decimal),
            old_reserved=str(old_reserved),
            new_reserved=str(new_reserved),
            reference_id=reference_id
        )
            
        return True
    
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
                         balance_before: Decimal, balance_after: Decimal) -> CashOperation:
        """Create a cash operation record."""
        self._operation_counter += 1
        operation_id = f"cash_op_{self._operation_counter}_{int(datetime.now().timestamp() * 1000)}"
            
        operation = CashOperation(
            operation_id=operation_id,
            operation_type=operation_type,
            amount=amount,
            timestamp=datetime.now(),
            description=description,
            reference_id=reference_id,
            balance_before=balance_before,
            balance_after=balance_after
        )
            
        self._storage.add_cash_operation(operation)
        return operation
