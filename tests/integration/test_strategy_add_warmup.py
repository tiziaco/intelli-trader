"""D-10 `add` end-to-end — cold symbol registers DARK, warms via the P7 pipeline, trades.

Drives the STRAT-02 ``add`` verb through a fully-wired OFFLINE paper system (no OKX/network):
``add`` of a strategy on a COLD symbol registers the instance but leaves it DARK (the WR-02
gate, ``is_ready`` False) and emits a ``UniversePollEvent``; the poll re-derives membership
FROM the registered strategies (``StrategyDerivedSelectionModel``), so the new symbol enters
the universe and the EXISTING P7 warmup pipeline kicks off (``_begin_warmup`` ->
``spawn_warmup``). The warmup completion (``BarsLoaded``) then flows through the REAL D-03b
consumers — ``StrategiesHandler.on_bars_loaded`` warms the indicators, ``UniverseHandler``
``mark_ready`` + subscribe — after which the strategy flips READY and produces a signal on the
next on-grid bar. A ``BarsLoadFailed`` leaves the instance dark and REGISTERED (retried next
poll), never dropped.

There is NO second warmup path: the add verb only registers + persists + emits the poll; all
warming is the existing pipeline (D-10).

CI-safe: offline, SQLite registry, no network. NO ``__init__.py`` in this dir.
4-space indentation (matches ``tests/integration/*``).
"""

import datetime as _dt
from decimal import Decimal

import pytest

from itrader.core.bar import Bar
from itrader.core.enums import EventType
from itrader.core.instrument import Instrument
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.events_handler.events import (
    BarEvent,
    BarsLoaded,
    BarsLoadFailed,
    SignalEvent,
    StrategyCommandEvent,
)
from itrader.storage import SqlEngine
from itrader.config.sql import SqlSettings
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA
from itrader.strategy_handler.registry import encode_strategy_config
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.universe.membership import StrategyDerivedSelectionModel
from itrader.universe.universe import Universe
from itrader.universe.universe_handler import UniverseHandler, UniverseHandlerConfig
from tests.support.replay_harness import build_paper_replay_system
from tests.support.schema import provision_schema

pytestmark = pytest.mark.integration

_COLD = "CCCUSD"
_WARMUP = 3
_T = _dt.datetime(2024, 1, 10, tzinfo=_dt.timezone.utc)


class _AddProbe(Strategy):
    """SMA(3) probe: DARK until warmed, then BUYs every bar (deterministic signal)."""

    sizing_policy = FractionOfCash(Decimal("0.5"))

    def init(self) -> None:
        self.sma = self.indicator(SMA, "close", _WARMUP)

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        return self.buy(ticker)


def _catalog():
    return {"_AddProbe": _AddProbe}


def _bar(price: float, *, day: int) -> Bar:
    return Bar(
        time=_dt.datetime(2024, 1, day, tzinfo=_dt.timezone.utc),
        open=Decimal(str(price)), high=Decimal(str(price)),
        low=Decimal(str(price)), close=Decimal(str(price)), volume=Decimal("1"))


class _WarmProvider:
    """A provider whose ``spawn_warmup`` is a no-op — warmup lands via a driven BarsLoaded.

    Wiring a provider (not None) routes ``_begin_warmup`` down the LIVE arm
    (``spawn_warmup`` -> later ``BarsLoaded``) instead of the paper synchronous
    ``feed.warmup`` + immediate ``mark_ready`` — so the symbol stays DARK/PENDING until the
    test delivers the warmup payload, letting us assert the register-dark step first.
    """

    def __init__(self) -> None:
        self.spawned: list[str] = []
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    def spawn_warmup(self, symbol: str, timeframe, depth: int) -> None:
        self.spawned.append(symbol)

    def subscribe(self, symbol: str) -> None:
        self.subscribed.append(symbol)

    def unsubscribe(self, symbol: str) -> None:
        self.unsubscribed.append(symbol)


