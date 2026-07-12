"""D-12 (V17-08) RED gate — missed-fill catch-up on resume + venue-cancel reconciliation.

CONF-A follow-on (Phase 05.3, Wave-2). Two live-path resilience gaps on ``OkxExchange``:

1. **Missed-fill catch-up.** A fill that settles at the venue WHILE the ``watch_my_trades``
   stream is down is lost forever — the fill stream has no replay and nothing re-fetches it.
   On resume the arm must run a bounded ``fetch_my_trades(symbol, since=disconnect_ts)`` for
   each active-order symbol and route every returned trade through the EXISTING
   ``_handle_trade`` so the missed fill settles the mirror. Safe by D-08 ``{symbol}:{trade_id}``
   dedup: a re-fetched trade (or one the live stream ALSO redelivers) is an idempotent no-op,
   so the fill settles EXACTLY once.

2. **Venue-side cancel reconciliation.** ``_consume_orders`` is log-only today, so a
   venue-side CANCELLED/EXPIRED (a cancel/expiry the engine did not command — an OKX MMP
   cancel, a post-only reject, a GTD expiry) never reconciles the mirror and the order sits
   PENDING forever. The arm must translate it into a ``FillEvent(CANCELLED/EXPIRED)``.

RED today: ``OkxExchange`` exposes neither ``catch_up_missed_fills`` nor a per-row
``_handle_order_update`` translation — GREEN once D-12 (Phase 05.3) lands both.

Import-clean, fully offline: a synchronous scripted ``LiveConnector`` double whose ``call``
drives the passed coroutine to completion (AsyncMock create_order / fetch_my_trades resolve in
one ``send``). No network, no credentials. Folder-derived ``unit`` marker.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Awaitable, TypeVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from itrader.core.enums import FillStatus, OrderCommand, OrderType, Side
from itrader.core.ids import OrderId, PortfolioId
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.execution_handler.exchanges.okx import OkxExchange

_T = TypeVar("_T")


class _ScriptedConnector:
    """Synchronous fake ``LiveConnector`` whose ``call`` DRIVES the coroutine to completion.

    Unlike the A7 raising-double, this one returns the coroutine's value (the create_order
    venue id, the fetch_my_trades page) — an AsyncMock coroutine resolves in a single
    ``send(None)``. ``spawn`` closes its coroutine (streams are not driven here).
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        return self._client

    @property
    def sandbox(self) -> bool:
        return True

    def call(self, coro: Awaitable[_T]) -> _T:
        try:
            coro.send(None)  # type: ignore[attr-defined]
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]
        raise AssertionError("scripted coroutine did not complete synchronously")

    def spawn(self, coro: Awaitable[Any]) -> Any:
        coro.close()  # type: ignore[attr-defined]
        return None

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None


@pytest.fixture
def fake_client() -> MagicMock:
    """A ccxt.pro-shaped client: create_order + precision helpers (fetch_my_trades set per test)."""
    client = MagicMock(name="fake_ccxt_pro_client")
    client.create_order = AsyncMock(name="create_order", return_value={"id": "OKX-1"})
    client.amount_to_precision = MagicMock(
        name="amount_to_precision", side_effect=lambda symbol, amount: str(amount))
    client.price_to_precision = MagicMock(
        name="price_to_precision", side_effect=lambda symbol, price: str(price))
    # CF-9 (D-11): validate_symbol fail-closes on a non-dict markets map — seed a
    # loaded markets map so submits through this warm client are not preflight-rejected.
    client.markets = {"BTC-USDT": {}}
    return client


def _submit_event(venue_qty: str = "0.5") -> OrderEvent:
    """A fresh NEW LIMIT submit OrderEvent for BTC-USDT."""
    return OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTC-USDT",
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal(venue_qty),
        exchange="okx",
        strategy_id=1,
        portfolio_id=PortfolioId(uuid.uuid4()),
        order_type=OrderType.LIMIT,
        order_id=OrderId(uuid.uuid4()),
        command=OrderCommand.NEW,
    )


def _fills(queue: "Queue[Any]", status: FillStatus) -> list[FillEvent]:
    """Drain the queue and return every FillEvent with ``status``."""
    out: list[FillEvent] = []
    while not queue.empty():
        event = queue.get_nowait()
        if isinstance(event, FillEvent) and event.status is status:
            out.append(event)
    return out


