"""Offline cache unit test for ``VenueAccount`` (Phase 5 / 05-03, RECON-01 / D-14/D-15).

Drives the credential-free ``fake_venue_connector`` double (05-02) to prove the
cached-venue body:

* ``snapshot()`` populates the balance/positions cache from the canned REST snapshot;
* a pushed ``watch_balance`` update mutates the cache on the connector loop thread;
* an engine-thread read BEFORE any snapshot surfaces a typed ``StateError`` (never 0);
* ``reserve`` beyond cached available raises ``InsufficientFundsError`` (overlay gate);
* ``reserve`` then ``release`` restores available (local pending-reservation overlay);
* every cached value is an EXACT ``Decimal`` (the ``to_money(str(x))`` edge, never
  ``Decimal(float)``).

Fully offline — no ``OKX_API_*`` credentials, no network. The ``fake_venue_connector``
fixture owns ``connect()`` / ``disconnect()`` so every spawned push stream is cancelled
and the client closed in teardown (Pitfall 4 — clean under ``filterwarnings=["error"]``).
"""

import time
import uuid
from decimal import Decimal

import pytest

from itrader.core.exceptions import InsufficientFundsError, StateError
from itrader.core.ids import OrderId
from itrader.portfolio_handler.account.venue import VenueAccount
from tests.support.fake_venue_connector import FakeLiveConnector


def _wait_for(predicate, timeout: float = 2.0) -> None:
    """Poll ``predicate`` until true or the deadline lapses (connector-loop drain)."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_snapshot_populates_cache_from_rest(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """``snapshot()`` fills balance/available/positions from the canned REST snapshot."""
    account = VenueAccount(fake_venue_connector)
    account.snapshot()

    # fetch_balance canned: total/free USDT == 78999.79; fetch_positions: long 0.5 BTC.
    assert account.balance == Decimal("78999.79")
    assert account.available_balance == Decimal("78999.79")
    assert account.positions == {"BTC/USDT": Decimal("0.5")}


def test_push_stream_mutates_cache(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """A ``watch_balance`` push writes the cache on the connector loop thread (D-15)."""
    account = VenueAccount(fake_venue_connector)
    account.start_streaming()

    # The canned watch_balance stream yields 100000 -> 91599.916 -> 78999.79 (total USDT);
    # watch_positions yields long 0.2 -> long 0.5. Drain to the final values.
    _wait_for(lambda: account._venue_balance == Decimal("78999.79"))
    _wait_for(lambda: account._venue_positions == {"BTC/USDT": Decimal("0.5")})

    assert account.balance == Decimal("78999.79")
    assert account.available_balance == Decimal("78999.79")
    assert account.positions == {"BTC/USDT": Decimal("0.5")}


def test_read_before_snapshot_raises_state_error(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """An unsnapshotted read surfaces a typed ``StateError`` — never a silent 0 (T-05-07)."""
    account = VenueAccount(fake_venue_connector)

    with pytest.raises(StateError):
        _ = account.balance
    with pytest.raises(StateError):
        _ = account.available_balance


def test_reserve_beyond_available_raises(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """``reserve`` beyond cached available raises ``InsufficientFundsError`` (overlay gate)."""
    account = VenueAccount(fake_venue_connector)
    account.snapshot()  # available == 78999.79

    order_id = OrderId(uuid.uuid4())
    with pytest.raises(InsufficientFundsError):
        account.reserve(order_id, Decimal("80000"))

    # Nothing was reserved — available is untouched.
    assert account.available_balance == Decimal("78999.79")


def test_reserve_then_release_restores_available(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """The local pending overlay lowers available on reserve, restores it on release."""
    account = VenueAccount(fake_venue_connector)
    account.snapshot()

    order_id = OrderId(uuid.uuid4())
    account.reserve(order_id, Decimal("1000"))
    assert account.available_balance == Decimal("77999.79")

    account.release(order_id)
    assert account.available_balance == Decimal("78999.79")

    # Release is idempotent — releasing an unknown reference is a silent no-op.
    account.release(order_id)
    assert account.available_balance == Decimal("78999.79")


def test_reserve_before_snapshot_raises_state_error(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """Reserving before any snapshot surfaces ``StateError`` (no cached available yet)."""
    account = VenueAccount(fake_venue_connector)
    order_id = OrderId(uuid.uuid4())
    with pytest.raises(StateError):
        account.reserve(order_id, Decimal("1"))


def test_cached_values_are_exact_decimals(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """Cached values are EXACT Decimals — proving the ``to_money(str(x))`` edge (no float)."""
    account = VenueAccount(fake_venue_connector)
    account.snapshot()

    balance = account.balance
    qty = account.positions["BTC/USDT"]
    assert isinstance(balance, Decimal)
    assert isinstance(qty, Decimal)
    # A ``Decimal(float)`` path would carry a binary-float artifact
    # (e.g. Decimal(78999.79) != Decimal("78999.79")); exact equality proves the string edge.
    assert balance == Decimal("78999.79")
    assert qty == Decimal("0.5")
