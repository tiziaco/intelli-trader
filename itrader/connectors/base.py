"""LiveConnector — the shared session/transport contract for a live venue (D-02 / D-04).

Reshaped from the Phase-1 two-arm marker (``watch_data`` / ``submit_order`` /
``cancel_order``) into a **session/transport primitive**. Per D-02 the connector owns
auth (key/secret/passphrase), the single ``ccxt.pro`` client instance, the asyncio loop
on a daemon thread, rate-limit/connection budget, ``sandbox`` routing, and the
``connect``/``disconnect`` lifecycle — and NOTHING else. It knows nothing about
orders-vs-candles-vs-balances and imports/constructs no domain events. The three OKX
arms (Plans 02-03 order, 02-04/02-05 data) are the operations owners; they type against
this contract and drive their domain calls *through* it (D-04).

The contract the arms need is the **scheduling seam**, not order/candle ops (RESEARCH
§Async Containment). Two primitives bottle the async/sync bridge at the connector edge:

- ``call(coro) -> T`` — a synchronous RPC: ``run_coroutine_threadsafe(coro, loop)``
  then block on ``.result(timeout)``. Used for request/response ops (``create_order``,
  ``cancel_order``, ``load_markets``).
- ``spawn(coro) -> handle`` — schedule a long-running stream task (``watch_*`` /the
  native business candle socket) on the loop; the handle is cancelled at
  ``disconnect``. It is NEVER ``.result()``-awaited (that would block the caller on an
  infinite stream).

``sandbox`` (D-02 correction — RESEARCH §Sandbox Routing): a single ``sandbox: bool``
routes both paths, but the ccxt ``x-simulated-trading`` header is **REST-only** and
never reaches any WebSocket. OKX WS demo is selected purely by the **demo host**
(``wss://wspap.okx.com:8443/...`` vs ``wss://ws.okx.com:8443/...``). The native data
socket therefore keys its host off ``sandbox`` — NOT off a WS header.

This stays a ``runtime_checkable`` ``Protocol`` (not an ABC) — the swap-a-fake
structural seam (D-04/D-08) that ``OkxConnector`` (Plan 02-02) and the local
``PaperConnector`` (Phase 4) satisfy, and that the connectors conftest's
``FakeLiveConnector`` satisfies for tests. There is no shared implementation to inherit;
the arms only need the structural surface. Method bodies are ``...`` — this is a
contract, not a base class. ``connectors/__init__.py`` gains ``OkxConnector`` in Plan
02-02 when the concretion exists; it is not exported here.
"""

from typing import Any, Awaitable, Protocol, TypeVar, runtime_checkable

_T = TypeVar("_T")


@runtime_checkable
class LiveConnector(Protocol):
    """Structural session/transport contract for a live venue (D-02 / D-04 / CF-3).

    The swap-a-fake seam the three OKX arms type against: a synchronous ``call`` RPC, a
    fire-and-track ``spawn`` for long-running streams, the shared ``client`` and
    ``sandbox`` accessors, and ``connect``/``disconnect`` lifecycle. Carries no
    order/candle/balance operations — those are arm concerns (D-02).

    Connector contract (CF-3) — the invariants every implementation MUST honour and
    every arm may rely on:

    - **Auth ownership (D-02):** the connector — and ONLY the connector — owns the
      venue credentials (key/secret/passphrase). No arm reads or holds them; an arm
      drives authenticated ops purely *through* this session. Credentials are
      env-sourced and never persisted (VENUE-03).
    - **Single client / single loop (D-02):** exactly ONE ``ccxt.pro`` ``client`` and
      ONE asyncio event loop (on a daemon thread) back this session. ``call`` and
      ``spawn`` both marshal onto that one loop; the arms never create their own loop
      or client.
    - **Thread seam:** ``call``/``spawn`` are the ONLY sanctioned async→sync bridge.
      ``call`` blocks the caller on ``run_coroutine_threadsafe(...).result(timeout)``
      (request/response ops); ``spawn`` schedules a long-running stream task and is
      NEVER ``.result()``-awaited (it would block the caller on an unending stream).
      Stream callbacks fire on the connector loop thread — they must not perform
      blocking venue I/O.
    - **Session routing (``sandbox`` / ``ws_hostname``, D-02 correction):** a single
      ``sandbox`` bool routes both REST (the ccxt ``x-simulated-trading`` header,
      REST-only) and WS. OKX WS demo is selected purely by the demo HOST, so the
      native data socket keys its host off ``ws_hostname`` (the region+sandbox-derived
      host), never off a WS header — a socket hard-coded to the live host while
      believing it is demo is the highest-severity threat.
    - **Lifecycle:** no network I/O runs at construction. ``connect`` starts the loop
      and builds the client; ``disconnect`` cancels every spawned stream task and stops
      the loop. ``spawn``/``call`` require a prior ``connect``.
    """

    def call(self, coro: Awaitable[_T]) -> _T:
        """RPC: run ``coro`` on the connector loop and block for its result.

        Bridges async→sync via ``run_coroutine_threadsafe(coro, loop).result(timeout)``
        for request/response ops (order submit/cancel, market load).
        """
        ...

    def spawn(self, coro: Awaitable[Any]) -> Any:
        """Schedule a long-running stream task (``watch_*``/native candle); return a handle.

        The handle is cancelled at ``disconnect``. NEVER ``.result()``-awaited — the
        underlying stream does not terminate on its own.
        """
        ...

    @property
    def client(self) -> Any:
        """The shared ``ccxt.pro`` client instance the arms call through (D-02)."""
        ...

    @property
    def sandbox(self) -> bool:
        """Demo-routing flag; the native data socket keys its host off this (D-02 correction)."""
        ...

    @property
    def ws_hostname(self) -> str:
        """Region+sandbox-derived WS host the native data socket keys its URL off (OKX-REGION).

        Supersedes the old sandbox-only host ternary: the (region, sandbox) pair selects
        one of wspap/ws/wseeapap/wseea so an EEA entity streams from its own demo/live host.
        """
        ...

    def connect(self) -> Any:
        """Start the loop-on-a-daemon-thread and build the shared client (lifecycle)."""
        ...

    def disconnect(self) -> Any:
        """Cancel spawned stream tasks and stop the loop (lifecycle)."""
        ...
