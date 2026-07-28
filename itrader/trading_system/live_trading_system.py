import random
import threading
from datetime import datetime, UTC
from decimal import Decimal
from typing import (
    Optional, Dict, List, Any, Callable, Mapping, TYPE_CHECKING)

from itrader.core.enums import HaltReason, SystemStatus
from itrader.core.exceptions import StateError, ValidationError
from itrader.execution_handler.execution_handler import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID
from itrader.outils.time_parser import to_timedelta
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.trading_system.venue_spec import build_venue_spec
# Only PURE imports belong at module top (no ccxt.pro/SQL/venue substrate). The heavy
# ones — LiveBarFeed, SqlSettings, the SQL spine, ConnectorProvider, okx_plugin,
# assemble_venue, LiveRunner — MUST stay lazy inside build_live_system's body, or
# importing this module drags them onto the backtest import graph
# (tests/integration/test_okx_inertness.py is the gate).
from itrader.trading_system.session_initializer import SessionInitializer
from itrader.trading_system.engine_context import EngineContext
from itrader.universe import Universe
from itrader.universe.universe_handler import UniverseHandlerConfig

from itrader.logger import get_itrader_logger
from itrader.events_handler.bus import PriorityEventBus
from itrader.events_handler.events import EventType, StreamStateEvent, ConnectorFatalEvent

if TYPE_CHECKING:
    # Forward-refs only — importing either eagerly would pull them onto the graph.
    from itrader.trading_system.compose import Engine
    from itrader.venues.lifecycle import VenueLifecycle

# Live drain-loop timing knobs, injected into the LiveRunner (which owns the loop).
_LIVE_QUEUE_TIMEOUT = 1.0   # queue poll
_LIVE_MAX_IDLE_TIME = 300.0  # idle-warn window

# The engine's PUBLIC external/web ingress allowlist — the primary external-surface
# security control. ``add_event`` is FAIL-CLOSED (default-deny, ASVS V4/V5): only these
# three externally-originated types are admissible; every other type, including every
# internal-fact type (FILL/BAR/TIME/ORDER/ERROR/...), is rejected. Internal flow is
# unaffected — handlers put onto ``global_queue`` directly, never through ``add_event``.
_EXTERNALLY_ADMISSIBLE = frozenset(
    {EventType.SIGNAL, EventType.STRATEGY_COMMAND, EventType.CONFIG_UPDATE}
)

# Live order + signal storage is selected by ENV-PRESENCE of a Postgres credential on the
# unified ``ITRADER_DATABASE_*`` surface — the same source Alembic's migrations/env.py
# uses. No hardcoded credential fallback: an unconfigured env falls back to in-memory
# storage with a loud warning. The probe lives in ``build_live_system`` so it honors
# per-construction env, and must run BEFORE constructing a Postgres ``SqlSettings``,
# which raises ``ValidationError`` when no credential is present.

