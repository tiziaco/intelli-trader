"""
Simulated account leaves — the verbatim money-math home (D-01 / D-05, ACCT-01/02).

``SimulatedCashAccount`` is ``CashManager`` moved **byte-for-byte** (D-05): the spot
cash-flow math the SMA_MACD byte-exact oracle exercises (``134 / 46189.87730727451``)
is carried here unchanged. Per the plan 01-01 D-04 resolution the oracle runs the SPOT
settlement path, so this cash leaf is the verbatim-critical surface — the fill / lock /
carry paths deliberately skip the 2dp quantize (Pitfall 1: a quantize there shifts the
equity curve and FAILS the oracle).

``SimulatedMarginAccount(SimulatedCashAccount)`` models margin as a strict *superset*
of cash (D-02): inheritance adds the margin-only surface (locks + borrow carry) plus the
margin/liquidation MATH pulled DOWN from ``PortfolioHandler`` (ACCT-02) with zero
cash-logic duplication.

The ``CashOperation`` audit entity moves here with the cash leaf and is re-exported from
the ``account/`` barrel, giving every importer a single stable home once
``cash_manager.py`` is deleted in plan 01-03.

Money (D-12): Decimal end-to-end via ``to_money``; quantization only at ledger
boundaries, never mid-stream. 4-space indentation (matches the ``cash_manager.py``
code-motion source).
"""

import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, UTC
from typing import Any, Optional, List, Dict
from dataclasses import dataclass

import uuid_utils.compat as uuid_compat

from itrader.core.enums import CashOperationType, PositionSide
from itrader.core.exceptions import (
    InsufficientFundsError,
    InvalidTransactionError,
    StateError,
)
from itrader.core.ids import OrderId
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger
from itrader.portfolio_handler.position import Position

from .base import Account


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


