"""VenueAccount injection-seam wiring tests (plan 02-05, CONN-04 / D-04).

Phase 2 gives ``VenueAccount`` its constructor seam: it accepts and stores the
injected ``LiveConnector`` session so the ``LiveTradingSystem`` composition root can
wire it alongside the OKX order/data arms. The cached-venue body (balance / margin /
position caching + reconciliation) landed in Phase 5 (RECON-01, plan 05-03); the
"still deferred" ``NotImplementedError`` guards that Phase 2 pinned here were removed
once that boundary was intentionally crossed. The cached-body contract is now owned
by ``test_venue_account_cache.py``. This module pins the surviving half: the seam is
live.

No real connector is constructed — a minimal fake session (satisfying the structural
``LiveConnector`` surface the seam needs) is injected, so nothing here touches
``ccxt.pro`` or credentials.
"""

from itrader.portfolio_handler.account import VenueAccount


class _FakeSession:
    """Minimal structural stand-in for the injected ``LiveConnector`` session.

    The Phase-2 seam only stores the session; it calls nothing on it, so an empty
    object is sufficient to prove the injection wiring without importing the OKX
    concretion (inertness discipline).
    """


def test_venue_account_stores_injected_session() -> None:
    """The constructor accepts and stores the injected session (the wiring seam)."""
    session = _FakeSession()
    account = VenueAccount(session, account_id="acct-test")
    assert account._connector is session
