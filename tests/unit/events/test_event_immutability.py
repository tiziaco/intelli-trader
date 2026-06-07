"""M3-01 (D-23 group 2): every event is an immutable, fully-linked fact.

Inverted contract — this file previously asserted that SignalEvent /
OrderEvent / FillEvent stay structurally mutable during the transition;
the new ``events_handler/events/`` package supersedes that:

- ALL event classes are ``frozen=True``/``slots=True``/``kw_only=True``
  ``Event`` subclasses: reassigning any field raises
  ``dataclasses.FrozenInstanceError``.
- Linkage IDs are required at construction (D-12): ``OrderEvent`` without
  ``order_id``, and ``FillEvent`` without ``fill_id`` or ``order_id``,
  raise ``TypeError``.
- Every event carries a unique, time-ordered UUIDv7 ``event_id`` (D-01)
  and a ``created_at`` defaulting to business time (D-02).
- ``type`` is a real field holding the correct ``EventType`` member.
- ``action`` / ``order_type`` are enum-typed (``Side`` / ``OrderType``,
  D-05).
- ``ErrorEvent`` is a concrete instantiable base; ``PortfolioErrorEvent``
  narrows ``source`` to "portfolio" — both carry ``EventType.ERROR``
  (D-06, killing the legacy ``type = EventType.UPDATE`` hack).
"""

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

import pytest
import uuid_utils.compat as uuid_compat

from itrader.core.bar import Bar
from itrader.core.enums import EventType, FillStatus, OrderType, Side
from itrader.core.ids import OrderId, StrategyId
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.events_handler.events import (
    BarEvent,
    ErrorEvent,
    Event,
    FillEvent,
    OrderEvent,
    PortfolioErrorEvent,
    PortfolioUpdateEvent,
    ScreenerEvent,
    SignalEvent,
    TimeEvent,
)

_TIME = datetime(2024, 1, 1)
_STRATEGY_ID = StrategyId(uuid_compat.uuid7())
_ORDER_ID = OrderId(uuid_compat.uuid7())


def _time_event() -> TimeEvent:
    return TimeEvent(time=_TIME)


def _bar() -> BarEvent:
    # M5-02: the payload carries an immutable Bar struct per ticker.
    return BarEvent(time=_TIME, bars={
        "BTCUSDT": Bar(time=_TIME, open=Decimal("40"), high=Decimal("60"),
                       low=Decimal("20"), close=Decimal("50"), volume=Decimal("1")),
    })


def _signal() -> SignalEvent:
    return SignalEvent(
        time=_TIME, ticker="BTCUSDT", action=Side.BUY,
        order_type=OrderType.MARKET, price=42.0, stop_loss=41.0,
        take_profit=45.0, strategy_id=_STRATEGY_ID, portfolio_id=1,
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
    )


def _order() -> OrderEvent:
    return OrderEvent(
        time=_TIME, ticker="BTCUSDT", action=Side.BUY, price=42.0,
        quantity=1.0, exchange="default", strategy_id=_STRATEGY_ID,
        portfolio_id=1, order_type=OrderType.MARKET, order_id=_ORDER_ID,
    )


def _fill() -> FillEvent:
    return FillEvent(
        time=_TIME, status=FillStatus.EXECUTED, ticker="BTCUSDT",
        action=Side.BUY, price=42.0, quantity=1.0, commission=0.1,
        portfolio_id=1, fill_id=uuid_compat.uuid7(), order_id=_ORDER_ID,
        strategy_id=_STRATEGY_ID,
    )


def _update() -> PortfolioUpdateEvent:
    return PortfolioUpdateEvent(time=_TIME, portfolios={})


def _screener() -> ScreenerEvent:
    return ScreenerEvent(
        time=_TIME, screener_id="sid", screener_name="name",
        subscribed_strategies=[], tickers=[],
    )


def _error() -> ErrorEvent:
    return ErrorEvent(
        time=_TIME, source="test", error_type="ValueError",
        error_message="boom",
    )


def _portfolio_error() -> PortfolioErrorEvent:
    return PortfolioErrorEvent(
        time=_TIME, error_type="ValueError", error_message="boom",
        portfolio_id=1, operation="update",
    )


_ALL_EVENTS: list[Any] = [
    pytest.param(lambda: Event(time=_TIME), id="Event"),
    pytest.param(_time_event, id="TimeEvent"),
    pytest.param(_bar, id="BarEvent"),
    pytest.param(_signal, id="SignalEvent"),
    pytest.param(_order, id="OrderEvent"),
    pytest.param(_fill, id="FillEvent"),
    pytest.param(_update, id="PortfolioUpdateEvent"),
    pytest.param(_screener, id="ScreenerEvent"),
    pytest.param(_error, id="ErrorEvent"),
    pytest.param(_portfolio_error, id="PortfolioErrorEvent"),
]


# ---------------------------------------------------------------------------
# (a) Every event class is frozen: field assignment raises FrozenInstanceError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("factory", _ALL_EVENTS)
def test_event_is_frozen(factory: Callable[[], Event]) -> None:
    event = factory()
    with pytest.raises(FrozenInstanceError):
        event.time = datetime(2025, 1, 1)  # type: ignore[misc]


def test_signal_event_payload_fields_are_frozen() -> None:
    signal = _signal()
    with pytest.raises(FrozenInstanceError):
        signal.quantity = 2.5  # type: ignore[misc]


