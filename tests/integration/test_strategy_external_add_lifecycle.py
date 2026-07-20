"""D-22 — the FastAPI stand-in: external add -> warm -> trade -> restart -> resume.

**Why this file exists (D-22, P9 D-23 precedent).** LR-01 defers the FastAPI layer out of
this milestone, so the operator command surface — the whole reason STRAT-02 and STRAT-03
exist — would otherwise ship with NO end-to-end exercise: an API nobody has ever driven the
way FastAPI will. P9 set the precedent verbatim ("P9's own tests must drive the external
``CONFIG_UPDATE`` path directly so it isn't untested surface"); D-22 adopts it for P10. This
test drives every verb through ``LiveTradingSystem.add_event`` — the exact public ingress
FastAPI will call — so the D-10 fail-closed allowlist, the ``LiveRouteRegistrar`` dispatch,
the queue, and the ``StrategiesHandler`` command consumer are ALL in the assertion path. A
test that shortcut straight to that handler method would prove nothing about that road.

**D-21 — the empty registry is the valid first-start state.** Every lifecycle here begins
from an EMPTY ``strategy_registry``: the engine boots, registers zero strategies, and waits
for the external ``add``. No seed mechanism is exercised because none exists — from the
``add`` onward, the STORE is the source of truth for what trades, across a full restart.

**The restart leg seeds NOTHING by hand (RESEARCH Item 2 / D-02).** The only row the rebuild
rehydrates is the one the ``add`` verb itself wrote. Hand-adding the same instance alongside a
rehydrate would trip the D-02 duplicate-name loud reject — so the restart rebuilds from the DB
ONLY.

Substrate: the shared session testcontainers Postgres via ``pg_database_env`` — the ONLY path
that reaches ``build_live_system``'s construction-time rehydrate gate (the SQLite ``default()``
spine is not selectable through the factory; the credential probe forces Postgres when a spine
exists). SKIPS Dockerless (D-11). Offline replay data provider — no OKX, no network.

4-space indentation (matches ``tests/integration/*``). NO ``__init__.py`` in this dir.
"""

import datetime as _dt
from decimal import Decimal
from typing import Any

import pytest

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.core.bar import Bar
from itrader.core.instrument import Instrument
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.events_handler.error_policy import FailFastPolicy
from itrader.events_handler.events import (
    BarEvent,
    BarsLoaded,
    SignalEvent,
    StrategyCommandEvent,
)
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.price_handler.feed.cache_registration import StrategyWarmupConsumer
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA
from itrader.strategy_handler.registry import encode_strategy_config
from itrader.trading_system.live_trading_system import build_live_system
from itrader.trading_system.route_registrar import LiveRouteRegistrar
from itrader.trading_system.venue_spec import build_venue_spec
from itrader.universe.membership import StrategyDerivedSelectionModel
from itrader.universe.universe import Universe
from itrader.universe.universe_handler import UniverseHandler, UniverseHandlerConfig
from tests.support.replay_harness import TestDataPlugin
from tests.support.schema import provision_schema

_SYM = "LIFEUSD"
_WARMUP = 3
_NAME = "ext1"
_T = _dt.datetime(2024, 1, 10, tzinfo=_dt.timezone.utc)


class _LifecycleProbe(Strategy):
    """SMA(3) probe: DARK until warmed, then BUYs every bar (deterministic signal).

    Round-trips through the D-04 codec on the declared base surface
    (``timeframe``/``tickers``/``sizing_policy``/``max_positions``), so an ``add`` persists it
    and a restart rehydrates the SAME instance from ``store x catalog``.
    """

    sizing_policy = FractionOfCash(Decimal("0.5"))

    def init(self) -> None:
        self.sma = self.indicator(SMA, "close", _WARMUP)

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        return self.buy(ticker)


