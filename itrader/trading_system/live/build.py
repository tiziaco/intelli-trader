"""The live composition root — initialisation as one linear, readable page (design §4.9).

Eight steps, each building one thing, with real types at top-of-file imports. That is legal
here and nowhere else: the §3.2 import boundary keeps everything under
``trading_system/live/`` off the backtest graph, so this module may name ccxt-, SQL- and
asyncio-bearing concretions directly instead of hiding them in function bodies.

What makes this structurally smaller than what it replaces, rather than merely rearranged:

* **No lazy-import blocks.** The boundary does that job.
* **No post-construction attach loop.** The facade takes every collaborator as a REQUIRED
  constructor parameter, so a built-but-unattached collaborator is a ``TypeError`` here.
* **No mode selector.** Venue selection is data (the catalogue) plus two arguments; there is
  no spec object travelling between two functions that each re-derive it.

Indentation: 4-space. ``mypy --strict`` applies, and this module is deliberately NOT covered
by any ``ignore_errors`` override.
"""

from __future__ import annotations

import random
import threading
from datetime import UTC, datetime
from functools import partial
from typing import Any, Callable, Dict, List, Optional

from itrader.config.credential_resolver import EnvCredentialResolver
from itrader.config.itrader_config import ITraderConfig
from itrader.config.sql import SqlDriver, SqlSettings
from itrader.connectors.okx import build_okx_connector
from itrader.connectors.pool import ConnectorPool
from itrader.core.clock import WallClock
from itrader.core.enums import HaltReason, SystemStatus
from itrader.core.exceptions import ValidationError
from itrader.events_handler.bus import PriorityEventBus
from itrader.events_handler.error_policy import ErrorPolicy
from itrader.events_handler.events import ConnectorFatalEvent, StreamStateEvent
from itrader.execution_handler.exchanges.base import AbstractExchange
from itrader.execution_handler.exchanges.okx import build_okx_exchange
from itrader.execution_handler.exchanges.paper import (
    build_paper_exchange,
    paper_exchange_recipe,
)
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.execution_handler.execution_handler import (
    COMPUTE_VENUE,
    DEFAULT_ACCOUNT_ID,
    default_exchange_config,
)
from itrader.logger import get_itrader_logger
from itrader.outils.time_parser import to_timedelta
from itrader.portfolio_handler.portfolio_factory import (
    AccountFactory,
    PortfolioFactory,
)
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
from itrader.price_handler.providers.okx_provider import build_okx_data_provider
from itrader.storage import SqlEngine
from itrader.storage.halt_record_store import HaltRecordStore
from itrader.storage.system_stats_store import SystemStatsStore
from itrader.storage.system_store import SystemStore
from itrader.storage.venue_account_store import VenueAccountStore
from itrader.storage.venue_store import VenueStore
from itrader.strategy_handler.registry.rehydrate import rehydrate_strategies
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.trading_system.config_router import ConfigRouter
from itrader.trading_system.engine_context import EngineContext
from itrader.trading_system.graph import Engine, build_handler_graph
from itrader.trading_system.live.bootstrap import (
    bootstrap_session,
    layer_persisted_overrides,
)
from itrader.trading_system.live.system import (
    LiveTelemetry,
    LiveTradingSystem,
    record_bar_metrics,
)
from itrader.trading_system.live_runner import LiveRunner
from itrader.trading_system.safety.pre_trade_throttle import PreTradeThrottle
from itrader.trading_system.safety.safety_controller import SafetyController
from itrader.trading_system.safety.stream_recovery_handler import StreamRecoveryHandler
from itrader.trading_system.worker_supervisor import WorkerSupervisor
from itrader.venues.accounts import VenueAccountManager
from itrader.venues.catalog import CATALOG

#: Live drain-loop timing knobs, injected into the ``LiveRunner``.
_LIVE_QUEUE_TIMEOUT = 1.0   # queue poll
_LIVE_MAX_IDLE_TIME = 300.0  # idle-warn window

_control_logger = get_itrader_logger().bind(component="ConnectorControlSignals")