def test_order_event_payload_fields_are_frozen() -> None:
    order = _order()
    with pytest.raises(FrozenInstanceError):
        order.price = 99.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        order.quantity = 3.0  # type: ignore[misc]


def test_fill_event_payload_fields_are_frozen() -> None:
    fill = _fill()
    with pytest.raises(FrozenInstanceError):
        fill.price = 43.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        fill.quantity = 2.0  # type: ignore[misc]


def test_bar_event_payload_fields_are_frozen() -> None:
    # M5-02: immutability covers the bars field AND the Bar struct inside it.
    bar = _bar()
    with pytest.raises(FrozenInstanceError):
        bar.bars = {}  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        bar.bars["BTCUSDT"].close = Decimal("99")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (b) Required linkage IDs (D-12): malformed construction is a TypeError
# ---------------------------------------------------------------------------

def test_order_event_requires_order_id() -> None:
    with pytest.raises(TypeError):
        OrderEvent(  # type: ignore[call-arg]
            time=_TIME, ticker="BTCUSDT", action=Side.BUY, price=42.0,
            quantity=1.0, exchange="default", strategy_id=_STRATEGY_ID,
            portfolio_id=1, order_type=OrderType.MARKET,
        )


def test_fill_event_requires_fill_id() -> None:
    with pytest.raises(TypeError):
        FillEvent(  # type: ignore[call-arg]
            time=_TIME, status=FillStatus.EXECUTED, ticker="BTCUSDT",
            action=Side.BUY, price=42.0, quantity=1.0, commission=0.1,
            portfolio_id=1, order_id=_ORDER_ID, strategy_id=_STRATEGY_ID,
        )


def test_fill_event_requires_order_id() -> None:
    with pytest.raises(TypeError):
        FillEvent(  # type: ignore[call-arg]
            time=_TIME, status=FillStatus.EXECUTED, ticker="BTCUSDT",
            action=Side.BUY, price=42.0, quantity=1.0, commission=0.1,
            portfolio_id=1, fill_id=uuid_compat.uuid7(),
            strategy_id=_STRATEGY_ID,
        )


# ---------------------------------------------------------------------------
# (c) event_id: version-7 stdlib uuid.UUID, unique per construction (D-01)
# ---------------------------------------------------------------------------

def test_event_id_is_uuid7_and_unique() -> None:
    first = _time_event()
    second = _time_event()
    assert type(first.event_id) is uuid.UUID
    assert first.event_id.version == 7
    assert second.event_id.version == 7
    assert first.event_id != second.event_id


# ---------------------------------------------------------------------------
# (d) created_at defaults to business time (D-02)
# ---------------------------------------------------------------------------

def test_created_at_defaults_to_business_time() -> None:
    event = _time_event()
    assert event.created_at == event.time


def test_created_at_explicit_value_is_preserved() -> None:
    explicit = datetime(2024, 6, 1)
    event = TimeEvent(time=_TIME, created_at=explicit)
    assert event.created_at == explicit


# ---------------------------------------------------------------------------
# (e) type is a real field holding the correct EventType member per class
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("factory", "expected_type"),
    [
        pytest.param(_time_event, EventType.TIME, id="TimeEvent"),
        pytest.param(_bar, EventType.BAR, id="BarEvent"),
        pytest.param(_signal, EventType.SIGNAL, id="SignalEvent"),
        pytest.param(_order, EventType.ORDER, id="OrderEvent"),
        pytest.param(_fill, EventType.FILL, id="FillEvent"),
        pytest.param(_update, EventType.UPDATE, id="PortfolioUpdateEvent"),
        pytest.param(_screener, EventType.SCREENER, id="ScreenerEvent"),
        pytest.param(_error, EventType.ERROR, id="ErrorEvent"),
        pytest.param(_portfolio_error, EventType.ERROR, id="PortfolioErrorEvent"),
    ],
)
def test_type_is_real_field_with_correct_member(
    factory: Callable[[], Event], expected_type: EventType
) -> None:
    event = factory()
    assert event.type is expected_type
    # real field, not a bare class attribute: instance carries it via slots
    assert "type" in {f for f in Event.__slots__}


# ---------------------------------------------------------------------------
# (f) every concrete event is an Event
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("factory", _ALL_EVENTS)
def test_isinstance_event(factory: Callable[[], Event]) -> None:
    assert isinstance(factory(), Event)


# ---------------------------------------------------------------------------
# (g) ErrorEvent hierarchy (D-06)
# ---------------------------------------------------------------------------

def test_portfolio_error_event_is_an_error_event() -> None:
    event = _portfolio_error()
    assert isinstance(event, ErrorEvent)
    assert event.type is EventType.ERROR
    assert event.source == "portfolio"


def test_error_event_is_concrete_and_instantiable() -> None:
    event = _error()
    assert event.type is EventType.ERROR
    assert event.severity == "ERROR"


# ---------------------------------------------------------------------------
# (h) enum-typed action / order_type (D-05)
# ---------------------------------------------------------------------------

def test_signal_event_action_and_order_type_are_enums() -> None:
    signal = _signal()
    assert signal.action is Side.BUY
    assert signal.order_type is OrderType.MARKET


def test_order_and_fill_action_are_enums() -> None:
    assert _order().action is Side.BUY
    assert _fill().action is Side.BUY
