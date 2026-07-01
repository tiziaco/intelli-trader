"""VenueAccount injection-seam wiring tests (plan 02-05, CONN-04 / D-04).

Phase 2 gives ``VenueAccount`` its constructor seam only: it accepts and stores the
injected ``LiveConnector`` session so the ``LiveTradingSystem`` composition root can
wire it alongside the OKX order/data arms. The cached-venue body (balance / margin /
position caching + reconciliation) stays deferred to Phase 5 (RECON-01) — every
abstract ``Account`` method must still raise ``NotImplementedError``. These tests pin
BOTH halves of that boundary: the seam is live, the body is not.

No real connector is constructed — a minimal fake session (satisfying the structural
``LiveConnector`` surface the seam needs) is injected, so nothing here touches
``ccxt.pro`` or credentials.
"""

import uuid
from decimal import Decimal

import pytest

from itrader.core.ids import OrderId
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
    account = VenueAccount(session)
    assert account._connector is session


def test_venue_account_balance_still_deferred() -> None:
    """``balance`` stays a Phase-5 ``NotImplementedError`` stub (body untouched)."""
    account = VenueAccount(_FakeSession())
    with pytest.raises(NotImplementedError, match="Phase 5"):
        _ = account.balance


def test_venue_account_available_still_deferred() -> None:
    """``available`` stays a Phase-5 ``NotImplementedError`` stub."""
    account = VenueAccount(_FakeSession())
    with pytest.raises(NotImplementedError, match="Phase 5"):
        _ = account.available


def test_venue_account_reserve_still_deferred() -> None:
    """``reserve`` stays a Phase-5 ``NotImplementedError`` stub."""
    account = VenueAccount(_FakeSession())
    with pytest.raises(NotImplementedError, match="Phase 5"):
        account.reserve(OrderId(uuid.uuid4()), Decimal("100"))


def test_venue_account_release_still_deferred() -> None:
    """``release`` stays a Phase-5 ``NotImplementedError`` stub."""
    account = VenueAccount(_FakeSession())
    with pytest.raises(NotImplementedError, match="Phase 5"):
        account.release(OrderId(uuid.uuid4()))
