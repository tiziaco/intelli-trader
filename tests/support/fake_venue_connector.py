"""Shared, teardown-safe ``FakeLiveConnector`` with canned recon streams (05-02, D-09).

This promotes the Phase-2 ``FakeLiveConnector`` (``tests/unit/connectors/conftest.py``) out
of the connectors subtree into a tree-agnostic ``tests.support`` package so the WHOLE
reconciliation cluster (portfolio / order / execution / integration) verifies against ONE
credential-free double. It reuses the Phase-2 teardown discipline VERBATIM (loop on a daemon
thread; ``call`` = synchronous RPC via ``run_coroutine_threadsafe``; ``spawn`` = a
never-``.result()``-awaited stream task; ``disconnect`` cancels tasks + closes the client) and
extends the fake ccxt.pro client with the Phase-5 account/fill/order surface.

Pitfall 4 (RESEARCH §Validation): under ``filterwarnings=["error"]`` an unclosed transport
session raises ``ResourceWarning`` and a never-awaited/never-cancelled task raises
``RuntimeWarning`` — both escalate to a suite FAILURE. Every stream task MUST be cancellable
and the client MUST close in teardown.

Pitfall 2 (RESEARCH): ccxt returns FLOATS everywhere. The canned payloads carry floats on
purpose — downstream reconciliation code MUST route every price/amount/fee/balance through
``to_money(str(...))``. This double intentionally does NOT pre-Decimalize.

The recon streaming methods (``watch_my_trades`` / ``watch_orders`` / ``watch_balance`` /
``watch_positions``) yield their canned batches one per ``await`` and then BLOCK until the
spawning task is cancelled — mirroring a live ccxt.pro socket that has no further updates. The
REST snapshots (``fetch_balance`` / ``fetch_positions`` / ``fetch_open_orders`` /
``fetch_my_trades``) return their canned value on every call.

This module lives in a package (``tests/support/__init__.py`` present) but OUTSIDE the
``tests/unit/*`` package-less trees, so it does not trigger the same-named-package collision.
"""

import asyncio
import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar
from unittest.mock import AsyncMock, MagicMock

_T = TypeVar("_T")

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_RECON_FIXTURE = "okx_recon_payloads.json"

# The four canned PUSH streams (ccxt.pro ``watch_*``) and the four canned REST snapshots
# (``fetch_*``) this double drives. Kept as module constants so a test can introspect the
# wired surface without reaching into the client.
_STREAM_METHODS = ("watch_my_trades", "watch_orders", "watch_balance", "watch_positions")
_REST_METHODS = ("fetch_balance", "fetch_positions", "fetch_open_orders", "fetch_my_trades")


def load_recon_payloads(name: str = _RECON_FIXTURE) -> dict[str, Any]:
    """Load the synthetic recon payloads fixture (credential-free; ccxt-unified shapes)."""
    with (_FIXTURES_DIR / name).open() as fh:
        return json.load(fh)


class _CannedStream:
    """An async callable that returns canned batches, then blocks until cancelled.

    Mirrors a ccxt.pro ``watch_*`` coroutine consumed in a ``while True: await watch()``
    loop: each ``await`` returns the next canned batch; once the canned sequence is
    exhausted it awaits forever so the ``spawn``ed stream task simply parks until the
    connector's ``disconnect()`` cancels it (Pitfall 4 — clean teardown, no RuntimeWarning).
    """

    def __init__(self, batches: list[Any]) -> None:
        # deepcopy so a consumer mutating a returned batch cannot corrupt the fixture.
        self._batches = [deepcopy(b) for b in batches]
        self._index = 0

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._index < len(self._batches):
            batch = self._batches[self._index]
            self._index += 1
            return batch
        # No further updates: park until the task is cancelled (never-set Event).
        await asyncio.Event().wait()


