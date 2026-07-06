"""``UniverseHandler`` on_time poll + add-side subscribe consumer (Plan 06-03 Task 2).

The Arm-A poll seam: ``on_time`` polls the injected ``UniverseSelectionModel``,
filters the desired set through ``validate_symbol`` (D-06) BEFORE ``Universe.apply``,
and emits ONE ``UniverseUpdateEvent`` only when the applied delta is non-empty
(no empty-delta floods). ``on_universe_update`` implements the ADD branch:
warmup-BEFORE-subscribe per added symbol (Pitfall 6).

The six behaviors asserted:
1. Unwired route is a no-op — no selection source → ``on_time`` returns, queue empty.
2. Selection returning the CURRENT membership → empty delta → NOTHING on the queue.
3. Selection that ADDS a symbol → filter → apply → exactly ONE ``UniverseUpdateEvent``.
4. A symbol REJECTED by ``validate_symbol`` is dropped BEFORE apply (never a member).
5. ``on_universe_update`` ADD: ``feed.warmup`` THEN ``provider.subscribe`` in order.
6. ``on_universe_update`` tolerates ``provider is None`` — warmup runs, subscribe skipped.
"""

from datetime import datetime, timezone
from decimal import Decimal
from queue import Empty, Queue

import pytest

from itrader.core.instrument import Instrument
from itrader.events_handler.events.market import TimeEvent, UniverseUpdateEvent
from itrader.universe.universe import Universe
from itrader.universe.universe_handler import UniverseHandler

pytestmark = pytest.mark.unit


_ASOF = datetime(2024, 1, 1, tzinfo=timezone.utc)


# --- fakes -----------------------------------------------------------------


class _FakeSelectionSource:
    """A selection source returning a configurable desired set."""

    def __init__(self, desired: set[str]) -> None:
        self._desired = desired

    def select(self, asof: datetime) -> set[str]:
        return set(self._desired)


class _FakeValidator:
    """A ``validate_symbol`` that rejects a chosen symbol (D-06 venue bound)."""

    def __init__(self, rejected: set[str]) -> None:
        self._rejected = rejected

    def validate_symbol(self, symbol: str) -> bool:
        return symbol not in self._rejected


class _RecordingFeed:
    """Records ``warmup`` calls into a shared ordered call log."""

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def warmup(self, symbol: str, timeframe: str, depth: int | None = None) -> None:
        self._log.append(("warmup", symbol))


class _RecordingProvider:
    """Records ``subscribe`` calls into a shared ordered call log."""

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def subscribe(self, symbol: str) -> None:
        self._log.append(("subscribe", symbol))


# --- helpers ---------------------------------------------------------------


def _inst(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("1"),
    )


def _universe(*symbols: str) -> Universe:
    members = sorted(symbols)
    return Universe(members=members, instrument_map={s: _inst(s) for s in members})


def _handler(universe: Universe, feed: object | None = None) -> UniverseHandler:
    return UniverseHandler(
        global_queue=Queue(),
        universe=universe,
        feed=feed if feed is not None else _RecordingFeed([]),
        timeframe="1d",
    )


def _drain_one(q: "Queue[object]") -> object:
    event = q.get_nowait()
    with pytest.raises(Empty):
        q.get_nowait()
    return event


# --- behaviors -------------------------------------------------------------


def test_on_time_no_source_is_a_noop() -> None:
    """1. Unwired route (no selection source) returns immediately; queue stays empty."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.on_time(TimeEvent(time=_ASOF))
    assert handler._global_queue.empty()
    assert universe.members == ["BTC/USDC"]


def test_on_time_current_membership_puts_nothing() -> None:
    """2. Selection == current membership → empty delta → NOTHING on the queue."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC"}))
    handler.on_time(TimeEvent(time=_ASOF))
    assert handler._global_queue.empty()


def test_on_time_add_emits_one_update_event() -> None:
    """3. Selection adds a symbol → apply → exactly one UniverseUpdateEvent(added)."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))
    handler.set_symbol_validator(_FakeValidator(rejected=set()))

    handler.on_time(TimeEvent(time=_ASOF))

    event = _drain_one(handler._global_queue)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)
    assert event.removed == ()
    assert set(universe.members) == {"BTC/USDC", "ETH/USDC"}


def test_on_time_rejected_symbol_dropped_before_apply() -> None:
    """4. A validate_symbol-rejected symbol never reaches the universe."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(
        _FakeSelectionSource({"BTC/USDC", "ETH/USDC", "FAKE/USDC"})
    )
    handler.set_symbol_validator(_FakeValidator(rejected={"FAKE/USDC"}))

    handler.on_time(TimeEvent(time=_ASOF))

    event = _drain_one(handler._global_queue)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)
    assert "FAKE/USDC" not in universe.members
    assert set(universe.members) == {"BTC/USDC", "ETH/USDC"}


def test_on_universe_update_warmup_before_subscribe() -> None:
    """5. ADD branch: feed.warmup THEN provider.subscribe, in that order per symbol."""
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC")
    handler = _handler(universe, feed=_RecordingFeed(log))
    handler.set_provider(_RecordingProvider(log))

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=("ETH/USDC", "SOL/USDC"), removed=())
    )

    assert log == [
        ("warmup", "ETH/USDC"),
        ("subscribe", "ETH/USDC"),
        ("warmup", "SOL/USDC"),
        ("subscribe", "SOL/USDC"),
    ]


def test_on_universe_update_provider_none_tolerant() -> None:
    """6. provider is None → warmup runs, subscribe skipped (paper/replay tolerant)."""
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC")
    handler = _handler(universe, feed=_RecordingFeed(log))
    # No provider set.

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=("ETH/USDC",), removed=())
    )

    assert log == [("warmup", "ETH/USDC")]
