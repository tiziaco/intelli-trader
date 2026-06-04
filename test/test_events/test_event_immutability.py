"""M2-03 (Pattern F): genuinely-immutable hot-path events are frozen.

Behavioral contract:
- ``SignalEvent`` stays MUTABLE — ``verified`` is assigned after construction by the
  order validator (event.py order-validation seam) and ``quantity`` is rewritten by the
  order manager; freezing it would raise ``FrozenInstanceError`` (Pitfall 4, M3 #11 blocker).
- ``FillEvent`` stays MUTABLE — ``price``/``quantity`` are rewritten post-construction by
  the simulated exchange after fee/slippage application.
- The remaining hot-path events (PingEvent, BarEvent, PortfolioUpdateEvent, ScreenerEvent,
  OrderEvent) are genuinely immutable and MUST be frozen: reassigning a field raises
  ``FrozenInstanceError``.
"""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from itrader.events_handler.event import (
    BarEvent,
    FillEvent,
    OrderEvent,
    PingEvent,
    PortfolioUpdateEvent,
    ScreenerEvent,
    SignalEvent,
)
from itrader.core.enums import OrderType


_TIME = datetime(2024, 1, 1)


def _signal():
    return SignalEvent(
        _TIME, "MARKET", "BTCUSDT", "BUY", 42.0, 1.0, 41.0, 45.0,
        "strat", "pf", {},
    )


def test_signal_event_verified_stays_mutable():
    """SignalEvent.verified must remain assignable post-construction (Pitfall 4)."""
    signal = _signal()
    signal.verified = True  # must NOT raise
    assert signal.verified is True


def test_signal_event_quantity_stays_mutable():
    """SignalEvent.quantity is rewritten by the order manager — must stay mutable."""
    signal = _signal()
    signal.quantity = 2.5  # must NOT raise
    assert signal.quantity == 2.5


def test_fill_event_stays_mutable():
    """FillEvent.price/quantity are rewritten by the simulated exchange — stay mutable."""
    order = OrderEvent(
        _TIME, "BTCUSDT", "BUY", 42.0, 1.0, "default", "strat", "pf",
        OrderType.MARKET,
    )
    fill = FillEvent.new_fill("EXECUTED", 1.5, order)
    fill.price = 43.0  # must NOT raise
    fill.quantity = 2.0  # must NOT raise
    assert fill.price == 43.0
    assert fill.quantity == 2.0


def test_ping_event_is_frozen():
    ping = PingEvent(_TIME)
    with pytest.raises(FrozenInstanceError):
        ping.time = datetime(2025, 1, 1)


def test_bar_event_is_frozen():
    bar = BarEvent(_TIME, {})
    with pytest.raises(FrozenInstanceError):
        bar.time = datetime(2025, 1, 1)


def test_portfolio_update_event_is_frozen():
    update = PortfolioUpdateEvent(_TIME, {})
    with pytest.raises(FrozenInstanceError):
        update.time = datetime(2025, 1, 1)


def test_screener_event_is_frozen():
    screener = ScreenerEvent(_TIME, "sid", "name", [], [])
    with pytest.raises(FrozenInstanceError):
        screener.screener_id = "other"


def test_order_event_is_frozen():
    order = OrderEvent(
        _TIME, "BTCUSDT", "BUY", 42.0, 1.0, "default", "strat", "pf",
        OrderType.MARKET,
    )
    with pytest.raises(FrozenInstanceError):
        order.price = 99.0
