"""
Transaction Manager for portfolio operations.
Validates transactions and records them in the audit history.
"""

from decimal import Decimal
from typing import Any, Optional, List

from itrader.portfolio_handler.transaction import Transaction
from itrader.core.exceptions import InvalidTransactionError
from itrader.logger import get_itrader_logger


class TransactionManager:
    """
    Validates and records transactions (D-11/D-12, Plan 05-05).

    Shrunk surface: ``validate`` (pure checks, raises typed) + ``record``
    (seam history append) + history queries. Settlement ORCHESTRATION lives
    in ``Portfolio.process_transaction`` (D-12: validate -> funds invariant ->
    position mutate -> cash apply -> record); the cash math lives on the
    ``Transaction`` entity (``net_cash_delta``) and in ``CashManager``.

    The never-worked saga machinery (the in-flight context dataclass, the
    transaction-state enum, pending-dict, rollback/cancel/retry) is DELETED,
    not finished (D-11): a fill is a FACT — solvency is enforced pre-trade by
    the reservation gate, so nothing needs rolling back. The applied
    ``Transaction`` entity recorded through the storage seam IS the durable
    audit record (it carries ``fill_id`` + event-derived time).
    """

    def __init__(self, portfolio: Any) -> None:
        self.portfolio = portfolio  # Reference to parent portfolio
        # D-19: lock removed — single-writer contract, see Portfolio docstring.
        self.logger = get_itrader_logger().bind(component="TransactionManager")

        # M2-08: transaction history (append-only) lives in the injected
        # state-storage seam. This manager no longer owns the container — it
        # routes reads/writes through self._storage. A real Portfolio always
        # injects a shared seam; a manager constructed standalone (e.g. with a
        # lightweight test portfolio) falls back to its own in-memory backend
        # so the seam is always present.
        from itrader.portfolio_handler.base import PortfolioStateStorage
        from itrader.portfolio_handler.storage import PortfolioStateStorageFactory
        storage = getattr(portfolio, "state_storage", None)
        if storage is None:
            # D-07 (05.2-05): honor the portfolio's durable environment/backend so
            # a standalone-constructed live portfolio fabricates the SAME 'live'
            # backend rather than silently falling back to in-memory. Defaults
            # ("backtest"/None) keep a lightweight test portfolio in-memory
            # (oracle-dark); portfolio.py:_init_managers is the primary lever.
            storage = PortfolioStateStorageFactory.create(
                getattr(portfolio, "_environment", "backtest"),
                sql_engine=getattr(portfolio, "_sql_engine", None),
                portfolio_id=getattr(portfolio, "portfolio_id", None),
            )
            # WR-02: share the fabricated seam with sibling managers so a
            # standalone-constructed portfolio does not end up with disjoint
            # per-manager backends (which would silently break cross-manager
            # invariants). A real Portfolio always sets state_storage first.
            try:
                portfolio.state_storage = storage
            except AttributeError:
                pass
        self._storage: PortfolioStateStorage = storage

        # Validation rules
        self.min_transaction_amount = Decimal('0.01')
        self.max_transaction_amount = Decimal('1000000.00')
        self.commission_rate_limit = Decimal('0.50')  # 50% max commission rate

        self.logger.info("TransactionManager initialized")

    def validate(self, transaction: Transaction) -> None:
        """Validate transaction data and business rules — PURE checks (D-09).

        Mutates NOTHING. Called by ``Portfolio.process_transaction`` as step 1
        of the validate-first settlement sequence (D-12), before the funds
        invariant and before any position/cash mutation.

        Args:
            transaction: Transaction to validate.

        Raises:
            InvalidTransactionError: If transaction data violates a rule
                (D-10: raise typed, return None — no bool channel).
        """

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
            transaction_id=transaction.id
        )

    def record(self, transaction: Transaction) -> None:
        """Record an applied transaction in the append-only seam history.

        Step 5 of the D-12 settlement sequence — only reached after all
        checks passed and position/cash mutated. The recorded ``Transaction``
        entity (with ``fill_id`` + event-derived time) IS the durable audit
        record (D-11).

        Args:
            transaction: The applied transaction to record.
        """
        self._storage.add_transaction(transaction)

        self.logger.info("Transaction recorded",
            transaction_id=transaction.id,
            portfolio_id=transaction.portfolio_id
        )

    def get_transaction_history(self, limit: Optional[int] = None) -> List[Transaction]:
        """Get transaction history."""
        history = self._storage.get_transaction_history()
        if limit:
            return history[-limit:]
        return history
