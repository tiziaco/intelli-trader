import random
import threading
from datetime import datetime, UTC
from decimal import Decimal
from functools import partial
from typing import (
    Optional, Dict, List, Any, Callable, TYPE_CHECKING)

from itrader.core.enums import HaltReason, SystemStatus
from itrader.core.exceptions import StateError, ValidationError
from itrader.execution_handler.execution_handler import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID
from itrader.outils.time_parser import to_timedelta
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.trading_system.venue_spec import build_venue_spec
# The boot sequence and the restart config-layering pass both live under
# ``trading_system/live/`` — inside the live import-graph boundary, so they may pull SQL at
# module top. tests/integration/test_okx_inertness.py asserts by PREFIX that nothing under
# that package reaches the backtest graph.
from itrader.trading_system.live.bootstrap import (
    bootstrap_session,
    layer_persisted_overrides,
)
from itrader.trading_system.session_initializer import SessionInitializer
from itrader.trading_system.engine_context import EngineContext
from itrader.universe import Universe
from itrader.universe.universe_handler import UniverseHandlerConfig

from itrader.logger import get_itrader_logger
from itrader.events_handler.bus import PriorityEventBus
from itrader.events_handler.events import EventType, StreamStateEvent, ConnectorFatalEvent

if TYPE_CHECKING:
    # Forward-ref only — importing it eagerly would pull it onto the graph.
    from itrader.trading_system.compose import Engine

# Live drain-loop timing knobs, injected into the LiveRunner.
_LIVE_QUEUE_TIMEOUT = 1.0   # queue poll
_LIVE_MAX_IDLE_TIME = 300.0  # idle-warn window

# ``add_event``'s default-deny allowlist. Internal flow is unaffected — handlers put
# onto ``global_queue`` directly, never through ``add_event``.
_EXTERNALLY_ADMISSIBLE = frozenset(
    {EventType.SIGNAL, EventType.STRATEGY_COMMAND, EventType.CONFIG_UPDATE}
)

_control_logger = get_itrader_logger().bind(component="ConnectorControlSignals")


# --- connector-loop CONTROL signals ------------------------------------------------
#
# These run on the CONNECTOR's asyncio loop thread, so they PUT a CONTROL event and do
# nothing else: the engine-thread routes actuate them (STREAM_STATE -> pause/resume,
# CONNECTOR_FATAL -> halt), where the blocking durable write belongs.
#
# They are free functions over the bus rather than facade methods because the venue-account
# manager arms them at bring-up, and the manager is constructed before the facade exists.
# One implementation, two callers.


