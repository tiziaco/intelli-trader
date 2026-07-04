"""Opt-in live OKX connectivity checks, gated behind the ``live`` marker.

This module gives the suite two proofs that the OKX venue is reachable and that the
demo ``OkxConnector`` authenticates read-only:

  * Test A — a CREDENTIAL-FREE public reachability check (``load_markets`` over the
    unauthenticated public REST endpoint). Proves the OKX host is up.
  * Test B — a CREDENTIAL-GATED authenticated check (read-only ``fetch_balance``
    through the demo ``OkxConnector``). Proves the demo auth triple works.

Both tests carry ``@pytest.mark.live`` — the PURPOSE axis flag for "makes a real
network round-trip". They are orthogonal to the folder-derived ``integration`` TYPE
marker (auto-applied by the root ``tests/conftest.py`` — do NOT hand-apply it here).
Because they are ``live``, the default ``make test`` / CI run (``-m "not live"``) never
touches the network. ONLY Test B additionally carries ``skipif`` on the credential
gate — ``live`` is the network property, ``skipif`` is the creds property; the two are
deliberately NOT conflated.

ALL connector imports are LAZY (inside the test bodies), so a credential-free/offline
COLLECTION never imports ``ccxt`` / ``ccxt.pro`` or connector code — collection stays
fast and offline even where the venue is unreachable.
"""

import os

import pytest

_OKX_ENV_VARS = ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE")
_HAS_OKX_CREDS = all(os.environ.get(var) for var in _OKX_ENV_VARS)


@pytest.mark.live
def test_okx_public_endpoint_reachable() -> None:
    """Credential-free public reachability: OKX serves a non-empty market list.

    Unauthenticated public call (no creds, no sandbox) proving the OKX host is
    reachable. Lazy ``ccxt`` import so a ``not live`` collection never touches it. A
    sync ccxt REST client holds no persistent socket needing an explicit close, but we
    still close it in a ``finally`` so no ResourceWarning can surface under
    ``filterwarnings=["error"]``.
    """
    import ccxt

    client = ccxt.okx()  # public — no credentials, no sandbox
    try:
        markets = client.load_markets()
        assert markets
        assert len(markets) > 0
    finally:
        # Sync REST client has no persistent socket, but close defensively so no
        # ResourceWarning can ever escalate under filterwarnings=["error"].
        close = getattr(client, "close", None)
        if callable(close):
            close()


@pytest.mark.live
@pytest.mark.skipif(
    not _HAS_OKX_CREDS,
    reason=(
        "OKX demo credentials absent — authenticated connectivity check skipped; "
        "set OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE (demo) to enable."
    ),
)
def test_okx_demo_authenticated_connectivity() -> None:
    """Credential-gated read-only auth check against the OKX DEMO venue.

    Reuses ``VenueAccount.snapshot()``'s exact balance-fetch shape
    (``connector.call(connector.client.fetch_balance())``) — READ-ONLY, no order, no
    venue-mutating action. Lazy connector imports so a credential-free collection never
    touches ``ccxt.pro`` / connector code.
    """
    from itrader.config.okx_settings import OkxSettings
    from itrader.connectors.okx import OkxConnector

    connector = OkxConnector(OkxSettings())  # type: ignore[call-arg]

    # T-05-04 real-money-misroute guard: sandbox is set in __init__ from settings and is
    # readable BEFORE connect(). Assert demo routing BEFORE any network call — a live
    # misroute must be impossible.
    assert connector.sandbox is True

    try:
        connector.connect()
        # Exact read-only shape VenueAccount.snapshot() uses. An AuthenticationError
        # would raise here and fail the test — that raise IS the auth assertion.
        bal = connector.call(connector.client.fetch_balance())
        assert bal is not None
        assert isinstance(bal, dict)
        assert bal
    finally:
        # Tear down so no authenticated ccxt.pro socket leaks under
        # filterwarnings=["error"] (T-conn-SOCK).
        connector.disconnect()