def _catalog() -> dict[str, type]:
    """The injected D-01 allowlist — the shape a production app supplies.

    Keyed on ``cls.__name__`` (the key ``encode_strategy_config`` stamps as ``strategy_type``
    and the registry column stores). The SAME catalog is injected on both boots, so rehydrate
    resolves the probe class on restart exactly as the ``add`` verb did on first boot.
    """
    return {"_LifecycleProbe": _LifecycleProbe}


class _WarmProvider:
    """A provider whose ``spawn_warmup`` is a no-op — warmup lands via a driven ``BarsLoaded``.

    Mirrors ``test_strategy_add_warmup``'s ``_WarmProvider``: wiring a provider (not None)
    routes ``_begin_warmup`` down the live arm (``spawn_warmup`` -> later ``BarsLoaded``) so
    the symbol stays DARK/PENDING until the test delivers the warmup payload — letting the test
    assert the register-dark step (WR-02) BEFORE it warms.
    """

    def __init__(self) -> None:
        self.spawned: list[str] = []
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    def spawn_warmup(self, symbol: str, timeframe: Any, depth: int) -> None:
        self.spawned.append(symbol)

    def subscribe(self, symbol: str) -> None:
        self.subscribed.append(symbol)

    def unsubscribe(self, symbol: str) -> None:
        self.unsubscribed.append(symbol)


def _instrument() -> Instrument:
    return Instrument(
        symbol=_SYM,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("1"))


def _bar(price: float, *, day: int) -> Bar:
    return Bar(
        time=_dt.datetime(2024, 1, day, tzinfo=_dt.timezone.utc),
        open=Decimal(str(price)), high=Decimal(str(price)),
        low=Decimal(str(price)), close=Decimal(str(price)), volume=Decimal("1"))


def _seed_store() -> StrategyRegistryStore:
    """A store handle over the SAME Postgres DB ``build_live_system`` builds its own engine on.

    Used ONLY to provision the schema (so the rehydrate gate's ``has_table`` probe finds the
    ``strategy_registry`` table and wires the durable store), to READ the rows the ``add`` verb
    persisted, and to clean up. It NEVER seeds a strategy row — the ``add`` verb writes the only
    row under test (RESEARCH Item 2 / D-02).
    """
    store = StrategyRegistryStore(SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2)))
    provision_schema(store.backend)
    return store


