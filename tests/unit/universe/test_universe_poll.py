"""``UniverseHandler`` on_poll poll + add-side subscribe consumer (Plan 06-03 / 07-05).

The Arm-A poll seam: ``on_poll`` consumes the DEDICATED ``UniversePollEvent``
(``EventType.UNIVERSE_POLL``, WR-06 — NOT the shared TIME route), freeze-gates
(WR-05 — early-return while halted/paused), polls the injected
``UniverseSelectionModel``, filters the desired set through ``validate_symbol``
(D-06) BEFORE ``Universe.apply``, precision-resolves added symbols (WR-04), and
emits ONE ``UniverseUpdateEvent`` only when the applied delta is non-empty (no
empty-delta floods). ``on_universe_update`` implements the ADD branch:
warmup-BEFORE-subscribe per added symbol (Pitfall 6).

The behaviors asserted:
1. Unwired route is a no-op — no selection source → ``on_poll`` returns, queue empty.
2. Selection returning the CURRENT membership → empty delta → NOTHING on the queue.
3. Selection that ADDS a symbol → filter → apply → exactly ONE ``UniverseUpdateEvent``.
4. A symbol REJECTED by ``validate_symbol`` is dropped BEFORE apply (never a member).
5. ``on_universe_update`` ADD: ``feed.warmup`` THEN ``provider.subscribe`` in order.
6. ``on_universe_update`` tolerates ``provider is None`` — warmup runs, subscribe skipped.
7. A wired-True freeze gate short-circuits ``on_poll`` — no select, no apply, no event.
8. A freeze gate returning False behaves exactly like an unwired gate (apply + emit).
9. A poll-added symbol takes the resolver's venue precision (WR-04), and the default
   ladder when no resolver is wired (paper-correct).
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
from itrader.events_handler.events import SignalEvent, UniversePollEvent
from itrader.events_handler.events.universe import UniverseUpdateEvent
from itrader.universe.universe import Universe
from itrader.universe.universe_handler import UniverseHandler, UniverseHandlerConfig

pytestmark = pytest.mark.unit


_ASOF = datetime(2024, 1, 1, tzinfo=timezone.utc)


# --- fakes -----------------------------------------------------------------


class _FakeSelectionSource:
    """A selection source returning a configurable desired set."""

    def __init__(self, desired: set[str]) -> None:
        self._desired = desired

    def select(self, asof: datetime) -> set[str]:
        return set(self._desired)


class _FakeExchange:
    """A venue exposing BOTH ``validate_symbol`` (D-06) and ``resolve_precision``
    (VENUE-04/D-09) — the single object ``set_venue_metadata`` takes (RUN-06/D-11,
    the two former seams collapsed). ``rejected`` drives ``validate_symbol``;
    ``precision`` maps symbol -> venue ``Instrument`` for ``resolve_precision`` (a
    symbol absent from ``precision`` resolves to ``None`` -> the caller falls to the
    default ladder). Merges the former ``_FakeValidator`` + ``_FakeResolver``.
    """

    def __init__(
        self,
        *,
        rejected: set[str] | None = None,
        precision: dict[str, Instrument] | None = None,
    ) -> None:
        self._rejected = rejected or set()
        self._precision = precision or {}

    def validate_symbol(self, symbol: str) -> bool:
        return symbol not in self._rejected

    def resolve_precision(self, symbol: str) -> Instrument | None:
        return self._precision.get(symbol)


class _RecordingFeed:
    """Records ``warmup``/``absorb_warmup`` calls into a shared ordered call log."""

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def warmup(self, symbol: str, timeframe: str, depth: int | None = None) -> None:
        self._log.append(("warmup", symbol))

    def absorb_warmup(self, symbol: str, timeframe: str, bars: object) -> None:
        self._log.append(("absorb", symbol))

    def cache_capacity(self) -> int:
        return 100


class _RecordingProvider:
    """Records ``spawn_warmup``/``subscribe`` calls into a shared ordered call log."""

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        self._log.append(("spawn", symbol))

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
        bus=Queue(),
        universe=universe,
        feed=feed if feed is not None else _RecordingFeed([]),
        config=UniverseHandlerConfig(poll_timeframe="1d"),
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
        bus=Queue(),
        universe=universe,
        feed=_RecordingFeed([]),
        config=UniverseHandlerConfig(
            poll_timeframe="1d", remove_policy=remove_policy
        ),
    )
    if read_model is not None:
        handler.set_portfolio_read_model(read_model)
    if provider is not None:
        handler.set_provider(provider)
    return handler


# --- behaviors -------------------------------------------------------------


def test_on_poll_no_source_is_a_noop() -> None:
    """1. Unwired route (no selection source) returns immediately; queue stays empty."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.on_poll(UniversePollEvent(time=_ASOF))
    assert handler._bus.empty()
    assert universe.members == ["BTC/USDC"]


