"""Fill-ID dedup + fast-fill-race idempotency for the OKX arm (RECON-02, D-12/D-13, Pitfall 11).

Proves the two documented latent gaps in ``OkxExchange._handle_trade`` are closed:

1. **Fill-ID dedup** — a reconnect re-send carries the same venue ``trade['id']``; the
   arm emits exactly ONE ``FillEvent`` for it and no-ops the duplicate (never
   double-counted into position/cash).
2. **Fast-fill race** — a fill can stream back on ``watch_my_trades`` before
   ``create_order`` returns the venue id. The arm BUFFERS such an uncorrelated fill and
   re-drains it once ``_submit_order`` writes the venue-id correlation — the fill is
   emitted, never silently dropped. The ``clOrdId`` pending correlation registered before
   the submit RPC is the primary resolve path; the buffer is the safety net.
3. **Stream resilience** — a malformed trade (missing price/amount/timestamp) is
   skipped-and-logged inside the forever-loop without killing the stream: a subsequent
   good fill still emits.

Driven offline against a MagicMock/AsyncMock ccxt.pro client wrapped in a minimal
``LiveConnector`` fake (mirrors ``test_okx_exchange.py``): ``call`` runs a coroutine on a
private loop (an RPC); the fill seam is exercised directly through ``_handle_trade`` /
``_submit_order`` and, for the stream-resilience case, through the async ``_stream_fills``
consume-loop. No real sockets; the private loop is closed in teardown so nothing escapes
into the strict suite (``filterwarnings=["error"]``, Pitfall 4). Folder-derived ``unit``
marker (no decorator).
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Awaitable, TypeVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from itrader.core.enums import FillStatus, OrderCommand, OrderType, Side
from itrader.core.money import to_money
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader.order_handler.order import Order

_T = TypeVar("_T")


class _FakeConnector:
    """Minimal synchronous fake of the ``LiveConnector`` session Protocol.

    ``call`` runs the passed coroutine to completion on a private loop (an RPC), so
    ``create_order`` (AsyncMock) is actually awaited and its return value surfaces.
    ``spawn`` closes the coroutine (stream loops are driven directly in the tests that
    need them), avoiding a never-awaited RuntimeWarning.
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
    """AsyncMock-backed fake ccxt.pro client exposing the order-arm surface."""
    client = MagicMock(name="fake_ccxt_pro_client")
    client.watch_my_trades = AsyncMock(name="watch_my_trades")
    client.watch_orders = AsyncMock(name="watch_orders")
    client.create_order = AsyncMock(name="create_order", return_value={"id": "OID-1"})
    client.cancel_order = AsyncMock(name="cancel_order", return_value={"id": "OID-1"})
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
def queue() -> "Queue[Any]":
    return Queue()


@pytest.fixture
def exchange(queue: "Queue[Any]", fake_connector: Any) -> OkxExchange:
    return OkxExchange(queue, fake_connector)


def _make_order(
    *,
    order_type: OrderType = OrderType.LIMIT,
    action: Side = Side.BUY,
    price: Decimal = Decimal("42000.0"),
    quantity: Decimal = Decimal("0.5"),
    order_id: int = 1,
    command: OrderCommand = OrderCommand.NEW,
) -> OrderEvent:
    return OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTC-USDT",
        action=action,
        price=price,
        quantity=quantity,
        exchange="okx",
        strategy_id=7,
        portfolio_id=3,
        order_type=order_type,
        order_id=order_id,
        command=command,
    )


def _drain_queue(q: "Queue[Any]") -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


# --- (i) fill-ID dedup: a duplicate trade id emits exactly one FillEvent -------


