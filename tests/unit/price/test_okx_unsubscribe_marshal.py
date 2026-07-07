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


def test_unsubscribe_absent_symbol_is_true_noop(provider: OkxDataProvider) -> None:
    """WR-01 (07-09): a fully-absent symbol marshals NOTHING (no spawn), doesn't raise.

    No task, and no OWN ``_streams_down`` / ``_reconnect_attempts`` entry → the guard
    returns before any connector interaction. This both avoids wasteful no-op
    marshaling and dodges ``spawn``'s "connect() must run before spawn()" assertion when
    ``unsubscribe`` is reached before the connector loop is running.
    """
    # Nothing subscribed for DOGE; a spurious down/attempt entry for ANOTHER symbol.
    provider._streams_down.add("OTHER/USDC")
    provider._reconnect_attempts["OTHER/USDC"] = 2

    provider.unsubscribe("DOGE/USDC")  # must not raise

    conn = _connector(provider)
    # WR-01: true safe no-op — no connector interaction at all.
    assert conn.spawn_calls == 0
    assert "DOGE/USDC" not in provider._streams
    # The unrelated symbol's state is untouched.
    assert provider._streams_down == {"OTHER/USDC"}
    assert provider._reconnect_attempts == {"OTHER/USDC": 2}


def test_unsubscribe_stale_supervisor_state_without_task_still_marshals(
    provider: OkxDataProvider,
) -> None:
    """The WR-01 guard is precise: a symbol with OWN supervisor state but no live task
    must STILL marshal cleanup — otherwise a stale down-flag / attempt count would leak
    and wedge is_streaming_healthy() / the D-20 retry ceiling. Only a FULLY-absent symbol
    is skipped.
    """
    sym = "DOGE/USDC"
    provider._streams_down.add(sym)  # own down-flag, but no _streams task
    provider._reconnect_attempts[sym] = 4

    provider.unsubscribe(sym)

    conn = _connector(provider)
    # Guard did NOT short-circuit: cleanup was marshaled and cleared this symbol's state.
    assert conn.spawn_calls == 1
    assert sym not in provider._streams_down
    assert sym not in provider._reconnect_attempts