# --- connector-loop CONTROL signals -------------------------------------------------
#
# These run on the CONNECTOR's asyncio loop thread, so they PUT a CONTROL event and do
# nothing else: the engine-thread routes actuate them (STREAM_STATE -> pause/resume,
# CONNECTOR_FATAL -> halt), where the blocking durable write belongs.
#
# They are free functions over the bus rather than facade methods because the venue-account
# manager and the data recipe both arm them at build, before any facade exists.


def emit_connector_fatal(bus: Any, reason: str) -> None:
    """Escalate a connector-loop fatal as a CONNECTOR_FATAL CONTROL event.

    The event carries a FIXED reason literal, NEVER ``str(exc)`` or the passed ``reason``,
    so no connector secret crosses the loop->engine boundary. Driving the blocking ``halt()``
    here would run its durable ``record_halt`` SQL write on the connector loop and stall
    every stream sharing it.
    """
    bus.put(ConnectorFatalEvent(
        time=datetime.now(UTC), reason=HaltReason.CONNECTOR_FATAL.value))


def emit_stream_down(bus: Any, stream_name: str) -> None:
    """Emit STREAM_STATE(down); the engine thread actuates it as ``pause_submission``."""
    _control_logger.warning(
        'Venue %s stream disconnected — emitting STREAM_STATE(down)', stream_name)
    bus.put(StreamStateEvent(
        time=datetime.now(UTC), stream_name=stream_name, up=False))


def emit_stream_up(bus: Any, stream_name: str) -> None:
    """Emit STREAM_STATE(up); the engine thread actuates it as ``on_reconnect``.

    The fresh REST snapshot / catch-up must NOT run here: a ``connector.call`` on the
    connector loop deadlocks it.
    """
    _control_logger.info(
        'Venue %s stream reconnected — emitting STREAM_STATE(up)', stream_name)
    bus.put(StreamStateEvent(
        time=datetime.now(UTC), stream_name=stream_name, up=True))


