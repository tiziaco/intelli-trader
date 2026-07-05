"""A2 (D-06 / V17-02) RED gate — the venue ack must be STAMPED + PERSISTED on the mirror.

CONF-A spine (D-19), Wave-1 slice 2. This is an EXPECTED-FAILING regression test: it
pins the V17-02 unrecoverable-ack bug and turns GREEN only once the D-06 ORDER-ACK path
lands in Phase 05.2. It MUST be RED against current code — that is the success condition
of a CONF-A spine plan, NOT a broken build.

The bug (V17-02)
----------------
When ``OkxExchange._submit_order`` submits an order, the venue returns the exchange
order id in ``response["id"]``. Today that id is written ONLY into the in-memory
``VenueCorrelationIndex`` (okx.py:320) — it is NEVER stamped onto the STORED order's
``venue_order_id`` field, so it is never persisted. After a process restart the
in-memory index is empty and the mirror carries no venue id, so the reconciler cannot
match its working-set orders to venue resting orders / fills by id. The ack is
effectively unrecoverable.

The fix (D-06, Phase 05.2)
--------------------------
The recommended shape emits a small ORDER-ACK event carrying ``order_id -> venue_order_id``
which ``OrderHandler`` consumes to stamp the mirror and ``update_order()`` persists. This
test drives the OBSERVABLE end-state (the stored order's ``venue_order_id``), not a storage
shape, so a posture choice in 05.2 (ORDER-ACK event vs a direct injected callback) turns it
GREEN without a rewrite: the exchange shares this test's ``global_queue`` and ``storage``,
and any queued ack is drained into the wired ``OrderHandler`` via the framework's
``on_<event>`` naming convention.

Crucially we do NOT hand-stamp ``venue_order_id`` in the fixture — that hand-stamping is
exactly the anti-pattern V17-02 hides behind (the restart tests faked the ack). The stored
order is seeded with ``venue_order_id=None`` and the submit path is the ONLY thing that may
stamp it.

Import-clean, fully offline: the ccxt.pro client is an ``AsyncMock`` wrapped in a minimal
synchronous fake ``LiveConnector`` whose private loop is closed in teardown (Pitfall 4,
``filterwarnings=["error"]``). No network, no credentials.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Awaitable, TypeVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.ids import OrderId, PortfolioId
from itrader.events_handler.events import OrderEvent
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader.order_handler.order import Order
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import InMemoryOrderStorage

_T = TypeVar("_T")

_VENUE_ID = "OKX-1"


class _FakeConnector:
    """Minimal synchronous fake of the ``LiveConnector`` session Protocol.

    ``call`` runs the passed coroutine to completion on a private loop (an RPC), so the
    ``create_order`` AsyncMock is actually awaited and its ``{"id": ...}`` return surfaces.
    ``spawn`` closes the coroutine (streams are not driven here), avoiding a
    never-awaited RuntimeWarning under the strict filter.
    """

    def __init__(self, client: Any, sandbox: bool = True) -> None:
        self._client = client
        self._sandbox = sandbox
        self._loop = asyncio.new_event_loop()

    @property
    def client(self) -> Any:
        return self._client

    @property
    def sandbox(self) -> bool:
        return self._sandbox

    def call(self, coro: Awaitable[_T]) -> _T:
        return self._loop.run_until_complete(coro)  # type: ignore[arg-type]

    def spawn(self, coro: Awaitable[Any]) -> Any:
        coro.close()  # type: ignore[attr-defined]
        return None

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def close(self) -> None:
        self._loop.close()


@pytest.fixture
def fake_client() -> MagicMock:
    """AsyncMock-backed ccxt.pro client whose create_order returns the venue id."""
    client = MagicMock(name="fake_ccxt_pro_client")
    client.create_order = AsyncMock(name="create_order", return_value={"id": _VENUE_ID})
    client.cancel_order = AsyncMock(name="cancel_order", return_value={"id": _VENUE_ID})
    client.amount_to_precision = MagicMock(
        name="amount_to_precision", side_effect=lambda symbol, amount: str(amount)
    )
    client.price_to_precision = MagicMock(
        name="price_to_precision", side_effect=lambda symbol, price: str(price)
    )
    return client


@pytest.fixture
def fake_connector(fake_client: MagicMock) -> Any:
    connector = _FakeConnector(fake_client, sandbox=True)
    try:
        yield connector
    finally:
        connector.close()


@pytest.fixture
def global_queue() -> "Queue[Any]":
    return Queue()


@pytest.fixture
def storage() -> InMemoryOrderStorage:
    return InMemoryOrderStorage()


@pytest.fixture
def order_handler(global_queue: "Queue[Any]", storage: InMemoryOrderStorage) -> OrderHandler:
    """An OrderHandler wired to the SHARED queue + storage.

    Sharing the queue means a future D-06 ORDER-ACK event emitted by the exchange is
    consumable here; sharing the storage means its ``update_order`` persists onto the
    same order this test reads back. The portfolio read-model is unused on the ack path,
    so a MagicMock stands in.
    """
    return OrderHandler(global_queue, MagicMock(name="portfolio_read_model"),
                        order_storage=storage)


def _drain_to_order_handler(queue: "Queue[Any]", handler: OrderHandler) -> None:
    """Route every queued event into ``handler`` via the ``on_<event>`` naming convention.

    Today ``_submit_order`` enqueues NOTHING (the venue id lands only in the in-memory
    index), so this is a no-op and the stored order stays unstamped -> RED. Once the D-06
    ORDER-ACK event lands (Phase 05.2), the exchange enqueues it and the matching
    ``handler.on_<type>`` (e.g. ``on_order_ack``) stamps + persists the mirror -> GREEN,
    with no rewrite of this test.
    """
    while not queue.empty():
        event = queue.get_nowait()
        handler_name = "on_" + event.type.name.lower()
        callback = getattr(handler, handler_name, None)
        if callback is not None:
            callback(event)


def test_submitted_order_stamps_and_persists_venue_order_id(
    global_queue: "Queue[Any]",
    storage: InMemoryOrderStorage,
    order_handler: OrderHandler,
    fake_connector: Any,
) -> None:
    """After ``_submit_order``, the STORED order's ``venue_order_id`` must equal the ack id.

    RED today: only the in-memory index is written, so the persisted mirror keeps
    ``venue_order_id=None``. GREEN after D-06 (Phase 05.2) stamps + persists the ack.
    """
    portfolio_id = PortfolioId(uuid.uuid4())
    order_id = OrderId(uuid.uuid4())

    # Seed the mirror with NO venue id — the submit path is the only thing that may
    # stamp it (never hand-stamped in the fixture: that is the V17-02 anti-pattern).
    order = Order(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        type=OrderType.LIMIT,
        status=OrderStatus.PENDING,
        ticker="BTC-USDT",
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("0.5"),
        exchange="okx",
        strategy_id=1,
        portfolio_id=portfolio_id,
        id=order_id,
    )
    storage.add_order(order)
    assert storage.get_order_by_id(order_id, portfolio_id).venue_order_id is None

    exchange = OkxExchange(global_queue, fake_connector)
    submit = OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTC-USDT",
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("0.5"),
        exchange="okx",
        strategy_id=1,
        portfolio_id=portfolio_id,
        order_type=OrderType.LIMIT,
        order_id=order_id,
    )

    exchange._submit_order(submit)
    # Drain any ack the exchange emitted into the wired handler (no-op today).
    _drain_to_order_handler(global_queue, order_handler)

    # Re-read from the store (persistence must survive a store re-read).
    stored = storage.get_order_by_id(order_id, portfolio_id)
    assert stored is not None
    assert stored.venue_order_id == _VENUE_ID, (
        "V17-02: the venue ack was not stamped/persisted on the mirror — "
        f"stored venue_order_id={stored.venue_order_id!r} (expected {_VENUE_ID!r}). "
        "Today the id lands only in the in-memory VenueCorrelationIndex; D-06 (Phase "
        "05.2) must persist it onto the order."
    )
