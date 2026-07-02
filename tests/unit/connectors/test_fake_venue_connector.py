"""Smoke coverage for the shared reconciliation double (Phase 5 / 05-02, D-09).

Proves the ``tests.support`` ``FakeLiveConnector`` + canned recon fixtures are
credential-free, teardown-safe under ``filterwarnings=["error"]``, and drive the full
account/fill/order surface the Phase-5 reconciliation cluster verifies against. Fully
offline — no ``OKX_API_*`` credentials, no network, no session left open.
"""

import asyncio

import pytest

from tests.support.fake_venue_connector import (
    FakeLiveConnector,
    build_fake_recon_client,
    load_recon_payloads,
    make_fake_venue_connector,
)

_STREAM_METHODS = ("watch_my_trades", "watch_orders", "watch_balance", "watch_positions")
_REST_METHODS = ("fetch_balance", "fetch_positions", "fetch_open_orders", "fetch_my_trades")


def test_recon_fixture_is_credential_free() -> None:
    """The committed recon payloads carry NO secret substrings (T-05-03 mitigation)."""
    import json
    from pathlib import Path

    raw = (Path(__file__).parents[2] / "support" / "fixtures" / "okx_recon_payloads.json").read_text()
    lowered = raw.lower()
    for forbidden in ("okx_api", "secret", "passphrase"):
        assert forbidden not in lowered, f"forbidden substring {forbidden!r} in recon fixture"
    # And it is valid JSON with the documented surface.
    payloads = json.loads(raw)
    for method in (*_STREAM_METHODS, *_REST_METHODS):
        assert method in payloads, f"recon fixture missing {method!r}"


def test_fake_client_wires_full_recon_surface() -> None:
    """The fake ccxt client exposes every canned push stream + REST snapshot."""
    client = build_fake_recon_client()
    for method in (*_STREAM_METHODS, *_REST_METHODS):
        assert hasattr(client, method), f"fake client missing {method!r}"
    # REST snapshots return the canned fixture values.
    payloads = load_recon_payloads()
    assert client.fetch_positions.return_value == payloads["fetch_positions"]
    assert client.fetch_open_orders.return_value == payloads["fetch_open_orders"]
    assert client.fetch_my_trades.return_value == payloads["fetch_my_trades"]


def test_construct_then_disconnect_is_teardown_safe() -> None:
    """Constructing + connecting + disconnecting emits no Resource/RuntimeWarning.

    Under ``filterwarnings=["error"]`` any escaped warning fails this test — so a clean
    pass IS the teardown-safety assertion (Pitfall 4).
    """
    connector = make_fake_venue_connector(sandbox=True)
    connector.connect()
    # Never spawn/call — the bare construct+disconnect path must still be clean.
    connector.disconnect()
    # Idempotent second disconnect is a no-op.
    connector.disconnect()


def test_call_drives_rest_snapshot() -> None:
    """``call`` runs a REST coroutine on the background loop and returns its result."""
    connector = make_fake_venue_connector(sandbox=True)
    connector.connect()
    try:
        balance = connector.call(connector.client.fetch_balance())
        assert balance["total"]["USDT"] == 78999.79
        positions = connector.call(connector.client.fetch_positions())
        assert positions[0]["symbol"] == "BTC/USDT"
    finally:
        connector.disconnect()


def test_spawn_consumes_canned_stream_then_cancels_clean() -> None:
    """A ``spawn``ed watch loop consumes canned batches then parks until cancelled.

    Exercises the exact seam the Phase-5 ``VenueAccount`` push consumer builds against:
    ``spawn`` a ``while True: await watch_balance()`` loop, observe the canned updates,
    then ``disconnect`` cancels the parked task with no RuntimeWarning.
    """
    connector = make_fake_venue_connector(sandbox=True)
    connector.connect()
    seen: list[float] = []

    async def _consume() -> None:
        while True:
            update = await connector.client.watch_balance()
            seen.append(update["total"]["USDT"])

    try:
        connector.spawn(_consume())
        # Give the daemon loop a beat to drain the three canned balance snapshots.
        import time

        deadline = time.monotonic() + 2.0
        while len(seen) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert seen == [100000.0, 91599.916, 78999.79]
    finally:
        connector.disconnect()


def test_root_fixture_reusable(fake_venue_connector: FakeLiveConnector) -> None:
    """The root ``fake_venue_connector`` fixture yields a connected, usable double.

    Proves the cross-tree seam: any test tree requests ``fake_venue_connector`` and gets
    a connected connector with teardown owned by the fixture (key_link pattern).
    """
    assert fake_venue_connector.sandbox is True
    trades = fake_venue_connector.call(fake_venue_connector.client.fetch_my_trades())
    assert [t["id"] for t in trades] == ["PLACEHOLDER-TRD-0001", "PLACEHOLDER-TRD-0002"]


def test_canned_stream_parks_after_exhaustion() -> None:
    """Directly assert the ``_CannedStream`` parks (blocks) once batches are exhausted."""
    from tests.support.fake_venue_connector import _CannedStream

    async def _drive() -> None:
        stream = _CannedStream([["a"], ["b"]])
        assert await stream() == ["a"]
        assert await stream() == ["b"]
        # Third await must block indefinitely -> a short wait_for times out.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(stream(), timeout=0.1)

    asyncio.run(_drive())
