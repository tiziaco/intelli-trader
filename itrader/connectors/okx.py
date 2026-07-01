"""OkxConnector — the shared authenticated session/transport primitive for OKX
(D-02 / CONN-03 / CONN-04).

This is the genuinely-new code of Phase 2: async is *bottled here*. Per D-02 the
connector owns exactly one concern each of auth, transport, and lifecycle — and NOTHING
domain-shaped:

- **One asyncio loop on a daemon thread.** ``connect()`` spins ``asyncio.new_event_loop()``
  on a ``threading.Thread(daemon=True, name="okx-connector")``; every venue call is bridged
  onto that loop. The engine (backtest/live) thread never touches the ccxt.pro client
  directly (Pitfall 3: ccxt.pro binds its sockets to the creating loop — cross-thread use
  corrupts socket state). The client is therefore built *inside* the loop
  (``_build_client`` scheduled via ``run_coroutine_threadsafe``), not in ``__init__``.

- **One ccxt.pro client + one rate-limit budget.** ``enableRateLimit=True`` leaves ccxt's
  built-in token-bucket throttler ON (RES-01). The three OKX arms (Plans 02-03 order,
  02-04/02-05 data) receive this session injected and drive their domain ops *through* its
  ``call``/``spawn`` seam and shared ``client`` — the connector performs no venue operations
  itself.

- **One ``sandbox: bool`` — no split-brain (CONN-03 / D-02 correction).** A single flag
  drives BOTH ccxt (``set_sandbox_mode(True)`` → REST ``x-simulated-trading`` header AND the
  ccxt WS host swap to ``wspap.okx.com``) AND is exposed via the ``sandbox`` property so the
  native business-candle socket (Plan 02-04) keys its own host off the same bool. The
  ``x-simulated-trading`` header is REST-only and never routes WS — the WS demo host is
  ``wspap.okx.com`` (RESEARCH §Sandbox Routing, Pitfall 2). A sandbox misroute placing a
  live order is the phase's highest-severity threat, so the routing lives in exactly one
  place and is gated by the CONN-03 test.

The scheduling seam (RESEARCH §Async Containment):

- ``call(coro) -> T`` — synchronous RPC: ``run_coroutine_threadsafe(coro, loop).result()``
  for request/response ops (order submit/cancel, market load).
- ``spawn(coro) -> Task`` — schedule a long-running ``watch_*`` / native-candle stream task on
  the loop, track it in ``self._stream_tasks``, and cancel it at ``disconnect()``. It is NEVER
  ``.result()``-awaited (the stream loops forever). Mirrors nautilus's per-client stream-task
  set + cancel-on-disconnect discipline.

**D-02 discipline (grep-guarded by the tests):** this module imports NO domain-event module
and constructs NO fill/order/bar event objects. It knows nothing about
orders-vs-candles-vs-balances — those are arm concerns. Credentials cross into the ccxt client
only via ``SecretStr.get_secret_value()`` at construction and are never logged.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Awaitable, TypeVar

import ccxt.pro as ccxtpro

from itrader.config.okx_settings import OkxSettings
from itrader.logger import get_itrader_logger

_T = TypeVar("_T")

# Bridge/lifecycle timeout (seconds). Order submit/cancel and client build must complete
# well within this; a hang here surfaces loud rather than blocking the engine forever.
_CALL_TIMEOUT = 30.0


class OkxConnector:
    """Authenticated OKX session/transport primitive satisfying ``LiveConnector`` (D-02 / D-04).

    Owns the asyncio loop-on-a-daemon-thread, the single ccxt.pro client, the single
    ``sandbox`` routing knob, the rate-limit budget, and the ``connect``/``disconnect``
    lifecycle — and no venue operations. Emits no domain events.
    """

    def __init__(self, settings: OkxSettings | None = None) -> None:
        self.logger = get_itrader_logger().bind(component="OkxConnector")
        # SecretStr credentials live here; surfaced only at client construction (T-02-02-LEAK).
        # OkxSettings sources every field from the environment, so the no-arg construction
        # is correct at runtime; mypy cannot see the env-source and flags the fields missing.
        self._settings = settings if settings is not None else OkxSettings()  # type: ignore[call-arg]
        # Single sandbox bool — drives ccxt routing AND is exposed for the native socket.
        self._sandbox = self._settings.sandbox
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Any = None
        # nautilus-mirrored: track long-running stream tasks; cancel-all on disconnect.
        self._stream_tasks: set[asyncio.Task[Any]] = set()

    @property
    def client(self) -> Any:
        """The shared ccxt.pro client the arms call through (built inside the loop)."""
        return self._client

    @property
    def sandbox(self) -> bool:
        """Demo-routing flag; the native data socket (Plan 02-04) keys its host off this."""
        return self._sandbox

    def connect(self) -> None:
        """Start the loop-on-a-daemon-thread and build the ccxt.pro client on that loop.

        The client MUST be constructed inside the loop thread (Pitfall 3) — hence
        ``_build_client`` is scheduled via ``run_coroutine_threadsafe`` and awaited here.
        """
        try:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name="okx-connector"
            )
            self._thread.start()
            asyncio.run_coroutine_threadsafe(
                self._build_client(), self._loop
            ).result(timeout=_CALL_TIMEOUT)
            self.logger.info("Connected to OKX", sandbox=self._sandbox)
        except Exception:
            # Never log the credential triple — only the failure + stack.
            self.logger.error("Failed to connect to OKX", exc_info=True)
            self.disconnect()
            raise

    def _run_loop(self) -> None:
        """Daemon-thread body: own the connector's event loop for its lifetime."""
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _build_client(self) -> None:
        """Construct the ccxt.pro client ON the loop, route sandbox, load markets.

        Runs inside the loop thread so the client binds its sockets to this loop. The
        passphrase goes in ccxt's ``password`` field; ``enableRateLimit`` stays ON (RES-01).
        ``load_markets()`` populates the precision tables the order arm's
        ``amount_to_precision``/``price_to_precision`` helpers need.
        """
        self._client = ccxtpro.okx(
            {
                "apiKey": self._settings.api_key.get_secret_value(),
                "secret": self._settings.api_secret.get_secret_value(),
                "password": self._settings.api_passphrase.get_secret_value(),
                "enableRateLimit": True,
            }
        )
        if self._sandbox:
            # Single bool → REST x-simulated-trading header + ccxt WS host swap to wspap.
            self._client.set_sandbox_mode(True)
        await self._client.load_markets()

    def call(self, coro: Awaitable[_T]) -> _T:
        """Synchronous RPC: run ``coro`` on the connector loop and block for its result."""
        assert self._loop is not None, "connect() must run before call()"
        future: Future[_T] = asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]
        return future.result(timeout=_CALL_TIMEOUT)

    def spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        """Schedule a long-running stream task on the loop; track and return its handle.

        NEVER ``.result()``-awaited — ``watch_*`` streams loop forever. The task is tracked in
        ``self._stream_tasks`` and cancelled in ``disconnect()``.
        """
        assert self._loop is not None, "connect() must run before spawn()"
        holder: dict[str, asyncio.Task[Any]] = {}
        ready = threading.Event()

        def _create() -> None:
            assert self._loop is not None
            task: asyncio.Task[Any] = self._loop.create_task(coro)  # type: ignore[arg-type]
            self._stream_tasks.add(task)
            task.add_done_callback(self._stream_tasks.discard)
            holder["task"] = task
            ready.set()

        self._loop.call_soon_threadsafe(_create)
        # WR-04: if the loop never scheduled ``_create`` (congested / not running),
        # ``holder["task"]`` would raise a bare KeyError that masks the real
        # "loop not scheduling" failure. Surface the timeout explicitly instead.
        if not ready.wait(timeout=_CALL_TIMEOUT):
            raise TimeoutError(
                "OKX connector loop did not schedule the spawned task in time")
        return holder["task"]

    def disconnect(self) -> None:
        """Cancel every spawned stream task, close the client, stop the loop, join the thread."""
        if self._loop is None:
            return
        try:
            tasks = list(self._stream_tasks)
            if tasks:

                async def _cancel_tasks() -> None:
                    for task in tasks:
                        task.cancel()
                    # Await so cancellation actually propagates before we tear the loop down.
                    await asyncio.gather(*tasks, return_exceptions=True)

                asyncio.run_coroutine_threadsafe(
                    _cancel_tasks(), self._loop
                ).result(timeout=_CALL_TIMEOUT)

            if self._client is not None:
                asyncio.run_coroutine_threadsafe(
                    self._client.close(), self._loop
                ).result(timeout=_CALL_TIMEOUT)

            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=_CALL_TIMEOUT)
            self.logger.info("Disconnected from OKX")
        except Exception:
            self.logger.error("Error during OKX disconnect", exc_info=True)
        finally:
            if self._loop is not None and not self._loop.is_running():
                self._loop.close()
            self._stream_tasks.clear()
            self._loop = None
            self._thread = None
            self._client = None