class _LifecycleSystem:
    """A fully-wired offline paper ``LiveTradingSystem`` over the shared Postgres spine.

    Built through the REAL ``build_live_system`` factory (the construction-time rehydrate gate
    is the seam under test), then the warmup/trade pipeline is wired by hand exactly as the
    sibling P10 integration harnesses do (``test_strategy_add_warmup`` /
    ``test_strategy_remove_flat``) — ``build_live_system`` wires the durable ``registry_store``
    + ``strategy_catalog`` at its gate, and ``_initialize_live_session`` (never called here, to
    keep the drive synchronous) would otherwise own the universe/route wiring.

    ``_running`` is flipped True by hand so ``add_event``'s ``_running`` guard admits — the
    daemon drain thread is never spawned; the test drives ``process_events`` synchronously
    (deterministic), so every ``add_event`` still walks allowlist -> queue -> route dispatch.
    """

    def __init__(self) -> None:
        plugin = TestDataPlugin()
        spec = build_venue_spec("paper", data_provider="replay")
        system = build_live_system(
            spec, data_plugins={"replay": plugin}, strategy_catalog=_catalog())
        self.system = system

        # Fail-fast under synchronous drive: build_live_system injects the live
        # publish-and-continue policy, which would swallow a handler failure into a
        # confusing green. Override to fail-fast (the same reflex build_paper_replay_system
        # applies) so a broken step aborts loudly.
        system.event_handler._error_policy = FailFastPolicy()

        # Provision the REST of the durable schema (signals / orders / ...) on the system's
        # OWN spine, now that build_live_system has registered every store's tables on its
        # metadata. The seed_store fixture already provisioned strategy_registry BEFORE this
        # build (the construction-time rehydrate gate's has_table probe needs it); this covers
        # the tables the live trade path writes through (the SQL-backed signal/order stores).
        # checkfirst=True makes the restart-rebuild a clean no-op against the same DB.
        if system._system_db_backend is not None:
            provision_schema(system._system_db_backend)

        simulated = system.execution_handler.exchanges["simulated"]
        # Size the feed ring to the strategy warmup so the F-1 warmability gate admits SMA(3)
        # (an unsized ring holds only the newest-bar floor and would reject it).
        system.feed.register_raw_bar_consumer(
            StrategyWarmupConsumer(required_history_depth=100))

        # Start EMPTY (D-21) — membership derives FROM the registered strategies, so the poll
        # only admits _SYM once the external add registers a strategy on it.
        self.universe = Universe(members=[], instrument_map={_SYM: _instrument()})
        system.order_handler.set_universe(self.universe)
        if isinstance(simulated, SimulatedExchange):
            simulated.set_universe(self.universe)

        sh = system.strategies_handler
        # registry_store / strategy_catalog / portfolio_read_model were wired by
        # build_live_system's rehydrate gate (durable Postgres store) — do NOT override them,
        # the add must persist to the SAME spine the restart rehydrates from. Only the
        # universe seam is left to wire here.
        sh.set_universe(self.universe)

        self.provider = _WarmProvider()
        self.universe_handler = UniverseHandler(
            bus=system.global_queue,
            universe=self.universe,
            feed=system.feed,
            config=UniverseHandlerConfig(poll_timeframe="1d", remove_policy="force-close"))
        self.universe_handler.set_portfolio_read_model(system.portfolio_handler)
        self.universe_handler.set_provider(self.provider)
        self.universe_handler.set_selection_source(StrategyDerivedSelectionModel(sh))

        # Wire the BUSINESS/live routes through the REAL production LiveRouteRegistrar —
        # the SAME central declarative table _initialize_live_session installs at start().
        # This is the dispatch leg of the D-22 path: it SETs the STRATEGY_COMMAND route to
        # the strategies-handler command consumer (and the UNIVERSE_POLL / BARS_LOADED / FILL
        # routes) so an add_event'd command reaches the handler by the production route, NOT a
        # test shortcut. Installing it here (rather than via _initialize_live_session) lets the
        # synthetic-symbol universe below stay under the test's control while the ordering-
        # sensitive route table is production-owned.
        LiveRouteRegistrar(
            strategies_handler=sh,
            universe_handler=self.universe_handler,
            safety=system._safety,
            stream_recovery=system._stream_recovery,
        ).install(system.event_handler)

        self.portfolio_id = system.portfolio_handler.add_portfolio(
            name="ext_pf", exchange="simulated", cash=1_000_000)

        # Flip running so add_event admits; the drain thread is never spawned (synchronous).
        system._running = True

    # -- teardown -------------------------------------------------------------

    def stop(self) -> None:
        self.system._running = False
        self.system.stop(timeout=5.0)

    # -- the external ingress (add_event, NEVER the handler method directly) ---

    def add_event(self, event: Any) -> bool:
        """Drive one command through the PUBLIC ingress, then drain synchronously."""
        admitted = self.system.add_event(event)
        self.system.event_handler.process_events()
        return admitted

    def strategy(self) -> Any:
        return next((s for s in self.system.strategies_handler.strategies
                     if s.name == _NAME), None)

    # -- warmup + trade drive -------------------------------------------------

    def deliver_warmup(self) -> None:
        bars = tuple(_bar(100 + i, day=i + 1) for i in range(_WARMUP))
        self.system.global_queue.put(
            BarsLoaded(time=_T, symbol=_SYM, timeframe="1d", bars=bars))
        self.system.event_handler.process_events()

    def _drain(self) -> list[Any]:
        bus = self.system.global_queue
        raw = getattr(bus, "_pq", bus)
        snapshot = list(getattr(raw, "queue", []))
        return [item[2] if isinstance(item, tuple) else item for item in snapshot]

    def calculate_signals_for(self, day: int) -> list[SignalEvent]:
        bar = _bar(200, day=day)
        self.system.strategies_handler.on_bar(
            BarEvent(time=bar.time, bars={_SYM: bar}))
        return [e for e in self._drain() if isinstance(e, SignalEvent)]