def test_on_poll_current_membership_puts_nothing() -> None:
    """2. Selection == current membership → empty delta → NOTHING on the queue."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC"}))
    handler.on_poll(UniversePollEvent(time=_ASOF))
    assert handler._bus.empty()


def test_on_poll_add_emits_one_update_event() -> None:
    """3. Selection adds a symbol → apply → exactly one UniverseUpdateEvent(added)."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))
    handler.set_venue_metadata(_FakeExchange())

    handler.on_poll(UniversePollEvent(time=_ASOF))

    event = _drain_one(handler._bus)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)
    assert event.removed == ()
    assert set(universe.members) == {"BTC/USDC", "ETH/USDC"}


def test_on_poll_rejected_symbol_dropped_before_apply() -> None:
    """4. A validate_symbol-rejected symbol never reaches the universe."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(
        _FakeSelectionSource({"BTC/USDC", "ETH/USDC", "FAKE/USDC"})
    )
    handler.set_venue_metadata(_FakeExchange(rejected={"FAKE/USDC"}))

    handler.on_poll(UniversePollEvent(time=_ASOF))

    event = _drain_one(handler._bus)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)
    assert "FAKE/USDC" not in universe.members
    assert set(universe.members) == {"BTC/USDC", "ETH/USDC"}


# --- CR-02 FAILED-retry on the next poll -----------------------------------


def test_on_poll_retries_failed_member_flips_pending_and_readds() -> None:
    """CR-02(a): a FAILED member is re-warmed on the next poll — even when the
    membership delta is EMPTY (desired == current). on_poll flips it back to
    PENDING (so the WR-02 gate keeps it dark until the re-warm lands) and folds
    it into the emitted UniverseUpdateEvent.added so it rides the same warmup
    trigger a genuinely-new add uses."""
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})  # ETH added, PENDING
    universe.mark_failed("ETH/USDC")          # its warmup backfill failed once
    handler = _handler(universe)
    # Selection returns the CURRENT membership — an EMPTY apply delta.
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))
    handler.set_venue_metadata(_FakeExchange())

    handler.on_poll(UniversePollEvent(time=_ASOF))

    # Despite the empty apply delta, ONE UniverseUpdateEvent re-drives ETH's warmup.
    event = _drain_one(handler._bus)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)
    assert event.removed == ()
    # Readiness returned to PENDING (no longer FAILED) — still not tradeable yet.
    assert universe.is_ready("ETH/USDC") is False
    assert universe.failed_symbols() == set()


def test_on_poll_failed_retry_then_rewarm_marks_ready() -> None:
    """CR-02(b): after the retry re-drives warmup, a successful re-warm marks the
    symbol READY. Uses the paper path (no provider): on_universe_update runs the
    synchronous feed.warmup + immediate mark_ready for the re-added symbol."""
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})  # ETH added, PENDING
    universe.mark_failed("ETH/USDC")
    handler = _handler(universe, feed=_RecordingFeed(log))  # NO provider (paper)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))
    handler.set_venue_metadata(_FakeExchange())

    handler.on_poll(UniversePollEvent(time=_ASOF))
    event = _drain_one(handler._bus)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)

    # Route the emitted event through the add consumer (paper: warmup + mark_ready).
    handler.on_universe_update(event)

    assert log == [("warmup", "ETH/USDC")]
    assert universe.is_ready("ETH/USDC") is True   # re-warm succeeded → READY


def test_on_poll_static_ready_universe_never_retries_oracle_inert() -> None:
    """CR-02(c): a static, all-READY universe (the backtest oracle shape) triggers
    NO FAILED retry — the empty-delta fast path stays silent, nothing is queued,
    and no readiness is disturbed. Guards the oracle-inertness of the retry path."""
    universe = _universe("BTC/USDC", "ETH/USDC")  # both READY at construction
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))
    handler.set_venue_metadata(_FakeExchange())

    handler.on_poll(UniversePollEvent(time=_ASOF))

    # No FAILED members → no retry → empty-delta fast path → nothing queued.
    assert handler._bus.empty()
    assert universe.is_ready("BTC/USDC") is True
    assert universe.is_ready("ETH/USDC") is True


# --- freeze gate (WR-05 / D-07 freeze-in-place) ----------------------------


class _SpySelectionSource:
    """A selection source that records whether ``select`` was called (freeze spy)."""

    def __init__(self, desired: set[str]) -> None:
        self._desired = desired
        self.select_calls = 0

    def select(self, asof: datetime) -> set[str]:
        self.select_calls += 1
        return set(self._desired)


def test_on_poll_freeze_gate_true_short_circuits() -> None:
    """7. A wired-True freeze gate skips the poll: no select, no apply, no event."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    spy = _SpySelectionSource({"BTC/USDC", "ETH/USDC"})
    handler.set_selection_source(spy)
    handler.set_venue_metadata(_FakeExchange())
    handler.set_freeze_gate(lambda: True)

    handler.on_poll(UniversePollEvent(time=_ASOF))

    # Membership frozen in place — no select consulted, no apply, nothing queued.
    assert spy.select_calls == 0
    assert handler._bus.empty()
    assert universe.members == ["BTC/USDC"]


