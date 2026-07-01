"""OkxConnector unit tests — sandbox routing, async loop/bridge, no-domain-import (Plan 02-02).

Offline, mocked-ccxt tests for the three load-bearing properties of the session/transport
primitive:

- ``-k sandbox`` (CONN-03 / T-02-02-MISROUTE): a single ``sandbox: bool`` drives both the
  ``set_sandbox_mode`` call AND the exposed ``sandbox`` flag. The wspap host swap is asserted on a
  **real** ccxt.pro.okx client (constructed offline — no socket opens; only ``load_markets`` is
  mocked) so the test proves the genuine ccxt routing, not a fake's echo. A live misroute placing a
  live order is the phase's highest-severity threat, so this is the gating CONN-03 assertion.
- ``-k loop`` (CONN-04 / T-02-02-LOOP): ``call`` is a synchronous RPC through the daemon-thread loop;
  ``spawn`` schedules a tracked stream task that ``disconnect`` cancels (and the client is closed).
  The no-domain-import guard also lives under ``loop`` (CONN-04: "no domain import in connector").

Pitfall 4: every test disconnects in teardown (idempotent) so no ResourceWarning/RuntimeWarning
escapes into the strict ``filterwarnings=["error"]`` suite.
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import ccxt.pro as ccxtpro
import pytest

from itrader.config.okx_settings import OkxSettings
from itrader.connectors.okx import OkxConnector

# Capture the genuine ccxt.pro.okx class BEFORE any patch so the offline factory can build a
# real client without recursing into the patched name.
_REAL_OKX = ccxtpro.okx

_PATCH_TARGET = "itrader.connectors.okx.ccxtpro.okx"


def _settings(monkeypatch: pytest.MonkeyPatch, *, sandbox: bool) -> OkxSettings:
    """Build OkxSettings from a controlled OKX_API_* env (demo values, never real secrets)."""
    monkeypatch.setenv("OKX_API_KEY", "demo-key")
    monkeypatch.setenv("OKX_API_SECRET", "demo-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "demo-pass")
    monkeypatch.setenv("OKX_SANDBOX", "true" if sandbox else "false")
    return OkxSettings()


def _real_offline_okx(config: dict) -> object:
    """A REAL ccxt.pro.okx client built offline: construction opens no socket, only
    ``load_markets`` (network) is stubbed and ``set_sandbox_mode`` is wrapped to spy the call
    while still performing the genuine urls['api'] -> wspap swap."""
    client = _REAL_OKX(config)
    client.load_markets = AsyncMock(return_value={})
    client.set_sandbox_mode = MagicMock(wraps=client.set_sandbox_mode)
    return client


# --------------------------------------------------------------------------- sandbox (CONN-03)


def test_sandbox_true_routes_to_wspap_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """sandbox=True -> set_sandbox_mode(True) called AND the ccxt WS/base URL swaps to wspap."""
    connector = OkxConnector(_settings(monkeypatch, sandbox=True))
    with patch(_PATCH_TARGET, _real_offline_okx):
        connector.connect()
        try:
            client = connector.client
            # The exposed flag the native data socket (Plan 02-04) keys its host off.
            assert connector.sandbox is True
            client.set_sandbox_mode.assert_called_once_with(True)
            # The genuine ccxt host swap: demo WS host is wspap.okx.com, live host is gone.
            api_urls = str(client.urls["api"])
            assert "wspap" in api_urls
            assert "ws.okx.com" not in api_urls
        finally:
            connector.disconnect()


def test_sandbox_false_uses_live_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """sandbox=False -> set_sandbox_mode NOT called; the live ws.okx.com host, no wspap."""
    connector = OkxConnector(_settings(monkeypatch, sandbox=False))
    with patch(_PATCH_TARGET, _real_offline_okx):
        connector.connect()
        try:
            client = connector.client
            assert connector.sandbox is False
            client.set_sandbox_mode.assert_not_called()
            api_urls = str(client.urls["api"])
            assert "wspap" not in api_urls
            assert "ws.okx.com" in api_urls
        finally:
            connector.disconnect()


# ----------------------------------------------------------------------------- loop (CONN-04)


def test_loop_call_returns_result_via_daemon_thread(
    monkeypatch: pytest.MonkeyPatch, fake_ccxt_client: MagicMock
) -> None:
    """call(coro) bridges the coroutine onto the daemon-thread loop and returns its result."""
    connector = OkxConnector(_settings(monkeypatch, sandbox=True))
    with patch(_PATCH_TARGET, return_value=fake_ccxt_client):
        connector.connect()
        try:

            async def _echo(value: int) -> int:
                return value

            assert connector.call(_echo(7)) == 7
        finally:
            connector.disconnect()


def test_loop_spawn_tracked_and_disconnect_cancels(
    monkeypatch: pytest.MonkeyPatch, fake_ccxt_client: MagicMock
) -> None:
    """spawn() schedules a tracked stream task; disconnect() cancels it and closes the client."""
    connector = OkxConnector(_settings(monkeypatch, sandbox=True))
    with patch(_PATCH_TARGET, return_value=fake_ccxt_client):
        connector.connect()
        try:
            client = connector.client  # capture before disconnect nulls it out

            async def _forever() -> None:
                while True:
                    await asyncio.sleep(0.01)

            task = connector.spawn(_forever())
            # Tracked and still running (never .result()-awaited).
            assert task in connector._stream_tasks
            assert not task.done()

            connector.disconnect()

            assert task.cancelled()
            client.close.assert_awaited_once()
        finally:
            connector.disconnect()  # idempotent: loop is None after the first disconnect


def test_loop_connector_imports_no_domain_events() -> None:
    """D-02 grep-guard: the connector source references no domain-event module or class."""
    import itrader.connectors.okx as okx_module

    src = inspect.getsource(okx_module)
    assert "events_handler.events" not in src
    for name in ("FillEvent", "OrderEvent", "BarEvent"):
        assert name not in src, f"connector references domain event {name}"
