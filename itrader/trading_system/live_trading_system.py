import random
import threading
from datetime import datetime, UTC
from decimal import Decimal
from typing import (
    Optional, Dict, List, Any, Callable, Mapping, TYPE_CHECKING)

from itrader.core.enums import HaltReason, SystemStatus
from itrader.core.exceptions import StateError
from itrader.execution_handler.execution_handler import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID
from itrader.outils.time_parser import to_timedelta
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.trading_system.venue_spec import build_venue_spec
# Only PURE imports belong at module top: no ccxt.pro, SQL, or venue substrate. Every
# heavy import MUST stay lazy inside a function body, or importing this module drags it
# onto the backtest import graph. tests/integration/test_okx_inertness.py is the gate,
# and this rule is why every in-body import below is where it is.
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

# ``add_event``'s default-deny allowlist: the engine's only external/web ingress. Every
# other type, including every internal-fact type, is rejected. Internal flow is
# unaffected — handlers put onto ``global_queue`` directly, never through ``add_event``.
_EXTERNALLY_ADMISSIBLE = frozenset(
    {EventType.SIGNAL, EventType.STRATEGY_COMMAND, EventType.CONFIG_UPDATE}
)


class LiveTradingSystem:
    """Live-trading facade: a thin delegator over an injected engine and collaborators.

    Drains the global queue on a background daemon thread rather than the backtest
    system's synchronous for-loop.
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
        """Pure-injection constructor: pre-built collaborators in, fresh runtime state out.

        Holds NO wiring logic.

        Parameters
        ----------
        engine : Engine
            The composed handler graph plus its handler-owned storages. The single
            source of truth — every handler/feed/storage field is sourced off it.
        lifecycles : Mapping[str, VenueLifecycle], optional
            ONE venue/connector holder PER ACCOUNT, keyed by account id. Empty or
            ``None`` when the venue is unregistered; paper carries a lifecycle with
            ``connector=None``.
        system_db_backend : Any, optional
            The shared ``SqlEngine`` spine, or ``None`` on the in-memory fallback.
        halt_record_store : Any, optional
            Durable halt-record store, so a halt survives a process restart.
        exchange : str
            The venue-name string, derived from ``spec.execution_venue``.
        status_callback : callable, optional
            Invoked as ``(new_status, status_data)`` on each status transition.
        """
        self.logger = get_itrader_logger().bind(component="LiveTradingSystem")
        self.status_callback = status_callback

        # Handlers/feed/storages are sourced OFF the engine, never duplicated as fields.
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

        # ONE VenueLifecycle per account, keyed by account id. No account is privileged —
        # the feed binds to a CONNECTION via FeedConnectionBinder, not to a lifecycle — so
        # insertion order carries no meaning. Used only for per-account iteration.
        self._venue_lifecycles: Dict[str, Any] = dict(lifecycles) if lifecycles else {}
        # Owns the ONE feed's borrowed connection + provider; re-borrows when an account is
        # retired. None on the in-memory arm.
        self._feed_binder: Optional[Any] = None

        # ATTACHED by build_live_system after construction: each references this facade's
        # own callbacks, so none can be built until the facade exists. All stay None on a
        # facade built outside build_live_system.
        self._safety: Optional[Any] = None
        self._stream_recovery: Optional[Any] = None
        self._throttle: Optional[Any] = None
        self._config_router: Optional[Any] = None
        # Strategies that could NOT be rehydrated at boot. A DEDICATED field, not folded
        # into ``last_error``: that is single-valued, so the next error would overwrite the
        # list — and this list is what tells an operator which strategies silently do not
        # trade.
        self._quarantined_strategies: list[str] = []

        # Read-model sinks, gated on the SQL spine. _system_store is the durable KV for
        # state.*; _system_stats_store is the append-only engine-operational stats series.
        self._system_store: Optional[Any] = None
        self._system_stats_store: Optional[Any] = None

        # The facade owns _stop_event so stop() can latch shutdown; both the LiveRunner
        # drain loop and its composed WorkerSupervisor honour it.
        self._running = False
        self._stop_event = threading.Event()

        self._stats = {
            'events_processed': 0,
            'orders_executed': 0,
            # A throttle-REFUSED order never reached execution, so counting it in
            # orders_executed would over-report submissions.
            'orders_throttle_rejected': 0,
            'last_event_time': None,
            'uptime_start': None,
            'errors_count': 0
        }
        self._stats_lock = threading.Lock()

        # "Not yet wired" sentinels, populated by _initialize_live_session.
        self.universe: Optional[Universe] = None
        self._universe_handler: Optional[Any] = None
        # Session init stays DEFERRED to start(). Moving it to construction time breaks the
        # add-strategy-after-construction and monkeypatch-before-start() contracts the live
        # test suite relies on. The idempotency guard makes a second call a no-op.
        self._session_initialized = False

        self._live_runner: Optional[Any] = None
        self._error_policy: Optional[Any] = None

        self.logger.info('Live trading system initialized')

    def _streaming_lifecycles(self) -> List[Any]:
        """Every assembled lifecycle whose bundle carries a live connector.

        ``bundle.connector is not None`` is the streaming-venue discriminator (paper
        carries a lifecycle with no connector); keeping it here keeps it in one place.
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

        Parameters
        ----------
        exchange : str
            The execution venue to build a spec for (e.g. ``'okx'``, ``'paper'``).
        status_callback : callable, optional
            Forwarded to the facade; invoked on each status transition.
        **overrides
            ``data_provider`` / ``account_id`` for a bespoke spec, or ``data_plugins``
            for TEST-only data-provider injection.

        Returns
        -------
        LiveTradingSystem
            The fully built facade.
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
        """LiveRunner loop-entry hook: the status/stats side-effects the runner cannot own."""
        self._safety.update_status(SystemStatus.RUNNING)
        with self._stats_lock:
            self._stats['uptime_start'] = datetime.now(UTC).isoformat()

    def _increment_error_count(self) -> None:
        with self._stats_lock:
            self._stats['errors_count'] += 1

    def _on_loop_error(self, exc: BaseException) -> None:
        self._increment_error_count()

    # ---- Safety delegators. Bodies live on the injected SafetyController; the facade
    # ---- forwards so external call sites work over one source of truth. HALTED is
    # ---- latched — reset_halt() is its only legal exit — while pause_submission is the
    # ---- reversible disconnect quiesce, resumed after a fresh REST snapshot. ---------

    def halt(self, reason: str) -> None:
        """Latch the freeze-in-place halt.

        Parameters
        ----------
        reason : str
            Operator-facing cause, recorded on the durable halt record.
        """
        self._safety.halt(reason)

    def reset_halt(self) -> bool:
        """Operator-only clear of the latched halt.

        Returns
        -------
        bool
            True if a halt was cleared, False if the engine was not halted.
        """
        return self._safety.reset_halt()

    def is_halted(self) -> bool:
        """Whether the engine is in the latched HALTED state.

        Returns
        -------
        bool
        """
        return self._safety.is_halted()

    def pause_submission(self, reason: str) -> None:
        """Reversibly quiesce NEW order submission.

        Parameters
        ----------
        reason : str
            Operator-facing cause, surfaced as ``paused_reason`` in the status view.
        """
        self._safety.pause_submission(reason)

    def resume_submission(self) -> None:
        """Clear the reversible pause after reconnect and a fresh REST snapshot."""
        self._safety.resume_submission()

    def _build_reconciliation_coordinator(self) -> Any:
        """Construct the startup ReconciliationCoordinator from CURRENT venue state.

        Built at ``start()`` rather than in ``build_live_system`` because an offline run
        swaps collaborators before ``start()``, so a build-time capture would reconcile
        against stale ones.

        It takes NO per-account scalars: each portfolio supplies its own account, that
        account supplies its connector, and the exchange resolves out of the pair-keyed
        registry. "Compare portfolio A against account B" is therefore a type error
        rather than a rule someone has to follow.
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

        Thread-safe ``bus.put`` ONLY — no blocking venue I/O on the connector asyncio
        loop. The engine-thread STREAM_STATE route actuates it as
        ``SafetyController.pause_submission``. Fires once per sustained disconnect.
        """
        self.logger.warning(
            'Venue %s stream disconnected — emitting STREAM_STATE(down)', stream_name)
        self.global_queue.put(StreamStateEvent(
            time=datetime.now(UTC), stream_name=stream_name, up=False))

    def _on_venue_stream_up(self, stream_name: str) -> None:
        """Connector-loop callback: emit a STREAM_STATE(up) CONTROL event.

        Thread-safe ``bus.put`` ONLY: the fresh REST snapshot / catch-up must NOT run
        here, because a ``connector.call`` on the connector loop deadlocks it. The
        engine-thread STREAM_STATE route actuates it as
        ``StreamRecoveryHandler.on_reconnect``, where the blocking resume I/O belongs.
        """
        self.logger.info(
            'Venue %s stream reconnected — emitting STREAM_STATE(up)', stream_name)
        self.global_queue.put(StreamStateEvent(
            time=datetime.now(UTC), stream_name=stream_name, up=True))

    def _request_connector_halt(self, reason: str) -> None:
        """Connector-loop callback: emit a CONNECTOR_FATAL CONTROL event.

        Puts a CONTROL event and nothing else. Driving the blocking ``halt()`` here would
        run its durable ``record_halt`` SQL write on the connector loop and stall every
        stream sharing it; the engine-thread CONNECTOR_FATAL route runs that off-loop.

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

        SafetyController owns the flip and invokes this OUTSIDE its ``_status_lock``, on
        the winning transition only, to add facade-side detail the machine does not hold.
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

        # A status transition is low-rate, so snapshotting here needs no aggregation.
        self._snapshot_system_stats()

    def _snapshot_system_stats(self) -> None:
        """Append one engine-operational counter row to ``system_stats``.

        Snapshots ONLY counters the engine already holds in memory — no domain-store
        entity data (equity and friends are read from their own stores) and no secret.
        Best-effort: a durable append failure is swallowed so it can never abort the
        engine event that triggered it.
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
                'throttle_breach_count': (
                    self._throttle.breach_count if self._throttle is not None else 0),
                # ONE aggregate error counter; warning/critical stay 0 until a
                # per-severity surface exists.
                'error_count_warning': 0,
                'error_count_error': errors,
                'error_count_critical': 0,
                'queue_depth': self.get_queue_size(),
                'uptime_seconds': uptime_seconds,
                # Health proxies from the safety latch: CONNECTOR_FATAL->halt and
                # STREAM_STATE->pause_submission are the sources.
                'connector_up': not halted,
                'stream_up': not paused,
            }
            self._system_stats_store.append(row, at=datetime.now(UTC))
        except Exception as exc:
            self.logger.warning(
                'Failed to append system_stats (swallowed): %s', exc)

    def _update_stats(self, event_type: Optional[str] = None):
        with self._stats_lock:
            if event_type:
                self._stats['events_processed'] += 1
                self._stats['last_event_time'] = datetime.now(UTC).isoformat()

                # Caller passes event.type.name, so compare against the enum name.
                if event_type == EventType.ORDER.name:
                    self._stats['orders_executed'] += 1

    def _on_order_throttle_rejected(self) -> None:
        """LiveRunner hook: a pre-submit-throttle-REFUSED ORDER.

        The throttle rejected this ORDER at the execution boundary, so the runner skips
        ``_update_stats`` — which would bump ``orders_executed`` and over-report
        submissions. The order WAS dequeued, so it still counts in ``events_processed``.
        """
        with self._stats_lock:
            self._stats['events_processed'] += 1
            self._stats['last_event_time'] = datetime.now(UTC).isoformat()
            self._stats['orders_throttle_rejected'] += 1

    def _record_bar_metrics(self, event) -> None:
        """Record the per-bar equity curve on ``EventType.BAR``.

        Must key on BAR, not TIME: ``LiveBarFeed`` emits only ``BarEvent`` on the live
        path — the bar's arrival IS the event — so a TIME key never fires and leaves the
        live equity curve permanently empty. Stamp each snapshot with the bar-open
        BUSINESS time, never wall-clock.
        """
        if getattr(event, 'type', None) != EventType.BAR:
            return
        for portfolio in self.portfolio_handler.get_active_portfolios():
            portfolio.record_metrics(event.time)

    def _initialize_live_session(self):
        """Initialize the live trading session by delegating to ``SessionInitializer``.

        Invoked at ``start()``, and by the offline ``TestRunner`` before its per-bar
        drive. IDEMPOTENT via the ``_session_initialized`` guard.
        """
        if self._session_initialized:
            return
        self.logger.info('Initializing live trading session')

        try:
            from itrader import config as _system_config

            engine = self._engine

            # Venue metadata (validate_symbol / resolve_precision) is a VENUE property,
            # not an account property, so any streaming lifecycle's exchange is an equally
            # correct source. The fallback is a SUBSCRIPT, not a soft ``.get``: a None here
            # would reach SessionInitializer and silently degrade validate_symbol /
            # resolve_precision with no exception raised anywhere near the defect.
            streaming = self._streaming_lifecycles()
            venue_exchange = (
                streaming[0].bundle.exchange if streaming
                else self.execution_handler.exchanges[
                    (COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)])

            # Read from the LIVE universe sub-model, never the frozen determinism base,
            # so the backtest oracle config stays untouched.
            universe_config = UniverseHandlerConfig(
                poll_timeframe=_system_config.stream.okx_stream_timeframe,
                remove_policy=_system_config.universe.remove_policy,
            )

            # safety + stream_recovery are threaded through so the registrar can point
            # the CONTROL routes at their engine-thread actuators.
            initializer = SessionInitializer(
                engine,
                universe_config=universe_config,
                venue_exchange=venue_exchange,
                # ONE feed, so ONE data provider: the connection the binder borrowed.
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

            # Set AFTER wiring succeeds, so a failed init can be retried.
            self._session_initialized = True
            self.logger.info('Live trading session initialized')
            
        except Exception as e:
            self.logger.error(f'Failed to initialize live session: {e}')
            self._safety.update_status(SystemStatus.ERROR, str(e))
            raise
    
    def start(self):
        """Initialize the session, then start the event-processing thread.

        Returns
        -------
        bool
            True once the drain thread is running. False when the system was already
            running, when a durable halt record refused the start, when the engine
            halted during session init, or when start failed (status -> ERROR).
        """
        if self._running:
            self.logger.warning('Live trading system is already running')
            return False

        # MUST sit ABOVE the try below: inside it, the broad `except Exception` would
        # swallow this and mask a facade built outside build_live_system() as a mere
        # SystemStatus.ERROR.
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

        # Best-effort: a durable-write failure must not abort start.
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
            # The DURABLE halt gate MUST run FIRST — before session init, venue connect,
            # feed warmup, stream spawn, or reconcile — so a durably-halted engine refuses
            # to start INERT: zero venue I/O, no state-mutating reconcile, no second
            # durable record.
            if self._safety.check_durable_halt_on_start():
                self._running = False
                return False

            self._initialize_live_session()

            # The venue connector's network connect happens HERE, deferred out of
            # __init__ so construction stays I/O-free. EVERY account is started: an
            # assembled-but-unconnected account would still be registered in
            # ExecutionHandler.exchanges and halt-wired, yet every order routed to it
            # would fail against an unconnected session. Paper no-ops the connector step.
            for lifecycle in self._venue_lifecycles.values():
                lifecycle.start()

            # Warm the LIVE feed BEFORE the socket goes live, so every update() stays on
            # one thread until the stream starts (single-writer ring guard).

            streaming = self._streaming_lifecycles()
            data_provider = (
                self._feed_binder.feed_provider
                if self._feed_binder is not None else None)
            if data_provider is not None:
                # Subscription set is SOURCED FROM MEMBERSHIP. Per member: warm the feed
                # FIRST (REST replay sets the ring), THEN subscribe the live socket.
                # Never reorder — subscribing first races the ring's first write.
                from itrader import config as _system_config
                members = self.universe.members if self.universe is not None else []
                for sym in members:
                    self.feed.warmup(sym, _system_config.stream.okx_stream_timeframe)
                    data_provider.subscribe(sym)

            # SOLE spawn site for OkxExchange._stream_fills()/_stream_orders(). Without
            # it no real FillEvent ever streams back and every order mirror stays PENDING
            # forever while looking healthy. Must run AFTER the connector client +
            # load_markets are live (the watch_* streams need them) and BEFORE the
            # reconcile, so the streams are live during it (fill-ID dedup covers the
            # concurrent-stream case). connect() RETURNS a ConnectionResult and never
            # raises, so a bare call would swallow the failure.
            for lifecycle in streaming:
                result = lifecycle.bundle.exchange.connect()
                if not result.success:
                    raise RuntimeError(
                        f'OKX exchange stream connect failed: {result.error_message}')

            # Engine thread, before RUNNING: durable ledger restore for any account kind,
            # then — keyed on account KIND (Account.is_venue_truth, never
            # exchange == 'okx') — the venue REST reconcile plus the baseline guard that
            # HALTs on an unexplained base-asset residual.
            self._build_reconciliation_coordinator().run_startup_reconcile()

            # A reconcile/baseline-guard halt during session init must LATCH. The
            # processing thread's first action is an unconditional RUNNING stamp, so it
            # must not be spawned at all — update_status refusing HALTED->RUNNING is only
            # the second line of defence.
            if self._safety.is_halted():
                self.logger.error(
                    'start() refused RUNNING: engine HALTED during session init '
                    '(reason=%s) — the reconciler/baseline guard declared venue state '
                    'untrustworthy; not spawning the processing thread',
                    self._safety.status_snapshot()['halt_reason'])
                self._running = False
                return False

            # LiveRunner owns both threads. _running is set BEFORE start() so a status
            # callback fired from the loop-entry hook already observes a running facade.
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
        """Stop the live trading system gracefully.

        Parameters
        ----------
        timeout : float
            Maximum seconds to wait for the drain thread to join.

        Returns
        -------
        bool
            True on a clean stop, including the "was not running" path. Venue teardown
            runs on every path regardless (see below).
        """
        # Venue teardown runs UNCONDITIONALLY, independent of _running: any lifecycle that
        # constructs-then-stops without a successful start() (validation, a failed start(),
        # status inspection, GC) must still cancel every spawned stream task and close the
        # ccxt/native sessions, or an authenticated socket leaks — a dangling venue
        # connection in production, and a ResourceWarning (a hard failure) under
        # filterwarnings=["error"]. Hence the finally, covering every return path including
        # the early "not running" exit, over EVERY account symmetric with start().
        # Snapshot into a list, not a live view, so a teardown that mutates the map cannot
        # raise "dictionary changed size during iteration"; it sits BEFORE the try so the
        # finally holds the full map on every path. getattr because stop() must survive a
        # partially-constructed facade.
        lifecycles = list((getattr(self, '_venue_lifecycles', None) or {}).items())
        try:
            if not self._running:
                self.logger.warning('Live trading system is not running')
                return True

            self.logger.info('Stopping live trading system')
            self._safety.update_status(SystemStatus.STOPPING)

            if self._live_runner is not None:
                self._live_runner.stop(timeout=timeout)

            self._running = False
            self._safety.update_status(SystemStatus.STOPPED)

            self.logger.info('Live trading system stopped')
            return True
        finally:
            # The try/except sits per-iteration, deliberately NOT inside
            # VenueLifecycle.stop(), which stays honest and keeps raising for its own
            # callers. Isolating here stops one bad venue from stranding the other venues'
            # sockets or the SQL dispose below, and stops a teardown failure from masking
            # an exception already propagating out of the try body.
            for account_id, lifecycle in lifecycles:
                try:
                    lifecycle.stop()
                except Exception as e:
                    self.logger.error(
                        f'Error disconnecting venue connector for account {account_id}: {e}')
            # Dispose the SQL spine so its connection pool closes — an undisposed engine
            # leaks a socket / ResourceWarning under filterwarnings=["error"].
            backend = getattr(self, '_system_db_backend', None)
            if backend is not None:
                try:
                    backend.dispose()
                except Exception as e:
                    self.logger.error(f'Error disposing operational SQL backend: {e}')
    
    def is_running(self) -> bool:
        """Whether the system is live.

        Returns
        -------
        bool
            True only when the facade is running AND its drain thread is alive.
        """
        runner = self._live_runner
        thread = runner._thread if runner is not None else None
        return self._running and thread is not None and thread.is_alive()
    
    def get_status(self) -> Dict[str, Any]:
        """Merge the SafetyController status latch with facade-side stats.

        Returns
        -------
        dict
            Status, ``halt_reason``, the reversible ``paused`` state, thread liveness,
            queue depth, throttle/breaker counters, quarantined strategies, and the
            ``statistics`` block with derived ``uptime_seconds``.
        """
        snap = self._safety.status_snapshot()
        status = snap['status']
        with self._stats_lock:
            uptime = None
            if self._stats['uptime_start'] and status == SystemStatus.RUNNING:
                start_time = datetime.fromisoformat(self._stats['uptime_start'])
                # uptime_start is tz-aware, so the comparand must be too, or this raises
                # "can't subtract offset-naive and offset-aware datetimes".
                uptime = (datetime.now(UTC) - start_time).total_seconds()

            return {
                'status': status.value,
                'halt_reason': snap['halt_reason'],
                # The reversible pause-on-disconnect state, surfaced DISTINCTLY from the
                # terminal halt — paused != HALTED.
                'paused': snap['paused'],
                'paused_reason': snap['paused_reason'],
                'is_running': self.is_running(),
                'exchange': self.exchange,
                'queue_size': self.get_queue_size(),
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
                # NOT trading, despite their registry rows still declaring them enabled:
                # the row is never rewritten, because the DB holds operator INTENT.
                'quarantined_strategies': list(self._quarantined_strategies),
                # Read None-safely — ErrorPolicy is unwired on a facade built outside
                # build_live_system.
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
        """The current depth of the global event queue.

        Returns
        -------
        int
        """
        return self.global_queue.qsize()

    def get_signal_records(self):
        """The signals captured during the live run.

        A read-model sink read, NOT a cross-domain handler call, so the queue-only
        contract holds.

        Returns
        -------
        list
            Every recorded signal, in capture order.
        """
        return self._signal_store.get_all()

    def get_signal_store(self):
        """The signal store itself, for its query surface.

        Returns
        -------
        SignalStore
            Exposes ``by_strategy`` / ``by_ticker`` in addition to ``get_all``.
        """
        return self._signal_store

    def add_event(self, event):
        """Enqueue an externally-originated event.

        The engine's PUBLIC external/web surface, and therefore DEFAULT-DENY. The
        sanctioned order entry is SIGNAL-form: a raw ``OrderEvent`` admitted here would
        reach the execution queue with NO admission control, so only ``SIGNAL`` (which
        routes through ``AdmissionManager``), ``STRATEGY_COMMAND`` and ``CONFIG_UPDATE``
        are allowed through.

        Parameters
        ----------
        event
            The event to enqueue. Must be one of the three admissible types; a
            ``CONFIG_UPDATE`` is additionally validated synchronously here.

        Returns
        -------
        bool
            True once queued. False when the system is not running, the type is not
            admissible, ingress validation refused it, or the put itself failed.
        """
        if not self._running:
            self.logger.warning('Cannot add event: Live trading system is not running')
            return False

        event_type = getattr(event, 'type', None)
        if event_type not in _EXTERNALLY_ADMISSIBLE:
            self.logger.warning(
                'Rejected external add_event of type %s (D-10 fail-closed default-deny) — only '
                'SIGNAL, STRATEGY_COMMAND and CONFIG_UPDATE are admissible from the external '
                'surface; every internal-fact type (incl. raw ORDER injection) must route through '
                'the engine internally, never the public queue directly', event_type)
            return False

        # Synchronous reject at the boundary; the engine-thread ConfigRouter re-checks
        # behind it for defense-in-depth.
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
        the value. The ``venue`` / ``portfolio`` scopes get a shape check only, because
        venue-kind and portfolio-existence are state-dependent and belong on the engine
        thread.
        """
        import uuid

        from itrader.config.order import OrderConfig
        from itrader.config.system import SystemSettings
        from itrader.config.universe import UniverseConfig

        # No durable store means no ConfigRouter and no target to persist to. Reject here
        # so the caller gets a truthful False rather than a silent enqueue-then-drop.
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
            # Reject a truthy non-bool, or the string "false" silently ENABLES a venue.
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

        Runs on the EXTERNAL caller thread, so it must NOT read the live mutable ``config``
        sub-models the ENGINE thread writes — that would be a cross-thread read of the
        single-writer overlay. A fresh instance of the same sub-model TYPE gives the same
        check: ``validate_assignment=True`` re-runs the field's own coercion and
        ``Field(...)`` constraints per-field, so siblings are irrelevant.
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
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
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

    The sequence is ``defaults <- YAML <- env <- persisted``. Frozen base params
    (``rng_seed`` / ``environment`` / identity) resolve at CONSTRUCTION and are never
    persisted-overridden. Each scope is read back from its OWNING module store — system
    from ``SystemStore``, order from the ORDER store, venue from ``VenueStore``, portfolio
    from each Portfolio's own bound ``state_storage`` — so config is never read back from
    ``SystemStore`` for the order/portfolio scopes.

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

    # Each scope layers under its OWN guard, so a bad persisted override is logged and
    # skipped rather than crashing boot, and one bad scope never aborts the others.
    # Deliberately NOT a bare Exception: a genuine programming error still surfaces.
    _degrade_clean = (
        SQLAlchemyError, ConfigurationError, pydantic.ValidationError, ValueError)

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

    # The read_all() acquisition keeps its own guard; the per-row push is then guarded PER
    # ENTRY so one poisoned venue degrades only that venue.
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

    # Resolved via the handler's PUBLIC all_portfolios(), never the private registry. The
    # guard is PER ENTRY so one poisoned config_json degrades only that portfolio;
    # all_portfolios() is a pure copy, so the loop needs no acquisition guard.
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
    reads config, builds the ONE live ``sql_engine`` (Postgres-gated), builds the component
    graph off the ``PriorityEventBus``, assembles venues, constructs the facade via pure
    injection, and composes the ``LiveRunner``, its ``WorkerSupervisor`` and the
    ``ErrorPolicy`` around it. Live session wiring stays DEFERRED to ``start()``.

    ``data_plugins`` and ``strategy_catalog`` are CODE artifacts the application hands in,
    as opposed to ``spec``, which is persisted config.

    Parameters
    ----------
    spec : VenueSpec
        The declarative venue spec; ``spec.execution_venue`` names the venue.
    status_callback : callable, optional
        Forwarded to the facade; invoked on each status transition.
    data_plugins : dict[str, Any], optional
        TEST-only data-provider plugins, registered AFTER the production ones.
    strategy_catalog : dict[str, type], optional
        The only thing that turns a stored ``strategy_type`` string into a class, so
        the app decides what is instantiable at boot. With registry rows present, a
        missing catalog fails LOUD rather than booting an engine that looks healthy
        and trades nothing.

    Returns
    -------
    LiveTradingSystem
        The facade, fully wired but NOT started.
    """
    logger = get_itrader_logger().bind(component="LiveTradingSystem")
    exchange = spec.execution_venue

    # Inert without CONTROL events: everything flows BUSINESS-tier and the monotonic seq
    # keeps strict FIFO.
    global_queue = PriorityEventBus()
    # Live carries store=None — the LiveBarFeed reads no store.
    from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
    feed = LiveBarFeed(provider=None, base_timeframe=to_timedelta('1d'))

    # Storage is selected by ENV-PRESENCE of a Postgres credential on the unified
    # ITRADER_DATABASE_* surface — the same source Alembic's env.py uses — with no
    # hardcoded credential fallback. Probed at BUILD time so it honors per-construction
    # env, and BEFORE constructing a Postgres SqlSettings, which raises when no credential
    # is present. The SQLite default driver skips _require_pg_credentials, so the probe
    # itself never raises.
    from itrader.config.sql import SqlSettings
    probe = SqlSettings()
    if probe.password is None and probe.url is None:
        # Fail loudly into the in-memory fallback — never a default credential string.
        logger.warning(
            "No Postgres credential in env (ITRADER_DATABASE_PASSWORD / "
            "ITRADER_DATABASE_URL unset) — using in-memory order + signal storage "
            "(orders/signals will NOT survive a restart)"
        )
        # Each arm selects ONLY the environment string + the shared SQL spine;
        # compose_engine's handler-OWNED storage init derives the concrete backends from
        # (environment, sql_engine). 'backtest' with sql_engine=None yields in-memory order
        # + signal stores.
        environment = 'backtest'
        system_db_backend: Optional[Any] = None
    else:
        from itrader.config.sql import SqlDriver, SqlSettings
        from itrader.storage import SqlEngine

        # 'live' + the shared SqlEngine drive that same init to the durable path: orders
        # via CachedSqlOrderStorage over SqlOrderStorage (store-first working set,
        # rehydrate() on restart), the signal store live-driven over the same spine.
        backend = SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
        environment = 'live'
        system_db_backend = backend

    # Durable halt-record store over the shared spine, so a halt survives a process
    # restart. A SEPARATE infra handle from the venue holder — folding it in would
    # recreate the collaborator bag.
    if system_db_backend is not None:
        from itrader.storage.halt_record_store import HaltRecordStore
        halt_record_store: Optional[Any] = HaltRecordStore(system_db_backend)
    else:
        halt_record_store = None

    # The live handler graph comes from the shared compose_engine, never a hand-rolled
    # parallel copy. EngineContext is the mode-injection seam: feed = the LiveBarFeed,
    # store = None, and environment + sql_engine reflect the credential-probe arm.
    from itrader import config as _system_config
    from itrader.trading_system.compose import compose_engine

    # The ERROR-route collaborators are built BEFORE compose so they ride in through
    # compose_engine, the one mode-agnostic build site, never a post-build monkeypatch.
    # alert_sink is the CRITICAL/halt egress and binds only declared ErrorEvent fields, so
    # no connector secret can leak. error_policy's halt + error_counter are late-bound
    # below, once SafetyController and the facade exist.
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
    # Safe here because registration is INERT: it stores plugin objects and runs no
    # ``build*()``, so it pulls no ccxt and changes no import-time behaviour.
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

    # The credentials boundary. venue_account_store is the durable (venue_name,
    # account_id) home: it supplies each account's secret_ref POINTER and records/asserts
    # the trust-on-first-use venue_uid. credential_resolver is injected into the OKX
    # connector plugin — WITHOUT it the plugin falls back to a bare OkxSettings() reading
    # the ONE global OKX_API_* set, so two account_ids would connect with IDENTICAL
    # credentials while the system believes they are separate accounts.
    from itrader.config.credential_resolver import EnvCredentialResolver

    if system_db_backend is not None:
        from itrader.storage.venue_account_store import VenueAccountStore
        venue_account_store: Optional[Any] = VenueAccountStore(system_db_backend)
    else:
        venue_account_store = None
    credential_resolver = EnvCredentialResolver()

    # Store-only: no build*() runs, so this pulls no ccxt.
    exec_registry = ExecutionVenueRegistry()
    data_registry = DataProviderRegistry()
    connectors = ConnectorProvider(
        {'okx': OkxConnectorPlugin(resolver=credential_resolver)})
    exec_registry.register('okx', OkxVenuePlugin())
    # The plugin builds its own SimulatedExchange from the config it is given. Seeding a
    # LIVE-derived symbol set instead of the default preset would change live admission.
    exec_registry.register('paper', PaperVenuePlugin(default_exchange_config()))
    data_registry.register('okx', OkxDataPlugin())

    # TEST-only DATA provider injection, registered AFTER production: the paper<->replay
    # pairing lives ONLY in the fixture.
    if data_plugins:
        for _name, _plugin in data_plugins.items():
            data_registry.register(_name, _plugin)

    # The ONE seeded determinism RNG, built at the wiring seam and injected on ctx rather
    # than derived inside a handler.
    rng = random.Random(int(_system_config.rng_seed))

    ctx = EngineContext(
        bus=global_queue,
        config=_system_config,
        environment=environment,
        feed=feed, rng=rng, store=None,
        sql_engine=system_db_backend,
    )
    # The ONE bundle memo, shared with the venue-assembly loop below, so the execution arm
    # and the per-account assembly can never hold two exchanges for one (venue,
    # account_id) — two OkxExchange objects per account would double-spawn that account's
    # fill/order streams.
    venue_bundles = VenueBundles(exec_registry, connectors, ctx)
    # The ONE (venue, account_id) -> exchange map, created BEFORE compose so the execution
    # handler (built inside compose, reads it on order) and VenueAccountManager (built
    # below, writes each brought-online exchange into it) hold the SAME object. Distinct
    # from ``exec_registry``: that is the venue PLUGIN registry the bundle memo builds
    # over; this is the exchange OBJECT registry.
    exchange_registry: Dict[tuple, Any] = {}

    # The account AUTHORITY and factory are built BEFORE compose, each with a REAL
    # collaborator at construction — no late-init, no Optional manager, no
    # post-construction attribute set. The mode difference lives ONLY in WHICH authority is
    # injected: the SQL arm validates the pair through the real VenueAccountManager
    # (raising VenueAccountNotProvisionedError on missing/disabled/not-online) and then
    # builds a COMPUTE leaf carrying the real pair, while the in-memory arm uses the
    # bundles-backed authority that never raises, so a manager-less boot is not stranded.
    # The venue-truth VenueAccount leaf CANNOT be the construction-time leaf: its balance
    # raises until the first snapshot, and Portfolio.__init__ reads balance.
    from itrader.portfolio_handler.portfolio_factory import (
        ComputeAccountAuthority,
        PortfolioFactory,
        VenueValidatedComputeAuthority,
    )

    venue_manager: Optional[Any] = None
    # The ONE feed's connection binder: the feed borrows the first available venue
    # CONNECTION and re-borrows when that account is retired/disabled. It owns the provider
    # build, the feed wiring and the re-borrow rule; the manager drives it from
    # bring_online.
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
        # The venue-ACCOUNT domain owner. It EXCLUSIVELY owns the durable
        # ``venue_accounts`` store and shares the ONE ``venue_bundles`` memo +
        # ``connectors`` provider the execution arm holds. It receives the shared
        # ``exchange_registry`` — the SAME map compose hands the execution handler — and
        # NOT the handler itself: ``bring_online`` writing that map directly is the cut
        # that lets the manager be built here, above compose.
        venue_manager = VenueAccountManager(
            venue_account_store,
            venue_bundles,
            connectors,
            exchange_registry,
            alert_sink=alert_sink,
            feed_binder=feed_binder,
        )
        account_authority: Any = VenueValidatedComputeAuthority(
            manager=venue_manager,
            compute=ComputeAccountAuthority(
                venue_bundles=venue_bundles, compute_venue=COMPUTE_VENUE),
        )
    else:
        account_authority = ComputeAccountAuthority(
            venue_bundles=venue_bundles, compute_venue=COMPUTE_VENUE)

    # The sole leaf-builder ``PortfolioHandler`` constructs every portfolio through.
    # ``environment`` / ``system_db_backend`` select the durable state-storage backend the
    # factory scopes per portfolio_id.
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
        # LIVE resolves each order's venue account from its portfolio through the
        # injected read-model, so an account's orders can never be submitted through
        # another account's authenticated session. Backtest deliberately leaves it False.
        route_orders_by_account=True)

    # Only the three handles the remaining wiring touches are taken here; the facade
    # sources the FULL graph off the engine in __init__.
    execution_handler = engine.execution_handler
    portfolio_handler = engine.portfolio_handler
    event_handler = engine.event_handler

    # PORTFOLIO + VENUE BOOTSTRAP. The account SET is STORE-DERIVED — read off durable
    # ``venue_accounts`` rows through VenueAccountManager, never re-derived from the spec —
    # so no account identity is computed in this file.
    #
    # Boot order is distinct-account check -> venue assembly -> rehydrate. Assembly MUST
    # precede rehydrate so the manager's ``_online`` map is full when rehydrate
    # materializes each row; otherwise a portfolio naming a not-provisioned / disabled /
    # not-online account silently sits on a compute leaf instead of raising.
    #
    # Both maps are declared here so facade construction, StreamRecoveryHandler and the
    # halt-signal wiring see them on EVERY path — a boot with no SQL spine comes up RUNNING
    # and empty.
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

        # The store the handler already OWNS. One instance, so the rehydrate read and the
        # add_portfolio write-back can never diverge.
        definition_store = portfolio_handler.definition_store

        # A not-yet-provisioned `portfolios` table is the first-start state, NOT a fault.
        # Deliberately narrow — it probes for the TABLE and nothing else, so a genuine
        # store fault still propagates LOUD rather than becoming a silent zero-portfolio
        # boot.
        has_table = definition_store is not None and _sa_inspect(
            system_db_backend.engine).has_table("portfolios")
        if definition_store is not None and not has_table:
            logger.warning(
                "The `portfolios` table is not provisioned — skipping portfolio "
                "rehydrate (first start, or the Alembic chain has not run). No "
                "portfolio will be restored until the schema exists.")

        # Runs FIRST, so a collision is refused before any account exists.
        if has_table:
            assert_distinct_accounts(persisted=definition_store.read_all())

        # VENUE ASSEMBLY. ``bring_online`` builds the account's VenueSpec (carrying its
        # OWN ``secret_ref`` and config overrides), assembles the bundle through the shared
        # memo, registers the exchange under the row's (venue, account_id) pair VERBATIM,
        # and arms the UID guard. ``read_enabled_for`` carries its own table probe, so a
        # boot before ``venue_accounts`` exists brings up zero accounts rather than
        # raising. The lifecycle map is keyed by the row's account id — the same key the
        # exchange registry and the facade's per-account reads use.
        for row in venue_manager.read_enabled_for(exchange):
            record = venue_manager.bring_online(row)
            venue_lifecycles[str(row["account_id"])] = record.lifecycle
        # Finalize the feed's connection binding once the bring-up loop is done. A boot
        # with zero streaming accounts leaves the feed UNBOUND and logs the cause here,
        # since bring_online's per-row rebind never ran.
        venue_manager.rebind_feed()

        # Recreates the portfolio objects with their PERSISTED ids, so portfolio-scoped
        # child tables and strategy-subscription rows reattach to portfolios that still
        # exist. Assembly running first changes neither WHICH portfolios rehydrate nor
        # their order — that contract is the store's.
        if has_table:
            rehydrate_portfolios(
                store=definition_store,
                portfolio_handler=portfolio_handler,
            )


    # DIRECT PURE INJECTION, no collaborator bag: the compose Engine is the single source
    # of truth for the handler graph, the VenueLifecycle map is the venue/connector holder,
    # and the SQL spine + halt store stay separate infra handles.
    facade = LiveTradingSystem(
        engine=engine,
        lifecycles=venue_lifecycles,
        system_db_backend=system_db_backend,
        halt_record_store=halt_record_store,
        exchange=exchange,
        status_callback=status_callback,
    )

    # RUNTIME-CONFIG PLATFORM: the engine-thread ConfigRouter over the OWNING module
    # stores — system -> SystemStore, order -> the ORDER store, venue -> VenueStore,
    # portfolio -> each Portfolio's OWN bound state_storage, never SystemStore. Attached to
    # the facade so _initialize_live_session threads it into the CONFIG_UPDATE route.
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
        # POSITION is pinned by three constraints. Portfolios must already EXIST with
        # restart-stable ids, so each stored subscription binds to a portfolio that is
        # really there and still carries that id after the next restart. Session init
        # BELOW reads the strategy list — wire_universe derives membership from it,
        # register_strategy_warmup sizes the feed ring from it — so a strategy registered
        # after either would never enter the universe and never size the ring. And it must
        # NOT live inside _initialize_live_session, which integration tests (including a
        # RESTART test) monkeypatch to a no-op, silently losing the rehydrate exactly where
        # it matters most.
        #
        # Deliberately NOT wrapped in try/except _degrade_clean: per-instance failures are
        # ALREADY handled inside rehydrate_strategies (skip + CRITICAL alert + the row left
        # untouched), while an infrastructure failure must fail LOUD. A blanket wrap would
        # convert the loud arm into a silent boot with zero strategies.
        from itrader.strategy_handler.registry.rehydrate import rehydrate_strategies

        # The store is READ BACK off the handler that OWNS it, so a rehydrated strategy's
        # first runtime verb always has a store to persist to; without that, an
        # enable/disable landing between boot and the next wiring step would apply live and
        # vanish at restart. A None store is the first-start state (unprovisioned
        # strategy_registry table) or an unwired SQL spine — not an infrastructure failure,
        # so skipping cannot produce the zero-strategies-while-rows-exist outcome, and a
        # genuine store fault still PROPAGATES loud out of rehydrate_strategies.
        strategy_registry_store = engine.strategies_handler.registry_store
        if strategy_registry_store is not None:
            facade._quarantined_strategies = rehydrate_strategies(
                store=strategy_registry_store,
                catalog=strategy_catalog,
                strategies_handler=engine.strategies_handler,
                alert_sink=alert_sink,
            )

    # The four safety collaborators. Each is a plain injected collaborator with NO facade
    # back-reference beyond the callbacks it is handed.
    from itrader.core.clock import WallClock
    from itrader.trading_system.safety.pre_trade_throttle import PreTradeThrottle
    from itrader.trading_system.safety.safety_controller import SafetyController
    from itrader.trading_system.safety.stream_recovery_handler import (
        StreamRecoveryHandler,
    )

    # dispatch_fn is LATE-BOUND so the gate always dispatches through the CURRENT inner
    # dispatch: a test monkeypatch of event_handler._dispatch is honoured, and
    # gate_and_dispatch replay reaches it too.
    safety = SafetyController(
        bus=global_queue,
        halt_record_store=halt_record_store,
        dispatch_fn=lambda ev: event_handler._dispatch(ev),
        notify_status_change=facade._notify_status_change,
        # Durable read-model KV sink for state.status / state.halt_reason.
        system_store=system_store,
    )
    # Engine-thread reconnect-resume I/O: catch-up + snapshot + all-streams gate -> resume.
    # Injected with the per-account LIFECYCLE MAP so catch-up and the health gate cover
    # EVERY account. ``venue_accounts`` is a CALLABLE over the accounts the portfolios
    # actually hold — a build-time capture goes stale the moment an account is
    # re-attached.
    stream_recovery = StreamRecoveryHandler(
        safety=safety,
        lifecycles=venue_lifecycles,
        venue_accounts=lambda: list(venue_accounts.values()),
        # Read LIVE through the binder so the all-streams health gate covers the candle arm
        # and tracks a runtime re-borrow.
        feed_provider=(
            lambda: feed_binder.feed_provider if feed_binder is not None else None),
    )
    # Pre-trade risk backstop (rate + notional caps), off the WALL clock.
    throttle = PreTradeThrottle(
        settings=_system_config.safety.throttle,
        clock=WallClock(),
        bus=global_queue,
    )
    facade._safety = safety
    facade._stream_recovery = stream_recovery
    facade._throttle = throttle
    # The feed-connection binder the live session reads its bound data provider through.
    facade._feed_binder = feed_binder

    # Read-model sinks: the durable KV (state.last_started_at at start();
    # SafetyController/ErrorHandler own the other state.* keys) plus the append-only
    # system_stats series over the SAME SqlEngine, which _snapshot_system_stats appends to
    # on each status transition. Both degrade to None on the in-memory fallback.
    facade._system_store = system_store
    if system_db_backend is not None:
        from itrader.storage.system_stats_store import SystemStatsStore
        facade._system_stats_store = SystemStatsStore(system_db_backend)
    else:
        facade._system_stats_store = None

    # Facade-dependent wiring: the halt-signal + stream-state listeners emit CONTROL
    # events (_request_connector_halt -> ConnectorFatalEvent, _on_venue_stream_down/up ->
    # StreamStateEvent), never flag flips.
    #
    # ONE loop over every streaming lifecycle, deliberately not a primary/secondary split.
    # Two copies of one wiring rule is how a second account ends up accepting orders after
    # a connector-fatal halt latched the first — a partially-halted engine is worse than a
    # single-account one, because the surviving arm looks healthy.
    #
    # The DATA provider stays deliberately single (one feed), so it is wired outside the
    # loop, read through the FeedConnectionBinder. The ``is not None`` guard stays: the
    # unregistered-venue arm, a zero-account boot and the in-memory arm all legitimately
    # yield no provider.
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

    # Engine-thread drift-halt signal -> freeze-in-place halt.
    portfolio_handler.set_halt_signal(facade.halt)

    # Late-bind the tripwire's runtime collaborators now that SafetyController and the
    # facade exist. compose_engine already injected the ErrorPolicy object as the
    # dispatcher's failure policy AND the ErrorHandler's failure_sink; bind() resolves the
    # construction cycle with the two deferred collaborators, both needed only when a
    # failure actually occurs.
    error_policy.bind(halt=safety.halt, error_counter=facade._increment_error_count)

    # The live runtime engine. LiveRunner OWNS the drain loop and COMPOSES the
    # WorkerSupervisor; the dispatch gate is SafetyController.gate_and_dispatch (the
    # freeze-in-place gate), with the pre-submit throttle firing at the ORDER->execution
    # boundary ahead of it.
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
