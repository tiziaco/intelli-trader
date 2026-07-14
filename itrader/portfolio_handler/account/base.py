"""
Account ABC — the balance / margin truth contract (D-01 / D-02 / D-05, ACCT-01).

The ``Account`` family models the **cash-vs-margin axis with inheritance** (D-01):
margin is a strict *superset* of cash — it needs balance / available / reserve /
release *and* adds margin locks + liquidation math — so inheritance expresses it
honestly with zero duplication (D-02). The orthogonal **simulated-vs-venue axis is
sibling leaves** of this same contract (``Simulated*`` compute, ``Venue*`` cache),
reusing the established ABC + sibling-leaf pattern (``fee_model`` / ``slippage_model``
/ ``exchanges``).

This module pins the abstract contract only — there is no money math here. The
byte-exact risk (the SMA_MACD oracle, ``134 / 46189.87730727451``) is realized when
the ``CashManager`` code-motion lands in plan 01-02 (``SimulatedCashAccount``); this
ABC keeps the contract honest so no order-domain ripple is introduced. Per D-05 the
Account-level ``reserve`` / ``release`` **drop ``portfolio_id``** — an ``Account``
*is* the single account under LX-04 (1 account : 1 portfolio), so it has no notion
of portfolio identity. The ``portfolio_id``-keyed ``PortfolioReadModel.reserve``
seam stays on ``PortfolioHandler`` unchanged (D-06 / D-07).

Money (D-12): balances, available, and reserved amounts are Decimal end-to-end —
no float casts inside account math, and quantization happens only at money
boundaries (ledger writes), never mid-stream. The fill / lock / carry paths
deliberately skip the 2dp quantize (a quantize there shifts the equity curve and
fails the byte-exact oracle).
"""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from itrader.core.ids import OrderId


