"""Unit tests for the OKX order arm (``OkxExchange``) — CONN-02 / CONN-05.

Proves the Task-1 behaviour offline against a mocked ccxt.pro client wrapped in a minimal
fake ``LiveConnector`` session (``call`` runs the coroutine on a private loop; ``spawn`` is
not exercised — the fill-translation seam is tested directly through ``_handle_trade``, which
is what the ``watch_my_trades`` consume-loop calls per trade):

- ``on_order`` rounds the outbound qty/price via ``amount_to_precision`` / ``price_to_precision``
  and submits through ``connector.call`` (CONN-05 outbound edge);
- a raw venue fill is translated into a ``FillEvent`` on ``global_queue`` with Decimal
  price/quantity/commission crossed via ``to_money`` and ``time`` stamped from the venue
  timestamp (D-07 + business-time discipline);
- the Decimal edge holds even for a raw *float* fill value — the string path (``to_money``)
  avoids the ``Decimal(float)`` binary artifact (CONN-05, Pitfall 5);
- ``on_market_data`` is a no-op for live (no bar-driven fill — the venue matches);
- ``cancel_order`` routes through ``connector.call``.

The connectors conftest (``tests/unit/connectors/conftest.py``) is directory-scoped, so the
fake client/connector are defined locally here (the recorded fill fixture is reused across
trees). No real sockets are opened; the private loop is closed in teardown so nothing escapes
into the strict suite (``filterwarnings=["error"]``, Pitfall 4).
"""

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from queue import Queue
from typing import Any, Awaitable, TypeVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from itrader.core.enums import ErrorSeverity, FillStatus, OrderCommand, OrderType, Side
from itrader.core.exceptions import ValidationError
from itrader.core.ids import OrderId
from itrader.core.money import to_money
from itrader.events_handler.events import ErrorEvent, FillEvent, OrderEvent
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader import idgen

_T = TypeVar("_T")

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "connectors" / "fixtures" / "okx_order_lifecycle.json"
)


def _load_lifecycle() -> Any:
    with _FIXTURE.open() as fh:
        return json.load(fh)


