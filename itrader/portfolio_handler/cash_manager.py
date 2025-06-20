"""
Cash Manager for portfolio operations.
Handles cash balance management, precision, and cash flow operations.
"""

import threading
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum

from itrader.core.exceptions import (
    InsufficientFundsError,
    InvalidTransactionError,
    ConcurrencyError
)
from itrader.logger import get_itrader_logger


class CashOperationType(Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSACTION_DEBIT = "TRANSACTION_DEBIT"
    TRANSACTION_CREDIT = "TRANSACTION_CREDIT"
    RESERVATION = "RESERVATION"
    RELEASE_RESERVATION = "RELEASE_RESERVATION"


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
    Manages portfolio cash operations with high precision and thread safety.
    
    Features:
    - Decimal precision for financial calculations
    - Thread-safe operations
    - Cash reservations for pending orders
    - Overdraft protection
    - Complete audit trail
    - Balance validation and consistency checks
    """
    
    def __init__(self, portfolio, initial_cash: float = 0.0):
        self.portfolio = portfolio
        self._lock = threading.RLock()
        self.logger = get_itrader_logger().bind(component="CashManager")
        
        # Cash balance with high precision
        self._balance = Decimal(str(initial_cash)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # Reserved cash for pending orders
        self._reserved_cash = Decimal('0.00')
        
        # Audit trail
        self._cash_operations: List[CashOperation] = []
        
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
        with self._lock:
            return self._balance
    
    @property
    def available_balance(self) -> Decimal:
        """Get available cash balance (total - reserved)."""
        with self._lock:
            return self._balance - self._reserved_cash
    
    @property
    def reserved_balance(self) -> Decimal:
        """Get reserved cash balance."""
        with self._lock:
            return self._reserved_cash
    
    def deposit(self, amount: float, description: str = "Cash deposit", reference_id: str = None) -> bool:
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
        
        with self._lock:
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
    
    def withdraw(self, amount: float, description: str = "Cash withdrawal", reference_id: str = None) -> bool:
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
        
        with self._lock:
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
    
    def process_transaction_cash_flow(self, amount: float, is_debit: bool, description: str, transaction_id: str) -> bool:
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
        amount_decimal = self._validate_and_convert_amount(abs(amount), "transaction")
        
        with self._lock:
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
    
    def reserve_cash(self, amount: float, description: str, reference_id: str) -> bool:
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
        
        with self._lock:
            available = self.available_balance
            
            if available < amount_decimal:
                raise InsufficientFundsError(
                    required_cash=float(amount_decimal),
                    available_cash=float(available)
                )
            
            old_reserved = self._reserved_cash
            self._reserved_cash += amount_decimal
            
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
                new_reserved=str(self._reserved_cash),
                reference_id=reference_id
            )
            
            return True
    
    def release_cash_reservation(self, amount: float, description: str, reference_id: str) -> bool:
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
        
        with self._lock:
            if amount_decimal > self._reserved_cash:
                raise InvalidTransactionError(
                    f"Cannot release ${amount_decimal}, only ${self._reserved_cash} is reserved",
                    {"amount": float(amount_decimal), "reserved": float(self._reserved_cash)}
                )
            
            old_reserved = self._reserved_cash
            self._reserved_cash -= amount_decimal
            
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
                new_reserved=str(self._reserved_cash),
                reference_id=reference_id
            )
            
            return True
    
    def get_balance_info(self) -> Dict[str, float]:
        """Get comprehensive balance information."""
        with self._lock:
            return {
                "total_balance": float(self._balance),
                "available_balance": float(self.available_balance),
                "reserved_balance": float(self._reserved_cash),
                "min_balance": float(self.min_balance),
                "max_balance": float(self.max_balance)
            }
    
    def get_cash_operations(self, limit: Optional[int] = None, operation_type: Optional[CashOperationType] = None) -> List[CashOperation]:
        """Get cash operations history."""
        with self._lock:
            operations = self._cash_operations
            
            if operation_type:
                operations = [op for op in operations if op.operation_type == operation_type]
            
            if limit:
                operations = operations[-limit:]
            
            return operations.copy()
    
    def validate_balance_consistency(self) -> bool:
        """Validate balance consistency and integrity."""
        with self._lock:
            # Check if balance is within valid range
            if self._balance < 0:
                self.logger.error("Negative balance detected", balance=str(self._balance))
                return False
            
            if self._reserved_cash < 0:
                self.logger.error("Negative reserved cash detected", reserved=str(self._reserved_cash))
                return False
            
            if self._reserved_cash > self._balance:
                self.logger.error("Reserved cash exceeds total balance",
                    reserved=str(self._reserved_cash),
                    balance=str(self._balance)
                )
                return False
            
            return True
    
    def _validate_and_convert_amount(self, amount: float, operation_type: str) -> Decimal:
        """Validate and convert amount to Decimal with proper precision."""
        if amount <= 0:
            raise InvalidTransactionError(
                f"Amount for {operation_type} must be positive",
                {"amount": amount}
            )
        
        # Convert to Decimal with proper precision
        amount_decimal = Decimal(str(amount)).quantize(self.precision, rounding=ROUND_HALF_UP)
        
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
        with self._lock:
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
            
            self._cash_operations.append(operation)
            return operation