class Account(ABC):
    """
    Abstract balance/margin-truth contract for a single portfolio's account
    (D-01 / D-02 / D-05, ACCT-01).

    Concrete leaves:

    * ``SimulatedCashAccount`` — spot cash-flow truth (CashManager code-motion,
      plan 01-02).
    * ``SimulatedMarginAccount(SimulatedCashAccount)`` — the margin superset
      (locks + liquidation math, plan 01-02).
    * ``VenueAccount`` — venue-cached truth (interface-only this phase, D-11;
      body deferred to Phase 5 / RECON-01).

    Money (D-12): every amount is Decimal end-to-end — no float casts, no
    mid-stream quantize (rounding happens only at money boundaries).
    """

    @property
    def is_venue_truth(self) -> bool:
        """Account KIND discriminator: True only for venue-cached (venue-truth) leaves.

        The startup ``ReconciliationCoordinator`` keys the venue reconcile on this
        discriminator (SAFE-05 / A4) rather than on ``exchange=='okx'`` — the compute
        (``Simulated*``) leaves inherit ``False`` here and NEVER reach the venue reconcile
        (matches D-23 RESTORE-only), while ``VenueAccount`` overrides it ``True``.
        """
        return False

    @property
    @abstractmethod
    def balance(self) -> Decimal:
        """
        Total settled cash balance of the account.

        Returns
        -------
        Decimal
            The account balance (full precision, Decimal end-to-end).
        """
        raise NotImplementedError("Subclasses must implement balance")

    @property
    @abstractmethod
    def available_balance(self) -> Decimal:
        """
        Cash available for new commitments — balance net of outstanding
        reservations (and, for margin leaves, locked margin).

        The single buying-power authority (D-10) read by the order-admission
        gate (``PortfolioHandler.on_signal``) and serialization
        (``Portfolio.to_dict``). This is the D-01 settlement-surface member —
        the old ABC member ``available`` was renamed here (its verbatim
        alias on ``SimulatedCashAccount`` is deleted; the ``VenueAccount``
        overlay-netted read is renamed to match).

        Returns
        -------
        Decimal
            The available amount (full precision, Decimal end-to-end).
        """
        raise NotImplementedError("Subclasses must implement available_balance")

    @property
    @abstractmethod
    def reserved_balance(self) -> Decimal:
        """
        Total cash currently reserved against outstanding admission
        reservations (D-01 settlement surface, read by ``to_dict``).

        Returns
        -------
        Decimal
            The reserved amount (full precision, Decimal end-to-end).
        """
        raise NotImplementedError("Subclasses must implement reserved_balance")

    @abstractmethod
    def assert_funds_invariant(self, required: Decimal) -> None:
        """
        Assert that a settlement debit of ``required`` does not exceed settled
        funds — the D-10 engine-bug guard on the fill debit side (D-01
        settlement surface).

        Raised on the fill path BEFORE any mutation (``Portfolio.transact_shares``
        asserts here first) so a failed invariant can never leave a partial
        mutation. The D-02 admission reservation gate should have prevented this
        state upstream; if this fires it is an engine bug and the caller stops
        loudly.

        Parameters
        ----------
        required : Decimal
            The actual net cash cost of the settlement debit (full precision).

        Raises
        ------
        InsufficientFundsError
            When ``required`` exceeds the settled balance.
        """
        raise NotImplementedError("Subclasses must implement assert_funds_invariant")

    @abstractmethod
    def apply_fill_cash_flow(self, amount: Decimal, fee: Decimal, description: str,
                             reference_id: str, timestamp: datetime) -> None:
        """
        Apply a fill settlement's signed, full-precision cash delta — the ONE
        trade-path cash primitive (D-01 / D-05 / D-06 settlement surface).

        Deliberately skips the 2dp quantize path (Pitfall 1: a mid-stream
        quantize would shift the balance → equity curve → break the byte-exact
        oracle on 8dp instrument costs). ``amount`` is the SIGNED net cash delta
        (negative for a BUY outflow, positive for a SELL inflow); ``fee`` the
        commission portion already included in it; ``timestamp`` the
        caller-supplied event-derived time (never wall clock).

        Parameters
        ----------
        amount : Decimal
            Signed full-precision net cash delta. No quantization.
        fee : Decimal
            Commission portion already included in ``amount``.
        description : str
            Audit description.
        reference_id : str
            Reference id (e.g. transaction id).
        timestamp : datetime
            Event-derived time (transaction/fill time).
        """
        raise NotImplementedError("Subclasses must implement apply_fill_cash_flow")

    def restore_cash(self, balance: Decimal) -> None:
        """
        Restore the settled cash balance from a durable snapshot on restart
        (D-07 / V17-05 — the restart-restore hook of the settlement surface).

        Called only on the live rehydrate path
        (``CachedSqlPortfolioStateStorage.rehydrate`` → this account) so a fresh
        account leaf REMEMBERS its pre-restart balance rather than its
        construction-time initial cash. Bypasses the deposit/withdraw policy gates
        (a restart restores already-validated persisted truth, not a new deposit);
        Decimal end-to-end (never ``Decimal(float)``).

        Concrete (not abstract): the simulated leaves override it with the direct
        ``_balance`` setter. The ``VenueAccount`` cash-restore is Phase 5
        (RECON-01) — until then the interface-only leaf inherits this loud
        NotImplementedError, matching its deferred-body posture.

        Parameters
        ----------
        balance : Decimal
            The persisted cash balance to restore (full precision).
        """
        raise NotImplementedError("Subclasses must implement restore_cash")

    @abstractmethod
    def reserve(self, order_id: OrderId, amount: Decimal) -> None:
        """
        Reserve ``amount`` for a pending order, keyed by ``order_id`` (D-05 —
        no ``portfolio_id``; the Account *is* the single account, LX-04 1:1).

        Reservations are tracked per-reference at full precision so a later
        ``release`` returns exactly what was reserved. Implementations raise
        ``InsufficientFundsError`` when ``amount`` exceeds available and
        reserve nothing in that case.

        Parameters
        ----------
        order_id : OrderId
            The order the reservation is keyed by.
        amount : Decimal
            The amount to reserve (full precision, no quantization).
        """
        raise NotImplementedError("Subclasses must implement reserve()")

    @abstractmethod
    def release(self, order_id: OrderId) -> None:
        """
        Release the reservation keyed by ``order_id`` (D-05 — no
        ``portfolio_id``).

        Idempotent: releasing an unknown or already-released reference is a
        silent no-op.

        Parameters
        ----------
        order_id : OrderId
            The order the reservation was keyed by.
        """
        raise NotImplementedError("Subclasses must implement release()")