def test_missed_fill_catch_up_settles_the_missed_fill_once(fake_client: MagicMock) -> None:
    """A fill missed during a stream drop is recovered by the resume catch-up — exactly once.

    RED today: ``OkxExchange`` has no ``catch_up_missed_fills`` — the fill that settled while
    the stream was down is never re-fetched and the mirror never settles it. GREEN after D-12:
    the bounded ``fetch_my_trades(symbol, since=disconnect_ts)`` re-fetches it, routes it
    through ``_handle_trade``, and D-08 dedup makes a redelivery a no-op (settles once).
    """
    queue: "Queue[Any]" = Queue()
    connector = _ScriptedConnector(fake_client)
    exchange = OkxExchange(queue, connector)

    # Submit correlates venue id "OKX-1" for BTC-USDT (registers the active symbol).
    exchange.on_order(_submit_event(venue_qty="0.5"))
    while not queue.empty():          # drop the OrderAckEvent
        queue.get_nowait()

    # A PARTIAL fill (0.3 of 0.5) settled at the venue while the stream was down — it stays
    # correlated (cumulative 0.3 < 0.5), so the D-08 dedup ring is what prevents a redelivered
    # double-settle. fetch_my_trades returns exactly this trade on the catch-up.
    missed_trade = {
        "id": "T-1",
        "order": "OKX-1",
        "price": 42000.0,
        "amount": 0.3,
        "timestamp": 1_700_000_000_000,
        "fee": {"cost": 0.0, "currency": "USDT"},
    }
    fake_client.fetch_my_trades = AsyncMock(
        name="fetch_my_trades", return_value=[missed_trade])

    exchange.catch_up_missed_fills()

    # The catch-up must have fetched with a bounded, non-paginated page.
    assert fake_client.fetch_my_trades.await_count == 1
    _, kwargs = fake_client.fetch_my_trades.await_args
    assert "limit" in kwargs and kwargs["limit"] is not None
    assert "paginate" not in kwargs

    executed = _fills(queue, FillStatus.EXECUTED)
    assert len(executed) == 1, (
        "D-12/V17-08: the fill that settled while the stream was down was NOT recovered by "
        f"the resume catch-up (got {len(executed)} EXECUTED FillEvent(s)). D-12 must "
        "fetch_my_trades(symbol, since=disconnect_ts) and route it through _handle_trade.")
    assert executed[0].quantity == Decimal("0.3")

    # Dedup-safety (D-08): the live stream redelivering the SAME trade must NOT double-settle.
    exchange._handle_trade(missed_trade)
    assert _fills(queue, FillStatus.EXECUTED) == [], (
        "D-12: a redelivered missed trade double-settled — D-08 {symbol}:{trade_id} dedup "
        "must make the re-fetched/redelivered trade an idempotent no-op.")


def test_watch_orders_cancelled_reconciles_the_mirror(fake_client: MagicMock) -> None:
    """A venue-side CANCELLED order-status row is translated into ``FillEvent(CANCELLED)``.

    RED today: ``_consume_orders`` is log-only, so a venue cancel never reconciles the mirror
    and the order sits PENDING forever. GREEN after D-12: the arm translates a
    CANCELLED/EXPIRED status into a ``FillEvent`` so ``OrderHandler.on_fill`` drives the
    mirror terminal.
    """
    queue: "Queue[Any]" = Queue()
    connector = _ScriptedConnector(fake_client)
    exchange = OkxExchange(queue, connector)

    exchange.on_order(_submit_event())      # correlates venue id "OKX-1"
    while not queue.empty():                 # drop the OrderAckEvent
        queue.get_nowait()

    cancel_row = {
        "id": "OKX-1",
        "status": "canceled",                # ccxt-unified venue-side cancel
        "timestamp": 1_700_000_000_000,
    }
    exchange._handle_order_update(cancel_row)

    cancelled = _fills(queue, FillStatus.CANCELLED)
    assert len(cancelled) == 1, (
        "D-12/V17-08: a venue-side CANCELLED watch_orders row was NOT translated into a "
        f"FillEvent(CANCELLED) (got {len(cancelled)}) — the mirror never reconciles and the "
        "order sits PENDING forever. D-12 must translate CANCELLED/EXPIRED into a FillEvent.")


def test_watch_orders_expired_reconciles_the_mirror(fake_client: MagicMock) -> None:
    """A venue-side EXPIRED order-status row is translated into ``FillEvent(EXPIRED)``."""
    queue: "Queue[Any]" = Queue()
    connector = _ScriptedConnector(fake_client)
    exchange = OkxExchange(queue, connector)

    exchange.on_order(_submit_event())
    while not queue.empty():
        queue.get_nowait()

    exchange._handle_order_update(
        {"id": "OKX-1", "status": "expired", "timestamp": 1_700_000_000_000})

    assert len(_fills(queue, FillStatus.EXPIRED)) == 1, (
        "D-12: a venue-side EXPIRED watch_orders row must translate into FillEvent(EXPIRED).")


def test_watch_orders_open_status_stays_log_only(fake_client: MagicMock) -> None:
    """A non-terminal status (``open``) emits NO FillEvent — only CANCELLED/EXPIRED reconcile.

    Over-fit guard: the translation must branch on the terminal venue-cancel statuses, not
    blanket-emit on every order update. 'closed' (FILLED) is deliberately NOT translated here
    either — that money crosses on watch_my_trades (double-settle guard).
    """
    queue: "Queue[Any]" = Queue()
    connector = _ScriptedConnector(fake_client)
    exchange = OkxExchange(queue, connector)

    exchange.on_order(_submit_event())
    while not queue.empty():
        queue.get_nowait()

    exchange._handle_order_update(
        {"id": "OKX-1", "status": "open", "timestamp": 1_700_000_000_000})
    exchange._handle_order_update(
        {"id": "OKX-1", "status": "closed", "timestamp": 1_700_000_000_000})

    drained = [queue.get_nowait() for _ in range(queue.qsize())]
    assert not any(isinstance(e, FillEvent) for e in drained), (
        "D-12: a non-cancel status (open/closed) must not emit a FillEvent — only a "
        "venue-side CANCELLED/EXPIRED reconciles the mirror here.")