def _add_command(*, portfolio_id: str) -> StrategyCommandEvent:
    """Build the external ``add`` for the probe, carrying the portfolio subscription.

    The probe instance is encoded through the D-04 codec (the config_json shape the FastAPI
    layer will POST), and the portfolio subscription rides alongside in the blob — the add
    verb strips ``portfolio_id`` out before build and wires the fan-out subscription.
    """
    built = _LifecycleProbe(timeframe="1d", tickers=[_SYM], name=_NAME)
    config = encode_strategy_config(built)
    config["portfolio_id"] = portfolio_id
    return StrategyCommandEvent.add(
        strategy_name=_NAME, strategy_type="_LifecycleProbe", config=config, time=_T)


@pytest.fixture()
def seed_store(pg_database_env):
    """Provision the schema on the shared Postgres DB and hand back a read/cleanup handle."""
    store = _seed_store()
    try:
        store.delete(_NAME)  # defensive: a leaked row from a prior aborted run
        yield store
    finally:
        store.delete(_NAME)
        store.dispose()


# --------------------------------------------------------------------------------------
# Test 1 — the full D-22 lifecycle: add -> dark -> warm -> trade -> restart -> resume
# --------------------------------------------------------------------------------------


def test_external_add_warms_trades_and_resumes_across_restart(seed_store):
    """D-22 — the whole phase composes through the external ingress and survives a restart."""
    boot = _LifecycleSystem()
    try:
        # 1. The external add — the PUBLIC ingress, admitted by the D-10 allowlist.
        admitted = boot.add_event(_add_command(portfolio_id=str(boot.portfolio_id)))
        assert admitted is True

        # 2. Registered + persisted with enabled=True and the resolved strategy_type.
        strategy = boot.strategy()
        assert strategy is not None
        row = seed_store.get(_NAME)
        assert row is not None
        assert row["enabled"] is True
        assert row["strategy_type"] == "_LifecycleProbe"

        # 3. DARK immediately after add (WR-02): the poll spawned warmup but no indicator
        #    bars have landed — no signal is possible yet.
        assert strategy.is_ready(_SYM) is False
        assert boot.universe.is_ready(_SYM) is False
        assert _SYM in boot.provider.spawned  # the existing P7 warmup pipeline kicked off

        # 4. Deliver the warmup through the EXISTING pipeline (BarsLoaded -> on_bars_loaded).
        boot.deliver_warmup()
        assert strategy.is_ready(_SYM) is True
        assert boot.universe.is_ready(_SYM) is True

        # 5. READY -> the next on-grid bar produces a signal (it trades).
        signals = boot.calculate_signals_for(day=20)
        assert len(signals) >= 1
        assert signals[0].ticker == _SYM

        original_sizing = strategy.sizing_policy
        original_subs = [str(p) for p in strategy.subscribed_portfolios]
        assert original_subs == [str(boot.portfolio_id)]
    finally:
        boot.stop()

    # 6. RESTART — a brand-new engine over the SAME Postgres DB. Seed NOTHING by hand; the
    #    only row is the one the add verb wrote. Rehydrate runs at CONSTRUCTION.
    restart = _LifecycleSystem()
    try:
        # 7. The same instance resumes — registered BEFORE start(), params + subscriptions
        #    match what was added.
        resumed = restart.strategy()
        assert resumed is not None
        assert type(resumed) is _LifecycleProbe
        assert resumed.tickers == [_SYM]
        assert resumed.sizing_policy == original_sizing
        assert [str(p) for p in resumed.subscribed_portfolios] == original_subs
    finally:
        restart.stop()


# --------------------------------------------------------------------------------------
# Test 2 — admission is REAL, not assumed
# --------------------------------------------------------------------------------------