def build_live_system(
    config: ITraderConfig,
    *,
    execution_venue: str,
    data_venue: Optional[str] = None,
    strategy_catalog: Optional[Dict[str, type]] = None,
    status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
    data_recipes: Optional[Dict[str, Callable[..., Any]]] = None,
) -> LiveTradingSystem:
    """Build the live system: eight linear steps, then the facade.

    Parameters
    ----------
    config : ITraderConfig
        The run's config root. The durable spine, the RNG seed, the stream/universe
        sub-models and the safety settings are all read off it — nothing is read from a
        second source.
    execution_venue : str
        The venue whose enabled accounts this run brings online. Selection is DATA: the
        catalogue answers what the venue is, so there is no spec object and no registry of
        plugin instances.
    data_venue : str | None
        Which venue serves candles. ``None`` resolves to the execution venue's catalogue
        default. An execution venue with NO catalogue entry must name one explicitly —
        guessing a data source for an unknown venue is how a run silently trades on
        another venue's prices.
    strategy_catalog : dict[str, type] | None
        The only thing that turns a stored ``strategy_type`` string into a class, so the
        app decides what is instantiable at boot. With registry rows present, a missing
        catalog fails LOUD rather than booting an engine that looks healthy and trades
        nothing.
    status_callback : callable | None
        Invoked as ``(new_status, status_data)`` on each status transition.
    data_recipes : dict[str, callable] | None
        TEST-ONLY override mapping of data-venue name to data-adapter recipe, merged OVER
        the production recipes so a fixture can supply an offline data source. Never
        barrel-exported, and never populated by production.

    Returns
    -------
    LiveTradingSystem
        The facade, fully wired but NOT started. Construction performs no venue I/O: every
        connect happens inside ``start()``.
    """
    logger = get_itrader_logger().bind(component="LiveTradingSystem")

    # 1. DURABLE SPINE. Selected by env-presence of a Postgres credential on the unified
    #    ITRADER_DATABASE_* surface — the same source Alembic's env.py uses — with no
    #    hardcoded credential fallback. Probed BEFORE constructing a Postgres SqlSettings,
    #    which raises when no credential is present; the SQLite default driver skips
    #    _require_pg_credentials, so the probe itself never raises.
    #
    #    Durability follows the SPINE, never an environment string: with a spine the
    #    portfolio handler holds a real definition store, and without one there is no
    #    database to be durable against. The WR-07 configuration — a real spine whose
    #    portfolios silently persist nothing — is unreachable from here.
    probe = SqlSettings()
    sql_engine: Optional[SqlEngine] = None
    environment = 'backtest'
    if probe.password is not None or probe.url is not None:
        sql_engine = SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
        environment = 'live'
    else:
        logger.warning(
            "No Postgres credential in env (ITRADER_DATABASE_PASSWORD / "
            "ITRADER_DATABASE_URL unset) — this run is NOT DURABLE: no portfolio "
            "definitions, no venue accounts, no halt records, no runtime config. Orders "
            "and signals live in memory and do not survive a restart.")

    halt_record_store = HaltRecordStore(sql_engine) if sql_engine is not None else None
    system_store = SystemStore(sql_engine) if sql_engine is not None else None
    venue_store = VenueStore(sql_engine) if sql_engine is not None else None
    system_stats_store = (
        SystemStatsStore(sql_engine) if sql_engine is not None else None)

    # 2. THE RUN'S INFRA. One bus, one push-driven feed, one seeded RNG, one alert egress.
    #    The live bus is inert without CONTROL events: everything flows BUSINESS-tier and
    #    the monotonic seq keeps strict FIFO.
    bus = PriorityEventBus()
    feed = LiveBarFeed(provider=None, base_timeframe=to_timedelta('1d'))
    rng = random.Random(int(config.rng_seed))
    alert_sink = LogAlertSink()
    # The ERROR-route policy is built BEFORE the graph so it rides in through the one
    # mode-agnostic build site, never a post-build monkeypatch. Its halt + error_counter are
    # bound below, once the safety plane exists.
    error_policy = ErrorPolicy(bus, failure_settings=config.safety.failure_rate)
    ctx = EngineContext(
        bus=bus, config=config, environment=environment,
        feed=feed, rng=rng, store=None, sql_engine=sql_engine)

    # 3. SESSIONS + VENUE DOMAIN. One pool, one routing map, one manager.
    #
    #    credential_resolver is what lets two account_ids connect with DIFFERENT keys: without
    #    it every named account falls back to the ONE global OKX_API_* set and the system
    #    believes two separate accounts when it has one.
    credential_resolver = EnvCredentialResolver()
    connector_pool = ConnectorPool(
        catalog=CATALOG, resolver=credential_resolver,
        recipes={'okx': build_okx_connector})

    # The compute venue's baseline exchange, registered under (paper, 'default'). It is the
    # in-process simulated venue every deployment has, and it is what supplies venue metadata
    # when a boot brings zero streaming accounts online. Registering it is NOT by itself a
    # route: an order reaches it only through a portfolio that NAMES ('paper', 'default'),
    # and on a durable spine the account authority refuses such a portfolio unless that row
    # exists. So the baseline is inert-by-authority rather than inert-by-absence.
    exchange_registry: Dict[tuple[str, str], Optional[AbstractExchange]] = {
        (COMPUTE_VENUE, DEFAULT_ACCOUNT_ID): build_paper_exchange(
            exchange_config=default_exchange_config(), bus=bus, rng=rng),
    }

    venue_manager: Optional[VenueAccountManager] = None
    if sql_engine is not None:
        venue_manager = VenueAccountManager(
            store=VenueAccountStore(sql_engine),
            pool=connector_pool,
            # The SAME map the execution handler reads on order. ``bring_online`` writing it
            # directly, as its LAST step, is the cut that lets the manager be built above the
            # handler graph instead of reaching through the handler to register an exchange.
            routing=exchange_registry,
            catalog=CATALOG,
            exchange_recipes={
                'okx': build_okx_exchange,
                # Bound to THIS run's exchange config; a default preset would silently
                # narrow order admission.
                'paper': paper_exchange_recipe(default_exchange_config()),
            },
            ctx=ctx,
            alert_sink=alert_sink,
            # Bound to the bus, not to a facade: the manager arms these on every
            # session-bearing adapter at bring-up, and no facade exists yet.
            halt_signal=partial(emit_connector_fatal, bus),
            stream_state_listener=(
                partial(emit_stream_down, bus), partial(emit_stream_up, bus)),
        )

    # The leaf-builder every portfolio is constructed through. The mode difference lives
    # ONLY in the injected validator: with a manager the pair is asserted provisioned and
    # enabled, so a live portfolio can never sit on a fabricated balance — and a live
    # portfolio naming NO account is refused there rather than named onto the compute
    # venue's default one.
    portfolio_factory = PortfolioFactory(
        account_factory=AccountFactory(
            validate=venue_manager.assert_available
            if venue_manager is not None else None),
        environment=environment,
        sql_engine=sql_engine,
    )

    # 4. THE MODE-BLIND HANDLER GRAPH — real arguments, no Optional mode selectors.
    engine = build_handler_graph(
        ctx,
        exchange_registry=exchange_registry,
        portfolio_factory=portfolio_factory,
        results_store=None,
        alert_sink=alert_sink,
        system_store=system_store,
        error_policy=error_policy,
        strategy_catalog=strategy_catalog,
    )

    # 5. SAFETY PLANE. Recovery ENUMERATES the manager at use time — no mirrored container
    #    for a later bring-up to fall out of step with.
    throttle = PreTradeThrottle(
        settings=config.safety.throttle, clock=WallClock(), bus=bus)
    telemetry = LiveTelemetry(
        bus=bus, exchange=execution_venue, status_callback=status_callback,
        system_stats_store=system_stats_store, throttle=throttle)
    safety = SafetyController(
        bus=bus,
        halt_record_store=halt_record_store,
        # LATE-BOUND so the gate always dispatches through the CURRENT inner dispatch: a
        # test monkeypatch of event_handler._dispatch is honoured, and gate_and_dispatch
        # replay reaches it too.
        dispatch_fn=lambda ev: engine.event_handler._dispatch(ev),
        notify_status_change=telemetry.on_status_change,
        system_store=system_store,
    )
    # The one genuine construction cycle: the controller notifies telemetry on every
    # transition, and the notification snapshots the controller's own latch.
    telemetry.bind(safety)
    # Engine-thread drift-halt signal -> freeze-in-place halt.
    engine.portfolio_handler.set_halt_signal(safety.halt)
    error_policy.bind(halt=safety.halt, error_counter=telemetry.increment_errors)

    # 6. DATA PLANE (§4.6): ONE adapter, over its OWN session, armed by its own recipe at
    #    build. Which venue serves candles is a RUN-level choice, not a per-account
    #    property: an account retiring changes order routing only, because the feed borrows
    #    nothing from any account.
    #
    #    Building is I/O-FREE — the session is opened by ``start()``.
    resolved_data_venue = _resolve_data_venue(execution_venue, data_venue)
    data_connector = _open_data_session(
        connector_pool, resolved_data_venue, venue_manager, execution_venue)
    recipes: Dict[str, Callable[..., Any]] = {'okx': build_okx_data_provider}
    if data_recipes:
        recipes.update(data_recipes)
    try:
        data_recipe = recipes[resolved_data_venue]
    except KeyError:
        # Loud, because the alternative is an engine that runs and trades on nothing.
        raise KeyError(
            f"no data recipe for venue {resolved_data_venue!r} — this system builds "
            f"{sorted(recipes)}") from None
    data_provider = data_recipe(
        connector=data_connector,
        ctx=ctx,
        feed=feed,
        global_queue=bus,
        # The SAME bus-bound callbacks the execution adapters are armed with, so a
        # candle-stream fatal freezes the engine and a candle-stream drop pauses submission
        # exactly as a fill-stream one does.
        halt_signal=partial(emit_connector_fatal, bus),
        stream_state_listener=(
            partial(emit_stream_down, bus), partial(emit_stream_up, bus)),
    )

    stream_recovery = StreamRecoveryHandler(
        safety=safety,
        accounts=(
            venue_manager.online_records if venue_manager is not None else list),
        # The ONE data adapter, so the all-streams health gate covers the candle arm too.
        feed_provider=lambda: data_provider,
        alert_sink=alert_sink,
    )

    # 7. RUNTIME-CONFIG PLATFORM + the RESTART SEQUENCE. The router writes each scope to its
    #    OWNING module store — system -> SystemStore, order -> the ORDER store, venue ->
    #    VenueStore, portfolio -> each Portfolio's OWN bound state_storage.
    config_router = (
        ConfigRouter(
            config=config,
            system_store=system_store,
            venue_store=venue_store,
            order_handler=engine.order_handler,
            portfolio_handler=engine.portfolio_handler,
            execution_handler=engine.execution_handler,
            venue_kind=partial(_venue_is_simulated, engine.execution_handler),
            bus=bus,
            clock=WallClock(),
        )
        if sql_engine is not None else None)

    boot = partial(
        _restart_sequence,
        sql_engine=sql_engine,
        venue_manager=venue_manager,
        engine=engine,
        config=config,
        execution_venue=execution_venue,
        alert_sink=alert_sink,
        system_store=system_store,
        venue_store=venue_store,
        strategy_catalog=strategy_catalog,
    )

    # 8. THE FACADE, plus the drain-loop runtime its hooks are already bound to. EVERY
    #    collaborator is a required constructor argument, so a collaborator built above and
    #    not passed here is a TypeError rather than a None nothing reports.
    stop_event = threading.Event()
    live_runner = LiveRunner(
        bus=bus,
        stop_event=stop_event,
        worker_supervisor=WorkerSupervisor(
            bus, stop_event, config.universe.poll_cadence_s),
        # The freeze-in-place gate, with the pre-submit throttle firing at the
        # ORDER->execution boundary ahead of it.
        dispatch_gate=safety.gate_and_dispatch,
        update_stats=telemetry.update,
        record_bar_metrics=partial(record_bar_metrics, engine.portfolio_handler),
        pre_submit=throttle.allow,
        queue_timeout=_LIVE_QUEUE_TIMEOUT,
        max_idle_time=_LIVE_MAX_IDLE_TIME,
        on_loop_start=telemetry.on_loop_start,
        on_loop_error=telemetry.on_loop_error,
        on_order_throttle_rejected=telemetry.on_order_throttle_rejected,
    )

    facade = LiveTradingSystem(
        engine=engine,
        config=config,
        exchange=execution_venue,
        telemetry=telemetry,
        safety=safety,
        stream_recovery=stream_recovery,
        throttle=throttle,
        error_policy=error_policy,
        live_runner=live_runner,
        stop_event=stop_event,
        boot=boot,
        config_router=config_router,
        venue_accounts=venue_manager,
        connector_pool=connector_pool,
        data_provider=data_provider,
        data_connector=data_connector,
        sql_engine=sql_engine,
        halt_record_store=halt_record_store,
        system_store=system_store,
        system_stats_store=system_stats_store,
    )
    logger.info('Live trading system built', exchange=execution_venue)
    return facade


