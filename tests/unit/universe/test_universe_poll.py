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
from uuid import uuid4

import pytest

from itrader.core.enums import PositionSide, Side
from itrader.core.ids import PortfolioId
from itrader.core.instrument import Instrument
from itrader.core.portfolio_read_model import PositionView
from itrader.events_handler.events import SignalEvent
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


class _RecordingProviderWithUnsub:
    """Records ``subscribe``/``unsubscribe`` calls into a shared call log."""

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def subscribe(self, symbol: str) -> None:
        self._log.append(("subscribe", symbol))

    def unsubscribe(self, symbol: str) -> None:
        self._log.append(("unsubscribe", symbol))


class _FakeReadModel:
    """A read model reporting per-(portfolio, ticker) open positions.

    ``holdings`` maps ticker -> {portfolio_id: PositionView}. ``get_position``
    and ``active_portfolio_ids`` compose the open-position truth the remove
    consumer / flat-detect read.
    """

    def __init__(self, holdings: dict[str, dict[PortfolioId, PositionView]]) -> None:
        self._holdings = holdings
        self._pids: set[PortfolioId] = set()
        for by_pid in holdings.values():
            self._pids.update(by_pid)

    def active_portfolio_ids(self) -> list[PortfolioId]:
        return list(self._pids)

    def get_position(self, portfolio_id: PortfolioId, ticker: str) -> PositionView | None:
        return self._holdings.get(ticker, {}).get(portfolio_id)

    def go_flat(self, ticker: str) -> None:
        """Simulate the position going flat (post-fill)."""
        self._holdings.pop(ticker, None)


class _FakeFill:
    """Minimal fill carrying a ticker for on_fill flat-detect."""

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker


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


def _pid() -> PortfolioId:
    return PortfolioId(uuid4())


def _long(ticker: str, pid: PortfolioId) -> tuple[str, dict[PortfolioId, PositionView]]:
    view = PositionView(
        ticker=ticker,
        side=PositionSide.LONG,
        net_quantity=Decimal("10"),
        avg_price=Decimal("40"),
    )
    return ticker, {pid: view}


def _remove_handler(
    universe: Universe,
    *,
    remove_policy: str = "orphan-and-track",
    read_model: object | None = None,
    provider: object | None = None,
) -> UniverseHandler:
    handler = UniverseHandler(
        global_queue=Queue(),
        universe=universe,
        feed=_RecordingFeed([]),
        timeframe="1d",
        remove_policy=remove_policy,
    )
    if read_model is not None:
        handler.set_portfolio_read_model(read_model)
    if provider is not None:
        handler.set_provider(provider)
    return handler


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


# --- remove-policy consumer + detach-on-flat (plan 06-04 Task 2) ------------


def test_remove_policy_defaults_to_orphan_and_track() -> None:
    """remove_policy defaults to 'orphan-and-track' when unset."""
    handler = _handler(_universe("BTC/USDC"))
    assert handler._remove_policy == "orphan-and-track"


def test_remove_orphan_with_open_position_defers_unsubscribe() -> None:
    """orphan-and-track REMOVE WITH an open position: mark_leaving, NO unsubscribe."""
    log: list[tuple[str, str]] = []
    pid = _pid()
    universe = _universe("BTC/USDC", "ETH/USDC")
    handler = _remove_handler(
        universe,
        read_model=_FakeReadModel(dict([_long("ETH/USDC", pid)])),
        provider=_RecordingProviderWithUnsub(log),
    )

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=(), removed=("ETH/USDC",))
    )

    # WS/ring kept alive — no unsubscribe; symbol marked leaving.
    assert log == []
    assert "ETH/USDC" in universe.leaving_symbols()


def test_remove_orphan_without_open_position_unsubscribes_now() -> None:
    """orphan-and-track REMOVE WITHOUT an open position: unsubscribe now, no mark_leaving."""
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC", "ETH/USDC")
    handler = _remove_handler(
        universe,
        read_model=_FakeReadModel({}),  # nobody holds ETH/USDC
        provider=_RecordingProviderWithUnsub(log),
    )

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=(), removed=("ETH/USDC",))
    )

    assert log == [("unsubscribe", "ETH/USDC")]
    assert "ETH/USDC" not in universe.leaving_symbols()


def test_remove_force_close_with_open_position_emits_exit_then_unsubscribes() -> None:
    """force-close REMOVE WITH an open position: emit a market-exit SignalEvent
    (opposite side, exit_fraction=1) for the holder, then unsubscribe."""
    log: list[tuple[str, str]] = []
    pid = _pid()
    universe = _universe("BTC/USDC", "ETH/USDC")
    handler = _remove_handler(
        universe,
        remove_policy="force-close",
        read_model=_FakeReadModel(dict([_long("ETH/USDC", pid)])),
        provider=_RecordingProviderWithUnsub(log),
    )

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=(), removed=("ETH/USDC",))
    )

    # A market-exit SignalEvent was emitted for the holding portfolio.
    event = handler._global_queue.get_nowait()
    assert isinstance(event, SignalEvent)
    assert event.ticker == "ETH/USDC"
    assert event.action is Side.SELL  # opposite of the open LONG
    assert event.exit_fraction == Decimal("1")
    assert event.portfolio_id == pid
    assert isinstance(event.price, Decimal)
    # Then detaches (unsubscribe), and the symbol is marked leaving.
    assert ("unsubscribe", "ETH/USDC") in log
    assert "ETH/USDC" in universe.leaving_symbols()


def test_on_fill_leaving_symbol_now_flat_detaches() -> None:
    """on_fill for a leaving symbol that is now flat: unsubscribe + clear_leaving."""
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC", "ETH/USDC")
    read_model = _FakeReadModel({})  # ETH/USDC is now flat
    handler = _remove_handler(
        universe,
        read_model=read_model,
        provider=_RecordingProviderWithUnsub(log),
    )
    universe.mark_leaving("ETH/USDC")

    handler.on_fill(_FakeFill("ETH/USDC"))

    assert log == [("unsubscribe", "ETH/USDC")]
    assert "ETH/USDC" not in universe.leaving_symbols()


def test_on_fill_non_leaving_or_still_holding_is_noop() -> None:
    """on_fill for a non-leaving symbol, or a leaving symbol still held: no-op."""
    log: list[tuple[str, str]] = []
    pid = _pid()
    universe = _universe("BTC/USDC", "ETH/USDC")
    read_model = _FakeReadModel(dict([_long("ETH/USDC", pid)]))  # still holding
    handler = _remove_handler(
        universe,
        read_model=read_model,
        provider=_RecordingProviderWithUnsub(log),
    )
    universe.mark_leaving("ETH/USDC")

    # Non-leaving symbol → no-op.
    handler.on_fill(_FakeFill("BTC/USDC"))
    # Leaving symbol still holding an open position → no detach.
    handler.on_fill(_FakeFill("ETH/USDC"))

    assert log == []
    assert "ETH/USDC" in universe.leaving_symbols()
