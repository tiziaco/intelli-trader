"""Store-derived OKX-boot test helpers.

The live account set is STORE-DERIVED and its bring-up CONNECTS: an OKX account becomes
routable only once its session is open, its identity asserted and its streams armed. That
whole sequence belongs to ``start()``, so a test that wants an online OKX account offline
has to (1) build the account's real session, (2) replace its I/O with offline stubs, and
(3) run the production bring-up over it. These helpers are that sequence, in one place.

Stubbing the SESSION rather than the adapter is deliberate: the adapter, the identity
guard, the halt wiring and the routing write are all production objects doing their
production work — only the socket is missing.

The ``provisioned_okx`` fixture in ``tests/integration/conftest.py`` supplies the durable
row on a Postgres spine.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

#: Every helper here is OKX-specific by name, so the venue is a literal of this module
#: rather than something read back off the system under test.
_OKX = "okx"


class OfflineVenueClient:
    """A ccxt-shaped client answering every REST read a boot performs, with no socket.

    The venue answers EMPTY: no balances, no positions, no resting orders. That is what
    lets the real startup reconcile + baseline guard run offline and still reach RUNNING —
    an empty venue agrees with an empty engine, so nothing is adopted and nothing halts.

    The methods are plain (non-async) and return finished values because the ``call`` stub
    below is a pass-through: a real coroutine handed to a pass-through would never be
    awaited, and ``filterwarnings=["error"]`` turns that into a failure.
    """

    #: Loaded-markets map the arm's ``validate_symbol`` consults (fail-closed when absent).
    markets: dict = {}

    def fetch_balance(self) -> dict:
        return {"total": {}}

    def fetch_positions(self) -> list:
        return []

    def fetch_open_orders(self) -> list:
        return []

    def fetch_my_trades(self, symbol, since=None, limit=None) -> list:
        return []

    def private_get_account_config(self) -> dict:
        """No account rows — the identity guard reads this as "no uid available".

        Answering with a fabricated uid would have the guard RECORD it on first connect,
        so a later test on the same durable row would see a mismatch it never caused.
        """
        return {"data": []}


def stub_session_io(connector: Any, *, client: Any = None) -> Any:
    """Replace one connector's network surface with offline stubs; return it.

    ``spawn`` CLOSES the coroutine it is handed rather than dropping it: an un-awaited
    coroutine raises ``RuntimeWarning``, which ``filterwarnings=["error"]`` turns into a
    test failure far from its cause.
    """
    def _spawn(coro: Any, *args: Any, **kwargs: Any) -> Any:
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        return MagicMock(name="stream_handle")

    connector.connect = MagicMock(name="connector.connect")
    connector.disconnect = MagicMock(name="connector.disconnect")
    # ``client`` is a read-only property over ``_client``; the loop is never started, so
    # ``call`` (which asserts a live loop) is replaced by a pass-through.
    connector._client = client if client is not None else OfflineVenueClient()
    connector.call = lambda result: result
    connector.spawn = _spawn
    return connector


def stub_okx_session(system: Any, *, client: Any = None) -> Any:
    """Pre-build the provisioned OKX account's session and stub its I/O; return it.

    The pool memoizes ONE session per account, so the connector this builds is the very
    object the production bring-up will use — which is what lets a test stub the socket
    BEFORE ``start()`` runs the real bring-up over it.
    """
    manager = system._venue_manager
    rows = manager.read_enabled_for(_OKX)
    assert len(rows) == 1, f"expected exactly one provisioned OKX row, got {len(rows)}"
    spec = manager.spec_for(rows[0])
    return stub_session_io(
        manager.pool.session(_OKX, spec.account_id, spec), client=client)


def stub_every_okx_session(system: Any, *, client: Any = None) -> dict[str, Any]:
    """Pre-build and stub EVERY provisioned OKX account's session; return them by id.

    The multi-account form of ``stub_okx_session``: a boot brings up every enabled row, so
    every row's socket has to be gone before the boot runs.
    """
    manager = system._venue_manager
    sessions: dict[str, Any] = {}
    for row in manager.read_enabled_for(_OKX):
        spec = manager.spec_for(row)
        sessions[spec.account_id] = stub_session_io(
            manager.pool.session(_OKX, spec.account_id, spec), client=client)
    return sessions


def bring_okx_online(system: Any, *, client: Any = None) -> Any:
    """Bring the store-provisioned OKX account online over a stubbed session.

    Runs the PRODUCTION ``bring_online``: the real adapter recipe, the real identity guard,
    the real halt wiring and the real routing write. Only the session's I/O is stubbed.
    """
    manager = system._venue_manager
    stub_okx_session(system, client=client)
    return manager.bring_online(manager.read_enabled_for(_OKX)[0])


def the_okx_record(system: Any) -> Any:
    """The single online OKX account record, or an assertion naming what was found."""
    records = system._venue_manager.online_records()
    assert len(records) == 1, (
        f"expected exactly one online account, got {len(records)}")
    return records[0]


def the_feed_provider(system: Any) -> Any:
    """The ONE data adapter the builder wired to the live feed."""
    return system._data_provider


def stub_data_session(system: Any, *, client: Any = None) -> Any:
    """Stub the DATA adapter's own session I/O; return it (``None`` when there is none).

    The data adapter holds a session of its own — normally the venue's public one — and
    ``start()`` opens it. A test that drives the real ``start()`` offline has to replace
    that socket too, or the run reaches out to the venue for candles.
    """
    connector = system._data_connector
    if connector is None:
        return None
    return stub_session_io(connector, client=client)
