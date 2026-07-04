"""A7 (D-13 / V17-09) RED gate — an ambiguous submit timeout must NOT terminalize the mirror.

CONF-A spine (D-19), Wave-1 slice 3. This is an EXPECTED-FAILING regression test: it pins
the V17-09 false-REJECTED bug and turns GREEN only once the D-13 in-flight handling lands in
Phase 05.3. It MUST be RED against current code — that is the success condition of a CONF-A
spine plan, NOT a broken build.

The bug (V17-09)
----------------
``OkxExchange.on_order`` wraps ``_submit_order`` in a boundary swallow (``okx.py:210``). On a
SUBMIT failure it emits ``FillEvent("REFUSED", ...)`` (``okx.py:250``) so the mirror
reconciles PENDING -> REJECTED. That is correct for a DEFINITIVE venue rejection (the order
never reached the book). But the same arm fires for a ``connector.call`` ``TimeoutError`` —
an AMBIGUOUS TRANSPORT error: the submit may well have REACHED the venue and be resting /
partially filled. Terminalizing the mirror to REJECTED on a timeout means a later real fill
arrives against an order the engine believes is dead (position + cash drift, unhedged risk).

The fix (D-13, Phase 05.3)
--------------------------
Distinguish the ambiguous transport error (``TimeoutError`` / a network error) from a
definitive venue rejection: on the ambiguous branch the mirror stays IN-FLIGHT / UNKNOWN
(no ``FillEvent(REFUSED)``), pending a ``fetch_order(clOrdId)`` probe or the next reconcile;
a definitive venue rejection STILL produces ``REFUSED``.

Over-fitting guard: the second test asserts a definitive ``ccxt.InvalidOrder`` rejection
STILL terminalizes to REFUSED today AND must continue to after D-13 — so the fix cannot
simply stop emitting REFUSED on every failure; it must branch on the error class.

Import-clean, fully offline: a synchronous fake ``LiveConnector`` whose ``call`` raises the
target error (closing the create_order coroutine first, so no never-awaited RuntimeWarning
under ``filterwarnings=["error"]``). No network, no credentials. Folder-derived ``unit`` marker.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Awaitable, TypeVar
from unittest.mock import AsyncMock, MagicMock

import ccxt
import pytest

from itrader.core.enums import FillStatus, OrderCommand, OrderType, Side
from itrader.core.ids import OrderId, PortfolioId
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.execution_handler.exchanges.okx import OkxExchange

_T = TypeVar("_T")


class _RaisingConnector:
    """Minimal synchronous fake ``LiveConnector`` whose ``call`` raises a fixed error.

    ``call`` CLOSES the passed create_order coroutine before raising so the AsyncMock
    coroutine is never left un-awaited (which would raise a RuntimeWarning under the strict
    filter). ``spawn`` closes its coroutine too (streams are not driven here).
    """

    def __init__(self, exc: BaseException, client: Any) -> None:
        self._exc = exc
        self._client = client

    @property
    def client(self) -> Any:
        return self._client

    @property
    def sandbox(self) -> bool:
        return True

    def call(self, coro: Awaitable[_T]) -> _T:
        coro.close()  # type: ignore[attr-defined]  # avoid never-awaited RuntimeWarning
        raise self._exc

    def spawn(self, coro: Awaitable[Any]) -> Any:
        coro.close()  # type: ignore[attr-defined]
        return None

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None


@pytest.fixture
def fake_client() -> MagicMock:
    """A ccxt.pro-shaped client: create_order awaited via connector.call; precision helpers."""
    client = MagicMock(name="fake_ccxt_pro_client")
    client.create_order = AsyncMock(name="create_order", return_value={"id": "OKX-1"})
    client.amount_to_precision = MagicMock(
        name="amount_to_precision", side_effect=lambda symbol, amount: str(amount))
    client.price_to_precision = MagicMock(
        name="price_to_precision", side_effect=lambda symbol, price: str(price))
    return client


def _submit_event() -> OrderEvent:
    """A fresh NEW LIMIT submit OrderEvent."""
    return OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTC-USDT",
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("0.5"),
        exchange="okx",
        strategy_id=1,
        portfolio_id=PortfolioId(uuid.uuid4()),
        order_type=OrderType.LIMIT,
        order_id=OrderId(uuid.uuid4()),
        command=OrderCommand.NEW,
    )


def _refused_fills(queue: "Queue[Any]") -> list[FillEvent]:
    """Drain the queue and return every REFUSED FillEvent."""
    refused: list[FillEvent] = []
    while not queue.empty():
        event = queue.get_nowait()
        if isinstance(event, FillEvent) and event.status == FillStatus.REFUSED:
            refused.append(event)
    return refused


def test_submit_timeout_inflight_does_not_terminalize_mirror(fake_client: MagicMock) -> None:
    """A ``TimeoutError`` on submit must NOT emit ``FillEvent(REFUSED)`` (A7).

    RED today: ``on_order`` swallows the TimeoutError and emits REFUSED, terminalizing the
    mirror to REJECTED on an AMBIGUOUS transport error — the order may actually be resting
    at the venue. GREEN after D-13 (Phase 05.3) leaves the mirror in-flight pending a
    ``fetch_order`` probe / the next reconcile.
    """
    queue: "Queue[Any]" = Queue()
    connector = _RaisingConnector(TimeoutError("submit ack timed out"), fake_client)
    exchange = OkxExchange(queue, connector)

    exchange.on_order(_submit_event())

    refused = _refused_fills(queue)
    assert refused == [], (
        "A7/V17-09: a connector TimeoutError on submit terminalized the mirror to REJECTED "
        f"(emitted {len(refused)} REFUSED FillEvent(s)) — an ambiguous transport timeout is "
        "NOT a definitive venue rejection (the order may be resting/partially filled). D-13 "
        "(Phase 05.3) must leave the mirror in-flight pending fetch_order / the next reconcile."
    )


def test_definitive_venue_rejection_still_produces_refused(fake_client: MagicMock) -> None:
    """A definitive ``ccxt.InvalidOrder`` rejection STILL terminalizes to REFUSED (over-fit guard).

    This arm PASSES today and MUST continue to pass after D-13 — a genuine venue rejection
    (the order was refused outright) is correctly terminalized to REJECTED. It guards against
    an over-broad D-13 fix that simply stops emitting REFUSED on every failure: the fix must
    branch on the error CLASS (ambiguous transport vs definitive rejection), not blanket-skip.
    """
    queue: "Queue[Any]" = Queue()
    connector = _RaisingConnector(
        ccxt.InvalidOrder("venue rejected: insufficient balance"), fake_client)
    exchange = OkxExchange(queue, connector)

    exchange.on_order(_submit_event())

    refused = _refused_fills(queue)
    assert len(refused) == 1, (
        "A7/V17-09 (over-fit guard): a DEFINITIVE venue rejection (ccxt.InvalidOrder) must "
        f"still terminalize the mirror to REJECTED — expected exactly one REFUSED FillEvent, "
        f"got {len(refused)}. D-13 must spare only the ambiguous transport timeout, not every "
        "submit failure."
    )
