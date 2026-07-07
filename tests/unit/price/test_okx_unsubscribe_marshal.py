"""07-09 remediation: OKX unsubscribe marshals cleanup onto the connector loop (WR-03).

``unsubscribe`` runs on the ENGINE thread but touches state owned by the
connector-loop thread (``task.cancel()`` + the ``_streams_down`` /
``_reconnect_attempts`` supervisor dicts written by the reconnect supervisor).
WR-03 keeps the engine-thread-owned ``_streams`` pop inline but MARSHALS both the
cancel and the supervisor-dict cleanup onto the connector loop via
``connector.spawn`` — the SAME ownership model ``subscribe`` uses — so the connector
loop is the single writer (no new lock).

Offline / socket-free: a fake connector drives the awaitless cleanup coroutine to
completion synchronously and records that ``spawn`` was invoked. Folder-derived
``unit`` marker; respects filterwarnings=["error"]. 4-SPACE.
"""

from __future__ import annotations

from typing import Any

import pytest

from itrader.price_handler.providers.okx_provider import OkxDataProvider

pytestmark = pytest.mark.unit


class _RecordingTask:
    """A cancellable stand-in recording cancel() calls."""

    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> bool:
        self.cancel_calls += 1
        return True


class _DrivingConnector:
    """A fake connector that RUNS the marshaled cleanup coroutine synchronously.

    The WR-03 cleanup coroutine has no awaits, so a single ``send(None)`` runs its
    whole body (then raises ``StopIteration``). Records every ``spawn`` call so a
    test can assert the cleanup went THROUGH ``connector.spawn``.
    """

    def __init__(self) -> None:
        self.spawn_calls = 0

    def spawn(self, coro: Any) -> None:
        self.spawn_calls += 1
        try:
            coro.send(None)
        except StopIteration:
            pass
        return None


@pytest.fixture
def provider() -> OkxDataProvider:
    return OkxDataProvider(_DrivingConnector(), symbol="BTC/USDT", timeframe="1d")


def _connector(provider: OkxDataProvider) -> _DrivingConnector:
    conn = provider._connector
    assert isinstance(conn, _DrivingConnector)
    return conn


def test_unsubscribe_marshals_cancel_and_cleanup_through_spawn(
    provider: OkxDataProvider,
) -> None:
    """After unsubscribe + the marshaled cleanup: cancel ran once, supervisor dicts cleared."""
    sym = "ETH/USDC"
    task = _RecordingTask()
    provider._streams[sym] = task  # type: ignore[assignment]
    provider._streams_down.add(sym)
    provider._reconnect_attempts[sym] = 3

    provider.unsubscribe(sym)

    conn = _connector(provider)
    # The cleanup went THROUGH connector.spawn (marshaled onto the connector loop).
    assert conn.spawn_calls == 1
    # The engine-thread-owned _streams pop happened inline.
    assert sym not in provider._streams
    # The marshaled cleanup ran: cancel once, supervisor dicts cleared.
    assert task.cancel_calls == 1
    assert sym not in provider._streams_down
    assert sym not in provider._reconnect_attempts


def test_unsubscribe_absent_symbol_is_safe_noop(provider: OkxDataProvider) -> None:
    """An absent symbol pops None → no cancel, no exception; discard/pop are no-ops."""
    # Nothing subscribed; a spurious down/attempt entry for ANOTHER symbol is untouched.
    provider._streams_down.add("OTHER/USDC")
    provider._reconnect_attempts["OTHER/USDC"] = 2

    provider.unsubscribe("DOGE/USDC")  # must not raise

    conn = _connector(provider)
    # Cleanup is still marshaled (preserving the original always-run discard/pop
    # semantics), but it cancels nothing and leaves the unrelated symbol's state intact.
    assert conn.spawn_calls == 1
    assert "DOGE/USDC" not in provider._streams
    assert provider._streams_down == {"OTHER/USDC"}
    assert provider._reconnect_attempts == {"OTHER/USDC": 2}
