import threading
from datetime import datetime, UTC
from typing import Optional, Dict, Any, Callable, TYPE_CHECKING

from itrader.core.enums import HaltReason, SystemStatus
from itrader.core.exceptions import StateError
from itrader.outils.time_parser import to_timedelta
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.trading_system.venue_spec import build_venue_spec
# 06.1-04 (SEAM-04/D-13): pure imports HOISTED to module top. Safe now because the
# barrel drop (06.1-04 Task 1, D-12) removed this module from the backtest import graph,
# so their module-top execution never touches the backtest path. session_initializer /
# engine_context / universe_handler are all pure (no ccxt.pro/SQL/venue substrate) — the
# P6 register-vs-build inertness block in test_okx_inertness proves importing this module
# pulls no heavy backend. The genuinely-HEAVY imports (LiveBarFeed / SqlSettings / SQL
# spine / ConnectorProvider / okx_plugin / assemble_venue / LiveRunner) STAY lazy inside
# build_live_system's body (D-13).
from itrader.trading_system.session_initializer import SessionInitializer
from itrader.trading_system.engine_context import EngineContext
from itrader.universe import Universe
from itrader.universe.universe_handler import UniverseHandlerConfig

from itrader.logger import get_itrader_logger
from itrader.events_handler.bus import PriorityEventBus
from itrader.events_handler.events import EventType, StreamStateEvent, ConnectorFatalEvent

if TYPE_CHECKING:
    # Pure forward-refs for the pure-injection facade signature (06.1-02/D-10) — under
    # TYPE_CHECKING so importing this module pulls neither onto the graph (compose is a
    # pure import; VenueLifecycle is import-inert). The facade module is mypy ignore_errors.
    from itrader.trading_system.compose import Engine
    from itrader.venues.lifecycle import VenueLifecycle

# RUN-01/RUN-02 (D-06): the live drain-loop timing knobs. Formerly loose
# ``__init__`` params (``queue_timeout``/``max_idle_time``); the pure-injection
# facade sheds them and ``build_live_system`` injects these values into the
# ``LiveRunner`` (which now OWNS the drain loop). Values preserve the historical
# facade defaults exactly (1.0s queue poll, 300s idle-warn window).
_LIVE_QUEUE_TIMEOUT = 1.0
_LIVE_MAX_IDLE_TIME = 300.0

# D-10 (WR — the primary external-surface security control): ``add_event`` is the
# engine's PUBLIC external/web ingress. It is FAIL-CLOSED (default-deny, ASVS V4/V5):
# ONLY the two sanctioned externally-originated event types are admissible — a
# ``SIGNAL`` (routes through ``OrderHandler.on_signal`` -> ``AdmissionManager`` for
# validation + sizing + reservation + mirror) and a ``STRATEGY_COMMAND`` (an operator
# add/remove-ticker command). EVERY other event type — every internal-fact type
# (FILL / BAR / UNIVERSE_UPDATE / UNIVERSE_POLL / BARS_LOADED / BARS_LOAD_FAILED /
# TIME / ORDER / ERROR / PORTFOLIO_UPDATE ...) — is rejected by default. Internal
# order flow is UNAFFECTED: handlers put their events on ``global_queue`` directly,
# never through this external ``add_event`` surface (RESEARCH OQ7: zero internal
# production callers of ``add_event``).
_EXTERNALLY_ADMISSIBLE = frozenset({EventType.SIGNAL, EventType.STRATEGY_COMMAND})

# Live operational store credential surface (D-live wiring completed). The live order +
# signal store is selected by ENV-PRESENCE of a Postgres credential on the unified
# ``ITRADER_DATABASE_*`` surface — ``ITRADER_DATABASE_PASSWORD`` (component-var arm) or the
# ``ITRADER_DATABASE_URL`` verbatim escape hatch — and built from the unified ``SqlSettings``
# Postgres arm, the SAME credential source Alembic ``migrations/env.py`` uses (one canonical
# source; no separate legacy env-var seam). WR-10: no hardcoded credential fallback — an
# unconfigured env falls back to in-memory order + signal storage with a loud warning. The
# presence check runs a lazy default ``SqlSettings()`` probe inside ``build_live_system``
# (below) so it honors per-construction env: the SQLite default driver skips
# ``_require_pg_credentials`` (so the probe never raises when creds are absent) while still
# sourcing ``ITRADER_DATABASE_*`` into ``probe.password`` / ``probe.url`` (IN-01). It gates
# BEFORE constructing ``SqlSettings(driver=POSTGRESQL_PSYCOPG2)``, which RAISES
# ``ValidationError`` (``_require_pg_credentials``) when no credential is present.

# WR-03 / CFG-03 / D-08 / IN-01: the SINGLE wiring source for the live OKX subscription
# now lives in ``config.stream`` (the eager ``SystemConfig.stream`` field, backed by
# StreamSettings in config/stream.py). The OKX data provider stamps this
# symbol/timeframe into every ClosedBar (the feed's ring key), the feed warms up on
# the same pair, and universe membership is checked against it — so the
# OkxDataProvider constructor args and the feed.warmup() args can never drift into a
# ring-key vs membership mismatch (which would otherwise surface only as a
# MissingPriceDataError at first window()). Live-only read sites source
# ``config.stream`` (the process-wide singleton) via a local ``from itrader import
# config`` import; composition-root injection (and the universe-driven pair) land later.
# BTC/USDC (not BTC/USDT): the OKX EEA entity restricts USDT spot pairs under MiCA —
# an order on BTC/USDT returns sCode 51155 "local compliance restrictions".

# TEST-01/D-18/D-21: the paper/backtest parity window + the offline replay driver left
# this module for the test harness (tests/support/replay_harness.py). Production paper
# re-points to the OKX live data feed (D-21), so this module carries NO replay apparatus
# and NO parity constants.


# VENUE-04/D-09 — the venue-precision resolver + the precision->scale helper that lived
# here have been retired: precision_to_scale is now a shared money util in `core/money.py`
# and precision resolution is a first-class `AbstractExchange.resolve_precision` capability
# (implemented on `OkxExchange`). The universe handler binds directly on the exchange.


# SystemStatus now lives in its canonical home ``core/enums/system.py`` and is
# imported above; the ``SystemStatus.X`` usages below resolve unchanged.


