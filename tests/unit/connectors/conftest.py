"""Shared async mocked-ccxt fixtures for the connectors test tree (Phase 2 / 02-01, D-08).

Wave-0 infrastructure: a reusable, teardown-safe test double for the reshaped
``LiveConnector`` session/transport Protocol (``call`` / ``spawn`` / ``client`` /
``sandbox`` / ``connect`` / ``disconnect``) plus an ``AsyncMock``-based fake
``ccxt.pro`` client. The three OKX arms (Plans 02-03/02-04/02-05) type against these.

Pitfall 4 (RESEARCH §Validation): under ``filterwarnings=["error"]`` an unclosed
transport session raises ``ResourceWarning`` and a never-awaited/never-cancelled task
raises ``RuntimeWarning`` — both escalate to a suite FAILURE. Every fixture here MUST
cancel spawned stream tasks and close the client in teardown. ``FakeLiveConnector``
mirrors the real design (loop-on-a-daemon-thread) so ``call`` is a genuine synchronous
RPC (``run_coroutine_threadsafe(...).result(timeout)``) and ``spawn`` schedules a
long-running stream task that is NEVER ``.result()``-awaited — exactly the containment
seam the arms build against.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar
from unittest.mock import AsyncMock, MagicMock

import pytest

_T = TypeVar("_T")

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> Any:
    """Load a documented-shape JSON fixture by filename (synthetic — no real secrets)."""
    with (_FIXTURES_DIR / name).open() as fh:
        return json.load(fh)


class FakeLiveConnector:
    """Teardown-safe ``LiveConnector`` test double driving a fake ccxt.pro client.

    Satisfies the reshaped session/transport Protocol structurally: ``call`` (sync RPC
    onto a background loop), ``spawn`` (long-running stream task, returns the
    ``asyncio.Task`` handle, never awaited via ``.result()``), ``client`` / ``sandbox``
    properties, and ``connect`` / ``disconnect`` lifecycle. ``disconnect`` cancels every
    spawned task, closes the client, stops the loop, and joins the daemon thread — so no
    ResourceWarning/RuntimeWarning can escape into the strict suite (Pitfall 4).
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
        # IN-02: mirror the product guard (OkxConnector.spawn) — if the loop never
        # scheduled ``_create`` (congested / not running), falling through to
        # ``holder["task"]`` raises a bare KeyError that masks the real
        # "loop not scheduling" cause. Surface the timeout explicitly instead.
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


@pytest.fixture
def okx_business_candles() -> Any:
    """The documented-shape OKX business-channel candle push sequence (confirm 0..0..1)."""
    return _load_fixture("okx_business_candles.json")


@pytest.fixture
def okx_order_lifecycle() -> Any:
    """The documented-shape OKX order -> ack -> fill payload sequence."""
    return _load_fixture("okx_order_lifecycle.json")


@pytest.fixture
def fake_ccxt_client() -> MagicMock:
    """An ``AsyncMock``-backed fake ccxt.pro client exposing the arm surface.

    Streaming reads (``watch_*``) and RPCs (``create_order`` / ``cancel_order`` /
    ``load_markets`` / ``close``) are ``AsyncMock`` coroutines; the ``*_to_precision``
    helpers are synchronous in ccxt, so they are plain ``MagicMock`` string-returning
    stubs. Callers override ``.return_value`` / ``.side_effect`` per test.
    """
    client = MagicMock(name="fake_ccxt_pro_client")
    client.watch_ohlcv = AsyncMock(name="watch_ohlcv")
    client.watch_my_trades = AsyncMock(name="watch_my_trades")
    client.watch_orders = AsyncMock(name="watch_orders")
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


@pytest.fixture
def fake_connector(fake_ccxt_client: MagicMock) -> Any:
    """A connected ``FakeLiveConnector`` driving ``fake_ccxt_client``.

    Yields a live session (loop already running on a daemon thread) and guarantees
    ``disconnect()`` in teardown — cancelling any spawned stream task and closing the
    client so no ResourceWarning/RuntimeWarning escapes into the strict suite.
    """
    connector = FakeLiveConnector(fake_ccxt_client, sandbox=True)
    connector.connect()
    try:
        yield connector
    finally:
        connector.disconnect()
