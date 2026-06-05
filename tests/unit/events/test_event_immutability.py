"""M2-03 (Pattern F): genuinely-immutable hot-path events are frozen.

Behavioral contract:
- ``SignalEvent`` stays structurally MUTABLE until the Plan 04-04 freeze, but no
  production code writes to it anymore (D-03/D-13: ``verified`` is deleted, the
  validator verdict is the typed ValidationResult + Order-entity state).
- ``FillEvent`` stays MUTABLE — ``price``/``quantity`` are rewritten post-construction by
  the simulated exchange after fee/slippage application.
- ``OrderEvent`` stays MUTABLE — ``price``/``quantity`` of a resting order are rewritten by
  ``MatchingEngine.modify`` (resting-order modify is real run-path behavior).
- The remaining hot-path events (TimeEvent, BarEvent, PortfolioUpdateEvent, ScreenerEvent)
  are genuinely immutable and MUST be frozen: reassigning a field raises
  ``FrozenInstanceError``.
"""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from itrader.events_handler.event import (
    BarEvent,
    FillEvent,
    OrderEvent,
    PortfolioUpdateEvent,
    ScreenerEvent,
    SignalEvent,
    TimeEvent,
)
from itrader.core.enums import OrderType


_TIME = datetime(2024, 1, 1)


def _signal():
    return SignalEvent(
        time=_TIME, order_type="MARKET", ticker="BTCUSDT", action="BUY",
        price=42.0, stop_loss=41.0, take_profit=45.0,
        strategy_id="strat", portfolio_id="pf", strategy_setting={},
        quantity=1.0,
    )


def test_signal_event_quantity_defaults_to_none():
    """Omitted quantity means 'order/risk layer sizes me' (D-10 — no 0 sentinel)."""
    signal = SignalEvent(
        time=_TIME, order_type="MARKET", ticker="BTCUSDT", action="BUY",
        price=42.0, stop_loss=41.0, take_profit=45.0,
        strategy_id="strat", portfolio_id="pf", strategy_setting={},
    )
    assert signal.quantity is None


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


def test_time_event_is_frozen():
    time_event = TimeEvent(_TIME)
    with pytest.raises(FrozenInstanceError):
        time_event.time = datetime(2025, 1, 1)


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


def test_order_event_stays_mutable():
    """OrderEvent.price/quantity are rewritten by MatchingEngine.modify — stay mutable."""
    order = OrderEvent(
        _TIME, "BTCUSDT", "BUY", 42.0, 1.0, "default", "strat", "pf",
        OrderType.MARKET,
    )
    order.price = 99.0  # must NOT raise (resting-order modify path)
    order.quantity = 3.0
    assert order.price == 99.0
    assert order.quantity == 3.0