class SimulatedCashAccount(Account):
    """
    Simulated spot cash account — ``CashManager`` moved verbatim (D-01 / D-05,
    ACCT-01).

    The verbatim-critical leaf on the byte-exact oracle SPOT path (D-04): the
    cash-flow math here is byte-for-byte the ``CashManager`` code-motion, so the
    SMA_MACD oracle stays ``134 / 46189.87730727451``. Satisfies the ``Account``
    ABC (``balance`` / ``available`` / ``reserve(order_id, amount)`` /
    ``release(order_id)``), the D-05 reserve/release dropping ``portfolio_id``
    (the account IS the single account, LX-04 1:1).

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
        self.logger = get_itrader_logger().bind(component="SimulatedCashAccount")

        # Cash balance with high precision (D-04 string entry via to_money;
        # quantize to the cash scale at this ledger boundary, D-03 HALF_UP).
        self._balance = to_money(initial_cash).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # M2-08: reserved cash (working state) + cash operations (audit trail) now
        # live in the injected state-storage seam. This account no longer owns
        # those containers — it routes reads/writes through self._storage. The
        # cash *balance* (self._balance) stays on the account: it is not one of the
        # four relocated containers (positions / transactions / cash-ops+reserved /
        # snapshots) — reserved cash is the working-state container, the running
        # balance is intrinsic ledger state. A real Portfolio always injects a
        # shared seam; an account constructed standalone (e.g. with a lightweight
        # test portfolio) falls back to its own in-memory backend.
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
                backend=getattr(portfolio, "_backend", None),
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

        # Configuration
        self.min_balance = Decimal('0.00')  # Minimum allowed balance
        self.max_balance = Decimal('10000000.00')  # Maximum allowed balance
        self.precision = Decimal('0.01')  # Precision for rounding

        self.logger.info("SimulatedCashAccount initialized",
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
        """Get available cash balance (D-10: one buying-power authority).

        ``balance − reserved − locked_margin`` (Plan 02-04, Pitfall 6). In spot
        mode (``enable_margin=False``) nothing is ever locked, so
        ``locked_margin_total`` is a clean ``Decimal('0')`` and this is
        byte-exact ``balance − reserved`` (``x − Decimal('0') == x``).
        """
        return (
            self._balance
            - self._storage.get_reserved_cash()
            - self._storage.get_locked_margin()
        )

    @property
    def reserved_balance(self) -> Decimal:
        """Get reserved cash balance."""
        return self._storage.get_reserved_cash()

    def restore_cash(self, balance: Decimal) -> None:
        """Restore the cash balance from a durable snapshot on restart (D-07 / V17-05).

        The ONE live-restart-only cash setter: sets ``self._balance`` directly from the
        persisted account-state scalar
        (``CachedSqlPortfolioStateStorage.load_account_state``) so a fresh account leaf
        REMEMBERS the pre-restart balance instead of its construction-time initial cash.
        Deliberately bypasses the ``deposit``/``withdraw`` min/max-balance policy gates —
        those guard NEW live admin cash flows; a restart is restoring already-validated
        persisted truth, not admitting a new deposit. Decimal end-to-end via ``to_money``
        (never ``Decimal(float)`` — the persisted Postgres ``Numeric`` round-trips
        exactly). Oracle-dark: only reachable on the live rehydrate path (the in-memory
        backtest backend exposes no ``rehydrate``), so SMA_MACD stays byte-exact.

        Args:
            balance: The persisted cash balance to restore (full precision Decimal).
        """
        self._balance = to_money(balance)

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

        # Record operation (IN-04: return value discarded — the record is
        # appended to storage inside the helper).
        self._create_operation(
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
                required_cash=amount_decimal,
                available_cash=available
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

        # Record operation (IN-04: return value discarded — the record is
        # appended to storage inside the helper).
        self._create_operation(
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
                    required_cash=amount_decimal,
                    available_cash=available
                )

            new_balance = old_balance - amount_decimal
            operation_type = CashOperationType.TRANSACTION_DEBIT
        else:
            # Credit (inflow)
            new_balance = old_balance + amount_decimal
            operation_type = CashOperationType.TRANSACTION_CREDIT

        # Execute cash flow
        self._balance = new_balance

        # Record operation (IN-04: return value discarded — the record is
        # appended to storage inside the helper).
        self._create_operation(
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
                required_cash=required,
                available_cash=self._balance,
            )

    def reserve(self, order_id: OrderId, amount: Decimal) -> None:
        """Reserve cash for a pending order, keyed by ``order_id`` (D-05/Plan 05-03).

        The Account-level reserve (D-05 — drops ``portfolio_id``; the account IS
        the single account, LX-04 1:1). Wraps the verbatim ``reserve_cash``
        mechanics with the fixed description ``"order cash reservation"`` and
        ``str(order_id)`` as the reference id.

        Reservations are tracked per ``order_id`` at FULL precision (OQ4: the
        released amount must equal the reserved amount exactly, so this
        deliberately skips ``_validate_and_convert_amount``'s 2dp quantize).
        The audit entry records balance_before == balance_after — only the
        reservation changes, never the ledger balance.

        Args:
            order_id: The order the reservation is keyed by.
            amount: Amount to reserve (full precision, no quantization)

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
                required_cash=amount_decimal,
                available_cash=available
            )

        self._storage.add_reservation(str(order_id), amount_decimal)

        # Record operation (balance unchanged — reservation only)
        self._create_operation(
            CashOperationType.RESERVATION,
            amount_decimal,
            "order cash reservation",
            str(order_id),
            self._balance,
            self._balance,
            timestamp=datetime.now(UTC)  # admission audit — wall clock, not oracle-serialized
        )

    def release(self, order_id: OrderId) -> None:
        """Release the cash reservation keyed by ``order_id`` (D-05/Plan 05-03).

        The Account-level release (D-05 — drops ``portfolio_id``). Wraps the
        verbatim ``release_reservation`` mechanics with ``str(order_id)`` as the
        reference id.

        Idempotent: releasing an unknown or already-released reference is a
        silent no-op — no exception, no audit entry. When a reservation
        existed, the exact reserved amount (full precision, OQ4) is released
        and a RELEASE_RESERVATION audit entry is recorded.

        Args:
            order_id: The order the reservation was keyed by
        """
        released = self._storage.pop_reservation(str(order_id))
        if released is None:
            return

        # Record operation (balance unchanged — reservation only)
        self._create_operation(
            CashOperationType.RELEASE_RESERVATION,
            released,
            "Cash reservation released",
            str(order_id),
            self._balance,
            self._balance,
            timestamp=datetime.now(UTC)  # admission audit — wall clock, not oracle-serialized
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
                # IN-05: convert at the serialization edge so a binary-float
                # artifact from an incoming float `amount` does not surface in
                # the structured error/audit payload ("Decimal until the edge").
                {"amount": str(to_money(amount))}
            )

        # Convert to Decimal with proper precision (D-04 string entry).
        amount_decimal = to_money(amount).quantize(self.precision, rounding=ROUND_HALF_UP)

        if amount_decimal <= 0:
            raise InvalidTransactionError(
                f"Amount for {operation_type} too small after precision rounding",
                # IN-05/WR-03: mirror the positivity branch — serialize at the
                # edge so an incoming float `amount` (and the rounded Decimal)
                # do not leak a binary-float artifact into the audit payload.
                {"amount": str(to_money(amount)), "rounded_amount": str(amount_decimal)}
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


class SimulatedMarginAccount(SimulatedCashAccount):
    """
    Simulated margin account — the strict *superset* of cash (D-01 / D-02,
    ACCT-02).

    Margin needs everything the cash leaf provides (balance / available /
    reserve / release + the full cash-flow audit trail) AND adds the margin-only
    surface: position-keyed margin locks, short borrow-interest carry, and the
    margin/liquidation MATH pulled DOWN from ``PortfolioHandler`` (ACCT-02 — the
    pure-Decimal math moves here; the liquidation ``global_queue.put`` emission
    and the ``_liquidate_position`` / ``_run_liquidation_pass`` event-minting
    shell STAY in the handler, queue-only rule preserved). Inheritance expresses
    the superset honestly with ZERO cash-logic duplication (D-02).

    Dark-but-verbatim (D-04): the SMA_MACD oracle runs the SPOT path, so this
    leaf is not on the byte-exact hot path — but the math is byte-for-byte the
    ``PortfolioHandler`` / ``CashManager`` code-motion and stays mypy-clean. The
    lock / borrow-interest paths carry full precision (no 2dp quantize, Pitfall
    1); the liq price is quantized only at the FillEvent boundary in the handler
    mint step, never mid-formula.
    """

    def __init__(self, portfolio: Any, initial_cash: float | Decimal = 0.0) -> None:
        super().__init__(portfolio, initial_cash)
        # The Universe read-model used to resolve per-symbol Instruments for the
        # margin/liquidation math. Wired by the runner via ``set_universe`` (the
        # math-pulldown moves the universe seam with it); 01-03 re-points the
        # handler to call DOWN into the account once this leaf is consumed.
        self._universe: Any = None
        self.logger = get_itrader_logger().bind(component="SimulatedMarginAccount")

    def set_universe(self, universe: Any) -> None:
        """Inject the Universe read-model used to resolve per-symbol Instruments.

        D-13: stores the reference; ``maintenance_margin`` reads
        ``universe.instrument(ticker).maintenance_margin_rate`` per open
        position. Mirrors the handler's ``set_universe`` seam (the math-pulldown
        moves the universe dependency down with the math, ACCT-02).
        """
        self._universe = universe

    @property
    def locked_margin_total(self) -> Decimal:
        """Total margin currently locked across all open positions (D-10).

        Position-keyed, a DISTINCT lifecycle from the order-keyed reservation
        (Pitfall 2). Returns a clean ``Decimal('0')`` when nothing is locked
        (Pitfall 6) — never a float, never a quantized zero.
        """
        return self._storage.get_locked_margin()

    def get_locked_margin_for(self, position_id: str) -> Decimal:
        """Return the isolated margin locked for one position id (WR-03).

        Public read-surface delegator over the storage seam so sibling handlers
        (the liquidation engine's ``_liq_inputs``) read a single position's
        locked margin WITHOUT reaching through the private ``_storage``
        attribute — a refactor of the pluggable storage backend then surfaces as
        a typed contract change here, not a silent ``AttributeError`` across a
        domain boundary. Returns a clean ``Decimal('0')`` when nothing is locked.
        """
        return self._storage.get_locked_margin_for(position_id)

    def lock_margin(self, position_id: str, amount: Decimal) -> None:
        """Lock (insert or replace) margin for a position, keyed by id (D-10).

        The margin-mode analogue of ``reserve`` (Pitfall 2 — a DISTINCT,
        position-lifetime container, not the order-keyed reservation). Held at
        FULL precision (no 2dp quantize, same discipline as ``reserve``)
        so a later ``release_margin`` returns the EXACT locked amount with no
        rounding drift. The ledger balance is unchanged — only buying power
        (``available_balance``) moves. A scale-in replaces the prior lock with
        the recomputed ``new_aggregate_notional / L``.

        No audit ``CashOperation`` is recorded here: the lock is working state
        (like a reservation move), and the open/close fill that drives it
        already records its own commission/PnL settlement entry.

        Args:
            position_id: The position the margin is locked under.
            amount: The locked margin (full precision, no quantization).
        """
        self._storage.add_locked_margin(position_id, amount)

    def release_margin(self, position_id: str) -> Decimal:
        """Release the margin locked for a position id, returning the amount.

        Idempotent: releasing an unknown or already-released position is a
        silent no-op that returns a clean ``Decimal('0')`` (no exception). When
        a lock existed, the EXACT locked amount (full precision) is released and
        returned — the caller settles PnL + releases the lock together on close
        (Plan 02-04, D-11).

        Args:
            position_id: The position whose locked margin is released.

        Returns:
            The released amount (full precision), or ``Decimal('0')`` if no
            lock existed.
        """
        released = self._storage.pop_locked_margin(position_id)
        if released is None:
            return Decimal("0")

        return released

    def accrue_borrow_interest(self, amount: Decimal, reference_id: str,
                               description: str, timestamp: datetime) -> None:
        """Debit a short's per-bar borrow-interest carry (CARRY-01/D-03/D-08).

        The financing-cost analogue of ``apply_fill_cash_flow`` for the short
        side: a REAL ledger outflow (carry erodes equity as it accrues so the
        P4 liquidation trigger sees carry-eroded equity), recorded as a
        first-class ``BORROW_INTEREST`` ``CashOperation`` so the drag is an
        attributable ledger line DISTINCT from trade PnL (D-08 — carry never
        folds into ``Position.realised_pnl``).

        Full precision, like ``apply_fill_cash_flow`` (Pitfall 1: routing
        through ``_validate_and_convert_amount``'s 2dp quantize would shift the
        equity curve → byte-exact oracle FAIL). ``timestamp`` is the bar's
        BUSINESS time supplied by the caller — NEVER ``datetime.now(UTC)``
        (Pitfall 5 / D-04 — a wall-clock stamp breaks the determinism double-run
        gate).

        A zero ``amount`` (rate-0 / no-short under default-off) is a silent
        no-op — no balance change, no audit entry — keeping SMA_MACD byte-exact.

        Args:
            amount: Decimal carry magnitude to debit (positive outflow). A
                non-positive amount is a no-op.
            reference_id: Reference id (e.g. position id) keying the audit line.
            description: Audit description.
            timestamp: Bar business time (event-derived — never wall clock).
        """
        if amount <= Decimal("0"):
            return

        old_balance = self._balance
        new_balance = old_balance - amount
        self._balance = new_balance

        self._create_operation(
            CashOperationType.BORROW_INTEREST,
            amount,
            description,
            reference_id,
            old_balance,
            new_balance,
            timestamp=timestamp,
        )

        self.logger.debug("Borrow interest accrued",
            amount=str(amount),
            old_balance=str(old_balance),
            new_balance=str(new_balance),
            reference_id=reference_id
        )

    def assert_lock_fits_buying_power(self, lock_amount: Decimal,
                                      position_id: str) -> None:
        """WR-01 (T-03-15): assert a margin lock fits available buying power.

        A settlement-side solvency assertion run BEFORE a position-keyed margin
        lock is applied: the lock (``aggregate_notional / L``) must fit the
        buying power that remains AFTER releasing any prior lock on the SAME
        position (a scale-in replaces its own lock, so its already-locked amount
        is not double-counted). Fails LOUD — a silent over-lock beyond buying
        power on the short/levered path is a solvency leak the D-02 admission
        reservation should have caught upstream; if it reaches here it is an
        engine bug and the backtest stops loudly.

        Available buying power for this check =
            ``available_balance + own_prior_lock``
        (``available_balance`` already nets reserved + locked; the position's
        own prior lock is about to be released and re-locked, so it is added
        back). A lock within that figure settles normally.

        WR-04 (Plan 04-02) — CALL-ORDER CONTRACT: callers MUST invoke this
        assertion while the position's prior lock is STILL present (i.e. assert
        BEFORE ``release_margin``). The add-back reads
        ``get_locked_margin_for(position_id)`` to credit the position's own prior
        lock; if the prior lock has already been popped by ``release_margin`` it
        reads ``0`` and the add-back is silently dropped. The ``portfolio.py``
        margin-lock sites (open/scale-in and partial/full close) honour this
        order — assert, then release, then re-lock.

        Args:
            lock_amount: The margin about to be locked (``aggregate_notional / L``).
            position_id: The position the lock is keyed under.

        Raises:
            InsufficientFundsError: When ``lock_amount`` exceeds buying power.
        """
        own_prior_lock = self._storage.get_locked_margin_for(position_id)
        buying_power = self.available_balance + own_prior_lock
        if lock_amount > buying_power:
            raise InsufficientFundsError(
                required_cash=lock_amount,
                available_cash=buying_power,
            )

    # ------------------------------------------------------------------
    # Margin / liquidation MATH pulled DOWN from PortfolioHandler (ACCT-02,
    # D-13/MARGIN-03 + LIQ-01/02). Pure Decimal end-to-end (Pitfall 5 — NEVER
    # Decimal(float)); the liq price is quantized to the instrument price scale
    # ONLY at the FillEvent boundary in the handler mint step, never mid-formula.
    # Receiver references adapted from the handler's
    # ``self.get_portfolio(portfolio_id)`` form to the account's own state — the
    # account IS the single account under LX-04 (1:1). The emission shell stays
    # in PortfolioHandler this wave; 01-03 re-points it to call DOWN here.
    # ------------------------------------------------------------------

    def maintenance_margin(self) -> Decimal:
        """Return maintenance margin computed on demand (D-13/MARGIN-03).

        ``maintenance_margin = Σ (Instrument.maintenance_margin_rate × |size| ×
        current_price)`` over the portfolio's OPEN positions, resolving each
        ticker's Instrument via the injected Universe. Decimal end-to-end
        (RESEARCH Pitfall 8 — Position.net_quantity is already |size| Decimal and
        current_price is Decimal; the rate is Decimal). NOT a stored Position
        field (D-13a). With no open positions the sum is ``Decimal("0")``.
        """
        portfolio = self.portfolio
        total = Decimal("0")
        positions = portfolio.position_manager.get_all_positions()
        # WR-02 (T-03-17): the per-symbol Instrument read dereferences the
        # injected Universe. If positions exist but the Universe was never wired
        # (``set_universe`` not called), fail LOUD with a context-rich StateError
        # — never a bare ``AttributeError: 'NoneType' has no attribute
        # 'instrument'``. With NO open positions the read is never reached, so an
        # unwired Universe is benign and the sum is ``Decimal("0")``.
        if positions and self._universe is None:
            raise StateError(
                portfolio.portfolio_id,
                "universe-unwired",
                required_state="universe-wired (call set_universe)",
                operation="maintenance_margin",
            )
        for position in positions.values():
            instrument = self._universe.instrument(position.ticker)
            total += (
                instrument.maintenance_margin_rate
                * abs(position.net_quantity)
                * position.current_price
            )
        return total

    def margin_ratio(self) -> Decimal:
        """Return ``total_equity / maintenance_margin`` (D-12/D-13).

        Mark-to-market equity over maintenance margin — the figure a UI/live layer
        (deferred N+4) reads for margin-call warnings. Reads HONESTLY even when
        breached: an equity drop below maintenance returns a ratio < 1 with NO
        clamp (D-16 — the honest sub-1 reading is the P4 liquidation input). When
        maintenance margin is ``Decimal("0")`` (no open positions, no margin
        required) it returns the deterministic sentinel ``Decimal("0")`` rather
        than dividing by zero.
        """
        maintenance = self.maintenance_margin()
        if maintenance == Decimal("0"):
            return Decimal("0")
        # Bind to a Decimal-typed local: self.portfolio is Any here (the handler's
        # typed PortfolioHandler.total_equity(portfolio_id) -> Decimal source kept
        # this strict-clean), so pin the type at the boundary.
        equity: Decimal = self.portfolio.total_equity
        return equity / maintenance

    @staticmethod
    def _isolated_liq_price(position: Position, wb: Decimal, mmr: Decimal) -> Decimal:
        """Corrected isolated liquidation price (D-01-CORR — HAND-VERIFIED).

        ``margin_per_unit = wb / |size|`` where ``wb`` is the position-keyed
        locked isolated margin (``get_locked_margin_for``) and
        ``|size| = abs(net_quantity)``. With ``entry = avg_price``:

        * LONG : ``(entry − margin_per_unit) / (1 − mmr)``
        * SHORT: ``(entry + margin_per_unit) / (1 + mmr)``

        The corrected formula (NOT the literal CONTEXT D-01 string, which yields
        a negative price). For Entry=100, |size|=200, WB=4000, MMR=0.01 it gives
        the long 80.808080… / short 118.811881… worked numbers. Full Decimal
        precision is carried; quantization happens only at the FillEvent price
        boundary (the mint step).
        """
        size = abs(position.net_quantity)
        entry = position.avg_price
        margin_per_unit = wb / size
        if position.side == PositionSide.LONG:
            return (entry - margin_per_unit) / (Decimal("1") - mmr)
        return (entry + margin_per_unit) / (Decimal("1") + mmr)

    @staticmethod
    def _is_breached(position: Position, close: Decimal, liq_price: Decimal) -> bool:
        """Return True when the bar close crosses the liquidation price.

        LONG breaches when ``close <= liq`` (price fell into the maintenance
        floor); SHORT breaches when ``close >= liq`` (price rose into it). The
        liq price is computed once by the breach pass and passed in.
        """
        if position.side == PositionSide.LONG:
            return close <= liq_price
        return close >= liq_price

    @staticmethod
    def _liquidation_penalty(fee_rate: Decimal, size: Decimal, liq_price: Decimal) -> Decimal:
        """Forced-close penalty = ``fee_rate × |size| × liq_price`` (D-05/LIQ-02).

        Rides ``FillEvent.commission`` (no new FillStatus). Full Decimal
        precision; defaults to ``Decimal("0")`` for a 0 fee rate (oracle-dark).
        """
        return fee_rate * size * liq_price

    def _liq_inputs(self, position: Position) -> "tuple[Decimal, Decimal, Decimal]":
        """Resolve ``(wb, mmr, fee_rate)`` for a position from cash + Universe.

        ``wb`` = the position-keyed locked isolated margin
        (``get_locked_margin_for(str(position.id))`` — the account's OWN margin
        surface, the account being the single account under LX-04 1:1); ``mmr`` =
        ``Instrument.maintenance_margin_rate``; ``fee_rate`` resolved
        Instrument-first (``instrument.liquidation_fee_rate``) — the Universe
        Instrument is the single per-symbol source of truth (the
        ``TradingRules`` config fallback is consulted by the caller only when no
        Universe Instrument carries the rate; here the Instrument always does
        since it defaults to ``Decimal("0")``).
        """
        wb = self.get_locked_margin_for(str(position.id))
        instrument = self._universe.instrument(position.ticker)
        mmr = instrument.maintenance_margin_rate
        fee_rate = instrument.liquidation_fee_rate
        return wb, mmr, fee_rate