def build_fake_recon_client(payloads: dict[str, Any] | None = None) -> MagicMock:
    """Build a fake ccxt.pro client wired with the canned recon streams + REST snapshots.

    Streaming reads (``watch_my_trades`` / ``watch_orders`` / ``watch_balance`` /
    ``watch_positions``) are ``_CannedStream`` async callables driving the fixture batches.
    REST reads (``fetch_balance`` / ``fetch_positions`` / ``fetch_open_orders`` /
    ``fetch_my_trades``) plus the order RPCs and ``load_markets`` / ``close`` are ``AsyncMock``
    coroutines; the synchronous ``*_to_precision`` helpers are string-returning ``MagicMock``
    stubs (matching ccxt's sync signature). Callers may override ``.return_value`` /
    ``.side_effect`` per test.
    """
    data = payloads if payloads is not None else load_recon_payloads()

    client = MagicMock(name="fake_ccxt_pro_recon_client")

    # PUSH streams — canned batches then park-until-cancelled.
    for method in _STREAM_METHODS:
        setattr(client, method, _CannedStream(data.get(method, [])))

    # REST snapshots — canned value on every call.
    for method in _REST_METHODS:
        setattr(client, method, AsyncMock(name=method, return_value=deepcopy(data.get(method))))

    # Order arm + lifecycle RPCs reused from the Phase-2 shape (no-op canned defaults).
    client.create_order = AsyncMock(name="create_order")
    client.cancel_order = AsyncMock(name="cancel_order")
    client.load_markets = AsyncMock(name="load_markets")
    client.close = AsyncMock(name="close")
    client.amount_to_precision = MagicMock(
        name="amount_to_precision", side_effect=lambda symbol, amount: str(amount)
    )
    client.price_to_precision = MagicMock(
        name="price_to_precision", side_effect=lambda symbol, price: str(price)
    )
    return client


class FakeLiveConnector:
    """Teardown-safe ``LiveConnector`` test double driving a fake ccxt.pro client.

    Satisfies the reshaped session/transport Protocol structurally: ``call`` (sync RPC onto a
    background loop), ``spawn`` (long-running stream task, returns the ``asyncio.Task`` handle,
    never awaited via ``.result()``), ``client`` / ``sandbox`` properties, and ``connect`` /
    ``disconnect`` lifecycle. ``disconnect`` cancels every spawned task, closes the client,
    stops the loop, and joins the daemon thread — so no ResourceWarning/RuntimeWarning escapes
    into the strict suite (Pitfall 4). Byte-for-byte the Phase-2 design.
    """

    def __init__(self, client: Any, sandbox: bool = True) -> None:
        self._client = client
        self._sandbox = sandbox
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._tasks: list[asyncio.Task[Any]] = []

    @property
    def client(self) -> Any:
        """The shared ccxt.pro client the arms call through."""
        return self._client

    @property
    def sandbox(self) -> bool:
        """Demo/sandbox flag — the native data socket keys its host off this."""
        return self._sandbox

    def connect(self) -> None:
        """Start the event loop on a daemon thread (the async/sync bridge seam)."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def call(self, coro: Awaitable[_T], timeout: float = 5.0) -> _T:
        """RPC: run ``coro`` on the background loop and block for its result."""
        assert self._loop is not None, "connect() must run before call()"
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]
        return fut.result(timeout)

    def spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        """Schedule a long-running stream task; return its handle (never ``.result()``-awaited)."""
        assert self._loop is not None, "connect() must run before spawn()"
        holder: dict[str, asyncio.Task[Any]] = {}
        ready = threading.Event()

        def _create() -> None:
            assert self._loop is not None
            task = self._loop.create_task(coro)  # type: ignore[arg-type]
            self._tasks.append(task)
            holder["task"] = task
            ready.set()

        self._loop.call_soon_threadsafe(_create)
        # IN-02: mirror the product guard (OkxConnector.spawn) — if the loop never scheduled
        # ``_create`` (congested / not running), falling through to ``holder["task"]`` raises a
        # bare KeyError that masks the real "loop not scheduling" cause. Surface the timeout.
        if not ready.wait(timeout=5.0):
            raise TimeoutError(
                "fake connector loop did not schedule the spawned task in time")
        return holder["task"]

    def disconnect(self) -> None:
        """Cancel spawned tasks, close the client, stop the loop, join the thread."""
        if self._loop is None:
            return

        def _cancel_all() -> None:
            for task in self._tasks:
                task.cancel()

        self._loop.call_soon_threadsafe(_cancel_all)

        # Close the fake client on the loop so any async teardown runs there.
        close = getattr(self._client, "close", None)
        if close is not None:
            try:
                asyncio.run_coroutine_threadsafe(close(), self._loop).result(timeout=5.0)
            except Exception:
                pass

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._loop.close()
        self._loop = None
        self._thread = None
        self._tasks.clear()


def make_fake_venue_connector(
    sandbox: bool = True,
    payloads: dict[str, Any] | None = None,
    client_factory: Callable[[dict[str, Any] | None], MagicMock] = build_fake_recon_client,
) -> FakeLiveConnector:
    """One-call factory: canned recon fixtures -> fake ccxt client -> ``FakeLiveConnector``.

    Returns an UNCONNECTED connector — the caller (or the ``fake_venue_connector`` root
    fixture) is responsible for ``connect()`` / ``disconnect()`` so teardown stays in the
    fixture that owns the lifecycle (Pitfall 4).
    """
    client = client_factory(payloads)
    return FakeLiveConnector(client, sandbox=sandbox)