def emit_connector_fatal(bus: Any, reason: str) -> None:
    """Escalate a connector-loop fatal as a CONNECTOR_FATAL CONTROL event.

    The event carries a FIXED reason literal, NEVER ``str(exc)`` or the passed ``reason``,
    so no connector secret crosses the loop->engine boundary. Driving the blocking
    ``halt()`` here would run its durable ``record_halt`` SQL write on the connector loop
    and stall every stream sharing it.
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


class LiveTradingSystem:
    """Live-trading facade: a thin delegator over an injected engine and collaborators.

    Drains the global queue on a background daemon thread rather than the backtest
    system's synchronous for-loop.
    """

    def __init__(
        self,
        *,
        engine: "Engine",
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

        # The ONE data adapter and the session it owns. Built and fully armed by the
        # builder; the facade only opens the session at start() and subscribes the
        # universe's symbols. None when the run's data venue has no recipe (or no
        # session, as for an offline replay source).
        self._data_provider: Optional[Any] = None
        self._data_connector: Optional[Any] = None
        # The venue-ACCOUNT domain owner — the ONE enumeration of what is online, and the
        # one path that brings an account up or takes it down. None on the in-memory arm.
        self._venue_manager: Optional[Any] = None
        # The run-scoped session pool, torn down once at stop() after every account has
        # released its own session. None on the in-memory arm.
        self._connector_pool: Optional[Any] = None
        # The restart sequence start() runs: bring accounts online, rehydrate portfolios,
        # layer persisted config, rehydrate strategies — in that order, as one callable so
        # the ordering cannot be split apart by a later edit.
        self._restart_sequence: Optional[Callable[[], None]] = None

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
            for the TEST-only data-recipe override.

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
        """Whether the engine is in the latched HALTED state."""
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

        It takes NO per-account scalars: the account manager's online records supply each
        account's adapter and connector, and the portfolio is resolved from the record's
        own ``(venue_name, account_id)`` pair. "Compare portfolio A against account B" is
        therefore unexpressible rather than a rule someone has to follow.
        """
        from itrader.portfolio_handler.reconcile.reconciliation_coordinator import (
            ReconciliationCoordinator,
        )
        return ReconciliationCoordinator(
            portfolio_handler=self.portfolio_handler,
            seed_applied_trades=self.order_handler.order_manager.seed_applied_trades,
            order_storage=self._order_storage,
            global_queue=self.global_queue,
            halt=self.halt,
            records=self._online_account_records,
        )

    def _streaming_adapters(self) -> List[Any]:
        """Every online account's adapter that carries a live venue session.

        ``record.connector is not None`` is the streaming-venue discriminator (paper
        accounts carry no session). Enumerated at CALL time off the manager, so an account
        brought online later is covered without a second container to keep in step.
        """
        return [
            record.adapter for record in self._online_account_records()
            if record.connector is not None
        ]

    def _online_account_records(self) -> List[Any]:
        """The account manager's online records, or ``[]`` without a manager.

        Read at CALL time so an account brought online after a collaborator was
        constructed is still covered.
        """
        if self._venue_manager is None:
            return []
        records: List[Any] = self._venue_manager.online_records()
        return records

    def _on_venue_stream_down(self, stream_name: str) -> None:
        """Connector-loop callback: emit a STREAM_STATE(down) CONTROL event."""
        emit_stream_down(self.global_queue, stream_name)

    def _on_venue_stream_up(self, stream_name: str) -> None:
        """Connector-loop callback: emit a STREAM_STATE(up) CONTROL event."""
        emit_stream_up(self.global_queue, stream_name)

    def _request_connector_halt(self, reason: str) -> None:
        """Connector-loop callback: emit a CONNECTOR_FATAL CONTROL event."""
        emit_connector_fatal(self.global_queue, reason)

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
            # not an account property, so any session-bearing account's adapter is an
            # equally correct source. The fallback is a SUBSCRIPT, not a soft ``.get``: a
            # None here would reach SessionInitializer and silently degrade
            # validate_symbol / resolve_precision with no exception raised anywhere near
            # the defect.
            streaming = self._streaming_adapters()
            venue_exchange = (
                streaming[0] if streaming
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
                # ONE feed, so ONE data adapter — the one the builder wired to it.
                data_provider=self._data_provider,
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
    
    def _bootstrap_session(self) -> None:
        """Run the restart sequence the builder bound: bring-up, rehydrate, layer, roster.

        Called from ``start()`` rather than at construction because bring-up CONNECTS: an
        account becomes routable only after its session is open, so performing it while
        building the object would make constructing a live system a network operation.

        A facade built outside ``build_live_system`` has no durable state to restore and is
        a clean no-op.
        """
        if self._restart_sequence is None:
            return
        self._restart_sequence()

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

            # RESTART TRUTH, and the SOLE venue bring-up. Every network connect happens
            # inside it — deferred out of __init__ so construction stays I/O-free — and
            # each account becomes routable only once its session is open, its identity
            # asserted and its streams armed. It runs BEFORE session init (which reads a
            # venue adapter for symbol metadata and the bound feed provider), before the
            # feed warmup/subscribe below, and before the startup reconcile, which
            # enumerates exactly the accounts it brought online.
            self._bootstrap_session()

            # The data adapter's OWN session. Opened here rather than at build so
            # constructing a live system performs no venue I/O, and BEFORE the warmup
            # below, which fetches history through it. It is independent of every account:
            # a boot that brought zero accounts online still receives bars. An offline
            # data source (the replay harness) carries no session and skips this.
            feed_provider = self._data_provider
            if self._data_connector is not None:
                self._data_connector.connect()

            self._initialize_live_session()

            if feed_provider is not None:
                # Subscription set is SOURCED FROM MEMBERSHIP. Per member: warm the feed
                # FIRST (REST replay sets the ring), THEN subscribe the live socket.
                # Never reorder — subscribing first races the ring's first write, and
                # warming before the socket is live keeps every update() on one thread
                # (single-writer ring guard).
                from itrader import config as _system_config
                members = self.universe.members if self.universe is not None else []
                for sym in members:
                    self.feed.warmup(sym, _system_config.stream.okx_stream_timeframe)
                    feed_provider.subscribe(sym)

            # Engine thread, before RUNNING: durable ledger restore for any account kind,
            # then — for each account the manager reports ONLINE with a real session behind
            # it — the venue REST reconcile plus the baseline guard that HALTs on an
            # unexplained base-asset residual.
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
        # Venue teardown runs UNCONDITIONALLY, independent of _running: an account that
        # comes online and then stops without a successful start() (validation, a failed
        # start(), status inspection, GC) must still cancel every spawned stream task and
        # close the ccxt/native sessions, or an authenticated socket leaks — a dangling
        # venue connection in production, and a ResourceWarning (a hard failure) under
        # filterwarnings=["error"]. The finally covers every return path, over EVERY
        # account, symmetric with start().
        # Snapshot the PAIRS, not a live view, so a teardown that mutates the manager's map
        # cannot raise "dictionary changed size during iteration"; it sits BEFORE the try so
        # the finally holds the full set on every path.
        manager = getattr(self, '_venue_manager', None)
        online_pairs = (
            [(record.spec.venue_name, record.spec.account_id)
             for record in manager.online_records()]
            if manager is not None else [])
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
            # Per-account teardown, each closing ONLY its own session. The try/except sits
            # per-iteration so one bad venue cannot strand the other accounts' sockets or
            # the pool/SQL teardown below, and so a teardown failure cannot mask an
            # exception already propagating out of the try body.
            for venue_name, account_id in online_pairs:
                try:
                    manager.bring_offline(venue_name, account_id)
                except Exception as e:
                    self.logger.error(
                        f'Error retiring venue account ({venue_name}, {account_id}): {e}')
            # The ONE run-scoped session teardown, after every account released its own:
            # it closes anything left (a public session, a session whose account never
            # completed bring-up) and drops the memo.
            pool = getattr(self, '_connector_pool', None)
            if pool is not None:
                try:
                    pool.close_all()
                except Exception as e:
                    self.logger.error(f'Error closing the connector pool: {e}')
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
        """The current depth of the global event queue."""
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
            candidate = model_cls()
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
        TEST-only override mapping of data-venue name to data-adapter RECIPE, merged
        OVER the production recipes so a fixture can supply an offline data source.
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
    from itrader.venues.okx_plugin import OkxConnectorPlugin, OkxVenuePlugin
    from itrader.execution_handler.exchanges.okx import build_okx_exchange
    from itrader.venues.paper_plugin import PaperVenuePlugin, paper_exchange_recipe
    from itrader.venues.registry import ExecutionVenueRegistry

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

    exec_registry = ExecutionVenueRegistry()
    connectors = ConnectorProvider(
        {'okx': OkxConnectorPlugin(resolver=credential_resolver)})
    # The venue-account domain's own session pool: one authenticated session per account,
    # built from the venue's connector recipe and torn down by the account that owns it.
    # Distinct from ``connectors`` above, which the surviving bundle memo still holds.
    from itrader.connectors.okx import build_okx_connector
    from itrader.connectors.pool import ConnectorPool
    from itrader.venues.catalog import CATALOG

    connector_pool = ConnectorPool(
        catalog=CATALOG,
        resolver=credential_resolver,
        recipes={'okx': build_okx_connector},
    )
    exec_registry.register('okx', OkxVenuePlugin())
    # The plugin builds its own SimulatedExchange from the config it is given. Seeding a
    # LIVE-derived symbol set instead of the default preset would change live admission.
    exec_registry.register('paper', PaperVenuePlugin(default_exchange_config()))

    # The DATA recipes: venue name -> the function building that venue's data adapter.
    # A mapping of functions, selected by a dict lookup, exactly like the execution
    # recipes. TEST-only overrides are merged OVER production, so the paper<->replay
    # pairing lives only in the fixture that asks for it.
    from itrader.price_handler.providers.okx_provider import build_okx_data_provider

    data_recipes: Dict[str, Any] = {'okx': build_okx_data_provider}
    if data_plugins:
        data_recipes.update(data_plugins)

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

    # THE DATA PLANE — ONE adapter, on its OWN session, built here and never re-pointed.
    #
    # Which venue serves candles is a RUN-level choice: the spec names it, falling back to
    # the execution venue's catalogue default. It is not a per-account property, and an
    # account retiring changes order routing only — the feed is untouched, because it
    # borrows nothing from any account.
    #
    # The session is the venue's PUBLIC one whenever the descriptor says its market data
    # needs no credentials (OKX candles are public), so the data plane does not name an
    # account at all. A venue that declares ``data_requires_auth`` gets the run account's
    # authenticated session instead — the only case where the feed must name an account,
    # because its data is not public. A venue with no catalogue entry is a test-injected
    # data source with no session to build.
    #
    # Building is I/O-FREE: no session is opened here. Opening it is engine I/O and
    # belongs to the run's start, so constructing a live system stays offline.
    data_venue = (
        getattr(spec, 'data_provider', None)
        or (CATALOG[exchange].default_data_provider if exchange in CATALOG else 'okx'))
    data_descriptor = CATALOG.get(data_venue)
    data_connector: Optional[Any] = None
    if data_descriptor is not None and not data_descriptor.data_requires_auth:
        data_connector = connector_pool.public_session(data_venue)
    elif data_descriptor is not None:
        data_account = getattr(spec, 'account_id', None)
        if data_account is None:
            raise ValidationError(
                'account_id', str(data_account),
                f"venue {data_venue!r} serves market data only over an AUTHENTICATED "
                f"session, but this run names no account to authenticate as — the feed "
                f"would come up with no data source")
        data_connector = connector_pool.session(data_venue, str(data_account), spec)
    try:
        data_recipe = data_recipes[data_venue]
    except KeyError:
        # Loud, because the alternative is an engine that runs and trades on nothing.
        raise KeyError(
            f"no data recipe for venue {data_venue!r} — this system builds "
            f"{sorted(data_recipes)}") from None
    data_provider = data_recipe(
        connector=data_connector,
        ctx=ctx,
        feed=feed,
        global_queue=global_queue,
        # The SAME bus-bound callbacks the execution adapters are armed with, so a
        # candle-stream fatal freezes the engine and a candle-stream drop pauses
        # submission exactly as a fill-stream one does.
        halt_signal=partial(emit_connector_fatal, global_queue),
        stream_state_listener=(
            partial(emit_stream_down, global_queue),
            partial(emit_stream_up, global_queue),
        ),
    )

    venue_manager: Optional[Any] = None
    if system_db_backend is not None:
        from itrader.venues.accounts import VenueAccountManager

        # The venue-ACCOUNT domain owner. It EXCLUSIVELY owns the durable
        # ``venue_accounts`` store and the account sessions in the pool. It receives the
        # shared ``exchange_registry`` — the SAME map compose hands the execution handler —
        # and NOT the handler itself: ``bring_online`` writing that map directly, as its
        # LAST step, is the cut that lets the manager be built here, above compose.
        venue_manager = VenueAccountManager(
            store=venue_account_store,
            pool=connector_pool,
            routing=exchange_registry,
            catalog=CATALOG,
            exchange_recipes={
                'okx': build_okx_exchange,
                # The paper adapter's recipe is bound to THIS run's exchange config; a
                # default preset would silently narrow order admission.
                'paper': paper_exchange_recipe(default_exchange_config()),
            },
            ctx=ctx,
            alert_sink=alert_sink,
            # Bound to the bus, not to the facade: the manager arms these on every
            # session-bearing adapter at bring-up, and the facade does not exist yet.
            # The facade's own callbacks delegate to the SAME functions.
            halt_signal=partial(emit_connector_fatal, global_queue),
            stream_state_listener=(
                partial(emit_stream_down, global_queue),
                partial(emit_stream_up, global_queue),
            ),
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

    execution_handler = engine.execution_handler
    portfolio_handler = engine.portfolio_handler
    event_handler = engine.event_handler

    # The PORTFOLIO + VENUE BOOTSTRAP is NOT run here. Bring-up CONNECTS — it opens each
    # account's session, spawns its streams and asserts its venue identity before the
    # account becomes routable — so running it at construction would make building a live
    # system a network operation. ``start()`` runs it, through the one home of its ordering
    # (``live/bootstrap.py``), so boot-time and runtime bring-up are the same call.

    # DIRECT PURE INJECTION, no collaborator bag: the compose Engine is the single source
    # of truth for the handler graph, and the SQL spine + halt store stay separate infra
    # handles.
    facade = LiveTradingSystem(
        engine=engine,
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
    venue_store: Optional[Any] = None
    if system_store is not None:
        from itrader.core.clock import WallClock
        from itrader.storage.venue_store import VenueStore
        from itrader.trading_system.config_router import ConfigRouter

        venue_store = VenueStore(system_db_backend)

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

    # THE RESTART SEQUENCE, bound here and RUN by start(). Its three steps are ordered by
    # hard data dependencies, which is why they travel as one callable rather than three
    # attachments a later edit could reorder:
    #
    #   1. bring every enabled account online and rehydrate the persisted portfolios
    #      (assembly BEFORE rehydrate, so a portfolio naming a not-provisioned or disabled
    #      account raises instead of silently sitting on an unbacked leaf);
    #   2. layer the persisted config, which iterates the portfolios step 1 materialized —
    #      running it first would iterate an empty collection and drop every stored
    #      portfolio override;
    #   3. rehydrate the stored strategy roster, which binds each subscription to a
    #      portfolio that must already exist with its restart-stable id.
    #
    # It runs at start() rather than here because step 1 CONNECTS: an account becomes
    # routable only once its session is open, so performing it while building the object
    # would make constructing a live system a network operation.
    def _run_restart_sequence() -> None:
        bootstrap_session(
            sql_engine=system_db_backend,
            venue_manager=venue_manager,
            portfolio_handler=portfolio_handler,
            execution_venue=exchange,
            alert_sink=alert_sink,
        )
        if system_store is None:
            return
        # Base params are already resolved at construction (frozen).
        layer_persisted_overrides(
            _system_config,
            system_store=system_store,
            venue_store=venue_store,
            order_handler=order_handler,
            portfolio_handler=portfolio_handler,
            execution_handler=execution_handler,
        )
        # Session init reads the strategy list — wire_universe derives membership from it,
        # register_strategy_warmup sizes the feed ring from it — so a strategy registered
        # after either would never enter the universe and never size the ring. It must also
        # NOT live inside _initialize_live_session, which integration tests (including a
        # RESTART test) monkeypatch to a no-op, silently losing the rehydrate exactly where
        # it matters most.
        #
        # Deliberately NOT wrapped in try/except: per-instance failures are ALREADY handled
        # inside rehydrate_strategies (skip + CRITICAL alert + the row left untouched),
        # while an infrastructure failure must fail LOUD. A blanket wrap would convert the
        # loud arm into a silent boot with zero strategies.
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

    facade._restart_sequence = _run_restart_sequence

    # The safety collaborators. Each is a plain injected collaborator with NO facade
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
    # ONE enumeration — the manager's online records, read at USE time — serves the
    # catch-up, the REST snapshot and the health gate, so every job covers EVERY account
    # and none of them can drift from the others. A build-time container is what previously
    # left the snapshot loop iterating something nothing wrote.
    stream_recovery = StreamRecoveryHandler(
        safety=safety,
        accounts=(
            lambda: venue_manager.online_records() if venue_manager is not None else []),
        # The ONE data adapter, so the all-streams health gate covers the candle arm too.
        feed_provider=lambda: data_provider,
        alert_sink=alert_sink,
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
    facade._data_provider = data_provider
    facade._data_connector = data_connector
    facade._venue_manager = venue_manager
    facade._connector_pool = connector_pool

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

    # Each account's own adapter + connector are halt- and stream-state-wired by
    # ``bring_online``, before the account becomes routable — one rule, applied at the one
    # place an account comes up, so a second account cannot end up accepting orders after a
    # connector-fatal halt latched the first. The DATA adapter is armed the same way, by
    # its own recipe at build; ``start()`` only opens its session and subscribes it.

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
