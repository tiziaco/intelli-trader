"""
Simulated account leaves — the compute-side money math.

``SimulatedCashAccount`` carries the spot cash-flow math the SMA_MACD byte-exact
oracle exercises (``134 / 46189.87730727451``). The fill / lock / carry paths
deliberately skip the 2dp quantize: a quantize there shifts the equity curve and
FAILS the oracle.

``SimulatedMarginAccount(SimulatedCashAccount)`` models margin as a strict *superset*
of cash — inheritance adds the margin-only surface (locks, borrow carry, and the
margin/liquidation math) with zero cash-logic duplication.

Neither leaf holds a reference back to the ``Portfolio`` that owns it. Both construct
from ``initial_cash`` plus an explicitly-supplied state-storage seam, and the
portfolio-side reads the margin math needs (open positions, portfolio id, total
equity) arrive as METHOD ARGUMENTS. That is what lets a built ``Account`` be handed TO
a ``Portfolio`` instead of the constructor demanding a ``Portfolio`` that does not
exist yet.

Money is Decimal end-to-end via ``to_money``; quantization happens only at ledger
boundaries, never mid-stream.
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
from itrader.portfolio_handler.base import PortfolioStateStorage
from itrader.portfolio_handler.position import Position

from .base import Account


@dataclass
class CashOperation:
    """Record of a cash operation for audit trail.

    ``operation_id`` is a UUIDv7 minted at record construction; ``timestamp`` is
    caller-supplied (event-derived on the fill path — never wall clock there).
    For fill settlements ``amount`` is the SIGNED net cash delta (principal ±
    commission) and ``fee`` the commission portion included in it, so balance
    reconstruction holds: balance = initial + Σ amounts.
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
    Simulated spot cash account — the verbatim-critical leaf on the byte-exact
    oracle SPOT path.

    Satisfies the ``Account`` ABC (``balance`` / ``available`` /
    ``reserve(order_id, amount)`` / ``release(order_id)``); reserve and release
    are keyed by order alone because the account IS the single account (1:1).

    Holds NO reference to the ``Portfolio`` that owns it. The state-storage seam
    is supplied EXPLICITLY by the caller rather than sniffed off a portfolio
    attribute — that seam was always the only thing this leaf wanted from the
    portfolio, so passing it names the dependency instead of reaching through an
    object graph for it.
    """

    def __init__(
        self,
        initial_cash: float | Decimal = 0.0,
        *,
        state_storage: PortfolioStateStorage,
        account_id: str | None = None,
        venue_name: str | None = None,
    ) -> None:
        """Construct a spot cash leaf from cash alone.

        Parameters
        ----------
        initial_cash:
            The opening cash balance, quantized to the cash scale at this ledger
            boundary.
        state_storage:
            The shared ``PortfolioStateStorage`` seam (reserved cash, locked
            margin, cash-operation audit trail). ``Portfolio._init_managers``
            passes the SAME instance its four managers hold, so the account and
            its siblings stay on one backend.

            Keyword-only so a stale ``Account(portfolio, cash)`` call fails loud
            with a ``TypeError`` rather than binding a portfolio into this slot.
            REQUIRED with no default: a leaf that minted its own backend would be
            invisible to the live restart path — ``state_storage.rehydrate(account)``
            repopulates the reservation and locked-margin caches on the
            PORTFOLIO's instance — so it would silently lose every reservation
            across a restart while reporting itself live. Backtest reads those
            containers nowhere else, so the byte-exact oracle and the whole suite
            stay green throughout.
        """
        # No lock: the single-writer contract makes one unnecessary (see Portfolio).
        self.logger = get_itrader_logger().bind(component="SimulatedCashAccount")

        # The ONE storage site for the (venue_name, account_id) pair this compute
        # leaf belongs to, read back through the ``Portfolio.venue_name`` /
        # ``.account_id`` properties. Optional because the backtest oracle leaf
        # names no account; the caller that DOES know the pair threads it in so
        # the leaf and the portfolio can never disagree about which account it is.
        self.account_id = account_id
        self.venue_name = venue_name

        # `Portfolio._validate_initial_state` asks the SAME helper for the cash
        # scale, so the opening-cash equality guard cannot be broken one-sidedly.
        self._balance = self.quantize_cash(initial_cash)

        # Reserved cash and the cash-operation audit trail live in the injected
        # seam; only the running balance is intrinsic ledger state on the account.
        self._storage: PortfolioStateStorage = state_storage

        self.min_balance = Decimal('0.00')
        self.max_balance = Decimal('10000000.00')
        # `precision` is inherited from the `Account` ABC — the cash scale is
        # declared once there, never copied here.

        self.logger.info("SimulatedCashAccount initialized",
            initial_balance=str(self._balance),
            min_balance=str(self.min_balance),
            max_balance=str(self.max_balance)
        )

    @property
    def state_storage(self) -> PortfolioStateStorage:
        """The shared persistence seam this leaf routes its working state through.

        Read-only so ``Portfolio`` ADOPTS the seam of the account it is handed
        rather than building a second one — the account is built BEFORE its
        portfolio exists, and the split backend that would result is the restart
        defect described on ``__init__``. There is no setter: rebinding after
        construction is the late-init shape this design removes.
        """
        return self._storage

    @property
    def balance(self) -> Decimal:
        return self._balance

    @property
    def available_balance(self) -> Decimal:
        """The single buying-power authority: ``balance − reserved − locked_margin``.

        In spot mode nothing is ever locked, so locked margin is a clean
        ``Decimal('0')`` and this is byte-exact ``balance − reserved``.
        """
        return (
            self._balance
            - self._storage.get_reserved_cash()
            - self._storage.get_locked_margin()
        )

    @property
    def reserved_balance(self) -> Decimal:
        return self._storage.get_reserved_cash()

    def restore_cash(self, balance: Decimal) -> None:
        """Restore the cash balance from a durable snapshot on restart.

        The ONE live-restart-only cash setter, reading the persisted account-state
        scalar so a fresh leaf REMEMBERS the pre-restart balance instead of its
        construction-time initial cash. Deliberately bypasses the
        ``deposit``/``withdraw`` min/max-balance gates: those guard NEW live admin
        cash flows, while a restart restores already-validated persisted truth.

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

        Raises:
            InvalidTransactionError: If amount is invalid, or would breach the
                maximum balance limit
        """
        amount_decimal = self._validate_and_convert_amount(amount, "deposit")

        old_balance = self._balance
        new_balance = old_balance + amount_decimal

        if new_balance > self.max_balance:
            raise InvalidTransactionError(
                f"Deposit would exceed maximum balance limit of ${self.max_balance}",
                {"amount": float(amount_decimal), "current_balance": float(old_balance)}
            )

        self._balance = new_balance

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

        Raises:
            InvalidTransactionError: If amount is invalid, or would breach the
                minimum balance
            InsufficientFundsError: If insufficient funds
        """
        amount_decimal = self._validate_and_convert_amount(amount, "withdrawal")

        old_balance = self._balance
        available = self.available_balance

        if available < amount_decimal:
            raise InsufficientFundsError(
                required_cash=amount_decimal,
                available_cash=available
            )

        new_balance = old_balance - amount_decimal

        if new_balance < self.min_balance:
            raise InvalidTransactionError(
                f"Withdrawal would breach minimum balance of ${self.min_balance}",
                {"amount": float(amount_decimal), "resulting_balance": float(new_balance)}
            )

        self._balance = new_balance

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

        Raises:
            InvalidTransactionError: If amount is invalid
            InsufficientFundsError: If insufficient funds for debit
        """
        abs_amount = abs(to_money(amount))
        amount_decimal = self._validate_and_convert_amount(abs_amount, "transaction")

        old_balance = self._balance

        if is_debit:
            available = self.available_balance
            if available < amount_decimal:
                raise InsufficientFundsError(
                    required_cash=amount_decimal,
                    available_cash=available
                )

            new_balance = old_balance - amount_decimal
            operation_type = CashOperationType.TRANSACTION_DEBIT
        else:
            new_balance = old_balance + amount_decimal
            operation_type = CashOperationType.TRANSACTION_CREDIT

        self._balance = new_balance

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
        """Apply a fill settlement's signed, full-precision cash delta.

        The ONE trade-path cash primitive. Deliberately does NOT route through
        ``_validate_and_convert_amount``: its 2dp HALF_UP quantize would silently
        shift the balance → equity curve → byte-exact oracle FAIL on 8dp
        instrument costs. It also skips the deposit/withdraw min/max-balance
        gates — solvency is enforced pre-trade by the reservation gate, and the
        settlement-side check is the separate ``assert_funds_invariant`` guard.

        Records exactly ONE ``CashOperation`` per fill.

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
        """Engine-bug guard: raise when a settlement debit exceeds balance.

        Compares against ``self._balance`` — NEVER the reservation-adjusted
        buying power: FILL dispatches portfolio-first, so the order's own
        un-released reservation would false-positive here. The admission
        reservation gate should have prevented this state; if it fires it is an
        engine bug and the backtest stops loudly through ``FailFastPolicy``.

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
        """Reserve cash for a pending order, keyed by ``order_id``.

        Reservations are tracked at FULL precision — the released amount must
        equal the reserved amount exactly, so this deliberately skips
        ``_validate_and_convert_amount``'s 2dp quantize. The audit entry records
        balance_before == balance_after: only the reservation moves, never the
        ledger balance.

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
        """Release the cash reservation keyed by ``order_id``.

        Idempotent: releasing an unknown or already-released reference is a
        silent no-op — no exception, no audit entry. When a reservation existed
        the exact reserved amount is released at full precision.

        Args:
            order_id: The order the reservation was keyed by
        """
        released = self._storage.pop_reservation(str(order_id))
        if released is None:
            return

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
        """Balance, buying power and the configured limits, as floats."""
        return {
            "total_balance": float(self._balance),
            "available_balance": float(self.available_balance),
            "reserved_balance": float(self._storage.get_reserved_cash()),
            "min_balance": float(self.min_balance),
            "max_balance": float(self.max_balance)
        }

    def get_cash_operations(self, limit: Optional[int] = None, operation_type: Optional[CashOperationType] = None) -> List[CashOperation]:
        """Return the cash-operation audit trail, oldest first.

        Args:
            limit: Keep only the most recent ``limit`` operations.
            operation_type: Keep only operations of this type.
        """
        operations = self._storage.get_cash_operations()

        if operation_type:
            operations = [op for op in operations if op.operation_type == operation_type]

        if limit:
            operations = operations[-limit:]

        return operations.copy()

    def validate_balance_consistency(self) -> bool:
        """Return False (and log) when balance or reserved cash is incoherent."""
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
        """Validate an admin-path amount and quantize it to the cash scale."""
        if amount <= 0:
            raise InvalidTransactionError(
                f"Amount for {operation_type} must be positive",
                # Serialize at the edge: a binary-float artifact from an incoming
                # float `amount` must not surface in the audit payload.
                {"amount": str(to_money(amount))}
            )

        amount_decimal = to_money(amount).quantize(self.precision, rounding=ROUND_HALF_UP)

        if amount_decimal <= 0:
            raise InvalidTransactionError(
                f"Amount for {operation_type} too small after precision rounding",
                {"amount": str(to_money(amount)), "rounded_amount": str(amount_decimal)}
            )

        return amount_decimal

    def _create_operation(self, operation_type: CashOperationType, amount: Decimal,
                         description: str, reference_id: Optional[str],
                         balance_before: Decimal, balance_after: Decimal,
                         timestamp: datetime,
                         fee: Decimal = Decimal("0")) -> CashOperation:
        """Append one cash-operation record to the audit trail.

        ``timestamp`` is CALLER-supplied so the record stays deterministic: the
        fill path passes the transaction's event-derived time, while admin paths
        (deposit/withdraw/reservations, none of them oracle-serialized) name
        their own wall-clock source at the call site.
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
    Simulated margin account — the strict *superset* of cash.

    Margin needs everything the cash leaf provides (balance / available /
    reserve / release plus the cash-flow audit trail) AND adds the margin-only
    surface: position-keyed margin locks, short borrow-interest carry, and the
    margin/liquidation math. Only the pure-Decimal math lives here — the
    liquidation ``global_queue.put`` emission and its event-minting shell stay in
    ``PortfolioHandler``, preserving the queue-only rule.

    The SMA_MACD oracle runs the SPOT path, so this leaf is not on the byte-exact
    hot path. The lock and borrow-interest paths still carry full precision (no
    2dp quantize); the liq price is quantized only at the FillEvent boundary in
    the handler's mint step, never mid-formula.
    """

    def __init__(
        self,
        initial_cash: float | Decimal = 0.0,
        *,
        state_storage: PortfolioStateStorage,
        account_id: str | None = None,
        venue_name: str | None = None,
    ) -> None:
        """Construct a margin leaf from cash alone.

        Parameters
        ----------
        initial_cash:
            The opening cash balance (see ``SimulatedCashAccount.__init__``).
        state_storage:
            The shared ``PortfolioStateStorage`` seam, keyword-only and REQUIRED —
            same contract as the cash superclass. This arm must state it
            independently because it declares its own ``__init__``: a default here
            would keep the restart defect alive on the leaf that ALSO parks
            position-keyed margin locks on the seam, dropping locked margin as
            well as reservations.
        """
        super().__init__(
            initial_cash, state_storage=state_storage,
            account_id=account_id, venue_name=venue_name)
        # Resolves per-symbol Instruments for the margin/liquidation math; wired
        # by the runner through ``set_universe``.
        self._universe: Any = None
        self.logger = get_itrader_logger().bind(component="SimulatedMarginAccount")

    def set_universe(self, universe: Any) -> None:
        """Inject the Universe read-model used to resolve per-symbol Instruments.

        ``maintenance_margin`` reads
        ``universe.instrument(ticker).maintenance_margin_rate`` per open position.
        """
        self._universe = universe

    @property
    def locked_margin_total(self) -> Decimal:
        """Total margin currently locked across all open positions.

        Position-keyed — a DISTINCT lifecycle from the order-keyed reservation.
        Returns a clean ``Decimal('0')`` when nothing is locked, never a float
        and never a quantized zero.
        """
        return self._storage.get_locked_margin()

    def get_locked_margin_for(self, position_id: str) -> Decimal:
        """Return the isolated margin locked for one position id.

        A public delegator over the storage seam so callers read a single
        position's locked margin WITHOUT reaching through the private
        ``_storage`` attribute — a backend refactor then surfaces as a typed
        contract change here, not a silent ``AttributeError`` across a domain
        boundary. Returns a clean ``Decimal('0')`` when nothing is locked.
        """
        return self._storage.get_locked_margin_for(position_id)

    def lock_margin(self, position_id: str, amount: Decimal) -> None:
        """Lock (insert or replace) margin for a position, keyed by id.

        The margin-mode analogue of ``reserve``, over a DISTINCT
        position-lifetime container. Held at FULL precision so a later
        ``release_margin`` returns the EXACT locked amount with no rounding
        drift. The ledger balance is unchanged — only buying power moves. A
        scale-in replaces the prior lock with the recomputed
        ``new_aggregate_notional / L``.

        No audit ``CashOperation`` is recorded: the lock is working state, and
        the fill that drives it already records its own settlement entry.

        Args:
            position_id: The position the margin is locked under.
            amount: The locked margin (full precision, no quantization).
        """
        self._storage.add_locked_margin(position_id, amount)

    def release_margin(self, position_id: str) -> Decimal:
        """Release the margin locked for a position id, returning the amount.

        Idempotent: releasing an unknown or already-released position is a silent
        no-op returning a clean ``Decimal('0')``. When a lock existed the EXACT
        locked amount is released and returned, so the caller can settle PnL and
        release the lock together on close.

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
        """Debit a short's per-bar borrow-interest carry.

        The financing-cost analogue of ``apply_fill_cash_flow`` for the short
        side: a REAL ledger outflow, so carry erodes equity as it accrues and the
        liquidation trigger sees the eroded figure. Recorded as a first-class
        ``BORROW_INTEREST`` operation so the drag stays an attributable ledger
        line DISTINCT from trade PnL — carry never folds into
        ``Position.realised_pnl``.

        Full precision, like ``apply_fill_cash_flow``.

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
        """Assert a margin lock fits available buying power.

        A settlement-side solvency assertion run BEFORE a position-keyed margin
        lock is applied. Buying power for this check is
        ``available_balance + own_prior_lock``: ``available_balance`` already
        nets reserved and locked cash, and the position's own prior lock is about
        to be released and re-locked, so it is added back rather than
        double-counted. Fails LOUD — a silent over-lock on the short/levered path
        is a solvency leak the admission reservation should have caught upstream.

        CALL-ORDER CONTRACT: callers MUST invoke this while the position's prior
        lock is STILL present — assert BEFORE ``release_margin``. The add-back
        reads ``get_locked_margin_for(position_id)``; once ``release_margin`` has
        popped that lock it reads ``0`` and the add-back is silently dropped,
        turning the assertion into a stricter check that rejects legitimate
        scale-ins. The ``portfolio.py`` lock sites honour this order.

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
    # Margin / liquidation math. Pure Decimal end-to-end; the liq price is
    # quantized to the instrument price scale ONLY at the FillEvent boundary in
    # the handler's mint step, never mid-formula. The portfolio-side reads these
    # need (open positions, portfolio id, mark-to-market equity) arrive as METHOD
    # ARGUMENTS: the leaf answers a margin question about state it is HANDED, so
    # it needs no object graph to walk and no back-reference to its Portfolio.
    # ------------------------------------------------------------------

    def maintenance_margin(self, positions: Any, portfolio_id: Any) -> Decimal:
        """Return maintenance margin computed on demand.

        ``Σ (Instrument.maintenance_margin_rate × |size| × current_price)`` over
        the supplied OPEN positions, resolving each ticker's Instrument via the
        injected Universe. Computed, never a stored Position field.

        Parameters
        ----------
        positions:
            The open positions to price, as the ticker-keyed mapping
            ``PositionManager.get_all_positions()`` returns.
        portfolio_id:
            The portfolio the positions belong to. Carried purely as attribution
            context on the fail-loud ``StateError`` below — not droppable, since
            losing it degrades a context-rich error on a money path.

        Returns
        -------
        Decimal
            The maintenance margin at full precision, ``Decimal("0")`` when there
            is nothing to price.
        """
        total = Decimal("0")
        # Fail loud with attribution rather than a bare ``AttributeError:
        # 'NoneType' has no attribute 'instrument'``. With no open positions the
        # Instrument read is never reached, so an unwired Universe is benign.
        if positions and self._universe is None:
            raise StateError(
                portfolio_id,
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

    def margin_ratio(self, equity: Decimal, positions: Any, portfolio_id: Any) -> Decimal:
        """Return ``total_equity / maintenance_margin``.

        Reads HONESTLY even when breached: an equity drop below maintenance
        returns a ratio < 1 with NO clamp, because that sub-1 reading is what the
        liquidation pass consumes. With zero maintenance margin (no open
        positions) it returns the deterministic ``Decimal("0")`` sentinel rather
        than dividing by zero.

        Parameters
        ----------
        equity:
            Mark-to-market total equity, already Decimal at the boundary.
        positions:
            The open positions, forwarded verbatim to ``maintenance_margin``.
        portfolio_id:
            The portfolio id, forwarded verbatim to ``maintenance_margin`` for
            its unwired-Universe guard.

        Returns
        -------
        Decimal
            The ratio, or the ``Decimal("0")`` zero-maintenance sentinel.
        """
        maintenance = self.maintenance_margin(positions, portfolio_id)
        if maintenance == Decimal("0"):
            return Decimal("0")
        return equity / maintenance

    @staticmethod
    def _isolated_liq_price(position: Position, wb: Decimal, mmr: Decimal) -> Decimal:
        """Isolated liquidation price.

        ``margin_per_unit = wb / |size|`` where ``wb`` is the position-keyed
        locked isolated margin and ``|size| = abs(net_quantity)``. With
        ``entry = avg_price``:

        * LONG : ``(entry − margin_per_unit) / (1 − mmr)``
        * SHORT: ``(entry + margin_per_unit) / (1 + mmr)``

        Dividing by ``(1 ∓ mmr)`` rather than multiplying is what keeps the price
        positive; the multiplied form yields a negative price. For Entry=100,
        |size|=200, WB=4000, MMR=0.01 this gives long 80.808080… and short
        118.811881…. Quantization happens only at the FillEvent price boundary.
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
        """Forced-close penalty = ``fee_rate × |size| × liq_price``.

        Rides ``FillEvent.commission`` rather than introducing a new FillStatus.
        """
        return fee_rate * size * liq_price

    def _liq_inputs(self, position: Position) -> "tuple[Decimal, Decimal, Decimal]":
        """Resolve ``(wb, mmr, fee_rate)`` for a position from cash + Universe.

        ``wb`` is the position-keyed locked isolated margin; ``mmr`` and
        ``fee_rate`` come from the Universe Instrument, the single per-symbol
        source of truth for both.
        """
        wb = self.get_locked_margin_for(str(position.id))
        instrument = self._universe.instrument(position.ticker)
        mmr = instrument.maintenance_margin_rate
        fee_rate = instrument.liquidation_fee_rate
        return wb, mmr, fee_rate
