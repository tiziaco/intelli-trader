"""The live facade — status, safety, ingress and lifecycle over a pre-built graph.

``LiveTradingSystem`` holds NO composition knowledge. Every collaborator arrives as a
**required** constructor parameter, so a collaborator that was built and never attached is
a ``TypeError`` at the composition root rather than an attribute that reads ``None`` at the
one call site that needed it (design §4.9). A parameter whose value
may legitimately be ``None`` — there is no durable spine, so there is no config router —
is still REQUIRED: absence is a value the root has to state, not one it can omit.

``LiveTelemetry`` lives here beside the facade because the two split one job: the facade
answers "what is this engine doing", the telemetry object owns the counters that answer
carries. Keeping the counters off the facade is also what lets the composition root build
the ``LiveRunner`` and the ``SafetyController`` BEFORE the facade exists — their hooks bind
to the telemetry object, not to a facade that does not exist yet.

Indentation: 4-space. ``mypy --strict`` applies.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

import pydantic

from itrader.config.itrader_config import ITraderConfig
from itrader.config.order import OrderConfig
from itrader.config.system import SystemSettings
from itrader.config.universe import UniverseConfig
from itrader.core.enums import SystemStatus
from itrader.events_handler.events import EventType
from itrader.execution_handler.execution_handler import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID
from itrader.logger import get_itrader_logger
from itrader.portfolio_handler.reconcile.reconciliation_coordinator import (
    ReconciliationCoordinator,
)
from itrader.trading_system.session_initializer import SessionInitializer
from itrader.universe import Universe
from itrader.universe.universe_handler import UniverseHandlerConfig

if TYPE_CHECKING:
    from itrader.trading_system.graph import Engine

#: ``add_event``'s default-deny allowlist. Internal flow is unaffected — handlers put onto
#: ``global_queue`` directly, never through ``add_event``.
_EXTERNALLY_ADMISSIBLE = frozenset(
    {EventType.SIGNAL, EventType.STRATEGY_COMMAND, EventType.CONFIG_UPDATE}
)


class LiveTelemetry:
    """Engine-operational counters, the status-change notification, and the stats sink.

    Built BEFORE the safety plane so ``SafetyController`` and ``LiveRunner`` can bind their
    hooks to it. ``bind`` closes the one genuine construction cycle: the controller notifies
    on every status transition, and the notification snapshots the controller's own latch.
    Resolved with an explicit ``bind`` rather than a post-construction attribute set, which
    is the same seam ``ErrorPolicy.bind`` already uses for its two deferred collaborators.
    """

    def __init__(
        self,
        *,
        bus: Any,
        exchange: str,
        status_callback: Optional[
            Callable[[SystemStatus, Dict[str, Any]], None]],
        system_stats_store: Optional[Any],
        throttle: Any,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="LiveTelemetry")
        self._bus = bus
        self._exchange = exchange
        self._status_callback = status_callback
        self._system_stats_store = system_stats_store
        self._throttle = throttle
        # Set by ``bind`` before any hook can fire; typed Any so the post-bind reads
        # below need no narrowing for a state that cannot occur.
        self._safety: Any = None
        self._lock = threading.Lock()
        self.stats: Dict[str, Any] = {
            'events_processed': 0,
            'orders_executed': 0,
            'orders_throttle_rejected': 0,
            'last_event_time': None,
            'uptime_start': None,
            'errors_count': 0,
        }

    def bind(self, safety: Any) -> None:
        """Attach the safety latch the status snapshot reads (the declared cycle)."""
        self._safety = safety

    # -- LiveRunner hooks ---------------------------------------------------------

    def on_loop_start(self) -> None:
        """Loop-entry hook: the status/stats side-effects the runner cannot own."""
        self._safety.update_status(SystemStatus.RUNNING)
        with self._lock:
            self.stats['uptime_start'] = datetime.now(UTC).isoformat()

    def on_loop_error(self, exc: BaseException) -> None:
        self.increment_errors()

    def increment_errors(self) -> None:
        with self._lock:
            self.stats['errors_count'] += 1

    def update(self, event_type: Optional[str] = None) -> None:
        with self._lock:
            if not event_type:
                return
            self.stats['events_processed'] += 1
            self.stats['last_event_time'] = datetime.now(UTC).isoformat()
            # Caller passes event.type.name, so compare against the enum name.
            if event_type == EventType.ORDER.name:
                self.stats['orders_executed'] += 1

    def on_order_throttle_rejected(self) -> None:
        """A pre-submit-throttle-REFUSED ORDER.

        The throttle rejected this ORDER at the execution boundary, so the runner skips
        ``update`` — which would bump ``orders_executed`` and over-report submissions. The
        order WAS dequeued, so it still counts in ``events_processed``.
        """
        with self._lock:
            self.stats['events_processed'] += 1
            self.stats['last_event_time'] = datetime.now(UTC).isoformat()
            self.stats['orders_throttle_rejected'] += 1

    # -- SafetyController hook ----------------------------------------------------

    def on_status_change(
        self,
        old_status: SystemStatus,
        new_status: SystemStatus,
        error_msg: Optional[str],
    ) -> None:
        """Status-change enrichment callback injected into ``SafetyController``.

        The controller owns the flip and invokes this OUTSIDE its ``_status_lock``, on the
        winning transition only, to add detail the machine does not hold.
        """
        if self._status_callback is not None:
            try:
                self._status_callback(new_status, {
                    'status': new_status.value,
                    'exchange': self._exchange,
                    'queue_size': self._bus.qsize(),
                    'timestamp': datetime.now(UTC).isoformat(),
                    'error': error_msg,
                })
            except Exception as exc:
                self.logger.error(f'Error in status callback: {exc}')

        # A status transition is low-rate, so snapshotting here needs no aggregation.
        self.snapshot_system_stats()

    def snapshot_system_stats(self) -> None:
        """Append one engine-operational counter row to ``system_stats``.

        Snapshots ONLY counters the engine already holds in memory — no domain-store entity
        data (equity and friends are read from their own stores) and no secret. Best-effort:
        a durable append failure is swallowed so it can never abort the engine event that
        triggered it.
        """
        if self._system_stats_store is None:
            return
        try:
            with self._lock:
                errors = self.stats['errors_count']
                uptime_start = self.stats['uptime_start']
            uptime_seconds = Decimal('0')
            if uptime_start is not None:
                started = datetime.fromisoformat(uptime_start)
                uptime_seconds = Decimal(
                    str((datetime.now(UTC) - started).total_seconds()))
            paused = (
                self._safety.is_submission_paused()
                if self._safety is not None else False)
            halted = self._safety.is_halted() if self._safety is not None else False
            self._system_stats_store.append({
                'throttle_breach_count': self._throttle.breach_count,
                # ONE aggregate error counter; warning/critical stay 0 until a per-severity
                # surface exists.
                'error_count_warning': 0,
                'error_count_error': errors,
                'error_count_critical': 0,
                'queue_depth': self._bus.qsize(),
                'uptime_seconds': uptime_seconds,
                # Health proxies from the safety latch: CONNECTOR_FATAL->halt and
                # STREAM_STATE->pause_submission are the sources.
                'connector_up': not halted,
                'stream_up': not paused,
            }, at=datetime.now(UTC))
        except Exception as exc:
            self.logger.warning(
                'Failed to append system_stats (swallowed): %s', exc)


def record_bar_metrics(portfolio_handler: Any, event: Any) -> None:
    """Record the per-bar equity curve on ``EventType.BAR``.

    Must key on BAR, not TIME: ``LiveBarFeed`` emits only ``BarEvent`` on the live path —
    the bar's arrival IS the event — so a TIME key never fires and leaves the live equity
    curve permanently empty. Stamp each snapshot with the bar-open BUSINESS time, never
    wall-clock.
    """
    if getattr(event, 'type', None) != EventType.BAR:
        return
    for portfolio in portfolio_handler.get_active_portfolios():
        portfolio.record_metrics(event.time)


class LiveTradingSystem:
    """Live-trading facade: a thin delegator over an injected engine and collaborators.

    Drains the global queue on a background daemon thread rather than the backtest
    system's synchronous for-loop.
    """

    def __init__(
        self,
        *,
        engine: "Engine",
        config: ITraderConfig,
        exchange: str,
        telemetry: LiveTelemetry,
        safety: Any,
        stream_recovery: Any,
        throttle: Any,
        error_policy: Any,
        live_runner: Any,
        stop_event: threading.Event,
        boot: Callable[[], List[str]],
        config_router: Optional[Any],
        venue_accounts: Optional[Any],
        connector_pool: Optional[Any],
        data_provider: Optional[Any],
        data_connector: Optional[Any],
        sql_engine: Optional[Any],
        halt_record_store: Optional[Any],
        system_store: Optional[Any],
        system_stats_store: Optional[Any],
    ) -> None:
        """Pure-injection constructor: pre-built collaborators in, fresh runtime state out.

        EVERY parameter is required. Several are typed ``Optional`` because absence is a
        real deployment state (no durable spine means no config router and no venue-account
        manager), but the root must still say so explicitly — that is what makes a
        built-but-unattached collaborator a ``TypeError`` rather than a silent ``None``.

        Parameters
        ----------
        engine : Engine
            The composed handler graph. The single source of truth — every
            handler/feed/storage field is sourced off it.
        config : ITraderConfig
            The run's config root, read for the universe/stream sub-models at session init.
        exchange : str
            The execution venue this run brings its enabled accounts online for.
        telemetry : LiveTelemetry
            The counters behind ``get_status`` and the ``system_stats`` sink.
        safety, stream_recovery, throttle, error_policy, live_runner :
            The safety plane and the drain-loop runtime, all built by the root.
        stop_event : threading.Event
            The shutdown latch shared with the ``LiveRunner`` and its ``WorkerSupervisor``.
        boot : callable
            The restart sequence ``start()`` runs, returning the quarantined-strategy ids.
        venue_accounts : Any | None
            The venue-ACCOUNT domain owner — the operator surface, exposed as the property
            of the same name. ``None`` only when there is no durable spine to own.
        """
        self.logger = get_itrader_logger().bind(component="LiveTradingSystem")

        self._engine = engine
        self._config = config
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
        self._order_storage = engine.order_handler.storage

        self._telemetry = telemetry
        self._safety = safety
        self._stream_recovery = stream_recovery
        self._throttle = throttle
        self._error_policy = error_policy
        self._live_runner = live_runner
        self._stop_event = stop_event
        self._boot = boot
        self._config_router = config_router
        # The venue-ACCOUNT domain owner — the ONE enumeration of what is online, and the
        # one path that brings an account up or takes it down.
        self._venue_manager = venue_accounts
        # The run-scoped session pool, torn down once at stop() after every account has
        # released its own session.
        self._connector_pool = connector_pool
        # The ONE data adapter and the session it owns, built and fully armed by the root;
        # the facade only opens the session at start() and subscribes the universe's
        # symbols. ``None`` when the run's data source carries no session (offline replay).
        self._data_provider = data_provider
        self._data_connector = data_connector

        self._system_db_backend = sql_engine
        self._halt_record_store = halt_record_store
        self._system_store = system_store
        self._system_stats_store = system_stats_store

        # Strategies that could NOT be rehydrated at boot. A DEDICATED field, not folded
        # into ``last_error``: that is single-valued, so the next error would overwrite the
        # list — and this list is what tells an operator which strategies silently do not
        # trade.
        self._quarantined_strategies: List[str] = []

        self._running = False

        # "Not yet wired" sentinels, populated by _initialize_live_session.
        self.universe: Optional[Universe] = None
        self._universe_handler: Optional[Any] = None
        # Session init stays DEFERRED to start(). Moving it to construction time breaks the
        # add-strategy-after-construction and monkeypatch-before-start() contracts the live
        # test suite relies on. The idempotency guard makes a second call a no-op.
        self._session_initialized = False

        self.logger.info('Live trading system initialized')

    # -- Operator surfaces ------------------------------------------------------------

    @property
    def venue_accounts(self) -> Any:
        """The venue-ACCOUNT domain owner: ``provision`` / ``set_enabled`` / ``bring_online``.

        The name ``VenueAccountNotProvisionedError`` already instructs operators to use
        (``system.venue_accounts.provision(venue, account_id, ...)``), so it has to be the
        name that exists.
        """
        return self._venue_manager

    # ---- Safety delegators. Bodies live on the injected SafetyController; the facade
    # ---- forwards so external call sites work over one source of truth. HALTED is
    # ---- latched — reset_halt() is its only legal exit — while pause_submission is the
    # ---- reversible disconnect quiesce, resumed after a fresh REST snapshot. ---------

    def halt(self, reason: str) -> None:
        """Latch the freeze-in-place halt; ``reason`` is recorded on the durable record."""
        self._safety.halt(reason)

    def reset_halt(self) -> bool:
        """Operator-only clear of the latched halt; False when it was not halted."""
        result: bool = self._safety.reset_halt()
        return result

    def is_halted(self) -> bool:
        """Whether the engine is in the latched HALTED state."""
        halted: bool = self._safety.is_halted()
        return halted

    def pause_submission(self, reason: str) -> None:
        """Reversibly quiesce NEW order submission."""
        self._safety.pause_submission(reason)

    def resume_submission(self) -> None:
        """Clear the reversible pause after reconnect and a fresh REST snapshot."""
        self._safety.resume_submission()

    # -- Venue-state reads --------------------------------------------------------------

    def _online_account_records(self) -> List[Any]:
        """The account manager's online records, or ``[]`` without a manager.

        Read at CALL time so an account brought online after a collaborator was constructed
        is still covered.
        """
        if self._venue_manager is None:
            return []
        records: List[Any] = self._venue_manager.online_records()
        return records

    def _streaming_adapters(self) -> List[Any]:
        """Every online account's adapter that carries a live venue session.

        ``record.connector is not None`` is the streaming-venue discriminator (paper
        accounts carry no session).
        """
        return [
            record.adapter for record in self._online_account_records()
            if record.connector is not None
        ]

    def _build_reconciliation_coordinator(self) -> ReconciliationCoordinator:
        """Construct the startup ``ReconciliationCoordinator`` from CURRENT venue state.

        Built at ``start()`` rather than at composition because an offline run swaps
        collaborators before ``start()``, so a build-time capture would reconcile against
        stale ones.

        It takes NO per-account scalars: the account manager's online records supply each
        account's adapter and connector, and the portfolio is resolved from the record's own
        ``(venue_name, account_id)`` pair. "Compare portfolio A against account B" is
        therefore unexpressible rather than a rule someone has to follow.
        """
        return ReconciliationCoordinator(
            portfolio_handler=self.portfolio_handler,
            seed_applied_trades=self.order_handler.order_manager.seed_applied_trades,
            order_storage=self._order_storage,
            global_queue=self.global_queue,  # type: ignore[arg-type]
            halt=self.halt,
            records=self._online_account_records,
        )

    # -- Session lifecycle --------------------------------------------------------------

    def _initialize_live_session(self) -> None:
        """Initialize the live trading session by delegating to ``SessionInitializer``.

        Invoked at ``start()``, and by the offline ``TestRunner`` before its per-bar drive.
        IDEMPOTENT via the ``_session_initialized`` guard.
        """
        if self._session_initialized:
            return
        self.logger.info('Initializing live trading session')

        try:
            engine = self._engine

            # Venue metadata (validate_symbol / resolve_precision) is a VENUE property, not
            # an account property, so any session-bearing account's adapter is an equally
            # correct source. The fallback is a SUBSCRIPT, not a soft ``.get``: a None here
            # would reach SessionInitializer and silently degrade validate_symbol /
            # resolve_precision with no exception raised anywhere near the defect.
            streaming = self._streaming_adapters()
            venue_exchange = (
                streaming[0] if streaming
                else self.execution_handler.exchanges[
                    (COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)])

            # Read from the LIVE universe sub-model, never the frozen determinism base, so
            # the backtest oracle config stays untouched.
            universe_config = UniverseHandlerConfig(
                poll_timeframe=self._config.stream.okx_stream_timeframe,
                remove_policy=self._config.universe.remove_policy,
            )

            # safety + stream_recovery are threaded through so the registrar can point the
            # CONTROL routes at their engine-thread actuators.
            initializer = SessionInitializer(
                engine,
                universe_config=universe_config,
                venue_exchange=venue_exchange,
                # ONE feed, so ONE data adapter — the one the root wired to it.
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
        """Run the restart sequence the root bound: bring-up, rehydrate, layer, roster.

        Called from ``start()`` rather than at construction because bring-up CONNECTS: an
        account becomes routable only once its session is open, so performing it while
        building the object would make constructing a live system a network operation.
        """
        self._quarantined_strategies = self._boot()

    def start(self) -> bool:
        """Initialize the session, then start the event-processing thread.

        Returns
        -------
        bool
            True once the drain thread is running. False when the system was already
            running, when a durable halt record refused the start, when the engine halted
            during session init, or when start failed (status -> ERROR).
        """
        if self._running:
            self.logger.warning('Live trading system is already running')
            return False

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
            # inside it — deferred out of construction so building stays I/O-free — and each
            # account becomes routable only once its session is open, its identity asserted
            # and its streams armed. It runs BEFORE session init (which reads a venue adapter
            # for symbol metadata and the bound feed provider), before the feed
            # warmup/subscribe below, and before the startup reconcile, which enumerates
            # exactly the accounts it brought online.
            self._bootstrap_session()

            # The data adapter's OWN session. Opened here rather than at build so
            # constructing a live system performs no venue I/O, and BEFORE the warmup below,
            # which fetches history through it. It is independent of every account: a boot
            # that brought zero accounts online still receives bars. An offline data source
            # (the replay harness) carries no session and skips this.
            feed_provider = self._data_provider
            if self._data_connector is not None:
                self._data_connector.connect()

            self._initialize_live_session()

            if feed_provider is not None:
                # Subscription set is SOURCED FROM MEMBERSHIP. Per member: warm the feed
                # FIRST (REST replay sets the ring), THEN subscribe the live socket. Never
                # reorder — subscribing first races the ring's first write, and warming
                # before the socket is live keeps every update() on one thread (single-writer
                # ring guard).
                members = self.universe.members if self.universe is not None else []
                for sym in members:
                    # ``warmup`` is the LIVE feed's REST-replay seam; the Engine holds the
                    # BASE feed type, which both roots share.
                    self.feed.warmup(  # type: ignore[attr-defined]
                        sym, self._config.stream.okx_stream_timeframe)
                    feed_provider.subscribe(sym)

            # Engine thread, before RUNNING: durable ledger restore for any account kind,
            # then — for each account the manager reports ONLINE with a real session behind
            # it — the venue REST reconcile plus the baseline guard that HALTs on an
            # unexplained base-asset residual.
            self._build_reconciliation_coordinator().run_startup_reconcile()

            # A reconcile/baseline-guard halt during session init must LATCH. The processing
            # thread's first action is an unconditional RUNNING stamp, so it must not be
            # spawned at all — update_status refusing HALTED->RUNNING is only the second line
            # of defence.
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

    def stop(self, timeout: float = 10.0) -> bool:
        """Stop the live trading system gracefully: drain, retire, close.

        Returns
        -------
        bool
            True on a clean stop, including the "was not running" path. Venue teardown runs
            on every path regardless (see below).
        """
        # Venue teardown runs UNCONDITIONALLY, independent of _running: an account that comes
        # online and then stops without a successful start() (validation, a failed start(),
        # status inspection, GC) must still cancel every spawned stream task and close the
        # ccxt/native sessions, or an authenticated socket leaks — a dangling venue
        # connection in production, and a ResourceWarning (a hard failure) under
        # filterwarnings=["error"]. The finally covers every return path, over EVERY account,
        # symmetric with start().
        # Snapshot the PAIRS, not a live view, so a teardown that mutates the manager's map
        # cannot raise "dictionary changed size during iteration"; it sits BEFORE the try so
        # the finally holds the full set on every path.
        manager = self._venue_manager
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
            self._live_runner.stop(timeout=timeout)
            self._running = False
            self._safety.update_status(SystemStatus.STOPPED)

            self.logger.info('Live trading system stopped')
            return True
        finally:
            # Per-account teardown, each closing ONLY its own session. The try/except sits
            # per-iteration so one bad venue cannot strand the other accounts' sockets or the
            # pool/SQL teardown below, and so a teardown failure cannot mask an exception
            # already propagating out of the try body.
            if manager is not None:
                for venue_name, account_id in online_pairs:
                    try:
                        manager.bring_offline(venue_name, account_id)
                    except Exception as e:
                        self.logger.error(
                            f'Error retiring venue account ({venue_name}, {account_id}): {e}')
            # The ONE run-scoped session teardown, after every account released its own: it
            # closes anything left (a public session, a session whose account never completed
            # bring-up) and drops the memo.
            if self._connector_pool is not None:
                try:
                    self._connector_pool.close_all()
                except Exception as e:
                    self.logger.error(f'Error closing the connector pool: {e}')
            # Dispose the SQL spine so its connection pool closes — an undisposed engine
            # leaks a socket / ResourceWarning under filterwarnings=["error"].
            if self._system_db_backend is not None:
                try:
                    self._system_db_backend.dispose()
                except Exception as e:
                    self.logger.error(f'Error disposing operational SQL backend: {e}')

    def is_running(self) -> bool:
        """True only when the facade is running AND its drain thread is alive."""
        thread = self._live_runner._thread
        return self._running and thread is not None and bool(thread.is_alive())

    # -- Read surfaces ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Merge the ``SafetyController`` status latch with facade-side stats."""
        snap = self._safety.status_snapshot()
        status = snap['status']
        stats = self._telemetry.stats
        uptime = None
        if stats['uptime_start'] and status == SystemStatus.RUNNING:
            start_time = datetime.fromisoformat(stats['uptime_start'])
            # uptime_start is tz-aware, so the comparand must be too, or this raises
            # "can't subtract offset-naive and offset-aware datetimes".
            uptime = (datetime.now(UTC) - start_time).total_seconds()
        thread = self._live_runner._thread

        return {
            'status': status.value,
            'halt_reason': snap['halt_reason'],
            # The reversible pause-on-disconnect state, surfaced DISTINCTLY from the terminal
            # halt — paused != HALTED.
            'paused': snap['paused'],
            'paused_reason': snap['paused_reason'],
            'is_running': self.is_running(),
            'exchange': self.exchange,
            'queue_size': self.get_queue_size(),
            'throttle_breach_count': self._throttle.breach_count,
            'thread_alive': thread.is_alive() if thread is not None else False,
            'thread_name': thread.name if thread is not None else None,
            'last_error': snap['last_error'],
            # NOT trading, despite their registry rows still declaring them enabled: the row
            # is never rewritten, because the DB holds operator INTENT.
            'quarantined_strategies': list(self._quarantined_strategies),
            'breaker': self._error_policy.breaker_snapshot(),
            'statistics': {**stats, 'uptime_seconds': uptime},
            'timestamp': datetime.now(UTC).isoformat(),
        }

    def get_queue_size(self) -> int:
        """The current depth of the global event queue."""
        size: int = self.global_queue.qsize()
        return size

    # -- External ingress ---------------------------------------------------------------

    def add_event(self, event: Any) -> bool:
        """Enqueue an externally-originated event.

        The engine's PUBLIC external/web surface, and therefore DEFAULT-DENY. The sanctioned
        order entry is SIGNAL-form: a raw ``OrderEvent`` admitted here would reach the
        execution queue with NO admission control, so only ``SIGNAL`` (which routes through
        ``AdmissionManager``), ``STRATEGY_COMMAND`` and ``CONFIG_UPDATE`` are allowed
        through.

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
                'Rejected external add_event of type %s (fail-closed default-deny) — only '
                'SIGNAL, STRATEGY_COMMAND and CONFIG_UPDATE are admissible from the external '
                'surface; every internal-fact type (incl. raw ORDER injection) must route '
                'through the engine internally, never the public queue directly', event_type)
            return False

        # Synchronous reject at the boundary; the engine-thread ConfigRouter re-checks behind
        # it for defense-in-depth.
        if event_type is EventType.CONFIG_UPDATE and not self._validate_config_ingress(event):
            return False

        try:
            self.global_queue.put(event)
            return True
        except Exception as e:
            self.logger.error(f'Failed to add event to queue: {e}')
            return False

    def _validate_config_ingress(self, event: Any) -> bool:
        """Synchronous ingress validation for a ``CONFIG_UPDATE``.

        Structural + type/range check WITHOUT persisting: resolves ``(scope, key)`` to its
        owning mutable sub-model — the model STRUCTURE is the allowlist — and dry-validates
        the value. The ``venue`` / ``portfolio`` scopes get a shape check only, because
        venue-kind and portfolio-existence are state-dependent and belong on the engine
        thread.
        """
        # No durable store means no ConfigRouter and no target to persist to. Reject here so
        # the caller gets a truthful False rather than a silent enqueue-then-drop.
        if self._config_router is None:
            self.logger.warning(
                'Rejected CONFIG_UPDATE ingress: no durable config store wired — runtime '
                'config updates require a SQL spine (fail-closed)')
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
        try:
            candidate = model_cls()
            setattr(candidate, key, value)
        except pydantic.ValidationError:
            self.logger.warning(
                'Rejected CONFIG_UPDATE ingress: bad type/range for known key %r', key)
            return False
        return True

    def __enter__(self) -> "LiveTradingSystem":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