class _FakeConnector:
    """Minimal synchronous fake of the ``LiveConnector`` session Protocol.

    ``call`` runs the passed coroutine to completion on a private loop (an RPC), so
    ``create_order`` / ``cancel_order`` (AsyncMock coroutines) are actually awaited and their
    return value surfaces. ``spawn`` closes the coroutine (the stream loops are not driven
    here — ``_handle_trade`` is tested directly), avoiding a never-awaited RuntimeWarning.
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
    """AsyncMock-backed fake ccxt.pro client exposing the order-arm surface.

    Mirrors the connectors-conftest shape: ``watch_*`` / ``create_order`` / ``cancel_order``
    are AsyncMock coroutines; the ``*_to_precision`` helpers are synchronous string stubs.
    """
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
    # CF-9 (D-11): validate_symbol fail-closes on a non-dict markets map. Default to a
    # loaded map containing the common test symbol so submit-path tests are not
    # preflight-rejected; the validation tests below override .markets explicitly.
    client.markets = {"BTC-USDT": {}}
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


# --- on_order: outbound rounding + RPC submit (CONN-05) -----------------------


def test_create_order_rounds_qty_and_price_and_submits_via_call(
    exchange: OkxExchange, fake_client: MagicMock
) -> None:
    """A NEW LIMIT order rounds qty/price through the ccxt string helpers and submits."""
    order = _make_order(order_type=OrderType.LIMIT)

    exchange.on_order(order)

    # IN-03: the outbound value crosses as the Decimal's STRING form, never float().
    fake_client.amount_to_precision.assert_called_once_with("BTC-USDT", str(order.quantity))
    fake_client.price_to_precision.assert_called_once_with("BTC-USDT", str(order.price))
    fake_client.create_order.assert_awaited_once()
    # Submitted with venue-rounded STRINGS (no Decimal(float) outbound).
    _sym, otype, side, amount, price = fake_client.create_order.call_args.args
    assert (otype, side, amount, price) == ("limit", "buy", "0.5", "42000.0")
    # The venue id from the response is correlated back to the originating order.
    assert exchange._index._orders_by_venue_id["OID-1"] is order


def test_market_order_omits_price_to_precision(
    exchange: OkxExchange, fake_client: MagicMock
) -> None:
    """A MARKET order rounds qty but passes no venue price (market = no fill ceiling)."""
    order = _make_order(order_type=OrderType.MARKET)

    exchange.on_order(order)

    fake_client.amount_to_precision.assert_called_once()
    fake_client.price_to_precision.assert_not_called()
    _sym, otype, _side, _amount, price = fake_client.create_order.call_args.args
    assert otype == "market"
    assert price is None


def test_market_buy_disables_requires_price_param(
    exchange: OkxExchange, fake_client: MagicMock
) -> None:
    """A spot MARKET BUY submits with createMarketBuyOrderRequiresPrice=False (WR-04).

    ccxt's okx defaults that option True — a spot market buy without a price then raises
    InvalidOrder. The arm submits base ``amount`` and disables the mode so the venue
    treats the amount as base quantity.
    """
    order = _make_order(order_type=OrderType.MARKET, action=Side.BUY)

    exchange.on_order(order)

    _sym, otype, side, _amount, price = fake_client.create_order.call_args.args
    assert (otype, side, price) == ("market", "buy", None)
    # Pitfall 11: a clOrdId is also attached (pending correlation before the RPC).
    assert fake_client.create_order.call_args.kwargs["params"] == {
        "createMarketBuyOrderRequiresPrice": False,
        "clOrdId": OkxExchange._client_order_id(order),
    }


def test_market_sell_does_not_set_requires_price_param(
    exchange: OkxExchange, fake_client: MagicMock
) -> None:
    """A MARKET SELL is unaffected — no createMarketBuyOrderRequiresPrice override (WR-04)."""
    order = _make_order(order_type=OrderType.MARKET, action=Side.SELL)

    exchange.on_order(order)

    assert "createMarketBuyOrderRequiresPrice" not in (
        fake_client.create_order.call_args.kwargs.get("params") or {}
    )


def test_limit_order_submits_empty_params(
    exchange: OkxExchange, fake_client: MagicMock
) -> None:
    """A LIMIT order carries no createMarketBuyOrderRequiresPrice override (WR-04)."""
    order = _make_order(order_type=OrderType.LIMIT, action=Side.BUY)

    exchange.on_order(order)

    # Pitfall 11: the only param on a plain LIMIT order is the clOrdId pending
    # correlation attached before the submit RPC (no market-buy override).
    assert fake_client.create_order.call_args.kwargs["params"] == {
        "clOrdId": OkxExchange._client_order_id(order),
    }


# --- fill stream: raw fill -> FillEvent on global_queue (D-07) -----------------


def test_watch_my_trades_fill_becomes_fillevent_on_queue(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """A recorded venue fill is translated to a FillEvent and put on global_queue."""
    order = _make_order()
    raw = _load_lifecycle()["my_trades"][0]["data"][0]  # the partial-fill trade
    exchange._index._orders_by_venue_id[raw["ordId"]] = order
    # ccxt watch_my_trades yields UNIFIED trades; derive one from the recorded raw fields.
    unified = {
        "order": raw["ordId"],
        "price": raw["fillPx"],   # "42000.0"
        "amount": raw["fillSz"],  # "0.2"
        "fee": {"cost": raw["fee"], "currency": raw["feeCcy"]},  # "-0.084"
        "timestamp": int(raw["ts"]),  # 1704067202000
    }

    exchange._handle_trade(unified)

    assert not queue.empty()
    fill = queue.get_nowait()
    assert isinstance(fill, FillEvent)
    assert fill.price == to_money(str(raw["fillPx"]))
    assert fill.quantity == to_money(str(raw["fillSz"]))
    # WR-01 (sign): commission is a magnitude — the arm abs()-normalises ccxt's
    # ``fee.cost`` (the portfolio validator rejects commission < 0), so the recorded
    # raw NEGATIVE OKX fee ("-0.084") surfaces as its positive magnitude.
    assert fill.commission == abs(to_money(str(raw["fee"])))
    assert fill.commission >= Decimal("0")
    # Venue-timestamp business time, never wall-clock.
    assert fill.time == datetime.fromtimestamp(int(raw["ts"]) / 1000, tz=timezone.utc)
    # Audit chain carried off the originating order.
    assert fill.order_id == order.order_id
    assert fill.strategy_id == order.strategy_id
    assert fill.portfolio_id == order.portfolio_id


def test_decimal_edge_no_float_artifact(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """A raw FLOAT fill value crosses via the string path — no Decimal(float) artifact."""
    order = _make_order()
    exchange._index._orders_by_venue_id["OID-1"] = order
    # Raw floats straight off ccxt — the edge must route them through to_money(str(x)).
    unified = {
        "order": "OID-1",
        "price": 42000.1,
        "amount": 0.2,
        "fee": {"cost": -0.084, "currency": "USDT"},
        "timestamp": 1704067202000,
    }

    exchange._handle_trade(unified)

    fill = queue.get_nowait()
    assert isinstance(fill.price, Decimal)
    assert isinstance(fill.quantity, Decimal)
    assert isinstance(fill.commission, Decimal)
    # Byte-equal to the string-parsed expectation ...
    assert fill.price == to_money(str(42000.1)) == Decimal("42000.1")
    # ... and NOT the binary-float artifact Decimal(float) would produce.
    assert fill.price != Decimal(42000.1)


def test_fill_for_unknown_order_is_skipped(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """A fill for an untracked venue order is skipped-and-logged, not crashed (T-02-03-VALID)."""
    exchange._handle_trade(
        {"order": "UNKNOWN", "price": "1", "amount": "1", "fee": {"cost": "0"}, "timestamp": 1}
    )
    assert queue.empty()


def test_malformed_fill_missing_price_is_skipped(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """A fill missing price/amount is guarded before Decimal conversion (T-02-03-VALID)."""
    order = _make_order()
    exchange._index._orders_by_venue_id["OID-1"] = order
    exchange._handle_trade({"order": "OID-1", "amount": "1", "timestamp": 1})
    assert queue.empty()


def test_none_fee_cost_coalesces_to_zero_commission(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """A ``fee: {"cost": None}`` fill yields a zero commission, not Decimal('None') (WR-01).

    ccxt emits a None fee cost when the fee is not yet known; the None must be coalesced
    to Decimal('0') BEFORE the ``to_money`` edge or the fill stream crashes on
    InvalidOperation and silently drops every subsequent fill.
    """
    order = _make_order()
    exchange._index._orders_by_venue_id["OID-1"] = order
    unified = {
        "order": "OID-1",
        "price": "42000.0",
        "amount": "0.2",
        "fee": {"cost": None, "currency": "USDT"},
        "timestamp": 1704067202000,
    }

    exchange._handle_trade(unified)

    fill = queue.get_nowait()
    assert isinstance(fill, FillEvent)
    assert fill.commission == Decimal("0")


# --- on_market_data no-op + cancel routing ------------------------------------


def test_on_market_data_is_noop_no_fill(exchange: OkxExchange, queue: "Queue[Any]") -> None:
    """The live venue matches — a bar produces no fill on the arm."""
    exchange.on_market_data(MagicMock(name="bar"))
    assert queue.empty()


def test_cancel_order_routes_through_call(
    exchange: OkxExchange, fake_client: MagicMock
) -> None:
    """CANCEL resolves the venue id and routes through connector.call -> cancel_order."""
    exchange._index._venue_id_by_order_id[1] = "OID-1"
    cancel = _make_order(order_id=1, command=OrderCommand.CANCEL)

    exchange.on_order(cancel)

    fake_client.cancel_order.assert_awaited_once_with("OID-1", "BTC-USDT")
    fake_client.create_order.assert_not_called()


# --- WR-03: unsupported order types are refused, not mis-submitted ------------


def test_stop_order_type_is_refused_not_mis_submitted(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """A STOP order is REFUSED rather than mis-submitted with a dropped trigger (WR-03).

    Trigger-param translation is deferred to the live order path; until then the arm
    must fail loud (-> FillEvent(REFUSED)) instead of sending type="stop" price=None.
    """
    order = _make_order(order_type=OrderType.STOP, price=Decimal("41000.0"))

    exchange.on_order(order)

    fake_client.create_order.assert_not_called()
    assert not queue.empty()
    fill = queue.get_nowait()
    assert isinstance(fill, FillEvent)
    assert fill.status is FillStatus.REFUSED


def test_trailing_stop_order_type_is_refused(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """A TRAILING_STOP order is likewise refused, not mis-submitted (WR-03)."""
    order = _make_order(order_type=OrderType.TRAILING_STOP, price=Decimal("41000.0"))

    exchange.on_order(order)

    fake_client.create_order.assert_not_called()
    fill = queue.get_nowait()
    assert fill.status is FillStatus.REFUSED


# --- WR-01: failed SUBMIT terminalizes (REFUSED); failed CANCEL does NOT -------


def test_submit_failure_emits_refused_fill(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """A failed create_order emits FillEvent(REFUSED) so the order mirror reconciles (WR-01).

    UNCHANGED submit behaviour: the reconciliation contract (mirrored by
    SimulatedExchange) is that a submit that never reached the venue flows back as
    REFUSED (mirror PENDING->REJECTED) — only logging would leave the mirror stuck
    at PENDING.
    """
    fake_client.create_order = AsyncMock(
        name="create_order", side_effect=RuntimeError("venue rejected")
    )
    order = _make_order(order_type=OrderType.LIMIT)

    exchange.on_order(order)

    assert not queue.empty()
    fill = queue.get_nowait()
    assert isinstance(fill, FillEvent)
    assert fill.status is FillStatus.REFUSED
    assert fill.order_id == order.order_id


def test_cancel_failure_emits_error_event_not_refused_fill(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """A failed cancel publishes an ErrorEvent and does NOT terminalize the mirror (WR-01).

    A cancel-ack failure is a command-ack failure, NOT an execution event: the
    venue order is very likely STILL RESTING. Emitting FillEvent(REFUSED) here
    would drive ReconcileManager._apply_refused -> REJECTED, wrongly terminalizing
    a live resting order. Instead the arm leaves the mirror untouched (no
    FillEvent) and publishes an auditable ErrorEvent on the operator/dead-letter
    channel; the next reconcile pass reconciles true venue state.
    """
    fake_client.cancel_order = AsyncMock(
        name="cancel_order", side_effect=RuntimeError("cancel rejected")
    )
    exchange._index._venue_id_by_order_id[1] = "OID-1"
    cancel = _make_order(order_id=1, command=OrderCommand.CANCEL)

    exchange.on_order(cancel)

    assert not queue.empty()
    emitted = queue.get_nowait()
    # No FillEvent — the mirror is left in its resting state (NOT terminalized).
    assert not isinstance(emitted, FillEvent)
    assert isinstance(emitted, ErrorEvent)
    assert emitted.operation == "cancel_order"
    assert emitted.severity is ErrorSeverity.ERROR
    assert emitted.source == "okx_exchange"
    # Scrub (T-05-27): the exception TYPE is bound, never the venue str(exc).
    assert emitted.error_type == "RuntimeError"
    assert "cancel rejected" not in emitted.error_message
    # Exactly one event — no stray FillEvent(REFUSED) alongside the ErrorEvent.
    assert queue.empty()


# --- D-18: OkxExchange.on_order preflight (defense-in-depth, ASVS V4/V5) -------


def test_on_order_preflight_rejects_non_positive_quantity(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """A non-positive quantity is rejected by the wired preflight before any venue call (D-18).

    RED today: ``on_order`` submits straight to the venue with no preflight, so an invalid
    order reaches ``create_order``. GREEN after D-18 wires ``validate_order`` into ``on_order``
    (mirroring simulated.py) — a preflight failure is a DEFINITIVE rejection -> FillEvent(REFUSED),
    and the venue is never called.
    """
    order = _make_order(order_type=OrderType.LIMIT, quantity=Decimal("0"))

    exchange.on_order(order)

    fake_client.create_order.assert_not_called()
    assert not queue.empty()
    fill = queue.get_nowait()
    assert isinstance(fill, FillEvent)
    assert fill.status is FillStatus.REFUSED
    assert fill.order_id == order.order_id


def test_on_order_preflight_rejects_unknown_symbol(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """An unknown symbol (not in the loaded markets) is rejected before any venue call (D-18).

    RED today: no symbol preflight — the order reaches ``create_order``. GREEN after D-18 wires
    ``validate_symbol`` into ``on_order``: a loaded ``markets`` map that omits the ticker is a
    DEFINITIVE rejection -> FillEvent(REFUSED); the venue is never called.
    """
    # A loaded markets map that does NOT contain the order's ticker.
    fake_client.markets = {"ETH/USDT": {}}
    order = _make_order(order_type=OrderType.LIMIT)  # ticker "BTC-USDT" not in markets

    exchange.on_order(order)

    fake_client.create_order.assert_not_called()
    assert not queue.empty()
    fill = queue.get_nowait()
    assert isinstance(fill, FillEvent)
    assert fill.status is FillStatus.REFUSED


def test_on_order_preflight_passes_valid_order_to_venue(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """A valid order clears the preflight and still submits to the venue (D-18 over-fit guard).

    The preflight must not block legitimate orders: a positive quantity with a symbol present
    in the loaded markets passes through to ``create_order`` exactly as before.
    """
    fake_client.markets = {"BTC-USDT": {}}
    order = _make_order(order_type=OrderType.LIMIT, quantity=Decimal("0.5"))

    exchange.on_order(order)

    fake_client.create_order.assert_awaited_once()


def test_validate_symbol_fail_closed_on_cold_cache(
    exchange: OkxExchange, fake_client: MagicMock
) -> None:
    """CF-9 (D-11 / T-05-04): validate_symbol returns False when markets is not a loaded dict.

    The old fail-OPEN posture returned True before ``load_markets`` populated the map,
    letting a delisted/invalid symbol slip through the pre-load window. CF-9 fail-CLOSES:
    a non-dict ``markets`` (None / an un-loaded MagicMock attribute) rejects the symbol —
    a loaded dict still validates membership as before.
    """
    # Cold cache: markets not yet a dict -> fail-closed reject (never a fail-open True).
    fake_client.markets = None
    assert exchange.validate_symbol("BTC-USDT") is False

    # Warm cache: a loaded dict validates membership (present -> True, absent -> False).
    fake_client.markets = {"BTC-USDT": {}}
    assert exchange.validate_symbol("BTC-USDT") is True
    assert exchange.validate_symbol("DOGE-USDT") is False


# --- WR-04: lossless base62 clOrdId — no truncation collision -----------------


def test_client_order_id_is_alphanumeric_and_within_okx_limit() -> None:
    """clOrdId renders to <=32 alphanumeric chars for a real UUIDv7 order id (WR-04)."""
    order = _make_order(order_id=OrderId(idgen.generate_order_id()))
    clordid = OkxExchange._client_order_id(order)

    assert clordid.isalnum()
    assert len(clordid) <= 32
    assert clordid.startswith("it")


def test_client_order_id_lossless_no_tail_bit_collision() -> None:
    """Two UUIDs differing ONLY in their tail bits produce DIFFERENT clOrdIds (WR-04).

    The old ``("it" + hex_token)[:32]`` truncation dropped the UUID's last 2 hex
    chars, so orders differing only there collided on one clOrdId (wrong-order
    fill correlation). Base62 of the full 128 bits is lossless — no collision.
    """
    import uuid

    base = uuid.uuid4()
    # Flip only the lowest byte — the exact bits the old truncation discarded.
    tail_flipped = uuid.UUID(bytes=base.bytes[:-1] + bytes([base.bytes[-1] ^ 0x01]))

    id_a = OkxExchange._client_order_id(_make_order(order_id=OrderId(base)))
    id_b = OkxExchange._client_order_id(_make_order(order_id=OrderId(tail_flipped)))

    assert id_a != id_b
    assert id_a.isalnum() and len(id_a) <= 32
    assert id_b.isalnum() and len(id_b) <= 32


def test_client_order_id_over_length_rendering_raises_typed_error() -> None:
    """D-18 / T-11-06: the charset+length guard is a REAL raise, not a bare ``assert``.

    A bare ``assert`` is stripped entirely under ``python -O``, which would leave the ONLY
    guard on a venue-bound identifier silently absent in an optimized production run. The
    identifier crosses into an authenticated venue session and is the sole handle correlating
    a fill back to an engine order, so an out-of-contract rendering must be REFUSED, never
    submitted and never silently truncated.

    Drives the LENGTH branch: ``(1 << 190) - 1`` goes through the ``int`` fallback in
    ``_client_order_id`` and renders to a 34-character base62 token — over OKX's 32-char
    limit. (The CHARSET branch is unreachable by construction: ``_CLORDID_ALPHABET`` and the
    ``it`` prefix are entirely alphanumeric, so ``clordid.isalnum()`` is always True. It is
    deliberately NOT asserted here — an always-passing assertion would be false coverage.)
    """
    oversized = _make_order(order_id=(1 << 190) - 1)

    with pytest.raises(ValidationError) as excinfo:
        OkxExchange._client_order_id(oversized)

    # The message names the offending identifier and the constraint it violated.
    message = str(excinfo.value)
    assert "it" in message
    assert "32" in message


def test_client_order_id_round_trip_correlation_resolves(
    exchange: OkxExchange, fake_client: MagicMock, queue: "Queue[Any]"
) -> None:
    """A submit registers the clOrdId pending correlation and an echoed fill resolves it (WR-04).

    Round-trip: _submit_order attaches clOrdId + registers it BEFORE the RPC; a
    fill echoing the SAME clOrdId (before any venue-id correlation) resolves the
    originating order and mints a FillEvent carrying its order_id.
    """
    order = _make_order(order_type=OrderType.LIMIT, order_id=OrderId(idgen.generate_order_id()))
    # No venue id from create_order yet — force the clOrdId fallback path.
    fake_client.create_order = AsyncMock(name="create_order", return_value={})

    exchange.on_order(order)

    clordid = OkxExchange._client_order_id(order)
    assert fake_client.create_order.call_args.kwargs["params"]["clOrdId"] == clordid
    assert exchange._index._orders_by_client_order_id[clordid] is order

    # An echoed fill carrying that clOrdId (venue-id lookup misses) resolves it.
    exchange._handle_trade({
        "id": "T-1",
        "order": "OID-LATE",
        "clientOrderId": clordid,
        "price": 42000.0,
        "amount": 0.5,
        "timestamp": 1_700_000_000_000,
        "fee": {"cost": 1.0},
    })

    drained: list[Any] = []
    while not queue.empty():
        drained.append(queue.get_nowait())
    fills = [e for e in drained if isinstance(e, FillEvent)]
    assert len(fills) == 1
    assert fills[0].order_id == order.order_id


# --- D-10: fill-translation failure emits a counted, scrubbed ErrorEvent ------

# The fixed literal bound on BOTH drain-path emits (never str(exc)/raw payload).
_FILL_TRANSLATION_MSG = (
    "OKX fill translation failed — venue fill skipped, deferred to reconcile"
)


def _assert_fill_translation_error_event(evt: Any, exc_type_name: str) -> None:
    """A single scrubbed FILL_TRANSLATION ErrorEvent (D-10 / T-05-27)."""
    assert isinstance(evt, ErrorEvent)
    assert evt.source == "okx_exchange"
    assert evt.operation == "fill-translation"
    assert evt.severity is ErrorSeverity.ERROR
    # error_type is the exception CLASS name — never str(exc).
    assert evt.error_type == exc_type_name
    # error_message is the FIXED literal — no secret / raw-trade payload leaked.
    assert evt.error_message == _FILL_TRANSLATION_MSG
    assert "boom-secret" not in evt.error_message


def test_consume_fills_translation_failure_emits_counted_errorevent(
    exchange: OkxExchange, queue: "Queue[Any]"
) -> None:
    """D-10: a per-trade translation failure in ``_consume_fills`` emits ONE scrubbed ErrorEvent.

    Drives a single loop iteration: one malformed trade (``_handle_trade`` raises with a
    secret-bearing message) then a sentinel that breaks the forever-loop. The except-arm
    must emit exactly one FILL_TRANSLATION ErrorEvent binding the exception TYPE + a fixed
    literal — never ``str(exc)`` — closing the invisible lost-fill hole (AUD-3).
    """

    class _Stop(Exception):
        pass

    def _raise(_trade: Any) -> None:
        raise ValueError("boom-secret: leaked-api-key")

    exchange._handle_trade = _raise  # type: ignore[method-assign]
    exchange._connector.client.watch_my_trades = AsyncMock(  # type: ignore[attr-defined]
        side_effect=[[{"order": "X"}], _Stop()]
    )

    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(_Stop):
            loop.run_until_complete(exchange._consume_fills("fills"))
    finally:
        loop.close()

    events = [queue.get_nowait() for _ in range(queue.qsize())]
    error_events = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(error_events) == 1
    _assert_fill_translation_error_event(error_events[0], "ValueError")


def test_catch_up_missed_fills_translation_failure_emits_counted_errorevent(
    exchange: OkxExchange, queue: "Queue[Any]", fake_client: MagicMock
) -> None:
    """D-10: the second drain path (``catch_up_missed_fills``) emits the same scrubbed ErrorEvent.

    A missed-fill catch-up whose per-trade translation raises must be equally visible: the
    resume-path except-arm emits ONE FILL_TRANSLATION ErrorEvent (TYPE + fixed literal only).
    """

    def _raise(_trade: Any) -> None:
        raise RuntimeError("boom-secret: leaked-api-key")

    exchange._handle_trade = _raise  # type: ignore[method-assign]
    exchange._active_symbols.add("BTC-USDT")
    exchange._disconnect_ts_ms = 1_700_000_000_000
    fake_client.fetch_my_trades = AsyncMock(
        name="fetch_my_trades", return_value=[{"order": "X"}]
    )

    exchange.catch_up_missed_fills()

    events = [queue.get_nowait() for _ in range(queue.qsize())]
    error_events = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(error_events) == 1
    _assert_fill_translation_error_event(error_events[0], "RuntimeError")
