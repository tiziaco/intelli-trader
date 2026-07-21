"""Narrow portfolio read boundary for the order domain (M4-04, D-13..D-17).

The order domain (OrderHandler, OrderManager, EnhancedOrderValidator,
SizingResolver) reads portfolio state synchronously at admission
time. Before M4 it imported the concrete ``PortfolioHandler`` and reached into
portfolio internals (finding #6). This module is the replacement: a single
``runtime_checkable`` ``PortfolioReadModel`` Protocol plus a frozen
``PositionView`` snapshot DTO.

Design decisions locked for this boundary:

* **D-13 — ONE combined Protocol.** Simplicity over read/write interface
  segregation. M4-04's "read-only views" is satisfied by the RETURNED views
  being read-only (frozen ``PositionView``, Decimal values) and by killing the
  concrete ``PortfolioHandler`` dependency — not by splitting the interface.
* **D-14 — ``available_cash`` (buying power) is the single trading-decision
  figure.** Equity/total cash stay on ``Portfolio`` for metrics/reporting and
  deliberately do NOT enter the order-domain surface.
  *Narrow amendment (Plan 07-01, M5-06):* ``total_equity`` joins the Protocol
  as the RiskPercent sizing input (RESEARCH Pitfall 8). The amendment is
  oracle-dark — the golden FractionOfCash policy never reads it — and
  cash-decision reads still go through ``available_cash`` exclusively.
* **D-15 — live objects inside a module, immutable snapshots across the
  boundary.** ``get_position`` returns a frozen ``PositionView`` (``None``
  when flat), never the live ``Position``.
* **D-16 — structural conformance.** ``PortfolioHandler`` implements this
  Protocol directly (no adapter, no inheritance); ``mypy --strict`` enforces
  the narrow boundary at every retyped constructor.
* **D-17 — the strategy-layer admission path (sizer/risk manager) retypes to
  this Protocol too.**

OQ1 resolution (planner decision): the Protocol carries SEVEN core admission
members — the four locked by D-13 (``available_cash``, ``get_position``,
``reserve``, ``release``) plus two admission-metadata members: ``exchange_for``
(exchange routing is admission metadata, not portfolio internals) and
``open_position_count`` (position-limit check), plus the D-15 seventh
``drop_pending`` (drop the local pending overlay on the venue ORDER-ACK — the
buying-power double-count fix, V17-13; routed through the same read/write seam
the order domain already uses for reserve/release). Per-ticker ``get_position``
composes any positions-dict membership read; the validator's ``total_equity``
exposure WARNING is deleted (equity excluded by D-14 — log-only change,
verdict-preserving). (Later narrow amendments add reporting/metrics reads —
``active_portfolio_ids``, ``total_equity``, ``maintenance_margin``,
``margin_ratio`` — each documented at its own accessor.)
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from itrader.core.enums import PositionSide
from itrader.core.ids import OrderId, PortfolioId

__all__ = ["PortfolioReadModel", "PositionView"]


@dataclass(frozen=True, slots=True)
class PositionView:
    """Immutable snapshot of an open position crossing the order boundary.

    Exactly the four fields order-domain consumers read today (D-15) —
    Decimal-typed money, frozen/slots so mutation raises and no attribute can
    be smuggled across the boundary.

    Attributes
    ----------
    ticker : str
        The instrument ticker the position is keyed by.
    side : PositionSide
        LONG or SHORT.
    net_quantity : Decimal
        The net open quantity (full precision, never quantized here).
    avg_price : Decimal
        The average entry price on the position's side.
    """

    ticker: str
    side: PositionSide
    net_quantity: Decimal
    avg_price: Decimal


@runtime_checkable
class PortfolioReadModel(Protocol):
    """Structural seam (D-16) for order-domain reads of portfolio state.

    This is a ``runtime_checkable`` ``Protocol`` rather than an ABC: it
    describes the narrow read/reserve boundary the concrete
    ``PortfolioHandler`` satisfies structurally — no adapter, no inheritance.
    Only ``reserve``/``release`` cross as writes, both delegating to the
    CashManager's typed-exception API; settlement stays queue-mediated.
    """

    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        """Return the portfolio's buying power (balance minus reservations).

        D-14: this is the SINGLE trading-decision cash figure — sizing,
        validation, and risk checks all read it, so they can never disagree.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.

        Returns
        -------
        Decimal
            Available cash at full ledger precision.
        """
        ...

    def get_position(self, portfolio_id: PortfolioId, ticker: str) -> PositionView | None:
        """Return a frozen snapshot of the open position, or ``None`` when flat.

        D-15: live ``Position`` objects never cross the boundary — the
        returned ``PositionView`` is an immutable point-in-time copy.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.
        ticker : str
            The instrument ticker to look up.

        Returns
        -------
        PositionView | None
            The frozen position snapshot, or ``None`` if no open position.
        """
        ...

    def reserve(self, portfolio_id: PortfolioId, order_id: OrderId, amount: Decimal) -> None:
        """Reserve cash for a pending order, keyed by the order id.

        Raises ``InsufficientFundsError`` when ``amount`` exceeds available
        cash; reserves nothing in that case. Reservations are tracked
        per-reference at full precision (OQ4) so release returns exactly what
        was reserved.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio whose cash is reserved.
        order_id : OrderId
            The order the reservation is keyed by.
        amount : Decimal
            The amount to reserve (full precision, no quantization).
        """
        ...

    def release(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Release the cash reservation keyed by an order id.

        Idempotent: releasing an unknown or already-released reference is a
        silent no-op.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio whose reservation is released.
        order_id : OrderId
            The order the reservation was keyed by.
        """
        ...

    def drop_pending(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        """Drop the local pending-reservation overlay entry on the venue ORDER-ACK.

        D-15 (V17-13): once the venue acks a resting order it owns the real
        reservation, so the local overlay must be dropped immediately rather than
        lingering to terminal release — otherwise the same hold is counted twice
        (once locally, once in the venue netting) and buying power is understated.

        Routed through this seam (the same one the order domain uses for
        ``reserve``/``release``) so the cross-domain write stays queue-mediated,
        never a direct account import. NON-terminal: it drops ONLY the admission
        overlay and never settles the fill (the fill settles later on the normal
        path). Idempotent — dropping an unknown or already-dropped order id is a
        silent no-op. On a portfolio whose account has no overlay (paper/simulated),
        the concrete handler getattr-skips the call cleanly.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio whose overlay entry is dropped.
        order_id : OrderId
            The acked order the overlay was keyed by.
        """
        ...

    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        """Return the exchange the portfolio trades on.

        Admission metadata (OQ1): exchange routing is part of order
        admission, not portfolio internals.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.

        Returns
        -------
        str
            The exchange name (e.g. ``"csv"``, ``"BINANCE"``).
        """
        ...

    def account_for(self, portfolio_id: PortfolioId) -> str | None:
        """Return the venue account the portfolio's orders reach.

        Admission metadata (D-27, plan 11-05): an order's target is the PAIR
        ``(venue, account_id)`` — ``exchange_for`` reads the venue half, this
        reads the account half. Once a live system runs several portfolios
        against several venue accounts, routing an order needs both.

        **This is deliberately a read-model member, not a direct import.**
        ``ExecutionHandler`` receives this Protocol injected and must NEVER
        import ``PortfolioHandler`` — the queue-only cross-domain contract
        governs handler-to-handler access, and the read-model seam is the
        sanctioned exception for reads. Do not "simplify" this into a concrete
        handler import.

        Returns ``None`` when the portfolio names no account. The type is
        ``str | None`` because ``Portfolio.account_id`` is optional: the default
        exists ONLY so the byte-exact backtest composition-root call stays
        untouched, and the composition-time invariant (plan 11-08) is what
        refuses to start a LIVE system whose portfolios do not each name a
        distinct account.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.

        Returns
        -------
        str | None
            The venue account id, or ``None`` when no account is named.
        """
        ...

    def open_position_count(self, portfolio_id: PortfolioId) -> int:
        """Return the number of currently open positions.

        Admission metadata (OQ1): backs the validator's position-limit check.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.

        Returns
        -------
        int
            Count of open positions.
        """
        ...

    def active_portfolio_ids(self) -> list[PortfolioId]:
        """Return the ids of all currently active portfolios.

        Admission metadata (WR-02, LIFE-01): the run-end time-in-force sweep
        enumerates active portfolios to expire their resting orders. Exposing
        only the ids (not the live ``Portfolio`` objects) keeps the order
        domain on the narrow read boundary — the concrete ``PortfolioHandler``
        no longer leaks across via a ``type: ignore``, and any conforming
        read-model (test double, future live read-model) is contract-bound to
        implement it (D-16: structural conformance is mypy-enforced).

        Returns
        -------
        list[PortfolioId]
            The ids of the active portfolios.
        """
        ...

    def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
        """Return total equity: full cash balance plus position market values.

        Plan 07-01 (M5-06): the RiskPercent sizing input — D-14's "equity
        excluded" rule is narrowly amended for it. The full ledger balance
        (available cash + reservations) is used, NOT buying power; equity is
        a sizing/metrics figure, not a cash-decision figure. Oracle-dark:
        the golden FractionOfCash policy never reads it.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.

        Returns
        -------
        Decimal
            Total equity at full ledger precision.
        """
        ...

    def maintenance_margin(self, portfolio_id: PortfolioId) -> Decimal:
        """Return the portfolio's maintenance margin, computed on demand.

        Plan 02-05 (MARGIN-03, D-13/D-13a): ``maintenance_margin =
        Σ (Instrument.maintenance_margin_rate × |size| × current_price)`` over
        the portfolio's OPEN positions, resolving each ticker's ``Instrument``
        via the injected ``Universe``. It is a COMPUTE-ON-DEMAND read-model
        accessor — NOT a stored mutable ``Position`` field (D-13: a second
        source of truth would drift and fight the N+4 ``Account`` venue mirror,
        D-13a). Decimal end-to-end (RESEARCH Pitfall 8 — never narrow through a
        float). With no open positions the maintenance margin is ``Decimal("0")``.

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.

        Returns
        -------
        Decimal
            Maintenance margin at full precision.
        """
        ...

    def margin_ratio(self, portfolio_id: PortfolioId) -> Decimal:
        """Return the portfolio's margin ratio, ``total_equity / maintenance_margin``.

        Plan 02-05 (MARGIN-03, D-12/D-13): the mark-to-market figure a UI/live
        layer (deferred N+4) reads to compute margin-call warnings. The numerator
        is ``total_equity()`` (D-12 mark-to-market), the denominator is
        ``maintenance_margin()``. It reads HONESTLY even when breached — no clamp
        (D-16): an equity drop below maintenance returns a ratio < 1 (the P4
        liquidation input). When ``maintenance_margin`` is ``Decimal("0")`` (no
        open positions, no margin required) it returns the deterministic sentinel
        ``Decimal("0")`` (no division by zero).

        Parameters
        ----------
        portfolio_id : PortfolioId
            The portfolio to read.

        Returns
        -------
        Decimal
            Margin ratio at full precision (``Decimal("0")`` when no margin is
            required).
        """
        ...