def _resolve_data_venue(execution_venue: str, data_venue: Optional[str]) -> str:
    """Which venue serves candles: the explicit choice, else the catalogue default."""
    if data_venue is not None:
        return data_venue
    descriptor = CATALOG.get(execution_venue)
    if descriptor is None:
        raise KeyError(
            f"execution venue {execution_venue!r} has no catalogue entry, so it declares "
            f"no default data provider — name one explicitly with data_venue=. The "
            f"catalogue supports {sorted(CATALOG)}")
    return descriptor.default_data_provider


def _open_data_session(
    pool: ConnectorPool,
    data_venue: str,
    venue_manager: Optional[VenueAccountManager],
    execution_venue: str,
) -> Optional[Any]:
    """The data adapter's OWN session, or ``None`` for a source that carries none.

    The session is the venue's PUBLIC one whenever the descriptor says its market data needs
    no credentials (OKX candles are public), so the data plane names no account at all. A
    venue declaring ``data_requires_auth`` needs an authenticated session instead — the only
    case where the feed must name an account, because its data is not public. A venue with no
    catalogue entry is a test-injected data source with no session to build.
    """
    descriptor = CATALOG.get(data_venue)
    if descriptor is None:
        return None
    if not descriptor.data_requires_auth:
        return pool.public_session(data_venue)
    # An authenticated data session belongs to a real provisioned account, so it comes from
    # the account domain rather than being conjured here.
    rows = venue_manager.read_enabled_for(data_venue) if venue_manager is not None else []
    if not rows:
        raise ValidationError(
            'data_venue', data_venue,
            f"venue {data_venue!r} serves market data only over an AUTHENTICATED session, "
            f"but this run ({execution_venue!r}) has no enabled account on it to "
            f"authenticate as — the feed would come up with no data source")
    spec = venue_manager.spec_for(rows[0])  # type: ignore[union-attr]
    return pool.session(data_venue, spec.account_id, spec)