def test_duplicate_trade_id_emits_single_fill(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """The same venue ``trade['id']`` seen twice yields ONE FillEvent (idempotent).

    A ccxt.pro reconnect re-pushes recent trades; without dedup the mirror double-counts.
    """
    order = _make_order()
    exchange._orders_by_venue_id["OID-1"] = order
    trade = {
        "id": "T-42",
        "order": "OID-1",
        "price": "42000.0",
        "amount": "0.2",
        "fee": {"cost": "0.084", "currency": "USDT"},
        "timestamp": 1704067202000,
    }

    exchange._handle_trade(trade)   # first delivery
    exchange._handle_trade(trade)   # reconnect re-send — must dedupe

    fills = _drain_queue(queue)
    assert len(fills) == 1
    assert isinstance(fills[0], FillEvent)
    assert fills[0].status is FillStatus.EXECUTED
    assert fills[0].quantity == to_money("0.2")
    # The dedup key is recorded so a later re-send stays a no-op.
    assert "T-42" in exchange._seen_trade_ids


def test_distinct_trade_ids_both_emit(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """Two DISTINCT trade ids for the same order are two real partial fills — both emit."""
    order = _make_order(quantity=Decimal("0.5"))
    exchange._orders_by_venue_id["OID-1"] = order
    base = {"order": "OID-1", "price": "42000.0", "fee": {"cost": "0.04"}, "timestamp": 1704067202000}

    exchange._handle_trade({**base, "id": "T-1", "amount": "0.2"})
    exchange._handle_trade({**base, "id": "T-2", "amount": "0.3"})

    fills = _drain_queue(queue)
    assert len(fills) == 2
    assert {f.quantity for f in fills} == {to_money("0.2"), to_money("0.3")}


# --- (ii) fast-fill race: a pre-correlation fill is buffered, then emitted -----


def test_fill_before_venue_id_is_buffered_not_dropped(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """A fill that streams back BEFORE the venue-id correlation lands is buffered,
    then emitted when ``_submit_order`` writes the correlation — never dropped."""
    order = _make_order(order_type=OrderType.LIMIT)
    # The venue id the RPC will return, but the fill arrives FIRST.
    fill = {
        "id": "T-1",
        "order": "OID-9",
        "price": "42000.0",
        "amount": "0.5",
        "fee": {"cost": "0.1", "currency": "USDT"},
        "timestamp": 1704067202000,
    }

    # Fill arrives before submit completes -> uncorrelated -> BUFFERED, not emitted.
    exchange._handle_trade(fill)
    assert queue.empty()
    assert exchange._pending_fills_by_venue_id.get("OID-9") == [fill]

    # Now the submit RPC returns the venue id -> correlation lands -> buffer drains.
    exchange._connector.client.create_order = AsyncMock(return_value={"id": "OID-9"})
    exchange._submit_order(order)

    fills = _drain_queue(queue)
    assert len(fills) == 1
    assert isinstance(fills[0], FillEvent)
    assert fills[0].quantity == to_money("0.5")
    assert fills[0].order_id == order.order_id
    # The buffer was consumed (no lingering entry).
    assert "OID-9" not in exchange._pending_fills_by_venue_id


def test_fill_resolves_via_clordid_before_venue_id(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """A fill carrying the echoed ``clOrdId`` resolves against the pending correlation
    registered before the submit RPC — even with no venue-id map entry yet."""
    order = _make_order(order_id=77)
    clordid = OkxExchange._client_order_id(order)
    # Pending correlation registered BEFORE the RPC returns the venue id.
    exchange._orders_by_clOrdId[clordid] = order
    fill = {
        "id": "T-5",
        "order": "OID-LATE",   # not yet in _orders_by_venue_id
        "clientOrderId": clordid,
        "price": "42000.0",
        "amount": "0.5",
        "fee": {"cost": "0.1"},
        "timestamp": 1704067202000,
    }

    exchange._handle_trade(fill)

    fills = _drain_queue(queue)
    assert len(fills) == 1
    assert fills[0].order_id == order.order_id
    # Resolved directly (not buffered).
    assert "OID-LATE" not in exchange._pending_fills_by_venue_id


def test_submit_registers_clordid_pending_correlation(
    exchange: OkxExchange, fake_client: MagicMock
) -> None:
    """``_submit_order`` attaches a ``clOrdId`` and registers the pending correlation
    keyed by it BEFORE the create_order RPC (the fast-fill-race pre-registration)."""
    order = _make_order(order_id=1)
    clordid = OkxExchange._client_order_id(order)

    exchange.on_order(order)

    assert fake_client.create_order.call_args.kwargs["params"]["clOrdId"] == clordid
    assert exchange._orders_by_clOrdId[clordid] is order


# --- (ii-b) restart rehydration: adopt_venue_correlation repopulates the maps --


def _make_rehydrated_order(*, venue_order_id: str, order_id: int = 55) -> Order:
    """A REAL Order rehydrated from the store carrying a persisted venue_order_id —
    one that NEVER went through _submit_order (so its correlation maps are empty)."""
    order = Order.new_limit_order(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTC-USDT",
        action=Side.BUY,
        price="42000",
        quantity="0.5",
        exchange="okx",
        strategy_id=7,
        portfolio_id=3,
    )
    order.venue_order_id = venue_order_id
    return order


def test_adopt_correlation_drains_prebuffered_fill(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """WR-02: a fill delivered BEFORE adoption is buffered; ``adopt_venue_correlation``
    repopulates the maps and DRAINS it — the fill emits, never silently lost."""
    order = _make_rehydrated_order(venue_order_id="OID-REHY")
    fill = {
        "id": "T-9",
        "order": "OID-REHY",
        "price": "42000.0",
        "amount": "0.5",
        "fee": {"cost": "0.1", "currency": "USDT"},
        "timestamp": 1704067202000,
    }
    # Post-restart fill arrives before the rehydrated order's correlation is adopted
    # (the maps are empty — _submit_order never ran for it) -> BUFFERED.
    exchange._handle_trade(fill)
    assert queue.empty()
    assert exchange._pending_fills_by_venue_id.get("OID-REHY") == [fill]

    # Restart rehydration adopts the correlation -> the buffer drains.
    exchange.adopt_venue_correlation(order)

    fills = _drain_queue(queue)
    assert len(fills) == 1
    assert isinstance(fills[0], FillEvent)
    assert fills[0].order_id == order.id
    assert fills[0].quantity == to_money("0.5")
    assert "OID-REHY" not in exchange._pending_fills_by_venue_id


def test_adopt_correlation_lets_postrestart_fill_reach_mirror(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """WR-02: after adoption, a fresh post-restart fill for the rehydrated order emits a
    FillEvent (resolves via the repopulated map) instead of being silently buffered."""
    order = _make_rehydrated_order(venue_order_id="OID-REHY2")
    exchange.adopt_venue_correlation(order)

    fill = {
        "id": "T-10",
        "order": "OID-REHY2",
        "price": "42000.0",
        "amount": "0.5",
        "fee": {"cost": "0.1", "currency": "USDT"},
        "timestamp": 1704067202000,
    }
    exchange._handle_trade(fill)

    fills = _drain_queue(queue)
    assert len(fills) == 1
    assert fills[0].order_id == order.id
    # Resolved via the adopted map — nothing left buffered.
    assert not exchange._pending_fills_by_venue_id


def test_adopt_correlation_none_venue_id_is_noop(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """An order with no venue_order_id (never acknowledged) is a clean no-op — no map
    write, no crash."""
    order = _make_rehydrated_order(venue_order_id="unused")
    order.venue_order_id = None

    exchange.adopt_venue_correlation(order)

    assert not exchange._orders_by_venue_id
    assert not exchange._venue_id_by_order_id
    assert queue.empty()


# --- (iii) stream resilience: a malformed trade does not kill the loop ---------


def test_malformed_trade_does_not_kill_stream(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """A malformed fill (missing price) is skipped-and-logged inside the forever-loop;
    a subsequent good fill in the same batch still emits — the stream keeps draining."""
    order = _make_order()
    exchange._orders_by_venue_id["OID-1"] = order
    malformed = {"id": "T-bad", "order": "OID-1", "amount": "0.2", "timestamp": 1}  # no price
    good = {
        "id": "T-good",
        "order": "OID-1",
        "price": "42000.0",
        "amount": "0.2",
        "fee": {"cost": "0.084"},
        "timestamp": 1704067202000,
    }
    # First await yields the batch; the second raises CancelledError to break the loop.
    fake_client.watch_my_trades = AsyncMock(
        side_effect=[[malformed, good], asyncio.CancelledError()]
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(exchange._stream_fills())

    fills = _drain_queue(queue)
    assert len(fills) == 1
    assert fills[0].quantity == to_money("0.2")
    assert fills[0].order_id == order.order_id


def test_raising_trade_is_swallowed_per_trade(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """Even a trade whose translation RAISES is swallowed per-trade (WR-02): the
    forever-loop survives and later fills still emit."""
    order = _make_order()
    exchange._orders_by_venue_id["OID-1"] = order
    good = {
        "id": "T-ok",
        "order": "OID-1",
        "price": "42000.0",
        "amount": "0.2",
        "fee": {"cost": "0.084"},
        "timestamp": 1704067202000,
    }
    # A correlated trade with a NON-NUMERIC price raises InvalidOperation at the
    # to_money Decimal edge inside _emit_fill — the _stream_fills per-trade except
    # must swallow it so the good trade behind it still emits.
    boom = {"id": "T-boom", "order": "OID-1", "price": "notanumber",
            "amount": "0.2", "timestamp": 1}
    fake_client.watch_my_trades = AsyncMock(
        side_effect=[[boom, good], asyncio.CancelledError()]
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(exchange._stream_fills())

    fills = _drain_queue(queue)
    assert len(fills) == 1
    assert fills[0].order_id == order.order_id
