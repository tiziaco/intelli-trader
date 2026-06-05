"""
Transaction Manager for portfolio operations.
Handles transaction validation, processing, and audit trail.
"""

import threading
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import Any, Optional, List, Dict

from itrader.core.ids import TransactionId
from dataclasses import dataclass

from itrader.portfolio_handler.transaction import Transaction
from itrader.core.enums import TransactionType, TransactionState
from itrader.core.exceptions import (
    InvalidTransactionError,
    InsufficientFundsError,
    ConcurrencyError
)
from itrader.logger import get_itrader_logger
from itrader import idgen


@dataclass
class TransactionContext:
    """Context information for transaction processing."""
    correlation_id: str
    state: TransactionState
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    retry_count: int = 0
    
    
class TransactionManager:
    """
    Manages the complete transaction lifecycle including validation,
    execution, rollback, and audit trail.
    
    Thread-safe implementation with proper error handling and logging.
    """
    
    def __init__(self, portfolio: Any) -> None:
        self.portfolio = portfolio  # Reference to parent portfolio
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        self.logger = get_itrader_logger().bind(component="TransactionManager")
        
        # Transaction state tracking
        self._pending_transactions: Dict[TransactionId, TransactionContext] = {}
        self._transaction_history: List[Transaction] = []
        
        # Validation rules
        self.min_transaction_amount = Decimal('0.01')
        self.max_transaction_amount = Decimal('1000000.00')
        self.commission_rate_limit = Decimal('0.50')  # 50% max commission rate
        
        self.logger.info("TransactionManager initialized")
    
    def process_transaction(self, transaction: Transaction) -> bool:
        """
        Process a transaction through the complete lifecycle.
        
        Args:
            transaction: Transaction to process
            
        Returns:
            bool: True if successful, False otherwise
            
        Raises:
            InvalidTransactionError: If transaction data is invalid
            InsufficientFundsError: If insufficient funds
            ConcurrencyError: If concurrent access issues
        """
        correlation_id = f"txn_{transaction.id}_{int(datetime.now().timestamp() * 1000)}"
        
        with self._lock:
            try:
                # Create transaction context
                context = TransactionContext(
                    correlation_id=correlation_id,
                    state=TransactionState.PENDING,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                
                self._pending_transactions[transaction.id] = context
                
                self.logger.info("Transaction processing started",
                    transaction_id=transaction.id,
                    correlation_id=correlation_id,
                    ticker=transaction.ticker,
                    type=transaction.type.name,
                    quantity=str(transaction.quantity),
                    price=str(transaction.price)
                )
                
                # Phase 1: Validate transaction
                self._validate_transaction(transaction, context)
                context.state = TransactionState.VALIDATED
                context.updated_at = datetime.now()
                
                # Phase 2: Check funds availability
                self._check_funds_availability(transaction, context)
                
                # Phase 3: Execute transaction
                self._execute_transaction(transaction, context)
                context.state = TransactionState.EXECUTED
                context.updated_at = datetime.now()
                
                # Phase 4: Record in history
                self._record_transaction(transaction, context)
                
                self.logger.info("Transaction processed successfully",
                    transaction_id=transaction.id,
                    correlation_id=correlation_id
                )
                
                return True
                
            except Exception as e:
                self._handle_transaction_error(transaction, context, e)
                return False
                
            finally:
                # Clean up pending transaction
                self._pending_transactions.pop(transaction.id, None)
    
    def _validate_transaction(self, transaction: Transaction, context: TransactionContext) -> None:
        """Validate transaction data and business rules."""
        
        # Basic data validation
        if transaction.price <= 0:
            raise InvalidTransactionError(
                "Transaction price must be positive",
                {"price": transaction.price, "transaction_id": transaction.id}
            )
        
        if transaction.quantity <= 0:
            raise InvalidTransactionError(
                "Transaction quantity must be positive",
                {"quantity": transaction.quantity, "transaction_id": transaction.id}
            )
        
        if transaction.commission < 0:
            raise InvalidTransactionError(
                "Commission cannot be negative",
                {"commission": transaction.commission, "transaction_id": transaction.id}
            )
        
        # Transaction money fields are already Decimal end-to-end (M2a) — use them
        # directly (no Decimal(str(...)) round-trip needed).
        price = transaction.price
        quantity = transaction.quantity
        commission = transaction.commission

        # Business rule validation
        transaction_value = price * quantity

        if transaction_value < self.min_transaction_amount:
            raise InvalidTransactionError(
                f"Transaction value ${transaction_value} below minimum ${self.min_transaction_amount}",
                {"transaction_value": str(transaction_value), "transaction_id": transaction.id}
            )

        if transaction_value > self.max_transaction_amount:
            raise InvalidTransactionError(
                f"Transaction value ${transaction_value} exceeds maximum ${self.max_transaction_amount}",
                {"transaction_value": str(transaction_value), "transaction_id": transaction.id}
            )

        # Commission rate validation
        if transaction_value > 0:
            commission_rate = commission / transaction_value
            if commission_rate > self.commission_rate_limit:
                raise InvalidTransactionError(
                    f"Commission rate {commission_rate:.4f} exceeds limit {self.commission_rate_limit}",
                    {"commission_rate": str(commission_rate), "transaction_id": transaction.id}
                )
        
        # Ticker validation (basic format check)
        if not transaction.ticker or len(transaction.ticker) < 3:
            raise InvalidTransactionError(
                "Invalid ticker format",
                {"ticker": transaction.ticker, "transaction_id": transaction.id}
            )
        
        self.logger.debug("Transaction validation passed",
            transaction_id=transaction.id,
            correlation_id=context.correlation_id
        )
    
    def _check_funds_availability(self, transaction: Transaction, context: TransactionContext) -> None:
        """Check if sufficient funds are available for the transaction."""
        
        if transaction.type == TransactionType.BUY:
            # transaction money fields are Decimal end-to-end (M2a); cash is Decimal
            # (no defensive Decimal(str(cash)) needed — the float round-trip is gone).
            required_cash = transaction.price * transaction.quantity + transaction.commission
            available_cash = self.portfolio.cash

            if available_cash < required_cash:
                raise InsufficientFundsError(
                    required_cash=float(required_cash),
                    available_cash=float(available_cash),
                    transaction_id=transaction.id
                )

            self.logger.debug("Funds availability check passed",
                transaction_id=transaction.id,
                correlation_id=context.correlation_id,
                required_cash=str(required_cash),
                available_cash=str(available_cash)
            )
    
    def _execute_transaction(self, transaction: Transaction, context: TransactionContext) -> None:
        """Execute the validated transaction."""
        
        # Calculate transaction cost with high precision
        transaction_cost = self._calculate_transaction_cost(transaction)

        # Apply the full-precision Decimal cost to the cash ledger via the
        # precision-preserving CashManager primitive (CR-03). This avoids the 2dp
        # quantization and the deposit/withdraw min/max-balance gate that the
        # `self.portfolio.cash` setter would impose (it routes through
        # deposit/withdraw -> _validate_and_convert_amount). The funds check for a
        # BUY already ran in _check_funds_availability, so re-running the policy
        # gate here would be both redundant and lossy. NO float() round-trip on
        # the money value (the #17 defect).
        old_cash = self.portfolio.cash
        self.portfolio.cash_manager.apply_transaction_delta(
            transaction_cost,
            description=f"Transaction {transaction.type.name} {transaction.ticker}",
            reference_id=str(transaction.id),
        )

        self.logger.debug("Transaction executed",
            transaction_id=transaction.id,
            correlation_id=context.correlation_id,
            old_cash=str(old_cash),
            new_cash=str(self.portfolio.cash),
            transaction_cost=str(transaction_cost)
        )
    
    def _calculate_transaction_cost(self, transaction: Transaction) -> Decimal:
        """
        Calculate transaction cost with high precision.
        
        Returns:
            Decimal: Transaction cost (negative for outflow, positive for inflow)
        """
        # Transaction money fields are already Decimal end-to-end (normalized in
        # Transaction.__post_init__) — use them directly with NO Decimal(str(...))
        # round-trip (WR-03).
        price = transaction.price
        quantity = transaction.quantity
        commission = transaction.commission

        if transaction.type == TransactionType.BUY:
            # Outflow of cash
            return -(price * quantity + commission)
        else:  # SELL
            # Inflow of cash
            return (price * quantity - commission)
    
    def _record_transaction(self, transaction: Transaction, context: TransactionContext) -> None:
        """Record transaction in history for audit trail."""
        
        self._transaction_history.append(transaction)
        
        self.logger.info("Transaction recorded",
            transaction_id=transaction.id,
            correlation_id=context.correlation_id,
            portfolio_id=transaction.portfolio_id
        )
    
    def _handle_transaction_error(self, transaction: Transaction, context: TransactionContext, error: Exception) -> None:
        """Handle transaction processing errors."""
        
        context.state = TransactionState.FAILED
        context.error_message = str(error)
        context.updated_at = datetime.now()
        
        self.logger.error("Transaction processing failed",
            transaction_id=transaction.id,
            correlation_id=context.correlation_id,
            error_type=type(error).__name__,
            error_message=str(error),
            exc_info=True
        )
        
        # Re-raise the exception for caller handling
        raise
    
    def get_transaction_history(self, limit: Optional[int] = None) -> List[Transaction]:
        """Get transaction history."""
        with self._lock:
            if limit:
                return self._transaction_history[-limit:]
            return self._transaction_history.copy()
    
    def get_pending_transactions(self) -> Dict[TransactionId, TransactionContext]:
        """Get currently pending transactions."""
        with self._lock:
            return self._pending_transactions.copy()
    
    def cancel_pending_transaction(self, transaction_id: TransactionId) -> bool:
        """Cancel a pending transaction."""
        with self._lock:
            if transaction_id in self._pending_transactions:
                context = self._pending_transactions[transaction_id]
                context.state = TransactionState.CANCELLED
                context.updated_at = datetime.now()
                
                self.logger.info("Transaction cancelled",
                    transaction_id=transaction_id,
                    correlation_id=context.correlation_id
                )
                return True
            return False
