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
    def available(self) -> Decimal:
        """
        Cash available for new commitments — balance net of outstanding
        reservations (and, for margin leaves, locked margin).

        Returns
        -------
        Decimal
            The available amount (full precision, Decimal end-to-end).
        """
        raise NotImplementedError("Subclasses must implement available")

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
