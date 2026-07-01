"""
VenueAccount — interface-only stub leaf of the ``Account`` ABC (D-11).

``VenueAccount`` is the venue-cached sibling of the ``Simulated*`` leaves: where
``SimulatedCashAccount`` / ``SimulatedMarginAccount`` *compute* balance/margin
truth, ``VenueAccount`` will *cache* the venue's truth (balances / positions /
margin streamed or polled from the connector). Its stable contract comes from the
``Account`` ABC (D-01) — **not** from the connector — so it does not need a rich
``LiveConnector`` to be shaped this phase (D-11 avoids the premature-interface trap
of freezing connector signatures before the integration exists).

This phase ships the **stub leaf only**: each abstract method raises
``NotImplementedError``. The connector-coupled body — caching venue
balance/margin/position streams, per-symbol drift reconciliation under the 1:1
account/portfolio mapping (LX-04) — is deferred to Phase 5 (RECON-01). The
connector → ``VenueAccount`` data flow (push-stream vs pull-getter, sync vs async,
OKX payloads) is explicitly Phase 2 (CONN-*) / Phase 5 (RECON-01).
"""

from decimal import Decimal

from itrader.core.ids import OrderId

from .base import Account


class VenueAccount(Account):
    """
    Venue-cached ``Account`` leaf — interface-only stub this phase (D-11).

    Implements the ``Account`` contract as ``NotImplementedError`` stubs; the
    cached-venue body is deferred to Phase 5 (RECON-01).
    """

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
