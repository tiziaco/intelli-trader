"""Narrow portfolio read boundary for the order domain (M4-04, D-13..D-17).

The order domain (OrderHandler, OrderManager, EnhancedOrderValidator,
DynamicSizer, RiskManager) reads portfolio state synchronously at admission
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
* **D-15 — live objects inside a module, immutable snapshots across the
  boundary.** ``get_position`` returns a frozen ``PositionView`` (``None``
  when flat), never the live ``Position``.
* **D-16 — structural conformance.** ``PortfolioHandler`` implements this
  Protocol directly (no adapter, no inheritance); ``mypy --strict`` enforces
  the narrow boundary at every retyped constructor.
* **D-17 — the strategy-layer admission path (sizer/risk manager) retypes to
  this Protocol too.**

OQ1 resolution (planner decision): the Protocol carries exactly SIX members —
the four locked by D-13 (``available_cash``, ``get_position``, ``reserve``,
``release``) plus two admission-metadata members: ``exchange_for`` (exchange
routing is admission metadata, not portfolio internals) and
``open_position_count`` (position-limit check). Per-ticker ``get_position``
composes any positions-dict membership read; the validator's ``total_equity``
exposure WARNING is deleted (equity excluded by D-14 — log-only change,
verdict-preserving).
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