def test_a_non_admissible_event_is_denied_by_the_allowlist(seed_store):
    """D-10 — a non-admissible type is DENIED, proving Test 1's success came from the gate.

    A ``BarEvent`` is an internal-fact type (``EventType.BAR``) absent from
    ``_EXTERNALLY_ADMISSIBLE``. The engine is running, so the reject is the ALLOWLIST's work,
    not the ``_running`` guard.
    """
    boot = _LifecycleSystem()
    try:
        bar_event = BarEvent(time=_T, bars={_SYM: _bar(100, day=1)})
        assert boot.system.add_event(bar_event) is False
    finally:
        boot.stop()


# --------------------------------------------------------------------------------------
# Test 3 — the external verb surface beyond `add` (STRAT-02 + STRAT-03 through the ingress)
# --------------------------------------------------------------------------------------


def test_disable_enable_reconfigure_through_the_ingress_and_reconfigured_params_survive_restart(
    seed_store,
):
    """STRAT-02/03 — disable/enable/reconfigure all ride add_event; restart resumes RECONFIGURED."""
    boot = _LifecycleSystem()
    try:
        boot.add_event(_add_command(portfolio_id=str(boot.portfolio_id)))
        assert boot.strategy() is not None

        # disable -> persists enabled=False.
        assert boot.add_event(StrategyCommandEvent.disable(strategy_name=_NAME, time=_T)) is True
        assert seed_store.get(_NAME)["enabled"] is False

        # enable -> persists enabled=True.
        assert boot.add_event(StrategyCommandEvent.enable(strategy_name=_NAME, time=_T)) is True
        assert seed_store.get(_NAME)["enabled"] is True

        # reconfigure -> applies live and persists the post-merge FULL set (P-4).
        assert boot.add_event(StrategyCommandEvent.reconfigure(
            strategy_name=_NAME, config={"max_positions": 3}, time=_T)) is True
        assert boot.strategy().max_positions == 3
        assert seed_store.get(_NAME)["config"]["max_positions"] == 3
    finally:
        boot.stop()

    # Restart rehydrates the RECONFIGURED params, not the originally-added ones.
    restart = _LifecycleSystem()
    try:
        resumed = restart.strategy()
        assert resumed is not None
        assert resumed.max_positions == 3
    finally:
        restart.stop()


# --------------------------------------------------------------------------------------
# Test 4 — D-11 remove through the external path: drop, then restart rehydrates NOTHING
# --------------------------------------------------------------------------------------


def test_remove_through_the_ingress_drops_and_restart_rehydrates_nothing(seed_store):
    """D-11 — remove via add_event runs the force-flat cycle to a drop; a restart rehydrates NOTHING.

    The strategy holds NO position when removed, so the D-11 force-flat condition already
    holds and the instance drops on the same cycle (``get_strategies_universe`` excludes the
    pending strategy, the poll's REMOVE branch fires, and the FILL-free flat completes
    immediately — ``test_strategy_remove_flat`` proves the WITH-position force-close path
    end-to-end; this file's unique job is the EXTERNAL ingress + the restart). The row is
    deleted, and a rebuild over the same DB rehydrates an empty roster.
    """
    boot = _LifecycleSystem()
    try:
        boot.add_event(_add_command(portfolio_id=str(boot.portfolio_id)))
        assert boot.strategy() is not None
        assert seed_store.get(_NAME) is not None

        # remove via the external ingress: deactivate + poll -> force-flat cycle -> drop.
        assert boot.add_event(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T)) is True

        # No position was held, so the flat condition already held — the object + rows drop.
        assert boot.strategy() is None
        assert seed_store.get(_NAME) is None
    finally:
        boot.stop()

    # After the drop, a restart rehydrates NOTHING — the instance is gone from the DB as well
    # as the roster.
    restart = _LifecycleSystem()
    try:
        assert restart.strategy() is None
        assert restart.system.strategies_handler.strategies == []
    finally:
        restart.stop()