# The live OKX subscription has ONE wiring source: ``config.stream``. The data provider
# stamps that symbol/timeframe into every ClosedBar (the feed's ring key), the feed warms
# up on the same pair, and universe membership is checked against it — so provider args
# and feed.warmup() args cannot drift into a ring-key vs membership mismatch (which would
# surface only as a MissingPriceDataError at the first window()).
# BTC/USDC, not BTC/USDT: the OKX EEA entity restricts USDT spot pairs under MiCA — an
# order on BTC/USDT returns sCode 51155 "local compliance restrictions".


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
        lifecycles: "Optional[Mapping[str, VenueLifecycle]]" = None,
        system_db_backend: Optional[Any] = None,
        halt_record_store: Optional[Any] = None,
        exchange: str,
        status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
    ):
        """Pure-injection facade constructor.

        Holds NO wiring logic — it takes pre-built collaborators and initialises
        fresh per-instance runtime state (status/locks/flags/stats).

        Parameters
        ----------
        engine : Engine
            The compose ``Engine`` — the wired handler graph plus its handler-owned
            storages (``store`` is None on live). The single source of truth.
        lifecycles : Mapping[str, VenueLifecycle], optional
            ONE venue/connector holder PER ACCOUNT, keyed by account id, as
            ``assemble_venues`` returns it. Empty/``None`` when the venue is
            unregistered; paper carries lifecycles with ``connector=None``.
        system_db_backend, halt_record_store : optional
            The SQL spine + durable halt-record store. Storage/durable infra, kept
            separate from the venue holder.
        exchange : str
            The venue-name string (``spec.execution_venue``-derived).
        status_callback : callable, optional
            Callback to notify status changes to external systems.
        """
        self.logger = get_itrader_logger().bind(component="LiveTradingSystem")
        self.status_callback = status_callback

        # Handlers/feed/storages are sourced OFF the engine — never duplicated as fields.
        self._engine = engine
        self.exchange = exchange
        self.global_queue = engine.global_queue
        # None on live — held for interface parity, never read as a real store.
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

        self._system_db_backend: Optional[Any] = system_db_backend
        self._halt_record_store: Optional[Any] = halt_record_store

        # ONE VenueLifecycle per account, keyed by account id. No account is privileged:
        # the feed binds to a CONNECTION via FeedConnectionBinder, not to a lifecycle, so
        # insertion order carries no meaning. Used only for per-account iteration
        # (start/stop, halt-wiring). Read ``.bundle`` / ``.provider`` THROUGH the lifecycle
        # at each use site; the ``bundle.connector is not None`` streaming discriminator is
        # applied there too, since paper carries a lifecycle with connector=None.
        self._venue_lifecycles: Dict[str, Any] = dict(lifecycles) if lifecycles else {}
        # Owns the ONE feed's borrowed connection + provider; re-borrows when an account is
        # retired. None on the in-memory arm — ``feed_provider`` None-guards it.
        self._feed_binder: Optional[Any] = None

        # Collaborators ATTACHED by build_live_system after construction — they reference
        # this facade's own callbacks, so they can only be built once it exists. The facade
        # is a thin delegator over them. All None on a facade built outside
        # build_live_system, where the corresponding routes stay pre-declared empty slots.
        self._safety: Optional[Any] = None
        self._stream_recovery: Optional[Any] = None
        self._throttle: Optional[Any] = None
        self._config_router: Optional[Any] = None
        # Strategies that could NOT be rehydrated at boot (retired class, or a config blob
        # that no longer deserializes). A DEDICATED field, not folded into ``last_error``:
        # that is single-valued and the next error would overwrite it, losing the list —
        # and this list is what tells an operator which strategies are silently not trading.
        self._quarantined_strategies: list[str] = []

        # Read-model sinks, attached post-construction and gated on the SQL spine (None on
        # the in-memory fallback). _system_store is the durable KV for state.*;
        # _system_stats_store is the append-only engine-operational stats series.
        self._system_store: Optional[Any] = None
        self._system_stats_store: Optional[Any] = None

        # The facade owns _stop_event so stop() can latch shutdown; it is honoured by both
        # the injected LiveRunner drain loop and its composed WorkerSupervisor.
        self._running = False
        self._stop_event = threading.Event()

        self._stats = {
            'events_processed': 0,
            'orders_executed': 0,
            # A throttle-REFUSED order never reached execution (it only emitted a
            # FillEvent(REFUSED)), so it is counted here rather than in orders_executed —
            # otherwise the read-model over-reports submissions.
            'orders_throttle_rejected': 0,
            'last_event_time': None,
            'uptime_start': None,
            'errors_count': 0
        }
        self._stats_lock = threading.Lock()

        # "Not yet wired" sentinels, populated by _initialize_live_session.
        self.universe: Optional[Universe] = None
        self._universe_handler: Optional[Any] = None
        # Session init stays DEFERRED to start() (and to the offline TestRunner, which
        # calls _initialize_live_session before its per-bar drive). Flipping it to
        # construction time conflicts with the pervasive add-strategy-after-construction
        # and monkeypatch-before-start() contracts across the live test suite. The
        # idempotency guard makes a second call a no-op, so no path double-inits.
        self._session_initialized = False

        self._live_runner: Optional[Any] = None
        self._error_policy: Optional[Any] = None

        self.logger.info('Live trading system initialized')

    # ---- Venue reads THROUGH the per-account lifecycle map (11-09) ----------------
    # ONE derived accessor, no stored state: "every streaming lifecycle". 11.2-07 (D-36)
    # DELETED the primary-lifecycle accessor — there is no privileged first account any
    # more (the feed is bound to a connection by FeedConnectionBinder, not a lifecycle).
    # Note what is deliberately NOT here: no ``_okx_exchange`` / ``_venue_account`` /
    # ``_okx_data_provider`` back-compat properties. Re-adding them as read-throughs
    # would keep six names alive while pretending to delete them, and the whole point
    # of holding the object instead of its pieces is that there is nothing left to
    # keep in sync.

    def _streaming_lifecycles(self) -> List[Any]:
        """Every assembled lifecycle whose bundle carries a live connector.

        ``bundle.connector is not None`` is the streaming-venue discriminator used
        throughout this module (paper carries a lifecycle with no connector). Returning
        a list rather than filtering at each call site keeps that one rule in one place.
        """
        return [
            lifecycle for lifecycle in self._venue_lifecycles.values()
            if lifecycle.bundle.connector is not None
        ]

    @classmethod
    def for_exchange(
        cls,
        exchange: str,
        *,
        status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
        **overrides: Any,
    ) -> "LiveTradingSystem":
        """Ergonomic entry point: build a declarative live ``spec`` and delegate.

        NOT a second construction path — ``build_live_system`` remains the one factory.
        ``**overrides`` may carry an explicit ``data_provider``/``account_id`` for a
        bespoke spec, or a ``data_plugins`` map for TEST-only data provider injection.
        """
        data_plugins = overrides.pop('data_plugins', None)
        # build_venue_spec is the one home for the {okx,paper}->okx default-provider map.
        spec = build_venue_spec(
            exchange,
            data_provider=overrides.pop('data_provider', None),
            account_id=overrides.pop('account_id', None),
        )
        return build_live_system(
            spec, status_callback=status_callback, data_plugins=data_plugins)

    def _on_loop_start(self) -> None:
        """LiveRunner loop-entry hook: stamp RUNNING + uptime_start.

        Reached via the injected ``on_loop_start`` callback so the status/stats
        side-effects stay on the facade — the LiveRunner owns no ``SystemStatus``.
        """
        self._safety.update_status(SystemStatus.RUNNING)
        with self._stats_lock:
            self._stats['uptime_start'] = datetime.now(UTC).isoformat()

    def _increment_error_count(self) -> None:
        """Error-counter hook: bump errors_count when ErrorPolicy publishes an ErrorEvent."""
        with self._stats_lock:
            self._stats['errors_count'] += 1

    def _on_loop_error(self, exc: BaseException) -> None:
        """LiveRunner loop catch-all hook: count a loop-level error."""
        self._increment_error_count()

    # ---- Thin safety delegators: the bodies live on the injected SafetyController;
    # ---- the facade forwards so external call sites work over one source of truth. --

    def halt(self, reason: str) -> None:
        """Freeze-in-place halt of the whole engine."""
        self._safety.halt(reason)

    def reset_halt(self) -> bool:
        """Operator-only clear of the latched HALTED state — the only legal exit."""
        return self._safety.reset_halt()

    def is_halted(self) -> bool:
        """Whether the engine is in the freeze-in-place HALTED state."""
        return self._safety.is_halted()

    def pause_submission(self, reason: str) -> None:
        """Reversibly pause NEW order submission on a disconnect."""
        self._safety.pause_submission(reason)

    def resume_submission(self) -> None:
        """Clear the reversible pause after reconnect + a fresh REST snapshot."""
        self._safety.resume_submission()

    def _build_reconciliation_coordinator(self) -> Any:
        """Construct the startup ReconciliationCoordinator from CURRENT venue state.

        Built at ``start()`` rather than in ``build_live_system`` so it reads the LIVE
        handler graph — an offline run swaps collaborators before ``start()`` and the
        reconcile must honour the current values. ``halt`` is the facade delegator, so a
        baseline residual latches the freeze-in-place halt. The import is lazy to keep the
        reconcile module off the backtest import path.

        The coordinator takes NO per-account scalars: it asks each portfolio for its own
        account, takes that account's connector from the account, and resolves its
        exchange out of the pair-keyed ``ExecutionHandler.exchanges`` registry. That makes
        "compare portfolio A against account B" a type error rather than a rule.
        """
        from itrader.portfolio_handler.reconcile.reconciliation_coordinator import (
            ReconciliationCoordinator,
        )
        return ReconciliationCoordinator(
            portfolio_handler=self.portfolio_handler,
            seed_applied_trades=self.order_handler.order_manager.seed_applied_trades,
            order_storage=self._order_storage,
            execution_handler=self.execution_handler,
            global_queue=self.global_queue,
            halt=self.halt,
        )

    def _on_venue_stream_down(self, stream_name: str) -> None:
        """Connector-loop callback: emit a STREAM_STATE(down) CONTROL event.

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
        """Connector-loop callback: emit a STREAM_STATE(up) CONTROL event.

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
        """Connector-loop callback: emit a CONNECTOR_FATAL CONTROL event.

        Fired from the connector ASYNCIO LOOP thread. It ONLY puts a CONTROL event — it
        must NOT drive the blocking ``halt()`` here, whose durable ``record_halt`` SQL
        write would stall every stream sharing the loop (Pitfall 9); the engine-thread
        CONNECTOR_FATAL route runs the blocking halt off the loop.

        The event carries a FIXED reason literal, NEVER ``str(exc)`` or the passed
        ``reason``, so no connector secret crosses the loop->engine boundary.
        """
        self.global_queue.put(ConnectorFatalEvent(
            time=datetime.now(UTC), reason=HaltReason.CONNECTOR_FATAL.value))

    def _notify_status_change(
        self,
        old_status: SystemStatus,
        new_status: SystemStatus,
        error_msg: Optional[str],
    ) -> None:
        """Status-change enrichment callback injected into SafetyController.

        SafetyController owns the status flip; it invokes this callback OUTSIDE its
        ``_status_lock`` and only on the winning transition, to fire the external
        ``status_callback`` with facade-side enrichment the machine does not hold.
        """
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

        # A status transition is a low-rate event, so snapshotting here needs no
        # aggregation layer. No-op when no durable stats sink is wired.
        self._snapshot_system_stats()

    def _snapshot_system_stats(self) -> None:
        """Append one engine-operational counter row to ``system_stats``.

        Snapshots ONLY counters the engine already holds in memory. It must copy NO
        domain-store entity data (portfolio equity and friends are read from their own
        stores) and NO secret. Best-effort: a durable append failure is swallowed-and-
        logged so it can never abort the engine event that triggered it. No-op when no
        durable sink is wired.
        """
        if self._system_stats_store is None:
            return
        try:
            with self._stats_lock:
                errors = self._stats['errors_count']
                uptime_start = self._stats['uptime_start']
            uptime_seconds = Decimal('0')
            if uptime_start is not None:
                started = datetime.fromisoformat(uptime_start)
                uptime_seconds = Decimal(
                    str((datetime.now(UTC) - started).total_seconds()))
            paused = (
                self._safety.is_submission_paused()
                if self._safety is not None else False)
            halted = self._safety.is_halted() if self._safety is not None else False
            row = {
                # 0 until the throttle is wired.
                'throttle_breach_count': (
                    self._throttle.breach_count if self._throttle is not None else 0),
                # The facade holds ONE aggregate error counter; warning/critical stay 0
                # until a per-severity surface exists (the schema leaves room for it).
                'error_count_warning': 0,
                'error_count_error': errors,
                'error_count_critical': 0,
                'queue_depth': self.get_queue_size(),
                'uptime_seconds': uptime_seconds,
                # Health proxies from the safety latch — CONNECTOR_FATAL->halt and
                # STREAM_STATE->pause_submission are the sources.
                'connector_up': not halted,
                'stream_up': not paused,
            }
            self._system_stats_store.append(row, at=datetime.now(UTC))
        except Exception as exc:
            self.logger.warning(
                'Failed to append system_stats (swallowed): %s', exc)

    def _update_stats(self, event_type: Optional[str] = None):
        """Update internal statistics."""
        with self._stats_lock:
            if event_type:
                self._stats['events_processed'] += 1
                self._stats['last_event_time'] = datetime.now(UTC).isoformat()

                # Caller passes event.type.name, so compare against the enum name.
                if event_type == EventType.ORDER.name:
                    self._stats['orders_executed'] += 1

    def _on_order_throttle_rejected(self) -> None:
        """LiveRunner hook: a pre-submit-throttle-REFUSED ORDER.

        The throttle rejected this ORDER at the execution boundary — it emitted only a
        ``FillEvent(REFUSED)`` and never executed — so the runner skips ``_update_stats``,
        which would bump ``orders_executed`` and over-report submissions. The order WAS
        dequeued, so it still counts in ``events_processed`` and on its own counter.
        """
        with self._stats_lock:
            self._stats['events_processed'] += 1
            self._stats['last_event_time'] = datetime.now(UTC).isoformat()
            self._stats['orders_throttle_rejected'] += 1

    def _record_bar_metrics(self, event) -> None:
        """Record the per-bar equity curve on ``EventType.BAR``.

        Must key on BAR, not TIME: ``LiveBarFeed`` emits only ``BarEvent`` on the live
        path — the bar's arrival IS the event, there is no ``TimeEvent`` — so a TIME key
        never fires and leaves the live equity curve permanently empty. Stamp each
        snapshot with the bar-open BUSINESS time (``event.time``), never wall-clock.

        Runs on the engine thread, off the connector asyncio coroutine, best-effort: a
        lost tail of the equity curve is recomputable, so this must never stall the loop.
        """
        if getattr(event, 'type', None) != EventType.BAR:
            return
        for portfolio in self.portfolio_handler.get_active_portfolios():
            portfolio.record_metrics(event.time)

    def _initialize_live_session(self):
        """Initialize the live trading session by delegating to ``SessionInitializer``.

        Invoked at ``start()``, and by the offline ``TestRunner`` before its per-bar
        drive. IDEMPOTENT — the ``_session_initialized`` guard early-returns on a second
        call, so no lifecycle path double-inits. A wiring failure maps to
        ``SystemStatus.ERROR``.
        """
        if self._session_initialized:
            return
        self.logger.info('Initializing live trading session')

        try:
            # ``config`` stays lazy — it is read only inside this body.
            from itrader import config as _system_config

            engine = self._engine

            # Venue metadata (validate_symbol / resolve_precision) is a VENUE property,
            # not an account property — every account on one venue shares it — so any
            # streaming lifecycle's exchange is an equally correct source. Falls back to
            # the compute-venue 'paper' exchange with its permissive defaults.
            # The fallback is a SUBSCRIPT, not a soft ``.get``: a None here would reach
            # SessionInitializer and silently degrade validate_symbol / resolve_precision
            # with no exception raised anywhere near the defect. It cannot fire on a wired
            # engine, since init_exchanges always resolves the compute-venue arm.
            streaming = self._streaming_lifecycles()
            venue_exchange = (
                streaming[0].bundle.exchange if streaming
                else self.execution_handler.exchanges[
                    (COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)])

            # Live-plane config: read from the LIVE universe sub-model, never the frozen
            # determinism base — that keeps the backtest oracle config untouched.
            universe_config = UniverseHandlerConfig(
                poll_timeframe=_system_config.stream.okx_stream_timeframe,
                remove_policy=_system_config.universe.remove_policy,
            )

            # safety + stream_recovery are threaded to the registrar so it can set the
            # CONTROL routes (STREAM_STATE/CONNECTOR_FATAL) to their engine-thread
            # actuators.
            initializer = SessionInitializer(
                engine,
                universe_config=universe_config,
                venue_exchange=venue_exchange,
                # ONE feed, so ONE data provider: the connection FeedConnectionBinder
                # borrowed. None on a zero-account boot / the in-memory arm.
                data_provider=(
                    self._feed_binder.feed_provider
                    if self._feed_binder is not None else None),
                freeze_gate=(
                    lambda: self._safety.is_halted()
                    or self._safety.is_submission_paused()),
                safety=self._safety,
                stream_recovery=self._stream_recovery,
                config_router=self._config_router,
            )
            self._universe_handler = initializer.initialize()
            # wire_universe set engine.universe; start() reads self.universe.members.
            self.universe = engine.universe

            # Set AFTER the wiring succeeds, so a failed init can be retried.
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

        # Hard programming-error signal for a facade constructed outside
        # build_live_system(). MUST sit ABOVE the try-block below — inside it the broad
        # `except Exception` would swallow this and mask it as SystemStatus.ERROR.
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

        # Best-effort: a durable-write failure must not abort start. No-op with no sink.
        if self._system_store is not None:
            try:
                self._system_store.upsert(
                    'state.last_started_at',
                    {'last_started_at': datetime.now(UTC).isoformat()},
                    at=datetime.now(UTC))
            except Exception as exc:
                self.logger.warning(
                    'Failed to persist state.last_started_at (swallowed): %s', exc)

        try:
            # The DURABLE halt refusal gate MUST run FIRST — before session init, venue
            # connect, feed warmup, stream spawn, or reconcile. It re-latches this fresh
            # instance HALTED from an unresolved durable record and returns True, so a
            # durably-halted engine refuses to start INERT: zero venue I/O, no
            # state-mutating reconcile, no second durable record. Clean store = no-op.
            if self._safety.check_durable_halt_on_start():
                self._running = False
                return False

            self._initialize_live_session()

            # The venue connector's network connect (build client + load_markets on the
            # daemon-thread loop) happens HERE, deferred out of __init__ so construction
            # stays I/O-free. A failure propagates to the except below.
            # EVERY account's lifecycle is started: an assembled-but-unconnected account
            # would be registered in ExecutionHandler.exchanges and halt-wired, yet every
            # order routed to it would fail against an unconnected session.
            # lifecycle.start() no-ops the connector step for paper (connector=None).
            for lifecycle in self._venue_lifecycles.values():
                lifecycle.start()

            # Warm the LIVE feed BEFORE the socket goes live, so every update() stays on
            # one thread until the stream starts (single-writer ring guard).
            streaming = self._streaming_lifecycles()
            data_provider = (
                self._feed_binder.feed_provider
                if self._feed_binder is not None else None)
            if data_provider is not None:
                # The live subscription set is SOURCED FROM MEMBERSHIP. Per member, warm
                # the feed FIRST (REST replay sets the ring) THEN subscribe the live
                # socket — warmup-before-subscribe, Pitfall 6, never reorder.
                from itrader import config as _system_config
                members = self.universe.members if self.universe is not None else []
                for sym in members:
                    self.feed.warmup(sym, _system_config.stream.okx_stream_timeframe)
                    data_provider.subscribe(sym)

            # SOLE spawn site for OkxExchange._stream_fills()/_stream_orders(). Without
            # it no real FillEvent ever streams back and every order mirror stays PENDING
            # forever while looking healthy. Must run AFTER the connector client +
            # load_markets are live (the watch_* streams need them) and BEFORE the
            # reconcile below, so the streams are live during it (fill-ID dedup covers
            # the concurrent-stream case).
            # connect() RETURNS a ConnectionResult and never raises, so a bare call would
            # swallow the failure — check .success and re-raise into the except block
            # below rather than inventing a second error path.
            for lifecycle in streaming:
                result = lifecycle.bundle.exchange.connect()
                if not result.success:
                    raise RuntimeError(
                        f'OKX exchange stream connect failed: {result.error_message}')

            # Runs on the ENGINE thread before RUNNING: durable ledger restore for any
            # account kind, then — keyed on account KIND (Account.is_venue_truth, never
            # exchange == 'okx') — the venue REST reconcile plus the baseline guard that
            # HALTs on an unexplained base-asset residual. Built HERE rather than in
            # build_live_system because the venue fields are swappable before start().
            self._build_reconciliation_coordinator().run_startup_reconcile()

            # A reconcile/baseline-guard halt during session init must LATCH: refuse to
            # enter RUNNING from HALTED. Do not spawn the processing thread (its first
            # action is an unconditional RUNNING stamp) and do not open the SIGNAL/ORDER
            # gate. update_status also refuses HALTED->RUNNING as a second line of
            # defence; this check stops start() from spawning the loop at all.
            if self._safety.is_halted():
                self.logger.error(
                    'start() refused RUNNING: engine HALTED during session init '
                    '(reason=%s) — the reconciler/baseline guard declared venue state '
                    'untrustworthy; not spawning the processing thread',
                    self._safety.status_snapshot()['halt_reason'])
                self._running = False
                return False

            # LiveRunner owns both threads: it clears the shared _stop_event, spawns the
            # drain daemon, and starts its composed WorkerSupervisor. _running is set
            # BEFORE start() so a status callback fired from the loop-entry hook already
            # observes the running facade.
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
        # Venue teardown must run UNCONDITIONALLY, independent of _running: any lifecycle
        # that constructs-then-stops without a successful start() (validation, a failed
        # start(), status inspection, GC) must still cancel every spawned stream task and
        # close the ccxt/native sessions, or an authenticated socket leaks — a dangling
        # venue connection in production, a ResourceWarning (hard failure) under
        # filterwarnings=["error"]. Hence the finally below, covering every return path
        # including the early "not running" exit.
        # EVERY account's lifecycle is torn down, symmetric with the start() loop. Stopping
        # only one covers just one of VenueLifecycle.stop()'s branches, leaking every other
        # connector. Extra close_all() calls are harmless — it clears its memo in a finally,
        # so a second call iterates an empty memo.
        # Snapshot into a list, not a live view, so a teardown that mutates the map cannot
        # raise "dictionary changed size during iteration"; keep it BEFORE the try so the
        # finally holds the full map on every return path. getattr because stop() must
        # survive a partially-constructed facade.
        lifecycles = list((getattr(self, '_venue_lifecycles', None) or {}).items())
        try:
            if not self._running:
                self.logger.warning('Live trading system is not running')
                return True

            self.logger.info('Stopping live trading system')
            self._safety.update_status(SystemStatus.STOPPING)

            # LiveRunner sets the shared _stop_event, joins the drain thread, then stops
            # its composed WorkerSupervisor.
            if self._live_runner is not None:
                self._live_runner.stop(timeout=timeout)

            self._running = False
            self._safety.update_status(SystemStatus.STOPPED)

            self.logger.info('Live trading system stopped')
            return True
        finally:
            # The try/except sits INSIDE the loop, per iteration, deliberately NOT inside
            # VenueLifecycle.stop() — that method stays honest and keeps raising for its
            # own callers and unit contract. Isolating here stops one bad venue from
            # stranding the remaining venues' sockets or blocking the SQL dispose below,
            # and stops a teardown failure from masking an exception already propagating
            # out of the try body.
            for account_id, lifecycle in lifecycles:
                try:
                    lifecycle.stop()
                except Exception as e:
                    self.logger.error(
                        f'Error disconnecting venue connector for account {account_id}: {e}')
            # Dispose the operational SQL spine so its connection pool closes — an
            # undisposed engine leaks a socket / ResourceWarning under
            # filterwarnings=["error"]. No-op on the in-memory fallback.
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
        # The status latch lives on SafetyController — read its snapshot and merge the
        # facade-side stats + throttle counter into one status view.
        snap = self._safety.status_snapshot()
        status = snap['status']
        with self._stats_lock:
            uptime = None
            if self._stats['uptime_start'] and status == SystemStatus.RUNNING:
                start_time = datetime.fromisoformat(self._stats['uptime_start'])
                # uptime_start is stored tz-aware, so the comparand must be too or this
                # raises "can't subtract offset-naive and offset-aware datetimes".
                uptime = (datetime.now(UTC) - start_time).total_seconds()

            return {
                'status': status.value,
                # Machine-readable halt reason; None unless HALTED.
                'halt_reason': snap['halt_reason'],
                # The reversible pause-on-disconnect state, surfaced DISTINCTLY from the
                # terminal halt — paused != HALTED.
                'paused': snap['paused'],
                'paused_reason': snap['paused_reason'],
                'is_running': self.is_running(),
                'exchange': self.exchange,
                'queue_size': self.get_queue_size(),
                # 0 until the throttle is wired by build_live_system.
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
                # Strategies that could not be rehydrated at boot and are therefore NOT
                # trading, despite their registry rows still declaring them enabled — the
                # row is never rewritten, since the DB holds operator INTENT.
                'quarantined_strategies': list(self._quarantined_strategies),
                # Tripwire snapshot: per-FailureClass in-window hit counts + last-trip
                # HaltReason. Read None-safely — ErrorPolicy is unwired on a facade built
                # outside build_live_system.
                'breaker': (
                    self._error_policy.breaker_snapshot()
                    if self._error_policy is not None else {}),
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
        """Return the signals captured during the live run.

        A read-model sink read, NOT a cross-domain handler call — the queue-only
        contract is preserved.
        """
        return self._signal_store.get_all()

    def get_signal_store(self):
        """Return the signal-store itself, exposing ``by_strategy`` / ``by_ticker``."""
        return self._signal_store

    def add_event(self, event):
        """
        Add an event to the global queue for processing.

        This is the engine's PUBLIC external/web surface, so it is DEFAULT-DENY (ASVS
        V4/V5). Only the three types in ``_EXTERNALLY_ADMISSIBLE`` are admitted: a
        ``SIGNAL`` (routed through ``OrderHandler.on_signal`` -> ``AdmissionManager``, so
        validation + sizing + cash reservation + order-mirror engage before any
        ``OrderEvent`` exists), a ``STRATEGY_COMMAND``, and a ``CONFIG_UPDATE``.

        Every internal-fact type is rejected. A raw ``OrderEvent`` admitted here would
        reach the execution queue with NO admission control — an elevation-of-privilege
        defect. The sanctioned entry stays SIGNAL-form. Internal flow is unaffected:
        handlers put ``OrderEvent``s on ``global_queue`` directly, never through here.

        A ``CONFIG_UPDATE`` additionally gets a SYNCHRONOUS structural + type/range check
        before it reaches the queue (the 400, once FastAPI exists), with the engine-thread
        ``ConfigRouter`` re-checking behind it for defense-in-depth.

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

        # FAIL-CLOSED allowlist: one gate covering every internal-fact type.
        event_type = getattr(event, 'type', None)
        if event_type not in _EXTERNALLY_ADMISSIBLE:
            self.logger.warning(
                'Rejected external add_event of type %s (D-10 fail-closed default-deny) — only '
                'SIGNAL, STRATEGY_COMMAND and CONFIG_UPDATE are admissible from the external '
                'surface; every internal-fact type (incl. raw ORDER injection) must route through '
                'the engine internally, never the public queue directly', event_type)
            return False

        # Synchronous fail-closed reject at the admission boundary; the engine-thread
        # ConfigRouter re-checks behind it.
        if event_type is EventType.CONFIG_UPDATE and not self._validate_config_ingress(event):
            return False

        try:
            self.global_queue.put(event)
            return True
        except Exception as e:
            self.logger.error(f'Failed to add event to queue: {e}')
            return False

    def _validate_config_ingress(self, event) -> bool:
        """Synchronous ingress validation for a ``CONFIG_UPDATE``.

        Structural + type/range check WITHOUT persisting: resolves ``(scope, key)`` to its
        owning mutable sub-model — the model STRUCTURE is the allowlist — and dry-validates
        the value. Returns ``False`` on a malformed scope/key or a bad type/range on a
        KNOWN field.

        The ``venue`` / ``portfolio`` scopes get a STRUCTURAL shape check only: venue-kind
        and portfolio-existence are state-dependent, so they belong on the engine thread.
        """
        import uuid

        from itrader.config.order import OrderConfig
        from itrader.config.system import SystemSettings
        from itrader.config.universe import UniverseConfig

        # With no durable store there is no ConfigRouter wired and no target to persist to.
        # Reject at ingress so the caller gets a truthful False rather than a silent
        # enqueue-then-drop.
        if self._config_router is None:
            self.logger.warning(
                'Rejected CONFIG_UPDATE ingress: no durable config store wired (in-memory '
                'fallback) — runtime config updates require a SQL spine (fail-closed)')
            return False

        scope = getattr(event, 'scope', None)
        key = getattr(event, 'key', None)
        value = getattr(event, 'value', None)
        if not isinstance(scope, str) or not scope or not isinstance(key, str) or not key:
            self.logger.warning(
                'Rejected CONFIG_UPDATE ingress: malformed scope/key (%r/%r)', scope, key)
            return False

        if scope == 'system':
            if key in SystemSettings.model_fields:
                model_cls: Any = SystemSettings
            elif key in UniverseConfig.model_fields:
                model_cls = UniverseConfig
            else:
                self.logger.warning(
                    'Rejected CONFIG_UPDATE ingress: unknown system key %r', key)
                return False
            return self._dry_validate_config_ingress(model_cls, key, value)

        if scope == 'order':
            if key not in OrderConfig.model_fields:
                self.logger.warning(
                    'Rejected CONFIG_UPDATE ingress: unknown order key %r', key)
                return False
            return self._dry_validate_config_ingress(OrderConfig, key, value)

        if scope.startswith('venue:'):
            venue_name = scope[len('venue:'):]
            if not venue_name or key not in {'fee_model', 'slippage_model', 'enabled'}:
                self.logger.warning(
                    'Rejected CONFIG_UPDATE ingress: malformed venue scope/key (%r/%r)',
                    scope, key)
                return False
            # ``enabled`` is a real boolean — reject a truthy non-bool here, or the string
            # "false" would silently ENABLE a venue.
            if key == 'enabled' and not isinstance(value, bool):
                self.logger.warning(
                    'Rejected CONFIG_UPDATE ingress: non-bool venue enabled value %r', value)
                return False
            return True  # venue-kind is a state-dependent engine-thread predicate

        if scope.startswith('portfolio:'):
            pid = scope[len('portfolio:'):]
            try:
                uuid.UUID(pid)
            except (ValueError, AttributeError, TypeError):
                self.logger.warning(
                    'Rejected CONFIG_UPDATE ingress: malformed portfolio id %r', pid)
                return False
            return True  # portfolio-existence + section resolution are engine-thread

        self.logger.warning('Rejected CONFIG_UPDATE ingress: unrouted scope %r', scope)
        return False

    def _dry_validate_config_ingress(self, model_cls: Any, key: str, value: Any) -> bool:
        """Dry-validate ``value`` against ``model_cls[key]`` on a FRESH default instance.

        This runs on the EXTERNAL caller thread, so it must NOT read the live mutable
        ``config`` sub-models the ENGINE thread writes — that would be a cross-thread read
        of the single-writer overlay. It therefore builds a FRESH default instance of the
        same sub-model TYPE and setattrs onto that: ``validate_assignment=True`` re-runs
        the field's own coercion and ``Field(...)`` constraints, the same validator the
        engine-thread router applies, evaluated per-field so siblings are irrelevant.
        """
        import pydantic

        try:
            candidate = model_cls()  # fresh default — never the shared live sub-model
            setattr(candidate, key, value)
        except pydantic.ValidationError:
            self.logger.warning(
                'Rejected CONFIG_UPDATE ingress: bad type/range for known key %r', key)
            return False
        return True

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


def _layer_persisted_overrides(
    config: Any,
    *,
    system_store: Any,
    venue_store: Any,
    order_handler: Any,
    portfolio_handler: Any,
    execution_handler: Any,
) -> None:
    """Boot restart-layering: apply each scope's persisted config from its OWN store.

    The layering sequence is ``defaults <- YAML <- env <- persisted``. The frozen base
    params (``rng_seed`` / ``environment`` / identity) resolve at CONSTRUCTION and are
    NEVER persisted-overridden at runtime. Overrides apply only to the mutable sub-models,
    each read back from its OWNING module store — config is never read back from
    SystemStore for the order/portfolio scopes:

    * ``system``    — ``SystemStore.read_all()`` rows keyed ``config.system.*`` /
      ``config.universe.*``, setattr field-wise (``validate_assignment`` re-coerces).
    * ``order``     — the ORDER store's ``load_config()``, plus an
      ``order_handler.update_config`` push.
    * ``venue``     — ``VenueStore.read_all()`` rows push each venue's fee/slippage to the
      execution handler.
    * ``portfolio`` — each Portfolio's OWN bound ``state_storage.load_config()``.

    This LOADING touches SQL, so it must live here and never at import time (Pitfall 3).
    It is a pure module function so the restart-layering test can drive it directly.

    Degrade-clean: the durable config schema is Alembic-owned, so a boot against a
    not-yet-provisioned schema must NOT crash — a missing config table just means "no
    persisted overrides yet". Never ``create_all`` here; the store stays schema-pure.
    """
    import pydantic
    from sqlalchemy.exc import SQLAlchemyError

    from itrader.config.order import OrderConfig
    from itrader.config.system import SystemSettings
    from itrader.config.universe import UniverseConfig
    from itrader.core.exceptions.base import ConfigurationError

    logger = get_itrader_logger().bind(component="build_live_system")

    # Each scope layers under its OWN guard, so a bad persisted override — an
    # un-provisioned schema, or a stored value invalidated by model-field tightening — is
    # logged and skipped rather than crashing boot, and one bad scope never aborts the
    # others. Deliberately NOT a bare Exception: a genuine programming error still surfaces.
    _degrade_clean = (
        SQLAlchemyError, ConfigurationError, pydantic.ValidationError, ValueError)

    # (system) — SystemStore.read_all() rows (config.system.* / config.universe.*).
    try:
        for row in system_store.read_all():
            key = row["key"]
            value = row["value"]
            stored = value.get("value") if isinstance(value, dict) else value
            if key.startswith("config.system."):
                field = key[len("config.system."):]
                if field in SystemSettings.model_fields:
                    setattr(config.system, field, stored)
            elif key.startswith("config.universe."):
                field = key[len("config.universe."):]
                if field in UniverseConfig.model_fields:
                    setattr(config.universe, field, stored)
    except _degrade_clean as exc:
        logger.warning(
            "Skipping persisted SYSTEM-config restart layering — schema unavailable or a "
            "stored override is invalid (%s); boot degrades clean", exc)

    # (order) — the ORDER store's own load_config (NOT SystemStore) + the handler push.
    try:
        order_cfg = order_handler.storage.load_config()
        if order_cfg:
            applied = {
                field: val
                for field, val in order_cfg.items()
                if field in OrderConfig.model_fields
            }
            for field, val in applied.items():
                setattr(config.order, field, val)
            if applied:
                order_handler.update_config(applied)
    except _degrade_clean as exc:
        logger.warning(
            "Skipping persisted ORDER-config restart layering — schema unavailable or a "
            "stored override is invalid (%s); boot degrades clean", exc)

    # (venue) — VenueStore rows push their fee/slippage to the execution handler.
    # The read_all() acquisition keeps its own guard (an un-provisioned schema raises and
    # has no rows to iterate). The per-row push is then guarded PER ENTRY so one poisoned
    # venue degrades only that venue — the acquisition guard wraps the read, never the loop.
    try:
        venue_rows = venue_store.read_all()
    except _degrade_clean as exc:
        logger.warning(
            "Skipping persisted VENUE-config restart layering — schema unavailable "
            "(%s); boot degrades clean", exc)
        venue_rows = []
    for row in venue_rows:
        try:
            venue_cfg = row.get("config") or {}
            push = {
                k: v
                for k, v in venue_cfg.items()
                if k in {"fee_model", "slippage_model"}
            }
            if push:
                execution_handler.update_config(push)
        except _degrade_clean as exc:
            logger.warning(
                "Skipping persisted VENUE-config layering for %s — stored override "
                "invalid (%s); boot degrades clean", row.get("venue_name"), exc)

    # (portfolio) — each Portfolio's OWN bound store, resolved via the handler's PUBLIC
    # all_portfolios() surface, never the private registry. The guard is PER ENTRY so one
    # poisoned config_json degrades only that portfolio. all_portfolios() is a pure copy
    # (no I/O), so the loop needs no acquisition guard.
    for _pid, portfolio in portfolio_handler.all_portfolios().items():
        try:
            portfolio_cfg = portfolio.state_storage.load_config()
            if portfolio_cfg:
                portfolio.update_config(portfolio_cfg)
        except _degrade_clean as exc:
            logger.warning(
                "Skipping persisted PORTFOLIO-config restart layering for %s — schema "
                "unavailable or a stored override is invalid (%s); boot degrades clean",
                _pid, exc)


def build_live_system(
    spec: Any,
    *,
    status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
    data_plugins: Optional[Dict[str, Any]] = None,
    strategy_catalog: Optional[Dict[str, type]] = None,
) -> LiveTradingSystem:
    """The live composition root — the ONLY live construction path.

    The live analog of ``build_backtest_system -> compose_engine -> BacktestRunner``:
    reads centralized config, builds the ONE live ``sql_engine`` (Postgres-gated), builds
    the component graph off the ``PriorityEventBus``, assembles venues, constructs the
    facade via pure injection, and composes the ``LiveRunner`` (which owns the drain loop),
    its ``WorkerSupervisor``, and the ``ErrorPolicy`` around it.

    Live session wiring stays DEFERRED to ``start()`` — flipping it to construction time
    conflicts with the add-strategy-after-construction and monkeypatch-before-``start()``
    contracts across the live test suite.

    ``data_plugins`` and ``strategy_catalog`` are CODE artifacts the application hands in,
    as opposed to ``spec``, which is persisted config. ``strategy_catalog`` is the only
    thing that turns a stored ``strategy_type`` string into a class, so the app decides
    which classes are instantiable at boot. Its ``None`` default keeps existing callers
    working: an empty registry has nothing to instantiate, and with rows present a missing
    catalog fails LOUD rather than booting an engine that looks healthy and trades nothing.

    All live/venue/SQL imports live INSIDE this body (lazy), so importing this module via
    the ``trading_system`` barrel pulls NO ccxt.pro / SqlSettings — the inertness gate.
    """
    logger = get_itrader_logger().bind(component="LiveTradingSystem")
    exchange = spec.execution_venue

    # Inert without CONTROL events: everything flows BUSINESS-tier and the monotonic seq
    # keeps strict FIFO.
    global_queue = PriorityEventBus()
    # LAZY-imported so the BACKTEST import path never pulls live_bar_feed (inertness gate).
    # Live carries store=None — the LiveBarFeed reads no store.
    from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
    feed = LiveBarFeed(provider=None, base_timeframe=to_timedelta('1d'))

    # Operational store live-drive. The SYNC-DURABLE working set (orders) persists
    # store-first; the DERIVED signal store is async/best-effort. Both share ONE SqlEngine.
    # Credential presence is probed at build time so it honors per-construction env: the
    # SQLite default driver skips ``_require_pg_credentials``, so the probe never raises
    # when credentials are absent while still sourcing ``ITRADER_DATABASE_*``.
    from itrader.config.sql import SqlSettings
    probe = SqlSettings()
    if probe.password is None and probe.url is None:
        # Fail loudly into the in-memory fallback — never a default credential string.
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

    # Durable halt-record store over the shared spine, so a halt survives a process
    # restart. None on the in-memory fallback. Kept as a SEPARATE infra handle from the
    # venue holder — folding it in would recreate the collaborator bag.
    if system_db_backend is not None:
        from itrader.storage.halt_record_store import HaltRecordStore
        halt_record_store: Optional[Any] = HaltRecordStore(system_db_backend)
    else:
        halt_record_store = None

    # The live handler graph comes from the shared compose_engine, never a hand-rolled
    # parallel copy. EngineContext is the mode-injection seam: feed = the LiveBarFeed,
    # store = None, and environment + sql_engine reflect the credential-probe arm so
    # compose's handler-owned storage init lands the identical durable path (Postgres ->
    # CachedSqlOrderStorage over the spine; in-memory -> InMemoryOrderStorage).
    # compose_engine is a PURE import, taken lazily to mirror this module's discipline.
    from itrader import config as _system_config
    from itrader.trading_system.compose import compose_engine

    # The live ERROR-route collaborators are built BEFORE compose so they ride into the
    # ErrorHandler and the injected handler-failure policy through compose_engine, the one
    # mode-agnostic build site — never a post-build monkeypatch.
    #   - alert_sink: the CRITICAL/halt egress. Binds only declared ErrorEvent fields, so
    #     no connector secret can leak (Pitfall 16).
    #   - system_store: a fresh SystemStore over the SAME SqlEngine; there is no existing
    #     one to share and no second engine to build. Import stays LAZY inside the gate.
    #   - error_policy: the live publish-and-continue tripwire. halt + error_counter are
    #     late-bound below, once SafetyController and the facade exist.
    from itrader.events_handler.error_policy import ErrorPolicy

    alert_sink = LogAlertSink()
    if system_db_backend is not None:
        from itrader.storage.system_store import SystemStore
        system_store: Optional[Any] = SystemStore(system_db_backend)
    else:
        system_store = None
    error_policy = ErrorPolicy(
        global_queue,
        failure_settings=_system_config.safety.failure_rate,
    )

    # VENUE REGISTRATION. Must precede compose, which receives a BUILT ``VenueBundles``.
    # Safe to sit here because registration is INERT: it stores plugin objects and runs no
    # ``build*()``, so it pulls no ccxt and changes no import-time behaviour.
    # The whole OKX/paper venue stack stays LAZY-imported so the BACKTEST import path
    # stays async/ccxt/credential-free (the hot-path inertness gate).
    from itrader.connectors.provider import ConnectorProvider
    from itrader.execution_handler.execution_handler import default_exchange_config
    from itrader.venues.bundles import VenueBundles
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

    # The credentials boundary's two collaborators.
    #   - venue_account_store: the durable (venue_name, account_id) home. Supplies each
    #     account's secret_ref POINTER for credential resolution, and records/asserts the
    #     trust-on-first-use venue_uid. Import stays LAZY inside the SQL gate.
    #   - credential_resolver: injected into the OKX connector plugin. WITHOUT it the
    #     plugin falls back to a bare OkxSettings() reading the ONE global OKX_API_* set,
    #     so two account_ids would connect with IDENTICAL credentials while the system
    #     believes they are separate accounts — the exact misroute the uid guard detects.
    from itrader.config.credential_resolver import EnvCredentialResolver

    if system_db_backend is not None:
        from itrader.storage.venue_account_store import VenueAccountStore
        venue_account_store: Optional[Any] = VenueAccountStore(system_db_backend)
    else:
        venue_account_store = None
    credential_resolver = EnvCredentialResolver()

    # (1) Build the two registries + the shared ConnectorProvider and register the
    # concrete plugins (store-only — no build*() runs, so this pulls no ccxt).
    exec_registry = ExecutionVenueRegistry()
    data_registry = DataProviderRegistry()
    connectors = ConnectorProvider(
        {'okx': OkxConnectorPlugin(resolver=credential_resolver)})
    exec_registry.register('okx', OkxVenuePlugin())
    # The plugin builds its own SimulatedExchange from the config it is given.
    # ``default_exchange_config()`` is the default preset (∪ {BTCUSD}); seeding a
    # LIVE-derived symbol set here would change live admission behaviour.
    exec_registry.register('paper', PaperVenuePlugin(default_exchange_config()))
    data_registry.register('okx', OkxDataPlugin())

    # TEST-only DATA provider injection: production registers no replay/test provider, so
    # the paper<->replay pairing lives ONLY in the fixture. Registered AFTER production.
    if data_plugins:
        for _name, _plugin in data_plugins.items():
            data_registry.register(_name, _plugin)

    # The ONE seeded determinism RNG for the live run, built at the wiring seam and
    # injected on ctx rather than derived inside a handler.
    rng = random.Random(int(_system_config.rng_seed))

    ctx = EngineContext(
        bus=global_queue,
        config=_system_config,
        environment=environment,
        feed=feed, rng=rng, store=None,
        sql_engine=system_db_backend,
    )
    # The ONE bundle memo, built after ctx and before compose. The venue-assembly loop
    # below shares this SAME instance, so the execution arm and the per-account assembly
    # can never hold two exchanges for one (venue, account_id) — two OkxExchange objects
    # per account would double-spawn that account's fill/order streams.
    venue_bundles = VenueBundles(exec_registry, connectors, ctx)
    # The ONE composition-root-owned (venue, account_id) -> exchange map, created BEFORE
    # compose so both the execution handler (built inside compose, reads it on order) and
    # VenueAccountManager (built below, writes each brought-online exchange into it) hold
    # the SAME object. Distinct from ``exec_registry`` above: that is the venue PLUGIN
    # registry the bundle memo builds over; this is the exchange OBJECT registry.
    exchange_registry: Dict[tuple, Any] = {}

    # Build the account AUTHORITY the PortfolioFactory holds, and the factory itself,
    # BEFORE compose — with a REAL collaborator at construction: no late-init, no
    # Optional[VenueAccountManager], no post-construction attribute set. The mode
    # difference lives ONLY here, in WHICH authority the root injects:
    #   * SQL arm       -> VenueValidatedComputeAuthority: asks the real
    #                      VenueAccountManager to VALIDATE the pair (exists + enabled +
    #                      brought-online), RAISING VenueAccountNotProvisionedError on any
    #                      failure, then builds a COMPUTE leaf carrying the real pair. The
    #                      venue-truth VenueAccount leaf CANNOT be the construction-time
    #                      leaf — its balance raises until the first snapshot, and
    #                      Portfolio.__init__ reads balance.
    #   * in-memory arm -> the bundles-backed compute authority (``account_id`` None, no
    #                      validation, never raises), so an in-memory live boot that
    #                      builds no manager is never stranded.
    # The manager's ``_online`` map fills between here and the first ``assert_available``
    # at rehydrate — ordinary object lifecycle, not deferred wiring.
    from itrader.portfolio_handler.portfolio_factory import (
        ComputeAccountAuthority,
        PortfolioFactory,
        VenueValidatedComputeAuthority,
    )

    venue_manager: Optional[Any] = None
    # The ONE feed's connection binder: the feed borrows the first available venue
    # CONNECTION and re-borrows when that account is retired/disabled. It owns the provider
    # build, the feed wiring and the re-borrow rule; the manager drives it from
    # bring_online. None on the in-memory arm.
    feed_binder: Optional[Any] = None
    if system_db_backend is not None:
        from itrader.venues.feed_binder import FeedConnectionBinder
        from itrader.venues.venue_account_manager import VenueAccountManager

        feed_binder = FeedConnectionBinder(
            feed=feed,
            data_registry=data_registry,
            ctx=ctx,
            connectors=connectors,
            global_queue=global_queue,
        )
        # The venue-ACCOUNT domain owner (D-21/D-26/D-27). It EXCLUSIVELY owns the durable
        # ``venue_accounts`` store (non-None on this arm, gated exactly like ``system_store``
        # — the D-21 non-Optional store contract holds), and shares the ONE ``venue_bundles``
        # memo + ``connectors`` provider the execution arm holds (D-08). D-43: it receives
        # the shared ``exchange_registry`` (the SAME map compose hands the execution handler),
        # NOT the execution handler itself — ``bring_online`` writes that map directly, which
        # is the cut that lets it be built here, above compose.
        venue_manager = VenueAccountManager(
            venue_account_store,
            venue_bundles,
            connectors,
            exchange_registry,
            alert_sink=alert_sink,
            feed_binder=feed_binder,
        )
        # ACCT-03: validate through the manager (raise on missing/disabled/not-online), build
        # a compute leaf carrying the real pair. Venue-truth leaf stays COMP-07 / Phase 12.
        account_authority: Any = VenueValidatedComputeAuthority(
            manager=venue_manager,
            compute=ComputeAccountAuthority(
                venue_bundles=venue_bundles, compute_venue=COMPUTE_VENUE),
        )
    else:
        account_authority = ComputeAccountAuthority(
            venue_bundles=venue_bundles, compute_venue=COMPUTE_VENUE)

    # The sole leaf-builder ``PortfolioHandler`` constructs every portfolio through (D-24),
    # holding its REAL authority at construction. ``environment`` / ``system_db_backend``
    # select the durable state-storage backend the factory scopes per portfolio_id.
    portfolio_factory = PortfolioFactory(
        authority=account_authority,
        environment=environment,
        sql_engine=system_db_backend,
    )

    engine = compose_engine(
        ctx, venue_bundles=venue_bundles, results_store=None,
        alert_sink=alert_sink, system_store=system_store, error_policy=error_policy,
        strategy_catalog=strategy_catalog,
        exchange_registry=exchange_registry,
        portfolio_factory=portfolio_factory,
        # D-27/MPORT-07: LIVE resolves each order's venue account from its
        # portfolio through the injected read-model, so an account's orders can
        # never be submitted through another account's authenticated session.
        # The backtest arm deliberately leaves this False — see compose_engine.
        route_orders_by_account=True)

    # compose already wired set_order_storage and the admission fee-model provider. That
    # provider takes the ORDER's own ``(venue, account_id)`` pair and resolves
    # ``execution_handler.exchanges`` INSIDE the call, yielding that exchange's
    # ``fee_model`` when it has one; admission logs the miss and degrades to
    # ``Decimal("0")`` when it does not. OkxExchange currently exposes no fee model.
    # Only the three handles the remaining venue + post-facade wiring touches are taken
    # here; the facade sources the FULL graph off the engine in __init__.
    execution_handler = engine.execution_handler
    portfolio_handler = engine.portfolio_handler
    event_handler = engine.event_handler

    # PORTFOLIO + VENUE BOOTSTRAP — the store-derived boot.
    #
    # The account SET is STORE-DERIVED: read off durable ``venue_accounts`` rows through
    # VenueAccountManager, never re-derived from the spec. No account identity is computed
    # in this file.
    #
    # Boot order is: distinct-account check -> venue assembly -> rehydrate. Assembly MUST
    # precede rehydrate, so the manager's ``_online`` map is full when rehydrate
    # materializes each row — otherwise a portfolio naming a not-provisioned / disabled /
    # not-online account would silently sit on a compute leaf instead of raising.
    #
    # venue_lifecycles / venue_accounts are declared here so the facade construction, the
    # StreamRecoveryHandler and the halt-signal wiring below see them on EVERY path. A boot
    # with no SQL spine has no store, hence no manager and no venue accounts — it comes up
    # RUNNING and empty.
    venue_lifecycles: Dict[str, Any] = {}
    venue_accounts: Dict[str, Any] = {}

    if system_db_backend is not None:
        from sqlalchemy import inspect as _sa_inspect

        from itrader.portfolio_handler.rehydrate.distinct_account_invariant import (
            assert_distinct_accounts,
        )
        from itrader.portfolio_handler.rehydrate.portfolio_rehydrate import (
            rehydrate_portfolios,
        )

        # The store the handler already OWNS (DECOMP-01a). One instance, so the rehydrate
        # read and the add_portfolio write-back can never diverge.
        definition_store = portfolio_handler.definition_store

        # A not-yet-provisioned `portfolios` table is the first-start state (fresh DB, or
        # an un-run Alembic chain), NOT a fault: degrade with a WARNING. Deliberately
        # narrow — it probes for the TABLE and nothing else, so a genuine store fault still
        # propagates LOUD rather than becoming a silent zero-portfolio boot.
        has_table = definition_store is not None and _sa_inspect(
            system_db_backend.engine).has_table("portfolios")
        if definition_store is not None and not has_table:
            logger.warning(
                "The `portfolios` table is not provisioned — skipping portfolio "
                "rehydrate (first start, or the Alembic chain has not run). No "
                "portfolio will be restored until the schema exists.")

        # (1) THE DISTINCT-ACCOUNT INVARIANT over the persisted rows. Runs FIRST, so a
        #     collision is refused before any account exists.
        if has_table:
            assert_distinct_accounts(persisted=definition_store.read_all())

        # (2) VENUE ASSEMBLY, store-derived: read this venue's enabled rows and bring each
        #     online. ``bring_online`` builds the account's VenueSpec (carrying its OWN
        #     ``secret_ref`` and config overrides), assembles the bundle through the shared
        #     memo, registers the exchange under the row's (venue, account_id) pair
        #     VERBATIM, and arms the UID guard. ``read_enabled_for`` carries its own table
        #     probe, so a boot before ``venue_accounts`` exists brings up zero accounts
        #     rather than raising. The lifecycle map is keyed by the row's account id — the
        #     same key the exchange registry and the facade's per-account reads use.
        for row in venue_manager.read_enabled_for(exchange):
            record = venue_manager.bring_online(row)
            venue_lifecycles[str(row["account_id"])] = record.lifecycle
        # Finalize the feed's connection binding once the bring-up loop is done. A boot
        # with zero streaming accounts leaves the feed UNBOUND and logs the cause here,
        # since bring_online's per-row rebind never ran; otherwise this is a no-op.
        venue_manager.rebind_feed()

        # (3) PORTFOLIO REHYDRATE recreates the portfolio objects with their PERSISTED
        #     ids, so portfolio-scoped child tables and strategy-subscription rows reattach
        #     to portfolios that still exist. Assembly running first does not change WHICH
        #     portfolios rehydrate or in what order — that contract is the store's.
        if has_table:
            rehydrate_portfolios(
                store=definition_store,
                portfolio_handler=portfolio_handler,
            )


    # Construct the facade via DIRECT PURE INJECTION — no collaborator bag. The compose
    # Engine is the single source of truth for the handler graph; the per-account
    # VenueLifecycle map is the venue/connector holder; the SQL spine + halt store stay
    # separate infra handles.
    facade = LiveTradingSystem(
        engine=engine,
        lifecycles=venue_lifecycles,
        system_db_backend=system_db_backend,
        halt_record_store=halt_record_store,
        exchange=exchange,
        status_callback=status_callback,
    )

    # RUNTIME-CONFIG PLATFORM. Construct VenueStore + the engine-thread ConfigRouter over
    # the OWNING module stores — system -> SystemStore, order -> the ORDER store, venue ->
    # VenueStore, portfolio -> each Portfolio's OWN bound state_storage, never SystemStore
    # — and attach it to the facade so _initialize_live_session threads it into the
    # CONFIG_UPDATE CONTROL route. Storage/venue imports stay LAZY inside the gate.
    # Degrades to no router / no layering without a SQL spine.
    order_handler = engine.order_handler
    if system_store is not None:
        from itrader.core.clock import WallClock
        from itrader.storage.venue_store import VenueStore
        from itrader.trading_system.config_router import ConfigRouter

        venue_store: Optional[Any] = VenueStore(system_db_backend)

        def _venue_kind(venue_name: str) -> bool:
            """True when the venue's execution arm is a SimulatedExchange.

            The registry is pair-keyed, so this matches every registered account on the
            named venue. The parameter stays a bare VENUE string because "is this venue
            simulated?" is a property of the venue, not of one account on it.
            """
            from itrader.execution_handler.exchanges.simulated import SimulatedExchange
            return any(
                isinstance(exchange, SimulatedExchange)
                for (venue, _account_id), exchange in execution_handler.exchanges.items()
                if venue == venue_name)

        facade._config_router = ConfigRouter(
            config=_system_config,
            system_store=system_store,
            venue_store=venue_store,
            order_handler=order_handler,
            portfolio_handler=portfolio_handler,
            execution_handler=execution_handler,
            venue_kind=_venue_kind,
            bus=global_queue,
            clock=WallClock(),
        )

        # RESTART LAYERING: apply persisted overrides on boot from each OWNING store.
        # Base params are already resolved at construction (frozen).
        _layer_persisted_overrides(
            _system_config,
            system_store=system_store,
            venue_store=venue_store,
            order_handler=order_handler,
            portfolio_handler=portfolio_handler,
            execution_handler=execution_handler,
        )

        # STRATEGY REHYDRATE: the stored roster becomes live instances. THIS EXACT
        # POSITION satisfies four independent constraints:
        #  (1) portfolios already EXIST with RESTART-STABLE ids, so subscribe_portfolio
        #      binds each stored subscription to a portfolio that is really there and will
        #      still carry the same id after the next restart. rehydrate_portfolios above
        #      is what supplies that guarantee.
        #  (2) session init BELOW reads the strategy list — wire_universe derives
        #      membership from it and register_strategy_warmup sizes the feed ring from it.
        #      A strategy registered after either would never enter the universe and never
        #      size the ring, so rehydrate MUST precede them.
        #  (3) NOT inside _initialize_live_session: integration tests, including a RESTART
        #      test, monkeypatch that method to a no-op, so a rehydrate placed there would
        #      be silently lost exactly where it matters most.
        #  (4) the import stays LAZY inside this gate and is never barrel-exported, keeping
        #      the backtest import path SQL-free.
        # Deliberately NOT wrapped in try/except _degrade_clean. Per-instance failures are
        # ALREADY handled inside rehydrate_strategies (skip + CRITICAL alert + the row left
        # untouched), while an infrastructure failure must fail LOUD. A blanket wrap would
        # convert the loud arm into a silent boot with zero strategies — worse than not
        # booting at all.
        from itrader.strategy_handler.registry.rehydrate import rehydrate_strategies

        # The store is READ BACK off the handler that OWNS it, derived in
        # StrategiesHandler.__init__ — no post-construction dep assignment. A rehydrated
        # strategy's first runtime verb therefore always has a store to persist to; without
        # that, an enable/disable landing between boot and the next wiring step would apply
        # live and vanish at restart.
        #
        # A None store is the first-start state (unprovisioned strategy_registry table) or
        # an unwired SQL spine; the factory owns that probe and its WARNING. It is NOT an
        # infrastructure failure, so skipping rehydrate cannot produce the
        # zero-strategies-while-rows-exist outcome — a genuine store fault still
        # PROPAGATES loud out of rehydrate_strategies.
        #
        # rehydrate_strategies itself stays HERE: it needs a fully-built handler and is a
        # genuine runtime operation, not dependency injection.
        strategy_registry_store = engine.strategies_handler.registry_store
        if strategy_registry_store is not None:
            facade._quarantined_strategies = rehydrate_strategies(
                store=strategy_registry_store,
                catalog=strategy_catalog,
                strategies_handler=engine.strategies_handler,
                alert_sink=alert_sink,
            )

    # Construct + ATTACH the four safety collaborators. Imports stay LAZY in-body so
    # importing this module pulls no live safety stack (inertness Pitfall 5). Each is a
    # plain injected collaborator with NO facade back-reference beyond the callbacks it is
    # handed; the facade is a thin delegator over them.
    from itrader.core.clock import WallClock
    from itrader.trading_system.safety.pre_trade_throttle import PreTradeThrottle
    from itrader.trading_system.safety.safety_controller import SafetyController
    from itrader.trading_system.safety.stream_recovery_handler import (
        StreamRecoveryHandler,
    )

    # The pure state machine. dispatch_fn is LATE-BOUND so the gate always dispatches
    # through the CURRENT inner dispatch — a test monkeypatch of event_handler._dispatch is
    # honoured, and gate_and_dispatch replay reaches it too.
    safety = SafetyController(
        bus=global_queue,
        halt_record_store=halt_record_store,
        dispatch_fn=lambda ev: event_handler._dispatch(ev),
        notify_status_change=facade._notify_status_change,
        # Durable read-model KV sink for state.status / state.halt_reason at their event
        # source. None on the in-memory fallback.
        system_store=system_store,
    )
    # Engine-thread reconnect-resume I/O: catch-up + snapshot + all-streams gate ->
    # resume. Injected with the per-account LIFECYCLE MAP, so catch-up and the health gate
    # cover EVERY account. ``venue_accounts`` is a CALLABLE over the accounts the
    # portfolios actually hold — a build-time capture would go stale the moment an account
    # is re-attached. Both are empty on a non-OKX wiring; every call is guard-claused.
    stream_recovery = StreamRecoveryHandler(
        safety=safety,
        lifecycles=venue_lifecycles,
        venue_accounts=lambda: list(venue_accounts.values()),
        # Read LIVE through the binder so the all-streams health gate covers the candle arm
        # and tracks a runtime re-borrow. None on the in-memory arm = no data arm to gate on.
        feed_provider=(
            lambda: feed_binder.feed_provider if feed_binder is not None else None),
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
    # handler graph at reconcile time (collaborators are swappable before start() for
    # offline runs), not a build-time capture. 11-09: it takes no venue scalars at all
    # now — each portfolio supplies its own account and that account's connector.
    facade._safety = safety
    facade._stream_recovery = stream_recovery
    facade._throttle = throttle
    # 11.2-07 (D-36): the feed-connection binder the live session reads its bound data
    # provider through. None on the in-memory arm (no venue manager was built).
    facade._feed_binder = feed_binder

    # RTCFG-06 read-model sinks (D-18/D-19). Attach the durable KV (state.last_started_at
    # at start(); SafetyController/ErrorHandler own the other state.* keys) and construct
    # the append-only system_stats series over the SAME SqlEngine — the thin stats writer
    # (_snapshot_system_stats) appends on each status transition. Both gated on the SQL
    # spine (import stays LAZY inside the gate — system_stats_store is inertness-_FORBIDDEN)
    # and degrade to None on the in-memory fallback (backtest never reaches here).
    facade._system_store = system_store
    if system_db_backend is not None:
        from itrader.storage.system_stats_store import SystemStatsStore
        facade._system_stats_store = SystemStatsStore(system_db_backend)
    else:
        facade._system_stats_store = None

    # Facade-dependent wiring (references the constructed facade's own callbacks). The
    # provider/exchange/connector halt-signal + stream-state listeners for a registered
    # venue now emit CONTROL events (§11c): _request_connector_halt -> ConnectorFatalEvent,
    # _on_venue_stream_down/up -> StreamStateEvent(down/up). No flag flips.
    #
    # 11-09: the former primary/secondary SPLIT (an ``if okx_exchange is not None``
    # block for account 0, then a ``for secondary in secondary_bundles`` loop for the
    # rest, doing the same three calls twice) is collapsed into ONE loop over every
    # streaming lifecycle. Two copies of one wiring rule is how a second account ends up
    # accepting orders after a connector-fatal halt latched the first — a
    # partially-halted engine is worse than a single-account one, because the surviving
    # arm looks healthy.
    #
    # 11.2-07 (D-36): the DATA provider stays deliberately single (one feed), so it is
    # wired outside the loop — read through the FeedConnectionBinder (the "primary" concept
    # is deleted). The ``is not None`` guard stays: the unregistered-venue arm, a
    # zero-account boot (D-09) and the in-memory arm (no binder) all legitimately yield no
    # provider. A runtime re-borrow re-wires its own halt signal off this same seam when
    # that path lands; here at boot the first-bound provider is wired once.
    feed_provider = feed_binder.feed_provider if feed_binder is not None else None
    if feed_provider is not None:
        feed_provider.set_halt_signal(facade._request_connector_halt)
        feed_provider.set_stream_state_listener(
            facade._on_venue_stream_down, facade._on_venue_stream_up)
    for lifecycle in venue_lifecycles.values():
        bundle = lifecycle.bundle
        if bundle.connector is None:
            continue
        bundle.exchange.set_halt_signal(facade._request_connector_halt)
        bundle.exchange.set_stream_state_listener(
            facade._on_venue_stream_down, facade._on_venue_stream_up)
        bundle.connector.set_halt_signal(facade._request_connector_halt)

    # 08-03 (D-03/D-04): the CRITICAL/halt alert sink now rides into the ErrorHandler via
    # compose_engine (built above as ``alert_sink``, injected at construction) — the old
    # post-build alert-sink assignment on the event handler is GONE (the dispatcher holds
    # no egress state, D-03).
    # 05-04 (D-01/D-02): engine-thread drift-halt signal -> freeze-in-place halt (the
    # facade delegator forwards to SafetyController.halt).
    portfolio_handler.set_halt_signal(facade.halt)

    # 08-03 (D-12): late-bind the tripwire's runtime collaborators now that the
    # SafetyController + the facade exist. compose_engine already injected the ErrorPolicy
    # object (built above, before safety) as the dispatcher's failure policy AND the
    # ErrorHandler's failure_sink; bind() resolves the construction cycle by wiring the
    # deferred collaborators — ``halt=safety.halt`` (D-12 same-thread direct freeze) and
    # ``error_counter=facade._increment_error_count`` (preserves the facade's errors_count
    # bookkeeping). Both are only needed when a failure actually occurs at runtime.
    error_policy.bind(halt=safety.halt, error_counter=facade._increment_error_count)

    # RUN-02 (D-05/D-06/D-07/D-08): the live runtime engine. LiveRunner OWNS the drain
    # loop; it COMPOSES the WorkerSupervisor (poll timer, D-05). SAFE-03/D-06 (P7): the
    # dispatch gate is repointed to SafetyController.gate_and_dispatch (the freeze-in-place
    # gate), and the pre-submit throttle (PreTradeThrottle.allow) fires at the
    # ORDER->execution boundary ahead of it. The former resume/halt per-tick drain hooks
    # are GONE (CONTROL events replace the flag side-channel). 08-03/D-06: the handler-
    # failure policy is injected at EventHandler construction (compose) now — LiveRunner no
    # longer carries it, and the old start() monkeypatch is gone.
    from itrader.trading_system.live_runner import LiveRunner
    from itrader.trading_system.worker_supervisor import WorkerSupervisor

    cadence = _system_config.universe.poll_cadence_s
    worker_supervisor = WorkerSupervisor(global_queue, facade._stop_event, cadence)
    live_runner = LiveRunner(
        bus=global_queue,
        stop_event=facade._stop_event,
        worker_supervisor=worker_supervisor,
        dispatch_gate=safety.gate_and_dispatch,
        update_stats=facade._update_stats,
        record_bar_metrics=facade._record_bar_metrics,
        pre_submit=throttle.allow,
        queue_timeout=_LIVE_QUEUE_TIMEOUT,
        max_idle_time=_LIVE_MAX_IDLE_TIME,
        on_loop_start=facade._on_loop_start,
        on_loop_error=facade._on_loop_error,
        on_order_throttle_rejected=facade._on_order_throttle_rejected,
    )
    facade._live_runner = live_runner
    facade._error_policy = error_policy

    logger.info('Live trading system built', exchange=exchange)
    return facade