def _venue_is_simulated(execution_handler: Any, venue_name: str) -> bool:
    """True when the venue's execution arm is a ``SimulatedExchange``.

    The registry is pair-keyed, so this matches every registered account on the named venue.
    The parameter stays a bare VENUE string because "is this venue simulated?" is a property
    of the venue, not of one account on it.
    """
    return any(
        isinstance(exchange, SimulatedExchange)
        for (venue, _account_id), exchange in execution_handler.exchanges.items()
        if venue == venue_name)


def _restart_sequence(
    *,
    sql_engine: Optional[SqlEngine],
    venue_manager: Optional[VenueAccountManager],
    engine: Engine,
    config: ITraderConfig,
    execution_venue: str,
    alert_sink: Any,
    system_store: Optional[SystemStore],
    venue_store: Optional[VenueStore],
    strategy_catalog: Optional[Dict[str, type]],
) -> List[str]:
    """Turn durable state back into a running engine — steps 7-8 of design §4.9.

    The three steps are ordered by hard data dependencies:

    1. bring every enabled account online and rehydrate the persisted portfolios (assembly
       BEFORE rehydrate, so a portfolio naming a not-provisioned or disabled account raises
       instead of silently sitting on an unbacked leaf);
    2. layer the persisted config, which iterates the portfolios step 1 materialized —
       running it first would iterate an EMPTY collection and drop every stored portfolio
       override, silently;
    3. rehydrate the stored strategy roster, which binds each subscription to a portfolio
       that must already exist with its restart-stable id.

    It runs at ``start()`` rather than at build because step 1 CONNECTS: an account becomes
    routable only once its session is open, so performing it while building the object would
    make constructing a live system a network operation.

    Returns the ids of the strategies that could NOT be rehydrated.
    """
    bootstrap_session(
        sql_engine=sql_engine,
        venue_manager=venue_manager,
        portfolio_handler=engine.portfolio_handler,
        execution_venue=execution_venue,
        alert_sink=alert_sink,
    )
    if system_store is None:
        return []
    # Base params are already resolved at construction (frozen).
    layer_persisted_overrides(
        config,
        system_store=system_store,
        venue_store=venue_store,
        order_handler=engine.order_handler,
        portfolio_handler=engine.portfolio_handler,
        execution_handler=engine.execution_handler,
    )
    # Session init reads the strategy list — wire_universe derives membership from it,
    # register_strategy_warmup sizes the feed ring from it — so a strategy registered after
    # either would never enter the universe and never size the ring. It must also NOT live
    # inside _initialize_live_session, which integration tests (including a RESTART test)
    # monkeypatch to a no-op, silently losing the rehydrate exactly where it matters most.
    #
    # Deliberately NOT wrapped in try/except: per-instance failures are ALREADY handled inside
    # rehydrate_strategies (skip + CRITICAL alert + the row left untouched), while an
    # infrastructure failure must fail LOUD. A blanket wrap would convert the loud arm into a
    # silent boot with zero strategies.
    #
    # The store is READ BACK off the handler that OWNS it, so a rehydrated strategy's first
    # runtime verb always has a store to persist to. A None store is the first-start state (an
    # unprovisioned strategy_registry table), not an infrastructure failure, so skipping cannot
    # produce the zero-strategies-while-rows-exist outcome.
    registry_store = engine.strategies_handler.registry_store
    if registry_store is None:
        return []
    quarantined: List[str] = rehydrate_strategies(
        store=registry_store,
        catalog=strategy_catalog,
        strategies_handler=engine.strategies_handler,
        alert_sink=alert_sink,
    )
    return quarantined
