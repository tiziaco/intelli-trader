"""
Phase-7 universe / live control-plane event vocabulary (Plan 07-01).

Locks the four new frozen event structs (``BarsLoaded``, ``BarsLoadFailed``,
``UniversePollEvent``, ``StrategyCommandEvent``) as data — construct-complete
factories, frozen immutability, ``type`` pins, business ``time`` + auto
``event_id`` — plus the backtest-inertness half of the 3-step flow: every new
``EventType`` member has an explicit-empty ``_routes`` entry so ``_dispatch``
never raises ``NotImplementedError`` on one of them (T-07-01-DROP).
"""

import queue
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

# Pre-import the real enum module BEFORE the stubbed import below (same
# identity-preservation trick as test_dispatch_registry.py).
from itrader.core.enums import EventType  # noqa: E402
from itrader.events_handler.events import (
    BarsLoaded,
    BarsLoadFailed,
    StrategyCommandEvent,
    UniversePollEvent,
)

_STUB_MODULES = {
    name: MagicMock()
    for name in [
        "itrader.strategy_handler.strategies_handler",
        "itrader.screeners_handler.screeners_handler",
        "itrader.order_handler.order_handler",
        "itrader.portfolio_handler.portfolio_handler",
        "itrader.execution_handler.execution_handler",
    ]
}
with patch.dict(sys.modules, _STUB_MODULES):
    from itrader.events_handler.full_event_handler import EventHandler


_T = datetime(2024, 1, 1, tzinfo=UTC)

_NEW_TYPES = (
    EventType.UNIVERSE_POLL,
    EventType.STRATEGY_COMMAND,
    EventType.BARS_LOADED,
    EventType.BARS_LOAD_FAILED,
)


# --- Event structs asserted as data ----------------------------------------


def test_bars_loaded_type_and_fields():
    ev = BarsLoaded(time=_T, symbol="BTC/USDC", timeframe="1d", bars=())
    assert ev.type is EventType.BARS_LOADED
    assert ev.symbol == "BTC/USDC" and ev.timeframe == "1d" and ev.bars == ()
    assert ev.time == _T and ev.event_id is not None


def test_bars_load_failed_type_and_fields():
    ev = BarsLoadFailed(time=_T, symbol="BTC/USDC", reason="TimeoutError")
    assert ev.type is EventType.BARS_LOAD_FAILED
    assert ev.symbol == "BTC/USDC" and ev.reason == "TimeoutError"
    assert ev.time == _T and ev.event_id is not None


def test_universe_poll_is_payloadless_control_signal():
    ev = UniversePollEvent(time=_T)
    assert ev.type is EventType.UNIVERSE_POLL
    assert ev.time == _T and ev.event_id is not None


def test_strategy_command_add_ticker_factory():
    ev = StrategyCommandEvent.add_ticker("SMA_MACD", "ETH/USDC", time=_T)
    assert ev.type is EventType.STRATEGY_COMMAND
    assert ev.verb == "add_ticker" and ev.symbol == "ETH/USDC"
    assert ev.strategy_name == "SMA_MACD" and ev.time == _T


def test_strategy_command_remove_ticker_factory():
    ev = StrategyCommandEvent.remove_ticker("SMA_MACD", "ETH/USDC", time=_T)
    assert ev.verb == "remove_ticker" and ev.symbol == "ETH/USDC"


@pytest.mark.parametrize(
    "event",
    [
        BarsLoaded(time=_T, symbol="BTC/USDC", timeframe="1d", bars=()),
        BarsLoadFailed(time=_T, symbol="BTC/USDC", reason="TimeoutError"),
        UniversePollEvent(time=_T),
        StrategyCommandEvent.add_ticker("SMA_MACD", "ETH/USDC", time=_T),
    ],
)
def test_events_are_frozen(event):
    """Every new event is an immutable fact — mutation raises."""
    with pytest.raises((AttributeError, TypeError)):
        event.symbol = "MUTATED"  # type: ignore[misc]


# --- Backtest-inertness: explicit-empty routes (3-step flow closure) --------


@pytest.fixture
def handler():
    q = queue.Queue()
    h = EventHandler(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        MagicMock(), q,
    )
    yield h
    while not q.empty():
        q.get_nowait()


@pytest.mark.parametrize("event_type", _NEW_TYPES)
def test_new_types_have_explicit_empty_route(handler, event_type):
    """Each new EventType is a key in routes mapping to an empty list."""
    assert event_type in handler.routes
    assert handler.routes[event_type] == []


@pytest.mark.parametrize(
    "event",
    [
        UniversePollEvent(time=_T),
        BarsLoaded(time=_T, symbol="BTC/USDC", timeframe="1d", bars=()),
        BarsLoadFailed(time=_T, symbol="BTC/USDC", reason="TimeoutError"),
        StrategyCommandEvent.add_ticker("SMA_MACD", "ETH/USDC", time=_T),
    ],
)
def test_dispatching_new_event_is_inert_no_op(handler, event):
    """Dispatching a new event through a bare EventHandler never raises
    NotImplementedError — it is an inert no-op with no live consumer."""
    handler.global_queue.put(event)
    handler.process_events()  # must not raise
    assert handler.global_queue.empty()