class _AddHarness:
    def __init__(self):
        self.store = StrategyRegistryStore(SqlEngine(SqlSettings.default()))
        provision_schema(self.store.backend)
        system, _ = build_paper_replay_system()
        self.system = system
        # Size the feed ring to the strategy warmup (what register_strategy_warmup does on
        # the real live path) so the F-1 warmability gate admits the SMA(3) probe — an
        # unsized ring holds only the newest-bar floor (1) and would (correctly) reject it.
        from itrader.price_handler.feed.cache_registration import StrategyWarmupConsumer
        system.feed.register_raw_bar_consumer(
            StrategyWarmupConsumer(required_history_depth=100))

        instrument = Instrument(
            symbol=_COLD,
            price_precision=Decimal("0.01"),
            quantity_precision=Decimal("0.00000001"),
            maintenance_margin_rate=Decimal("0.005"),
            max_leverage=Decimal("1"))
        # Start EMPTY — the poll adds _COLD once the add verb registers a strategy on it.
        self.universe = Universe(members=[], instrument_map={_COLD: instrument})
        self.portfolio_id = system.portfolio_handler.add_portfolio(
            name="add_pf", exchange="simulated", cash=1_000_000)

        sh: StrategiesHandler = system.strategies_handler
        sh.strategy_catalog = _catalog()
        sh.registry_store = self.store
        sh.portfolio_read_model = system.portfolio_handler
        sh.set_universe(self.universe)
        self.sh = sh

        self.provider = _WarmProvider()
        self.universe_handler = UniverseHandler(
            bus=system.global_queue,
            universe=self.universe,
            feed=system.feed,
            config=UniverseHandlerConfig(poll_timeframe="1d", remove_policy="force-close"))
        self.universe_handler.set_portfolio_read_model(system.portfolio_handler)
        self.universe_handler.set_provider(self.provider)
        self.universe_handler.set_selection_source(StrategyDerivedSelectionModel(sh))

        routes = system.event_handler.routes
        routes[EventType.UNIVERSE_POLL] = [self.universe_handler.on_poll]
        routes[EventType.UNIVERSE_UPDATE] = [self.universe_handler.on_universe_update]
        routes[EventType.BARS_LOADED] = [
            sh.on_bars_loaded, self.universe_handler.on_bars_loaded]
        routes[EventType.BARS_LOAD_FAILED] = [self.universe_handler.on_bars_load_failed]

    def dispose(self) -> None:
        self.store.dispose()

    def add(self) -> None:
        built = _AddProbe(timeframe="1d", tickers=[_COLD], name="add_probe")
        config = encode_strategy_config(built)
        # Carry the portfolio subscription alongside the config blob — the add verb strips
        # portfolio_id out of the blob before build_strategy and wires the subscription, so
        # the warmed strategy fans its signal out to a real portfolio.
        config["portfolio_id"] = str(self.portfolio_id)
        self.sh.on_strategy_command(StrategyCommandEvent.add(
            strategy_name="add_probe", strategy_type="_AddProbe", config=config, time=_T))
        self.system.event_handler.process_events()

    def strategy(self):
        return next((s for s in self.sh.strategies if s.name == "add_probe"), None)

    def deliver_warmup(self) -> None:
        bars = tuple(_bar(100 + i, day=i + 1) for i in range(_WARMUP))
        self.system.global_queue.put(
            BarsLoaded(time=_T, symbol=_COLD, timeframe="1d", bars=bars))
        self.system.event_handler.process_events()

    def fail_warmup(self) -> None:
        self.system.global_queue.put(
            BarsLoadFailed(time=_T, symbol=_COLD, reason="backfill_timeout"))
        self.system.event_handler.process_events()

    def _drain(self):
        bus = self.system.global_queue
        raw = getattr(bus, "_pq", bus)
        snapshot = list(getattr(raw, "queue", []))
        return [item[2] if isinstance(item, tuple) else item for item in snapshot]

    def calculate_signals_for(self, day: int):
        bar = _bar(200, day=day)
        self.sh.calculate_signals(BarEvent(time=bar.time, bars={_COLD: bar}))
        return [e for e in self._drain() if isinstance(e, SignalEvent)]


@pytest.fixture()
def harness():
    h = _AddHarness()
    try:
        yield h
    finally:
        h.dispose()


def test_add_registers_dark_then_warms_then_trades(harness):
    """D-10 — cold add is registered but DARK; BarsLoaded warms it; then it signals."""
    harness.add()

    # Registered but DARK immediately (WR-02): no indicator bars yet, the poll spawned
    # warmup but the symbol stays PENDING; no signal is possible.
    strategy = harness.strategy()
    assert strategy is not None
    assert strategy.is_ready(_COLD) is False
    assert harness.universe.is_ready(_COLD) is False
    assert _COLD in harness.provider.spawned  # the P7 warmup pipeline kicked off
    assert harness.store.get("add_probe") is not None

    # Deliver the warmup payload through the EXISTING pipeline (BarsLoaded -> on_bars_loaded
    # warms the indicators, UniverseHandler mark_ready + subscribe).
    harness.deliver_warmup()
    assert strategy.is_ready(_COLD) is True
    assert harness.universe.is_ready(_COLD) is True

    # Now READY -> the next on-grid bar produces a signal.
    signals = harness.calculate_signals_for(day=20)
    assert len(signals) >= 1
    assert signals[0].ticker == _COLD


def test_bars_load_failed_leaves_the_strategy_dark_and_registered(harness):
    """D-10 — a BarsLoadFailed marks FAILED (retried next poll); the instance is not dropped."""
    harness.add()
    assert harness.strategy() is not None

    harness.fail_warmup()

    # FAILED -> still dark, still registered (the CR-02 retry re-warms it next poll).
    assert harness.universe.is_ready(_COLD) is False
    assert harness.strategy() is not None
    assert harness.store.get("add_probe") is not None
