"""
VenueAccount — interface-only stub leaf of the ``Account`` ABC (D-11).

``VenueAccount`` is the venue-cached sibling of the ``Simulated*`` leaves: where
``SimulatedCashAccount`` / ``SimulatedMarginAccount`` *compute* balance/margin
truth, ``VenueAccount`` will *cache* the venue's truth (balances / positions /
margin streamed or polled from the connector). Its stable contract comes from the
``Account`` ABC (D-01) — **not** from the connector — so it does not need a rich
``LiveConnector`` to be shaped this phase (D-11 avoids the premature-interface trap
of freezing connector signatures before the integration exists).

This phase ships the **wiring seam + stub body**: plan 02-05 (CONN-04) adds the
constructor that accepts the injected ``LiveConnector`` session (D-04) so the
``LiveTradingSystem`` composition root can wire it alongside the OKX order/data
arms, but each abstract method still raises ``NotImplementedError``. The
connector-coupled body — caching venue balance/margin/position streams, per-symbol
drift reconciliation under the 1:1 account/portfolio mapping (LX-04) — is deferred
to Phase 5 (RECON-01). The constructor stores the session only; the connector →
``VenueAccount`` data flow (push-stream vs pull-getter, sync vs async, OKX
payloads) is explicitly Phase 5 (RECON-01).

Import discipline (inertness gate, CONN-04): this leaf is re-exported from the
``account`` barrel, which the backtest hot path imports (``SimulatedCashAccount``).
``LiveConnector`` is therefore imported ONLY under ``TYPE_CHECKING`` with a string
annotation — a runtime ``from itrader.connectors import ...`` would pull the
connectors barrel (and ``ccxt.pro``) onto the backtest import path and fail the
hot-path inertness gate.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from itrader.core.ids import OrderId

from .base import Account

if TYPE_CHECKING:
    from itrader.connectors import LiveConnector


class VenueAccount(Account):
    """
    Venue-cached ``Account`` leaf — injection seam landed, body still Phase 5 (D-11).

    Plan 02-05 (CONN-04) adds the constructor accepting the injected
    ``LiveConnector`` session (D-04); the ``Account`` contract methods remain
    ``NotImplementedError`` stubs — the cached-venue body is deferred to Phase 5
    (RECON-01).
    """

    def __init__(self, connector: "LiveConnector") -> None:
        """Store the injected venue session (wiring seam only, D-04 / CONN-04).

        The composition root builds the concrete ``OkxConnector`` once and injects
        the ``LiveConnector`` session here; this leaf holds it for the Phase-5
        cached-venue body. No balance/margin/position caching runs this phase.

        Parameters
        ----------
        connector : LiveConnector
            The injected session/transport Protocol (never the concretion, D-04).
        """
        self._connector = connector

    @property
    def balance(self) -> Decimal:
        """Cached venue balance — deferred to Phase 5 (RECON-01)."""
        raise NotImplementedError(
            "VenueAccount.balance is deferred to Phase 5 (RECON-01): the "
            "connector-coupled cached-venue body is out of scope this phase."
        )

    @property
    def available(self) -> Decimal:
        """Cached venue available — deferred to Phase 5 (RECON-01)."""
        raise NotImplementedError(
            "VenueAccount.available is deferred to Phase 5 (RECON-01): the "
            "connector-coupled cached-venue body is out of scope this phase."
        )

    def reserve(self, order_id: OrderId, amount: Decimal) -> None:
        """Venue-side reservation — deferred to Phase 5 (RECON-01)."""
        raise NotImplementedError(
            "VenueAccount.reserve() is deferred to Phase 5 (RECON-01): the "
            "connector-coupled cached-venue body is out of scope this phase."
        )

    def release(self, order_id: OrderId) -> None:
        """Venue-side release — deferred to Phase 5 (RECON-01)."""
        raise NotImplementedError(
            "VenueAccount.release() is deferred to Phase 5 (RECON-01): the "
            "connector-coupled cached-venue body is out of scope this phase."
        )