class LiveTradingSystem:
    """
    Encapsulates the settings and components for carrying out live trading.
    Processes events from a global queue in a separate thread instead of 
    using a for-loop like the backtest system.
    
    Enhanced with web control capabilities for REST API and WebSocket integration.
    """
    
    def __init__(
        self,
        *,
        engine: "Engine",
        lifecycle: "Optional[VenueLifecycle]" = None,
        system_db_backend: Optional[Any] = None,
        halt_record_store: Optional[Any] = None,
        exchange: str,
        status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
    ):
        """Pure-injection facade constructor (RUN-01/RUN-03/D-09/D-10).

        DIRECT pure injection over the pre-built collaborators — NO ``components``
        bag: the compose ``engine`` (the single source of truth for the handler
        graph + its handler-owned storages + ``store=None``), the single
        ``VenueLifecycle`` holder (D-07 — the venue/connector cluster, sourced off it
        with the paper ``connector``-None guard, D-08), and the SEPARATE SQL spine +
        halt store (D-09 — storage/durable infra, NOT venue/connector). ``exchange``
        (the venue-name string) + ``status_callback`` are the remaining loose params.
        Holds NO wiring logic; initialises fresh per-instance RUNTIME state
        (status/locks/flags/stats). Mirrors ``compose_engine -> Engine ->
        BacktestRunner`` (the injected engine is the source of truth; the holder is thin).

        D-03 boundary honesty: the ~200-line facade is a P7-EXIT gate (P7 owns the
        ~500 lines of safety/reconcile/stream extraction). The interim P6 facade is
        ~600-700 lines and that is CORRECT — RUN-03 acceptance here is STRUCTURAL.

        Parameters
        ----------
        engine : Engine
            The compose ``Engine`` — the wired handler graph (+ handler-owned storages,
            ``store=None`` on live). Source of truth for ``_initialize_live_session``.
        lifecycle : VenueLifecycle, optional
            The single venue/connector holder ``assemble_venue`` returns (D-07). ``None``
            when the venue is unregistered; paper carries a lifecycle with ``connector=None``.
        system_db_backend, halt_record_store : optional
            The SEPARATE SQL spine + durable halt-record store (D-09) — storage/durable
            infra, never folded into the venue holder.
        exchange : str
            The venue-name string (``spec.execution_venue``-derived).
        status_callback : callable, optional
            Callback to notify status changes to external systems.
        """
        self.logger = get_itrader_logger().bind(component="LiveTradingSystem")
        self.status_callback = status_callback

        # -- Injected compose Engine: the SINGLE source of truth for the handler graph;
        #    handlers/feed/storages are sourced OFF it (no duplicate fields, D-10). --
        self._engine = engine
        self.exchange = exchange
        self.global_queue = engine.global_queue
        # D-02: engine.store is None on live — HELD, never read as a real store.
        self.store = engine.store
        self.feed = engine.feed
        self.screeners_handler = engine.screeners_handler
        self.portfolio_handler = engine.portfolio_handler
        self.strategies_handler = engine.strategies_handler
        self.order_handler = engine.order_handler
        self.execution_handler = engine.execution_handler
        self.event_handler = engine.event_handler
        self._signal_store = engine.strategies_handler.signal_store
        self._order_storage = engine.order_handler.storage

        # -- SQL spine + halt store: SEPARATE infra handles (D-09, NOT venue/connector). --
        self._system_db_backend: Optional[Any] = system_db_backend
        self._halt_record_store: Optional[Any] = halt_record_store

        # -- Venue/connector handles sourced off the SINGLE VenueLifecycle holder
        #    (D-07/D-08). The ``lifecycle.bundle.connector``-is-not-None guard is the
        #    streaming-venue discriminator: paper (connector=None) keeps every ``_okx_*``
        #    handle None — byte-identical to build_live_system's former guard. The
        #    safety/reconcile/stream method bodies that read these fields stay UNCHURNED
        #    (P7 extracts from a known baseline, D-08). --
        self._venue_lifecycle: Optional[Any] = lifecycle
        self._venue_bundle: Optional[Any] = (
            lifecycle.bundle if lifecycle is not None else None)
        self._okx_connector: Optional[Any] = (
            lifecycle.bundle.connector if lifecycle is not None else None)
        self._okx_exchange: Optional[Any] = None
        self._venue_account: Optional[Any] = None
        self._okx_data_provider: Optional[Any] = None
        if lifecycle is not None and lifecycle.bundle.connector is not None:
            self._okx_exchange = lifecycle.bundle.exchange
            self._venue_account = lifecycle.bundle.account_factory()
            self._okx_data_provider = lifecycle.provider

        # -- Fresh per-instance RUNTIME state (NOT wiring) ----------------------
        # P7 (SAFE-01/03/§11e): the status latch + halt/pause machinery + the
        # deferred-protective queue moved to the injected SafetyController; the
        # connector stream-recovery I/O to StreamRecoveryHandler; the pre-submit caps to
        # PreTradeThrottle; and the startup reconcile to ReconciliationCoordinator. The
        # facade is a THIN delegator over them. build_live_system constructs + ATTACHES
        # them after construction (they reference the facade's own callbacks, so they can
        # only be built once this instance exists) — mirrors the _live_runner attach.
        self._safety: Optional[Any] = None
        self._stream_recovery: Optional[Any] = None
        self._throttle: Optional[Any] = None

        # Threading control. The shared _stop_event is honoured by BOTH the injected
        # LiveRunner drain loop and its composed WorkerSupervisor (build_live_system
        # threads it into them); the facade owns it so stop() can latch shutdown.
        self._running = False
        self._stop_event = threading.Event()

        # Statistics tracking
        self._stats = {
            'events_processed': 0,
            'orders_executed': 0,
            'last_event_time': None,
            'uptime_start': None,
            'errors_count': 0
        }
        self._stats_lock = threading.Lock()

        # WR-04: "not yet wired" sentinels populated by _initialize_live_session.
        self.universe: Optional[Universe] = None
        self._universe_handler: Optional[Any] = None
        # D-12 (interim): session init stays DEFERRED to start() (and the offline test
        # driver TestRunner, which calls _initialize_live_session before its per-bar
        # drive). The construction-time flip conflicts with the pervasive
        # add-strategy-after-construction + monkeypatch-_initialize_live_session-
        # before-start() contracts across the live test suite (06-06 kept it deferred).
        # The idempotency guard makes a second call a no-op so no path double-inits.
        self._session_initialized = False

        # RUN-02 loop runtime — ATTACHED by build_live_system AFTER construction
        # (LiveRunner + ErrorPolicy reference the facade's own gate/hook methods, so
        # they can only be built once this facade instance exists). start()/stop()
        # delegate the drain-loop lifecycle to the injected LiveRunner.
        self._live_runner: Optional[Any] = None
        self._error_policy: Optional[Any] = None

        self.logger.info('Live trading system initialized')

    @classmethod
    def for_exchange(
        cls,
        exchange: str,
        *,
        status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
        **overrides: Any,
    ) -> "LiveTradingSystem":
        """Thin spec-builder over the ONE factory ``build_live_system`` (RUN-01/D-09).

        NOT a second construction path (D-09): it builds a declarative live ``spec``
        (``execution_venue=exchange``; ``data_provider`` selected as today — ``okx`` for
        the okx venue, the OKX live feed for paper (D-21), else ``okx``; ``account_id``
        the single logical default) and delegates to ``build_live_system(spec)``. This is
        the ergonomic entry point the ~45 former direct ``LiveTradingSystem(exchange=...)``
        construction sites migrate to (LANDMINE 1). ``status_callback`` threads through
        unchanged; ``**overrides`` may carry an explicit ``data_provider``/``account_id``
        for a bespoke spec, or a ``data_plugins`` map for a TEST-only data provider
        injection (the paper↔replay pairing now lives ONLY in the test fixture, D-21).
        """
        data_plugins = overrides.pop('data_plugins', None)
        # build_venue_spec owns the {okx,paper}->okx default-provider map (D-11 — one home).
        spec = build_venue_spec(
            exchange,
            data_provider=overrides.pop('data_provider', None),
            account_id=overrides.pop('account_id', None),
        )
        return build_live_system(
            spec, status_callback=status_callback, data_plugins=data_plugins)

    def _on_loop_start(self) -> None:
        """LiveRunner loop-entry hook (RUN-02/D-04): stamp RUNNING + uptime_start.

        The drain loop's loop-entry facade bookkeeping, reached via the injected
        ``on_loop_start`` callback so the status/stats side-effects stay on the
        facade (the LiveRunner owns no ``SystemStatus``).
        """
        self._safety.update_status(SystemStatus.RUNNING)
        with self._stats_lock:
            self._stats['uptime_start'] = datetime.now(UTC).isoformat()

    def _increment_error_count(self) -> None:
        """ErrorPolicy/LiveRunner error-counter hook (RUN-02/D-04): bump errors_count.

        Preserves the facade's ``_stats['errors_count']`` bookkeeping when the
        injected ``ErrorPolicy`` publishes an ErrorEvent (WR-05 path).
        """
        with self._stats_lock:
            self._stats['errors_count'] += 1

    def _on_loop_error(self, exc: BaseException) -> None:
        """LiveRunner loop catch-all hook (RUN-02/D-04): count a loop-level error."""
        self._increment_error_count()

    # ---- Thin safety delegators (§11e) — the extracted donor bodies live on the
    # ---- injected SafetyController; the facade forwards so the ~45 external call
    # ---- sites + the live test suite keep working over one source of truth. --------

    def halt(self, reason: str) -> None:
        """Freeze-in-place halt of the whole engine (delegates to SafetyController, §11e)."""
        self._safety.halt(reason)

    def reset_halt(self) -> bool:
        """Operator-only clear of the latched HALTED state (delegates, D-05/F/U-9)."""
        return self._safety.reset_halt()

    def is_halted(self) -> bool:
        """Whether the engine is in the freeze-in-place HALTED state (delegates, D-02)."""
        return self._safety.is_halted()

    def pause_submission(self, reason: str) -> None:
        """Reversibly pause NEW order submission on a disconnect (delegates, D-19)."""
        self._safety.pause_submission(reason)

    def resume_submission(self) -> None:
        """Clear the reversible pause after reconnect + a fresh REST snapshot (delegates, D-19)."""
        self._safety.resume_submission()

    def _build_reconciliation_coordinator(self) -> Any:
        """Construct the startup ReconciliationCoordinator from CURRENT venue state (SAFE-05/§11d).

        Built at ``start()`` (not ``build_live_system``) so it reads the LIVE venue arms —
        ``_venue_account`` / ``_okx_exchange`` / ``_okx_connector`` are facade fields that
        an offline run swaps before ``start()``, and the reconcile must honour the current
        values. ``halt`` is the facade delegator (-> ``SafetyController.halt``) so a
        baseline residual latches the freeze-in-place halt. The import is lazy so the
        backtest import path never pulls the reconcile module (inertness gate).
        """
        from itrader.portfolio_handler.reconcile.reconciliation_coordinator import (
            ReconciliationCoordinator,
        )
        return ReconciliationCoordinator(
            portfolio_handler=self.portfolio_handler,
            seed_applied_trades=self.order_handler.order_manager.seed_applied_trades,
            order_storage=self._order_storage,
            venue_account=self._venue_account,
            connector=self._okx_connector,
            exchange=self._okx_exchange,
            global_queue=self.global_queue,
            halt=self.halt,
        )

    def _on_venue_stream_down(self, stream_name: str) -> None:
        """Connector-loop callback (SAFE-03/§11c): emit a STREAM_STATE(down) CONTROL event.

        Thread-safe ``bus.put`` ONLY — NO blocking venue I/O and NO flag flip on the
        connector asyncio loop (Pitfall 9). The engine-thread STREAM_STATE route actuates
        it as ``SafetyController.pause_submission`` (down). Fires once per sustained
        disconnect (past the debounce).
        """
        self.logger.warning(
            'Venue %s stream disconnected — emitting STREAM_STATE(down)', stream_name)
        self.global_queue.put(StreamStateEvent(
            time=datetime.now(UTC), stream_name=stream_name, up=False))

    def _on_venue_stream_up(self, stream_name: str) -> None:
        """Connector-loop callback (SAFE-03/§11c): emit a STREAM_STATE(up) CONTROL event.

        Thread-safe ``bus.put`` ONLY — it must not perform the fresh REST snapshot /
        catch-up here (a ``connector.call`` on the connector loop would deadlock,
        Pitfall 9). The engine-thread STREAM_STATE route actuates it as
        ``StreamRecoveryHandler.on_reconnect`` (the blocking resume I/O runs there).
        """
        self.logger.info(
            'Venue %s stream reconnected — emitting STREAM_STATE(up)', stream_name)
        self.global_queue.put(StreamStateEvent(
            time=datetime.now(UTC), stream_name=stream_name, up=True))

    def _request_connector_halt(self, reason: str) -> None:
        """Connector-loop callback (SAFE-03/§11c): emit a CONNECTOR_FATAL CONTROL event.

        Injected as the OKX stream arms' halt signal (``set_halt_signal``). Fired from the
        connector ASYNCIO LOOP thread on a fatal connector error / exhausted retry ceiling /
        the unclassified catch-all. It ONLY puts a CONTROL event — it must NOT drive the
        blocking ``halt()`` here (its durable ``record_halt`` SQL write would stall every
        stream sharing the loop, Pitfall 9). The engine-thread CONNECTOR_FATAL route runs
        the blocking ``SafetyController.halt`` off the loop. The event carries a FIXED reason
        literal (``HaltReason.CONNECTOR_FATAL.value``), NEVER ``str(exc)`` / the passed
        ``reason`` — so no connector secret crosses the loop->engine boundary (V7, T-07-01).
        """
        self.global_queue.put(ConnectorFatalEvent(
            time=datetime.now(UTC), reason=HaltReason.CONNECTOR_FATAL.value))

    def _notify_status_change(
        self,
        old_status: SystemStatus,
        new_status: SystemStatus,
        error_msg: Optional[str],
    ) -> None:
        """Facade status-change enrichment callback injected into SafetyController (§11e).

        The pure ``SafetyController`` owns the status flip + its own log; it invokes THIS
        callback (OUTSIDE its ``_status_lock``, on the winning transition only) to fire the
        external ``status_callback`` with the facade-side exchange / queue-size enrichment
        the machine deliberately does not hold.
        """
        # Notify external systems via callback
        if self.status_callback:
            try:
                status_data = {
                    'status': new_status.value,
                    'exchange': self.exchange,
                    'queue_size': self.get_queue_size(),
                    'timestamp': datetime.now(UTC).isoformat(),
                    'error': error_msg
                }
                self.status_callback(new_status, status_data)
            except Exception as e:
                self.logger.error(f'Error in status callback: {e}')
    
    def _update_stats(self, event_type: Optional[str] = None):
        """Update internal statistics."""
        with self._stats_lock:
            if event_type:
                self._stats['events_processed'] += 1
                self._stats['last_event_time'] = datetime.now(UTC).isoformat()

                # IN-04: compare against the enum name (caller passes event.type.name,
                # so EventType.ORDER.name == 'ORDER' holds the same str contract).
                if event_type == EventType.ORDER.name:
                    self._stats['orders_executed'] += 1

    def _record_bar_metrics(self, event) -> None:
        """Record the per-bar equity curve on ``EventType.BAR`` (D-16 / WR-01 fix).

        The live daemon previously keyed metric recording on ``EventType.TIME``, but
        ``LiveBarFeed`` emits ONLY ``BarEvent`` on the live path (no ``TimeEvent`` —
        the bar's arrival IS the event), so the TIME key never fired and the live
        equity curve was always empty (WR-01). Key on ``EventType.BAR`` and stamp each
        snapshot with the bar-open BUSINESS time (``event.time``), never wall-clock
        (D-09), iterating the active portfolios exactly like the backtest path (the
        offline ``TestRunner`` direct ``record_metrics`` per bar is the reference).

        Runs on the engine (queue-draining) thread — off the connector asyncio
        coroutine — on the async/best-effort path (D-10): a lost tail of the equity
        curve is harmless/recomputable, so recording it must never stall the loop.
        Non-BAR events are a no-op (guard-clause early exit).
        """
        if getattr(event, 'type', None) != EventType.BAR:
            return
        for portfolio in self.portfolio_handler.get_active_portfolios():
            portfolio.record_metrics(event.time)

    def _initialize_live_session(self):
        """Initialize the live trading session by delegating to ``SessionInitializer``.

        RUN-04 live / RUN-05 / RUN-06 / D-12: the ~175-line inline wiring collapses
        into the ``SessionInitializer`` collaborator over the shared phase seams
        (``wire_universe`` / ``register_strategy_warmup`` / the first-class
        ``UniverseHandler`` / ``LiveRouteRegistrar``). Invoked at ``start()`` (and by the
        offline test driver ``TestRunner`` before its per-bar drive). IDEMPOTENT
        (D-12/06-06): a ``self._session_initialized`` guard early-returns on a second
        call, so no lifecycle path double-inits. The ``try/except`` maps a wiring failure
        to ``SystemStatus.ERROR``. Per D-04 the facade's safety/reconcile/stream method
        bodies are untouched.
        """
        if self._session_initialized:
            return
        self.logger.info('Initializing live trading session')

        try:
            # 06.1-04 (D-13): SessionInitializer / UniverseHandlerConfig hoisted to
            # module top (the barrel drop removed this module from the backtest import
            # graph, so their module-top import no longer touches the backtest path).
            # ``config`` stays lazy here — it is read only inside this body.
            from itrader import config as _system_config

            # 06.1-02 (D-10): read the REAL compose Engine injected at construction
            # (build_live_system now calls compose_engine and injects the result). The
            # interim hand-assembled Engine holder (with its placeholder clock /
            # time_generator) is gone — self._engine IS the compose graph.
            engine = self._engine

            # The uniformly-resolved venue exchange (D-11): the OKX exchange when
            # present, else the paper 'simulated' exchange (permissive validate_symbol /
            # resolve_precision defaults). set_venue_metadata is UNCONDITIONAL over this
            # inside SessionInitializer — no OKX guard, zero OKX coupling.
            venue_exchange = (
                self._okx_exchange if self._okx_exchange is not None
                else self.execution_handler.exchanges.get('simulated'))

            # RUN-06/D-11 live-plane config: poll timeframe + remove_policy READ FROM the
            # LIVE/monitoring config (NOT PerformanceSettings — §8/D-01 keeps the
            # backtest oracle config untouched).
            universe_config = UniverseHandlerConfig(
                poll_timeframe=_system_config.stream.okx_stream_timeframe,
                remove_policy=_system_config.monitoring.universe_remove_policy,
            )

            # D-12: delegate the whole live session wiring to SessionInitializer
            # (wire_universe -> register_strategy_warmup -> subscription guard ->
            # first-class UniverseHandler -> LiveRouteRegistrar). SAFE-03/§11c: the
            # freeze-gate now reads the injected SafetyController, and safety +
            # stream_recovery are threaded to the registrar so it can SET the CONTROL
            # routes (STREAM_STATE/CONNECTOR_FATAL) to their engine-thread actuators.
            initializer = SessionInitializer(
                engine,
                universe_config=universe_config,
                venue_exchange=venue_exchange,
                data_provider=self._okx_data_provider,
                freeze_gate=(
                    lambda: self._safety.is_halted()
                    or self._safety.is_submission_paused()),
                safety=self._safety,
                stream_recovery=self._stream_recovery,
            )
            self._universe_handler = initializer.initialize()
            # wire_universe set engine.universe; mirror it onto the facade (start()
            # reads self.universe.members).
            self.universe = engine.universe

            # Idempotency latch (D-12): a second call (a restart start(), or a direct
            # test re-invocation) is a no-op — set AFTER the wiring succeeds so a failed
            # init can be retried.
            self._session_initialized = True
            self.logger.info('Live trading session initialized')
            
        except Exception as e:
            self.logger.error(f'Failed to initialize live session: {e}')
            self._safety.update_status(SystemStatus.ERROR, str(e))
            raise
    
    def start(self):
        """
        Start the live trading system by initializing the session
        and starting the event processing thread.
        """
        if self._running:
            self.logger.warning('Live trading system is already running')
            return False

        # WR-02: hard programming-error signal for a facade constructed outside
        # build_live_system() (LiveRunner/ErrorPolicy unwired). MUST sit ABOVE the
        # start() try-block below — inside it the broad `except Exception` would
        # swallow this and mask it as SystemStatus.ERROR + return False.
        if (self._live_runner is None or self._error_policy is None
                or self._safety is None):
            raise StateError(
                "LiveTradingSystem",
                "unwired",
                required_state="built via build_live_system() (LiveRunner/ErrorPolicy/SafetyController attached)",
                operation="start",
            )

        self.logger.info('Starting live trading system')
        self._safety.update_status(SystemStatus.STARTING)
        
        try:
            # SAFE-02/§11b (D-20 / WR-01): the DURABLE halt refusal gate runs FIRST —
            # right after STARTING and BEFORE any session init / OKX connect / feed warmup
            # / stream spawn / VenueAccount.snapshot() / VenueReconciler.reconcile().
            # ``SafetyController.check_durable_halt_on_start()`` re-latches this fresh
            # instance HALTED from an unresolved durable record (via update_status, NOT
            # halt() — no second durable write) and returns True so start() refuses
            # RUNNING INERT: zero venue I/O, no state-mutating reconcile, no second durable
            # record. A clean/absent store is a no-op (False). Sits before the D-17
            # error-policy bind so a refused start does not even install the live policy.
            if self._safety.check_durable_halt_on_start():
                self._running = False
                return False

            # D-17 (error-policy split, WR-04): install the live publish-and-continue
            # policy HERE — on the daemon/live path ONLY. A live session can't abort on
            # one handler error (it must emit an ErrorEvent and keep draining, RES-01
            # hardening); the offline deterministic ``TestRunner`` driver never reaches
            # this bind (it never calls start()), so it keeps the base fail-fast re-raise
            # so a handler failure aborts the replay loudly and the parity gate can't
            # false-green (T-05-28 / D-19).
            self.event_handler._on_handler_error = self._error_policy.on_handler_error  # type: ignore[method-assign]

            # Initialize the live session
            self._initialize_live_session()

            # CR-02 / 05-06 (VENUE-06, D-06): perform the venue connector's network
            # connect HERE via the VenueLifecycle (build client + load_markets on the
            # daemon-thread loop), deferred out of __init__ so construction stays
            # I/O-free. A failure propagates to the except below, which sets
            # SystemStatus.ERROR and returns False — never an unhandled raise.
            # lifecycle.start() connects the connector ONLY when the bundle carries one
            # (a paper bundle has connector=None, so start() no-ops the connector step
            # via a structural None-guard, D-10); an unregistered venue has no
            # lifecycle at all. stop() tears the connector down unconditionally (CR-01).
            if self._venue_lifecycle is not None:
                self._venue_lifecycle.start()

            # Phase 3 (FEED-05, RESEARCH Thread hand-off): warm the LIVE feed BEFORE
            # the socket goes live so every update() stays on the one thread until the
            # stream starts (single-writer ring/guard). Gated to the OKX arm — a
            # non-OKX venue has no provider, so the None provider is never dereferenced
            # (mirrors the CR-02 venue-guard). Warmup MUST precede start_stream.
            if self._okx_data_provider is not None:
                # Plan 06-05 (D-05): un-hardcode the stream symbol — the live
                # subscription set is now SOURCED FROM MEMBERSHIP. For each member,
                # warm the feed FIRST (REST replay sets the ring) THEN subscribe the
                # live socket (warmup-before-subscribe, Pitfall 6 — never reorder),
                # replacing the single-symbol start_stream() with the per-member
                # dynamic subscribe() seam (plan 02). A one-symbol universe subscribes
                # exactly that one symbol, so the single wiring-time default falls out
                # naturally. The config.stream timeframe remains the live timeframe.
                from itrader import config as _system_config
                members = self.universe.members if self.universe is not None else []
                for sym in members:
                    self.feed.warmup(sym, _system_config.stream.okx_stream_timeframe)
                    self._okx_data_provider.subscribe(sym)

            # CR-01 (RECON-02, RES-01): spawn the order-arm venue streams. This is
            # the SOLE spawn site for OkxExchange._stream_fills()/_stream_orders()
            # (okx.py connect() -> connector.spawn) — without it no real FillEvent
            # ever streams back, the order mirror stays PENDING forever and the
            # 05-08 order-arm reconnect supervisor is dead code in production.
            # Done AFTER the connector client + load_markets are live (the watch_*
            # streams need them) and BEFORE the VenueReconciler.reconcile() below,
            # so the fill/order streams are live during reconcile (the 05-05 fill-ID
            # dedup covers the concurrent-stream case). connect() RETURNS a
            # ConnectionResult and never raises (unlike the connector), so a bare
            # call would swallow a failure — check .success and re-raise so the
            # failure flows through the existing except block (SystemStatus.ERROR,
            # return False); do NOT invent a second error path.
            if self._okx_exchange is not None:
                result = self._okx_exchange.connect()
                if not result.success:
                    raise RuntimeError(
                        f'OKX exchange stream connect failed: {result.error_message}')

            # SAFE-05/§11d (D-17): the startup rehydrate -> venue-reconcile (venue-truth
            # accounts ONLY) -> baseline-guard sequence is owned by the
            # ReconciliationCoordinator (replaces the former inline rehydrate + venue
            # snapshot/link/reconcile + baseline-guard block). It runs on the ENGINE
            # thread BEFORE RUNNING: durable ledger RESTORE (D-23, any account kind), then
            # — keyed on account KIND (Account.is_venue_truth, NOT exchange=='okx') — the
            # venue REST reconcile + the baseline guard that HALTs (via the injected
            # SafetyController.halt) on an unexplained base-asset residual. Built HERE from
            # the CURRENT venue fields (they are live/swappable before start()); a paper/
            # simulated (compute) account restores its ledger and returns without the venue
            # reconcile; a None venue account is a clean skip.
            self._build_reconciliation_coordinator().run_startup_reconcile()

            # 05.3-08 (D-20 / WR-01): the DURABLE halt refusal gate that used to sit HERE
            # (after the full OKX handshake + reconcile) was moved to the TOP of start()
            # so a durably-HALTED engine refuses INERT — zero venue I/O, no state-mutating
            # reconcile, no second durable record. Only the D-05 in-process check below
            # remains at this position, to latch a halt raised DURING this run's
            # reconcile/baseline guard.

            # D-05 (V17-03): a reconcile/guard halt during session init must LATCH.
            # The VenueReconciler.reconcile() above (or the baseline guard) may have
            # called self.halt(...) because it could not trust venue state. REFUSE to
            # enter RUNNING from HALTED: do NOT spawn the processing thread (its first
            # action is the unconditional _update_status(RUNNING) stamp) and do NOT open
            # the SIGNAL/ORDER gate. The engine stays HALTED until an explicit operator
            # reset_halt() re-runs the verify-then-trust sequence. update_status already
            # refuses HALTED->RUNNING as a second line of defence; this check keeps
            # start() from even spawning the loop and returns False so the caller sees the
            # refusal. The stop() teardown in the caller's finally is safe (no thread).
            if self._safety.is_halted():
                self.logger.error(
                    'start() refused RUNNING: engine HALTED during session init '
                    '(reason=%s) — the reconciler/baseline guard declared venue state '
                    'untrustworthy; not spawning the processing thread',
                    self._safety.status_snapshot()['halt_reason'])
                self._running = False
                return False

            # RUN-02 (D-05/D-06): delegate the drain-loop + poll-timer lifecycle to the
            # injected LiveRunner. LiveRunner.start() clears the shared _stop_event once,
            # spawns the drain daemon (ex _event_processing_loop), and starts its composed
            # WorkerSupervisor (ex _run_poll_timer) — so the facade owns neither thread.
            # _running is set BEFORE start() so a status callback fired from the loop-entry
            # hook (_on_loop_start -> RUNNING stamp) already observes the running facade.
            self._running = True
            self._live_runner.start()

            self.logger.info('Live trading system started successfully')
            return True
            
        except Exception as e:
            self.logger.error(f'Failed to start live trading system: {e}')
            self._safety.update_status(SystemStatus.ERROR, str(e))
            self._running = False
            return False
    
    def stop(self, timeout=10.0):
        """
        Stop the live trading system gracefully.
        
        Parameters
        ----------
        timeout : float
            Maximum time to wait for the thread to stop (seconds)
        """
        # CR-01: tear down the OKX connector UNCONDITIONALLY, independent of
        # _running. The connector is constructed (and, once started, connected) in
        # the live wiring; any lifecycle that constructs-then-stops without a
        # successful start() — validation, a failed start(), status inspection, or
        # GC — must still cancel every spawned stream task and close the
        # ccxt/native sessions, or an authenticated demo/live socket leaks (a
        # ResourceWarning under the strict suite, a dangling venue connection in
        # production). The disconnect therefore lives in a finally so it runs on
        # every return path, including the early "not running" exit. disconnect()
        # is a safe no-op when the connector was never connected (its loop is None).
        # 05-06 (VENUE-06, D-06): teardown is delegated to VenueLifecycle.stop(),
        # which drives ConnectorProvider.close_all() (disconnect every memoized
        # connector) — a safe no-op for paper (empty memo) and for an unregistered
        # venue (lifecycle is None, guarded below).
        lifecycle = getattr(self, '_venue_lifecycle', None)
        try:
            if not self._running:
                self.logger.warning('Live trading system is not running')
                return True

            self.logger.info('Stopping live trading system')
            self._safety.update_status(SystemStatus.STOPPING)

            # RUN-02 (D-05/D-06): delegate the drain-loop + poll-timer teardown to the
            # injected LiveRunner — it sets the shared _stop_event, joins the drain thread,
            # then stops the composed WorkerSupervisor. Replaces the facade-owned
            # _thread/_poll_timer_thread join bookkeeping.
            if self._live_runner is not None:
                self._live_runner.stop(timeout=timeout)

            self._running = False
            self._safety.update_status(SystemStatus.STOPPED)

            self.logger.info('Live trading system stopped')
            return True
        finally:
            # Plan 02-05 / 05-06 (D-04 shutdown): tear down the venue connector via the
            # VenueLifecycle — cancel every spawned stream task and close the
            # ccxt/native sessions so no leaked socket / ResourceWarning survives
            # across runs. lifecycle.stop() drives ConnectorProvider.close_all().
            if lifecycle is not None:
                try:
                    lifecycle.stop()
                except Exception as e:
                    self.logger.error(f'Error disconnecting venue connector: {e}')
            # 05-06: dispose the operational SQL spine (the CachedSql* stores compose it)
            # so its connection pool is closed at shutdown — an undisposed engine leaks a
            # socket / ResourceWarning under filterwarnings=["error"]. Safe no-op when the
            # in-memory fallback was used (backend is None). Runs on every return path.
            backend = getattr(self, '_system_db_backend', None)
            if backend is not None:
                try:
                    backend.dispose()
                except Exception as e:
                    self.logger.error(f'Error disposing operational SQL backend: {e}')
    
    def is_running(self) -> bool:
        """
        Check if the live trading system is currently running.
        
        Returns
        -------
        bool
            True if the system is running, False otherwise
        """
        runner = self._live_runner
        thread = runner._thread if runner is not None else None
        return self._running and thread is not None and thread.is_alive()
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive system status information.
        
        Returns
        -------
        dict
            System status information including statistics
        """
        # §11e: the status latch lives on the injected SafetyController — read its
        # snapshot (status + halt/pause reasons) and MERGE the facade-side stats + the
        # D-09 throttle breach counter (the P9 read-model) into one status view.
        snap = self._safety.status_snapshot()
        status = snap['status']
        with self._stats_lock:
            uptime = None
            if self._stats['uptime_start'] and status == SystemStatus.RUNNING:
                start_time = datetime.fromisoformat(self._stats['uptime_start'])
                # WR-05: uptime_start is now stored tz-aware (datetime.now(UTC)),
                # so the comparand must also be tz-aware or this subtraction
                # raises "can't subtract offset-naive and offset-aware datetimes".
                uptime = (datetime.now(UTC) - start_time).total_seconds()

            return {
                'status': status.value,
                # 05-04 (D-07): the machine-readable halt reason (None unless HALTED).
                'halt_reason': snap['halt_reason'],
                # 05-08 (D-19): the reversible pause-on-disconnect state, surfaced
                # DISTINCTLY from the terminal halt (paused != HALTED).
                'paused': snap['paused'],
                'paused_reason': snap['paused_reason'],
                'is_running': self.is_running(),
                'exchange': self.exchange,
                'queue_size': self.get_queue_size(),
                # D-09 (SAFE-06): the pre-trade throttle breach counter read-model
                # (0 until the throttle is wired by build_live_system).
                'throttle_breach_count': (
                    self._throttle.breach_count if self._throttle is not None else 0),
                'thread_alive': (
                    self._live_runner._thread.is_alive()
                    if self._live_runner is not None and self._live_runner._thread
                    else False),
                'thread_name': (
                    self._live_runner._thread.name
                    if self._live_runner is not None and self._live_runner._thread
                    else None),
                'last_error': snap['last_error'],
                'statistics': {
                    **self._stats,
                    'uptime_seconds': uptime
                },
                'timestamp': datetime.now(UTC).isoformat()
            }
    
    def get_queue_size(self) -> int:
        """
        Get the current size of the global event queue.
        
        Returns
        -------
        int
            Number of events in the queue
        """
        return self.global_queue.qsize()
    
    def get_signal_records(self):
        """Return the signals captured during the live run (WR-03).

        Mirrors ``TradingSystem.get_signal_records``: reads the injected
        signal-store sink. A read-model sink read, NOT a cross-domain handler
        call — the queue-only contract is preserved.
        """
        return self._signal_store.get_all()

    def get_signal_store(self):
        """Return the signal-store itself for filtered queries (WR-03).

        Exposes ``by_strategy`` / ``by_ticker`` for inspection, mirroring
        ``TradingSystem.get_signal_store``.
        """
        return self._signal_store

    def add_event(self, event):
        """
        Add an event to the global queue for processing.

        D-10 (fail-closed, ASVS V4/V5): ``add_event`` is the engine's PUBLIC external/web
        surface, so it is DEFAULT-DENY. Only the two sanctioned externally-originated event
        types in ``_EXTERNALLY_ADMISSIBLE`` are admitted — a ``SIGNAL`` (routes through
        ``OrderHandler.on_signal`` -> ``AdmissionManager`` so validation + sizing + cash
        reservation + order-mirror engage before any ``OrderEvent`` is emitted) and a
        ``STRATEGY_COMMAND`` (an operator add/remove-ticker command). EVERY other type is
        rejected: every internal-fact type (FILL / BAR / UNIVERSE_UPDATE / UNIVERSE_POLL /
        BARS_LOADED / BARS_LOAD_FAILED / TIME / ORDER / ERROR / PORTFOLIO_UPDATE ...) is not
        admissible from the external surface — a raw ``OrderEvent`` here would otherwise reach
        the execution queue with NO admission control (elevation-of-privilege / input-validation
        defect). This inverts the prior narrow ORDER-only denylist (fail-open -> fail-closed):
        the sanctioned entry stays SIGNAL-form. The internal order flow is UNAFFECTED —
        handlers emit ``OrderEvent``s by putting them on ``global_queue`` directly, never
        through ``add_event`` (RESEARCH OQ7: zero internal production callers).

        Parameters
        ----------
        event
            The event to add to the queue

        Returns
        -------
        bool
            True if event was added successfully, False otherwise
        """
        if not self._running:
            self.logger.warning('Cannot add event: Live trading system is not running')
            return False

        # D-10: FAIL-CLOSED allowlist. Admit ONLY the sanctioned externally-originated types
        # (SIGNAL + STRATEGY_COMMAND); reject every other type by default (default-deny). This
        # covers the prior narrow ORDER reject and every other internal-fact type in one gate.
        event_type = getattr(event, 'type', None)
        if event_type not in _EXTERNALLY_ADMISSIBLE:
            self.logger.warning(
                'Rejected external add_event of type %s (D-10 fail-closed default-deny) — only '
                'SIGNAL and STRATEGY_COMMAND are admissible from the external surface; every '
                'internal-fact type (incl. raw ORDER injection) must route through the engine '
                'internally, never the public queue directly', event_type)
            return False

        try:
            self.global_queue.put(event)
            return True
        except Exception as e:
            self.logger.error(f'Failed to add event to queue: {e}')
            return False
    

    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


def build_live_system(
    spec: Any,
    *,
    status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
    data_plugins: Optional[Dict[str, Any]] = None,
) -> LiveTradingSystem:
    """The live composition root (RUN-01/D-09) — the ONLY live construction path.

    The live analog of ``build_backtest_system -> compose_engine -> BacktestRunner``:
    reads centralized config, builds the ONE live ``sql_engine`` (Postgres-gated),
    builds the live component graph off the **PriorityEventBus** (D-23 — inert without
    CONTROL events), relocates the P5 ``assemble_venue`` call out of ``__init__``,
    constructs the facade via PURE INJECTION, and composes the ``LiveRunner`` (owning
    the drain loop, D-06) + its ``WorkerSupervisor`` (D-05) + the minimal ``ErrorPolicy``
    (D-07) around it. Returns the fully-wired facade.

    D-12 (interim): live session wiring (``SessionInitializer`` via
    ``_initialize_live_session``) stays DEFERRED to ``start()`` (06-06 kept the
    construction-time flip deferred — it conflicts with the pervasive
    add-strategy-after-construction + monkeypatch-``_initialize_live_session``-before-
    ``start()`` contracts across the live test suite). The offline test driver
    ``TestRunner`` (tests/support/replay_harness) invokes it before its per-bar drive.

    D-21: production ``paper`` re-points to the OKX live data feed; the offline replay
    DATA provider left this module for the test harness (TEST-01/D-18). A test fixture
    injects a ``'replay'`` plugin via ``data_plugins`` — production never registers one.

    All live/venue/SQL imports live INSIDE this function body (lazy) so importing this
    module (via the ``trading_system`` barrel, on the backtest import graph) pulls NO
    ccxt.pro / SqlSettings — the recurring inertness gate (``test_okx_inertness.py``).
    """
    logger = get_itrader_logger().bind(component="LiveTradingSystem")
    exchange = spec.execution_venue

    # D-23: live drains the PriorityEventBus (replacing the raw queue.Queue) — inert
    # without CONTROL events (everything flows BUSINESS-tier; the monotonic seq keeps
    # strict FIFO, so live behavior is unchanged in P6). LiveRunner drains it; CONTROL
    # routes are NOT registered (their P7/P9 consumers don't exist yet).
    global_queue = PriorityEventBus()
    # Phase 3 (FEED-05): LiveBarFeed is the live driver — LAZY-imported here so the
    # BACKTEST import path never pulls live_bar_feed (inertness gate). D-02: live carries
    # store=None (the LiveBarFeed reads no store); the whole handler graph — screeners
    # included — now comes from compose_engine below, so no store/screeners are built here.
    from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
    feed = LiveBarFeed(provider=None, base_timeframe=to_timedelta('1d'))

    # ------------------------------------------------------------------
    # v1.6 operational store live-drive (05-06, RECON-04, D-10/D-11).
    # SYNC-DURABLE working set (orders) persists store-first; DERIVED signal store is
    # async/best-effort. Both share ONE SqlEngine. All SQL imports LAZY inside the
    # Postgres arm (inertness). Credential presence read at build time (per-construction)
    # through a lazy default ``SqlSettings()`` probe — the SQLite default driver skips
    # ``_require_pg_credentials``, so the probe never raises when credentials are absent
    # while still sourcing ``ITRADER_DATABASE_*`` env into ``password``/``url`` (IN-01).
    from itrader.config.sql import SqlSettings
    probe = SqlSettings()
    if probe.password is None and probe.url is None:
        # WR-10: fail loudly into the in-memory fallback (no default credential string).
        logger.warning(
            "No Postgres credential in env (ITRADER_DATABASE_PASSWORD / "
            "ITRADER_DATABASE_URL unset) — using in-memory order + signal storage "
            "(orders/signals will NOT survive a restart)"
        )
        # 06.1-02 (SEAM-01/D-05): the arm now selects ONLY the environment string + the
        # shared SQL spine — compose_engine's handler-OWNED storage init derives the
        # concrete backends from (environment, sql_engine). 'backtest' with sql_engine=None
        # yields the in-memory order + signal stores byte-identical to the former explicit
        # fallback construction (OrderStorageFactory.create('backtest') / create_in_memory()).
        environment = 'backtest'
        system_db_backend: Optional[Any] = None
    else:
        # CR-01/RECON-04: honor the unified ITRADER_DATABASE_* Postgres surface — one
        # SqlEngine drives the whole v1.6 operational store (same source Alembic uses).
        from itrader.config.sql import SqlDriver, SqlSettings
        from itrader.storage import SqlEngine

        # 06.1-02 (SEAM-01/D-05): 'live' + the shared SqlEngine drive compose's
        # handler-OWNED storage to the SAME durable path the former explicit construction
        # built — orders via CachedSqlOrderStorage(SqlOrderStorage(backend)) (store-first
        # working set, rehydrate() on restart), the signal store live-driven over the same
        # spine (see OrderStorageFactory / SignalStorageFactory '.create('live', ...)').
        backend = SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
        environment = 'live'
        system_db_backend = backend

    # 05.2-06 (D-10 / ARCH-4 Layer 2): durable halt-record store over the shared spine
    # (survives a process restart) — None on the in-memory fallback (degrade cleanly).
    # D-09: the SQL spine (system_db_backend) + halt_record_store stay SEPARATE facade/
    # infra handles — NOT folded into the venue holder (folding would recreate the bag).
    if system_db_backend is not None:
        from itrader.storage.halt_record_store import HaltRecordStore
        halt_record_store: Optional[Any] = HaltRecordStore(system_db_backend)
    else:
        halt_record_store = None

    # ------------------------------------------------------------------
    # 06.1-02 (SEAM-01 live consumption / D-05): obtain the live handler graph from the
    # now spec-free compose_engine instead of hand-rolling a parallel copy. The shared
    # EngineContext is the mode-injection seam: feed=the LiveBarFeed, store=None (the
    # LiveBarFeed reads no store, D-02), and environment + sql_engine reflect the
    # credential-probe arm so compose's handler-OWNED storage init lands the identical
    # durable path (Postgres arm -> CachedSqlOrderStorage over the SQL spine; in-memory
    # arm -> InMemoryOrderStorage). Live keeps exchange_config=None (the ExecutionHandler
    # default today — byte-preserving) and results_store=None. compose_engine reuses the
    # FeeModelCommissionEstimator admission adapter, retiring the re-inlined commission
    # closure. compose_engine is a PURE import, taken lazily here to mirror the module's
    # lazy-import discipline (inertness gate). 06.1-04 (D-13): EngineContext is now
    # hoisted to module top (pure — off the backtest graph after the barrel drop).
    from itrader import config as _system_config
    from itrader.trading_system.compose import compose_engine

    ctx = EngineContext(
        bus=global_queue,
        config=_system_config,
        environment=environment,
        feed=feed, store=None,
        sql_engine=system_db_backend,
    )
    engine = compose_engine(ctx, exchange_config=None, results_store=None)

    # compose already wired portfolio_handler.set_order_storage(order_handler.storage) and
    # the FeeModelCommissionEstimator admission gate (D-05), so the former inline commission
    # closure + the duplicate set_order_storage call are gone. build_live_system only needs
    # the three handles its remaining venue + post-facade wiring touches; the facade sources
    # the FULL graph (+ storages, store=None) off the engine in __init__ (D-10), so no
    # duplicate locals are threaded through here.
    execution_handler = engine.execution_handler
    portfolio_handler = engine.portfolio_handler
    event_handler = engine.event_handler

    # ------------------------------------------------------------------
    # Venue wiring (Plan 02-05, D-04 / CONN-04 — relocated P5 D-06 assemble_venue call).
    # The whole OKX/paper venue stack is LAZY-imported here so the BACKTEST import path
    # stays async/ccxt/credential-free (the hot-path inertness gate).
    # The single VenueLifecycle holder (D-07) + the two streaming handles the post-facade
    # halt-signal wiring still needs (okx_exchange/okx_connector). The facade __init__
    # sources ALL venue/connector fields (bundle/account/provider) off the lifecycle (D-08)
    # — build_live_system no longer field-by-field unpacks it.
    venue_lifecycle: Optional[Any] = None
    okx_connector: Optional[Any] = None
    okx_exchange: Optional[Any] = None

    from itrader.connectors.provider import ConnectorProvider
    from itrader.venues.assemble import assemble_venue
    from itrader.venues.okx_plugin import (
        OkxConnectorPlugin,
        OkxDataPlugin,
        OkxVenuePlugin,
    )
    from itrader.venues.paper_plugin import PaperVenuePlugin
    from itrader.venues.registry import (
        DataProviderRegistry,
        ExecutionVenueRegistry,
    )

    # (1) Build the two registries + the shared ConnectorProvider and register the
    # concrete plugins (store-only — no build*() runs, so this pulls no ccxt).
    exec_registry = ExecutionVenueRegistry()
    data_registry = DataProviderRegistry()
    connectors = ConnectorProvider({'okx': OkxConnectorPlugin()})
    exec_registry.register('okx', OkxVenuePlugin())
    exec_registry.register(
        'paper', PaperVenuePlugin(execution_handler.exchanges['simulated']))
    data_registry.register('okx', OkxDataPlugin())

    # TEST-only DATA provider injection (D-21): production registers NO replay/test data
    # provider (the replay harness left this package for tests/), but a test fixture may
    # inject one (the relocated TestDataPlugin) so the paper↔replay pairing lives ONLY in
    # the fixture, never in production. Registered AFTER the production plugins.
    if data_plugins:
        for _name, _plugin in data_plugins.items():
            data_registry.register(_name, _plugin)

    # (2) The shared mode-injection EngineContext built above (06.1-02) is REUSED for
    # venue assembly — the venue plugins read ctx.bus / ctx.config.stream (they never read
    # ctx.environment / ctx.store / ctx.sql_engine), so the arm-dependent environment is
    # transparent to venue assembly (D-23: live drains the PriorityEventBus ctx.bus wires).
    # D-21: production paper re-points to the OKX live data feed (the offline replay
    # feed left production for tests/). A TEST fixture injects a 'replay' plugin via
    # data_plugins and passes data_provider='replay' explicitly; production never does.
    # build_venue_spec owns the {okx,paper}->okx default-provider map (D-11 — one home).
    venue_spec = build_venue_spec(
        exchange,
        data_provider=getattr(spec, 'data_provider', None),
        account_id=getattr(spec, 'account_id', None),
    )

    # (3) Delegate venue assembly (registry membership replaces the venue-string branch).
    provider: Optional[Any] = None
    if exchange in exec_registry:
        bundle, venue_lifecycle = assemble_venue(
            ctx, venue_spec, connectors, exec_registry, data_registry)
        provider = venue_lifecycle.provider

        # bundle.connector is the STREAMING-venue discriminator (okx present, paper None).
        # A paper (connector=None) bundle has no streaming okx exchange; its data provider
        # is still wired to the feed below (the injected TEST 'replay' provider in tests, or
        # the OKX data provider in production paper — D-21). The facade __init__ sources
        # _venue_bundle/_venue_account/_okx_data_provider off the lifecycle (D-08); only the
        # streaming-venue execution_handler registration + the halt-signal handles stay here.
        okx_connector = bundle.connector
        if bundle.connector is not None:
            okx_exchange = bundle.exchange
            execution_handler.exchanges[exchange] = bundle.exchange

        # (4) UNIFORM provider->feed wiring (D-10) that needs NO facade method.
        feed.set_provider(provider)
        provider.set_bar_sink(feed.update)
        provider.set_global_queue(global_queue)

    # Construct the facade via DIRECT PURE INJECTION (RUN-03/D-09/D-10): the compose Engine
    # is the single source of truth for the handler graph; the VenueLifecycle is the single
    # venue/connector holder (D-07); the SQL spine + halt store stay SEPARATE infra handles
    # (D-09). No LiveSystemComponents bag — the facade sources everything off these directly.
    facade = LiveTradingSystem(
        engine=engine,
        lifecycle=venue_lifecycle,
        system_db_backend=system_db_backend,
        halt_record_store=halt_record_store,
        exchange=exchange,
        status_callback=status_callback,
    )

    # ------------------------------------------------------------------
    # SAFE-01..06 (§11): construct + ATTACH the four safety collaborators (P7). All
    # imports are LAZY in-body so importing this module (on the backtest import graph)
    # pulls no live safety stack — never barrel-exported (inertness Pitfall 5). Each is
    # a plain injected collaborator with NO facade back-reference beyond the callbacks it
    # is handed; the facade is a thin delegator over them.
    from itrader.core.clock import WallClock
    from itrader.trading_system.safety.pre_trade_throttle import PreTradeThrottle
    from itrader.trading_system.safety.safety_controller import SafetyController
    from itrader.trading_system.safety.stream_recovery_handler import (
        StreamRecoveryHandler,
    )

    # SAFE-01/02: the pure state machine. dispatch_fn is LATE-BOUND (lambda over
    # event_handler._dispatch) so the gate always dispatches through the CURRENT inner
    # dispatch — preserving the donor _dispatch_live's live read (a test/monkeypatch of
    # event_handler._dispatch is honoured, and gate_and_dispatch replay reaches it too).
    # notify_status_change is the facade's enrichment callback (external status_callback +
    # exchange/queue-size); halt_record_store is the durable spine (None on in-memory).
    safety = SafetyController(
        bus=global_queue,
        halt_record_store=halt_record_store,
        dispatch_fn=lambda ev: event_handler._dispatch(ev),
        notify_status_change=facade._notify_status_change,
    )
    # SAFE-04: engine-thread reconnect-resume I/O (catch-up + snapshot + all-streams gate
    # -> resume). Injected with the venue arms the facade sourced off the lifecycle; each
    # may be None on a non-OKX wiring (guard-claused inside on_reconnect).
    stream_recovery = StreamRecoveryHandler(
        safety=safety,
        okx_exchange=facade._okx_exchange,
        venue_account=facade._venue_account,
        okx_data_provider=facade._okx_data_provider,
    )
    # SAFE-06: pre-trade risk backstop (rate + notional caps). Off the WALL clock (the
    # live determinism seam) + the static config.safety.throttle caps.
    throttle = PreTradeThrottle(
        settings=_system_config.safety.throttle,
        clock=WallClock(),
        bus=global_queue,
    )
    # SAFE-05: the ReconciliationCoordinator is constructed at start() (in
    # _build_reconciliation_coordinator) rather than here — it must read the CURRENT
    # venue account / exchange / connector at reconcile time (the venue arms are the live
    # facade fields, swappable before start() for offline runs), not a build-time capture.
    facade._safety = safety
    facade._stream_recovery = stream_recovery
    facade._throttle = throttle

    # Facade-dependent wiring (references the constructed facade's own callbacks). The
    # provider/exchange/connector halt-signal + stream-state listeners for a registered
    # venue now emit CONTROL events (§11c): _request_connector_halt -> ConnectorFatalEvent,
    # _on_venue_stream_down/up -> StreamStateEvent(down/up). No flag flips.
    if provider is not None:
        provider.set_halt_signal(facade._request_connector_halt)
        provider.set_stream_state_listener(
            facade._on_venue_stream_down, facade._on_venue_stream_up)
        if okx_exchange is not None:
            okx_exchange.set_halt_signal(facade._request_connector_halt)
            okx_exchange.set_stream_state_listener(
                facade._on_venue_stream_down, facade._on_venue_stream_up)
            okx_connector.set_halt_signal(facade._request_connector_halt)

    # 05-04 (D-06): CRITICAL/halt alert sink at the composition root (only declared
    # ErrorEvent fields bound — no connector secret leaks, Pitfall 16 / T-05-01).
    event_handler._alert_sink = LogAlertSink()
    # 05-04 (D-01/D-02): engine-thread drift-halt signal -> freeze-in-place halt (the
    # facade delegator forwards to SafetyController.halt).
    portfolio_handler.set_halt_signal(facade.halt)

    # RUN-02 (D-05/D-06/D-07/D-08): the live runtime engine. LiveRunner OWNS the drain
    # loop; it COMPOSES the WorkerSupervisor (poll timer, D-05) and takes the minimal
    # ErrorPolicy (D-07). SAFE-03/D-06 (P7): the dispatch gate is repointed to
    # SafetyController.gate_and_dispatch (the freeze-in-place gate), and the pre-submit
    # throttle (PreTradeThrottle.allow) fires at the ORDER->execution boundary ahead of
    # it. The former resume/halt per-tick drain hooks are GONE (CONTROL events replace the
    # flag side-channel). The facade's error-policy install happens in start() (D-17).
    from itrader.trading_system.error_policy import ErrorPolicy
    from itrader.trading_system.live_runner import LiveRunner
    from itrader.trading_system.worker_supervisor import WorkerSupervisor

    cadence = _system_config.monitoring.universe_poll_cadence_s
    error_policy = ErrorPolicy(global_queue, error_counter=facade._increment_error_count)
    worker_supervisor = WorkerSupervisor(global_queue, facade._stop_event, cadence)
    live_runner = LiveRunner(
        bus=global_queue,
        stop_event=facade._stop_event,
        error_policy=error_policy,
        worker_supervisor=worker_supervisor,
        dispatch_gate=safety.gate_and_dispatch,
        update_stats=facade._update_stats,
        record_bar_metrics=facade._record_bar_metrics,
        pre_submit=throttle.allow,
        queue_timeout=_LIVE_QUEUE_TIMEOUT,
        max_idle_time=_LIVE_MAX_IDLE_TIME,
        on_loop_start=facade._on_loop_start,
        on_loop_error=facade._on_loop_error,
    )
    facade._live_runner = live_runner
    facade._error_policy = error_policy

    logger.info('Live trading system built', exchange=exchange)
    return facade