def test_on_poll_freeze_gate_false_behaves_as_unwired() -> None:
    """8. A freeze gate returning False behaves exactly like the prior on_time."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))
    handler.set_venue_metadata(_FakeExchange())
    handler.set_freeze_gate(lambda: False)

    handler.on_poll(UniversePollEvent(time=_ASOF))

    event = _drain_one(handler._bus)
    assert isinstance(event, UniverseUpdateEvent)
    assert event.added == ("ETH/USDC",)
    assert set(universe.members) == {"BTC/USDC", "ETH/USDC"}


# --- precision resolver (WR-04 / D-16 venue precision) ---------------------


def _venue_inst(symbol: str) -> Instrument:
    """A venue-precision Instrument with NON-default scales (3dp / 4dp)."""
    return Instrument(
        symbol=symbol,
        price_precision=Decimal("0.001"),
        quantity_precision=Decimal("0.0001"),
        maintenance_margin_rate=Decimal("0.01"),
        max_leverage=Decimal("3"),
    )


def test_on_poll_added_symbol_takes_resolver_precision() -> None:
    """9a. A wired resolver gives a poll-added symbol venue precision (not 2dp/8dp)."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))
    handler.set_venue_metadata(
        _FakeExchange(precision={"ETH/USDC": _venue_inst("ETH/USDC")})
    )

    handler.on_poll(UniversePollEvent(time=_ASOF))

    inst = universe.instrument("ETH/USDC")
    assert inst.price_precision == Decimal("0.001")  # resolver, not 2dp default
    assert inst.quantity_precision == Decimal("0.0001")  # not 8dp default


def test_on_poll_added_symbol_no_resolver_uses_default_ladder() -> None:
    """9b. With NO resolver wired (paper), an added symbol lands on the default ladder."""
    universe = _universe("BTC/USDC")
    handler = _handler(universe)
    handler.set_selection_source(_FakeSelectionSource({"BTC/USDC", "ETH/USDC"}))
    # No venue metadata wired (paper) -> no resolver -> Universe.apply default ladder.

    handler.on_poll(UniversePollEvent(time=_ASOF))

    inst = universe.instrument("ETH/USDC")
    assert inst.price_precision == Decimal("0.01")  # _DEFAULT_PRICE_SCALE (2dp)
    assert inst.quantity_precision == Decimal("0.00000001")  # _DEFAULT_QUANTITY_SCALE (8dp)


def test_on_universe_update_add_spawns_warmup_no_subscribe() -> None:
    """5. ADD branch (live): spawn_warmup per symbol, NO synchronous subscribe (D-03b).

    Subscribe now moves to ``on_bars_loaded`` (after the ring is warmed); the add
    branch only kicks off the async warmup fetch.
    """
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC", "SOL/USDC"})  # ETH, SOL pending
    handler = _handler(universe, feed=_RecordingFeed(log))
    handler.set_provider(_RecordingProvider(log))

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=("ETH/USDC", "SOL/USDC"), removed=())
    )

    # spawn only — no subscribe on the add branch.
    assert log == [("spawn", "ETH/USDC"), ("spawn", "SOL/USDC")]


def test_on_universe_update_provider_none_synchronous_paper_warmup() -> None:
    """6. provider is None → synchronous feed.warmup + immediate READY (WARNING 1).

    The no-provider paper path absorbs warmup synchronously and marks the symbol
    READY at once — a poll-added paper symbol is NEVER left PENDING.
    """
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})  # ETH pending
    handler = _handler(universe, feed=_RecordingFeed(log))
    # No provider set.

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=("ETH/USDC",), removed=())
    )

    assert log == [("warmup", "ETH/USDC")]
    assert universe.is_ready("ETH/USDC")  # never left PENDING


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
    event = handler._bus.get_nowait()
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
