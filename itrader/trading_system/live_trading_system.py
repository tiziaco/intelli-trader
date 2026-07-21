import threading
from datetime import datetime, UTC
from decimal import Decimal
from typing import Optional, Dict, Any, Callable, TYPE_CHECKING

from itrader.core.enums import HaltReason, SystemStatus
from itrader.core.exceptions import StateError
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
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

# D-10/D-23 (WR — the primary external-surface security control): ``add_event`` is the
# engine's PUBLIC external/web ingress. It is FAIL-CLOSED (default-deny, ASVS V4/V5):
# ONLY the THREE sanctioned externally-originated event types are admissible — a
# ``SIGNAL`` (routes through ``OrderHandler.on_signal`` -> ``AdmissionManager`` for
# validation + sizing + reservation + mirror), a ``STRATEGY_COMMAND`` (an operator
# add/remove-ticker command), and (D-23) a ``CONFIG_UPDATE`` (a runtime-config mutation
# routed on the engine thread to its owning store + handler, ingress-400-validated here
# BEFORE the queue). EVERY other event type — every internal-fact type
# (FILL / BAR / UNIVERSE_UPDATE / UNIVERSE_POLL / BARS_LOADED / BARS_LOAD_FAILED /
# TIME / ORDER / ERROR / PORTFOLIO_UPDATE ...) — is rejected by default. Internal
# order flow is UNAFFECTED: handlers put their events on ``global_queue`` directly,
# never through this external ``add_event`` surface (RESEARCH OQ7: zero internal
# production callers of ``add_event``).
_EXTERNALLY_ADMISSIBLE = frozenset(
    {EventType.SIGNAL, EventType.STRATEGY_COMMAND, EventType.CONFIG_UPDATE}
)

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
# now lives in ``config.stream`` (the eager ``ITraderConfig.stream`` field, backed by
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
        # D-22/D-23 (Wave 3): the engine-thread ConfigRouter — the CONFIG_UPDATE consumer.
        # ATTACHED by build_live_system after construction (it references the assembled
        # stores + handler graph); threaded into SessionInitializer -> LiveRouteRegistrar
        # so the CONFIG_UPDATE CONTROL route resolves to a live consumer. None on a facade
        # built outside build_live_system (the route stays the pre-declared empty slot).
        self._config_router: Optional[Any] = None
        # D-19 (10-05): the strategy names that could NOT be rehydrated at boot (a retired
        # class, or a config blob that no longer deserializes). Surfaced on the get_status
        # read-model. A DEDICATED field, not folded into `last_error`: `last_error` is
        # single-valued and the next error would overwrite it, losing the list — and this
        # list is what tells an operator which strategies are silently not trading. Empty
        # on a clean boot and on a facade built outside build_live_system.
        self._quarantined_strategies: list[str] = []

        # RTCFG-06 read-model sinks (D-18/D-19). ATTACHED by build_live_system after
        # construction, gated on the SQL spine (None on backtest / in-memory fallback):
        #   - _system_store: the durable KV where ``state.last_started_at`` is upserted at
        #     start() (SafetyController writes state.status/state.halt_reason into the SAME
        #     store at its own event source; the ErrorHandler writes state.last_error).
        #   - _system_stats_store: the append-only engine-operational stats series the thin
        #     stats writer snapshots into on each status transition (NO entity duplication).
        self._system_store: Optional[Any] = None
        self._system_stats_store: Optional[Any] = None

        # Threading control. The shared _stop_event is honoured by BOTH the injected
        # LiveRunner drain loop and its composed WorkerSupervisor (build_live_system
        # threads it into them); the facade owns it so stop() can latch shutdown.
        self._running = False
        self._stop_event = threading.Event()

        # Statistics tracking
        self._stats = {
            'events_processed': 0,
            'orders_executed': 0,
            # WR-02: an ORDER the pre-submit throttle REFUSED never reached execution
            # (it only emitted a FillEvent(REFUSED)); count it here, not in
            # orders_executed, so the read-model never over-reports submissions.
            'orders_throttle_rejected': 0,
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

        # D-18 (RTCFG-06): a status transition is a low-rate engine event — the thin stats
        # writer snapshots the engine-operational counters it already holds and appends one
        # row to the append-only ``system_stats`` series. Event-driven, no aggregation
        # layer, NO domain-entity data (D-17 — equity/orders/halts read from their own
        # stores). A no-op when no durable stats sink is wired (backtest / in-memory).
        self._snapshot_system_stats()

    def _snapshot_system_stats(self) -> None:
        """Append one engine-operational counter row to ``system_stats`` (D-18/RTCFG-06).

        Snapshots ONLY the counters the engine already holds in memory — the P7 throttle
        breach counter, the facade error count, the event-bus queue depth, uptime, and
        connector/stream health (derived from the safety latch). It copies NO domain-store
        entity data (D-17 — no portfolio equity) and NO secret (V7). Best-effort: a durable
        append failure (e.g. an un-migrated stats schema) is swallowed-and-logged so it can
        never abort the engine event that triggered it. A no-op when no durable sink is
        wired (backtest / in-memory fallback → ``_system_stats_store is None``).
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
                # P7 breach counter (D-09/D-14) — 0 until the throttle is wired.
                'throttle_breach_count': (
                    self._throttle.breach_count if self._throttle is not None else 0),
                # Error counts by severity (D-18, start minimal): the facade holds ONE
                # aggregate error counter today — snapshot it into error_count_error; the
                # per-severity split is a future extension the schema already leaves room
                # for (warning/critical stay 0 until a per-severity surface exists).
                'error_count_warning': 0,
                'error_count_error': errors,
                'error_count_critical': 0,
                'queue_depth': self.get_queue_size(),
                'uptime_seconds': uptime_seconds,
                # Connector/stream health proxies from the safety latch (event-driven
                # CONNECTOR_FATAL→halt / STREAM_STATE→pause_submission are the sources).
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

                # IN-04: compare against the enum name (caller passes event.type.name,
                # so EventType.ORDER.name == 'ORDER' holds the same str contract).
                if event_type == EventType.ORDER.name:
                    self._stats['orders_executed'] += 1

    def _on_order_throttle_rejected(self) -> None:
        """LiveRunner hook (WR-02 / D-04): a pre-submit-throttle-REFUSED ORDER.

        The pre-submit throttle rejected this ORDER at the execution boundary: it
        emitted only a ``FillEvent(REFUSED)`` and NEVER executed, so the runner skips
        the dispatch gate AND ``_update_stats`` for it (which would bump
        ``orders_executed`` and over-report submissions). The order was still dequeued
        and processed, so count it in ``events_processed`` and on its own
        ``orders_throttle_rejected`` counter — never ``orders_executed``. Facade body
        stays put; reached via an injected callable exactly like ``_update_stats``.
        """
        with self._stats_lock:
            self._stats['events_processed'] += 1
            self._stats['last_event_time'] = datetime.now(UTC).isoformat()
            self._stats['orders_throttle_rejected'] += 1

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
                else self.execution_handler.exchanges.get(
                    ('simulated', DEFAULT_ACCOUNT_ID)))  # D-27 pair key

            # RUN-06/D-11 live-plane config: poll timeframe + remove_policy READ FROM the
            # LIVE universe sub-model (NOT the frozen determinism base — P9 D-09 keeps the
            # backtest oracle config untouched; ex-config.monitoring.universe_remove_policy).
            universe_config = UniverseHandlerConfig(
                poll_timeframe=_system_config.stream.okx_stream_timeframe,
                remove_policy=_system_config.universe.remove_policy,
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
                config_router=self._config_router,
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

        # D-19 (RTCFG-06): record the read-model ``state.last_started_at`` at THIS event
        # source (facade start()). Best-effort — a durable-write failure must not abort
        # start (mirrors SafetyController._persist_state); a no-op with no durable sink.
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

            # 08-03 (D-06): the live publish-and-continue policy is injected at
            # EventHandler construction now (compose_engine, via build_live_system) — the
            # old start()-only handler-failure-policy monkeypatch on the dispatcher is GONE.
            # The offline deterministic ``TestRunner`` replay driver overrides the injected
            # policy back to a FailFastPolicy in its build fixture (build_paper_replay_system),
            # so the parity gate stays fail-fast BY DEFAULT and can't false-green (T-05-28 / D-19).

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
                # D-19 (10-05): the strategies that could not be rehydrated at boot and are
                # therefore NOT trading, despite their registry rows still declaring them
                # enabled (the row is never rewritten — the DB holds operator INTENT). A
                # DEDICATED field rather than part of 'last_error': that one is
                # single-valued and would be overwritten by the next error, losing exactly
                # the list an operator needs to see. Directly renderable by the future UI.
                'quarantined_strategies': list(self._quarantined_strategies),
                # D-13 (08-03): the CF-1 tripwire snapshot (per-FailureClass in-window hit
                # counts + last-trip HaltReason). Read None-safely — the ErrorPolicy is
                # unwired on a facade built outside build_live_system. P8 scope = get_status
                # ONLY (the SystemStore stats read-model is P9).
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

        D-10/D-23 (fail-closed, ASVS V4/V5): ``add_event`` is the engine's PUBLIC external/web
        surface, so it is DEFAULT-DENY. Only the THREE sanctioned externally-originated event
        types in ``_EXTERNALLY_ADMISSIBLE`` are admitted — a ``SIGNAL`` (routes through
        ``OrderHandler.on_signal`` -> ``AdmissionManager`` so validation + sizing + cash
        reservation + order-mirror engage before any ``OrderEvent`` is emitted), a
        ``STRATEGY_COMMAND`` (an operator add/remove-ticker command), and a ``CONFIG_UPDATE``
        (a runtime-config mutation — D-23 opens it as the third external type). EVERY other type
        is rejected: every internal-fact type (FILL / BAR / UNIVERSE_UPDATE / UNIVERSE_POLL /
        BARS_LOADED / BARS_LOAD_FAILED / TIME / ORDER / ERROR / PORTFOLIO_UPDATE ...) is not
        admissible from the external surface — a raw ``OrderEvent`` here would otherwise reach
        the execution queue with NO admission control (elevation-of-privilege / input-validation
        defect). This inverts the prior narrow ORDER-only denylist (fail-open -> fail-closed):
        the sanctioned entry stays SIGNAL-form. The internal order flow is UNAFFECTED —
        handlers emit ``OrderEvent``s by putting them on ``global_queue`` directly, never
        through ``add_event`` (RESEARCH OQ7: zero internal production callers).

        D-23/D-16 (ingress 400-validation, defense-in-depth): a ``CONFIG_UPDATE`` gets a
        SYNCHRONOUS fail-closed structural + type/range check HERE (a bad type/range on a KNOWN
        field, or a malformed scope/key, returns ``False`` — the 400 once FastAPI exists) BEFORE
        it reaches the queue, with the engine-thread ``ConfigRouter`` re-checking behind it.

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

        # D-10/D-23: FAIL-CLOSED allowlist. Admit ONLY the sanctioned externally-originated
        # types (SIGNAL + STRATEGY_COMMAND + CONFIG_UPDATE); reject every other type by default
        # (default-deny). This covers the prior narrow ORDER reject and every other internal-fact
        # type in one gate — a raw internal-fact event (e.g. OrderEvent) is still rejected.
        event_type = getattr(event, 'type', None)
        if event_type not in _EXTERNALLY_ADMISSIBLE:
            self.logger.warning(
                'Rejected external add_event of type %s (D-10 fail-closed default-deny) — only '
                'SIGNAL, STRATEGY_COMMAND and CONFIG_UPDATE are admissible from the external '
                'surface; every internal-fact type (incl. raw ORDER injection) must route through '
                'the engine internally, never the public queue directly', event_type)
            return False

        # D-23/D-16: ingress 400-style validation for CONFIG_UPDATE — a synchronous fail-closed
        # reject at the admission boundary (bad type/range on a known field, or malformed
        # scope/key). The engine-thread ConfigRouter re-checks (validate -> persist -> apply)
        # behind it (defense-in-depth). Every other admitted type is unaffected.
        if event_type is EventType.CONFIG_UPDATE and not self._validate_config_ingress(event):
            return False

        try:
            self.global_queue.put(event)
            return True
        except Exception as e:
            self.logger.error(f'Failed to add event to queue: {e}')
            return False

    def _validate_config_ingress(self, event) -> bool:
        """Synchronous ingress 400-validation for a ``CONFIG_UPDATE`` (D-23/D-16).

        Structural + type/range check WITHOUT persisting: resolves the ``(scope, key)`` to its
        owning mutable sub-model on the imported ``config`` singleton (the structure IS the
        allowlist — D-11/D-12) and dry-validates the value on a throwaway ``model_copy``
        (``validate_assignment`` re-coerces). Returns ``False`` (the 400) on a malformed
        scope/key or a bad type/range on a KNOWN field; the engine-thread ``ConfigRouter``
        re-checks everything behind it (defense-in-depth). The ``venue`` / ``portfolio`` scopes
        get a STRUCTURAL shape check only here — the venue-kind predicate (D-14) and
        portfolio-existence + section resolution (D-21) are engine-thread state-dependent checks.
        """
        import uuid

        from itrader.config.order import OrderConfig
        from itrader.config.system import SystemSettings
        from itrader.config.universe import UniverseConfig

        # CR-01 (D-23 fail-closed): with no durable store there is no ConfigRouter wired
        # (build_live_system only constructs it when system_store is not None) and no target
        # to persist to. Reject the update at ingress so the external caller gets a truthful
        # False instead of a silent enqueue-then-drop (the CONFIG_UPDATE route also stays the
        # pre-declared empty slot in that wiring — route_registrar.install()).
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
            # WR-01: ``enabled`` is a real boolean — reject a truthy non-bool at ingress so
            # the string "false" cannot silently enable a venue (mirrors the router's guard).
            if key == 'enabled' and not isinstance(value, bool):
                self.logger.warning(
                    'Rejected CONFIG_UPDATE ingress: non-bool venue enabled value %r', value)
                return False
            return True  # venue-kind is a state-dependent engine-thread predicate (D-14)

        if scope.startswith('portfolio:'):
            pid = scope[len('portfolio:'):]
            try:
                uuid.UUID(pid)
            except (ValueError, AttributeError, TypeError):
                self.logger.warning(
                    'Rejected CONFIG_UPDATE ingress: malformed portfolio id %r', pid)
                return False
            return True  # portfolio-existence + section resolution are engine-thread (D-21)

        self.logger.warning('Rejected CONFIG_UPDATE ingress: unrouted scope %r', scope)
        return False

    def _dry_validate_config_ingress(self, model_cls: Any, key: str, value: Any) -> bool:
        """Dry-validate ``value`` against ``model_cls[key]`` on a FRESH default instance.

        W4/LR-12: this ingress check runs on the EXTERNAL caller thread, so it must NOT read
        the live mutable ``config`` sub-models the ENGINE thread writes (a cross-thread read
        of the single-writer overlay). Instead of copying the live singleton, it constructs a
        FRESH default instance of the SAME sub-model TYPE and setattrs the value on THAT:
        ``validate_assignment=True`` re-runs the field's own type coercion + ``Field(...)``
        constraints — the SAME single source of truth the engine-thread router applies (one
        validator, no drift), evaluated per-field so sibling field values are irrelevant.
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
    """Boot restart-layering: apply each scope's persisted config from its OWN store (D-10/D-22).

    The layering sequence is ``defaults <- YAML <- env <- persisted`` — the frozen base params
    (``rng_seed`` / ``environment`` / identity) are already resolved at CONSTRUCTION and are NEVER
    persisted-overridden at runtime (RTCFG-04 / D-10); persisted overrides apply ONLY to the
    mutable sub-models, each read back from its OWNING module store (config is NEVER read back
    from SystemStore for the order/portfolio scopes — D-21/D-25):

    * ``system``    — ``SystemStore.read_all()`` rows keyed ``config.system.*`` / ``config.universe.*``
      -> ``setattr`` field-wise into the owning mutable sub-model (``validate_assignment`` re-coerces).
    * ``order``     — the ORDER store's ``load_config()`` -> ``setattr`` ``OrderConfig`` field(s) +
      ``order_handler.update_config`` push (NOT SystemStore).
    * ``venue``     — ``VenueStore.read_all()`` rows -> push each venue's fee/slippage to the
      execution handler (real-venue rows were only ever accepted for simulated venues, D-14).
    * ``portfolio`` — each Portfolio's OWN bound ``state_storage.load_config()`` -> apply via
      ``portfolio.update_config(...)`` (NOT SystemStore).

    This LOADING touches SQL and lives ONLY here (never at import — Pitfall 3 / GATE-01). It is a
    pure module function so P9's restart-layering integration test can drive it directly.

    Degrade-clean contract: the durable config schema is Alembic-owned in production (the
    ``order_config`` table + ``portfolio_account_state.config_json`` migration lands in Plan 04).
    A boot against a not-yet-provisioned schema (a fresh DB, or the interim Plan-03/pre-migration
    state) must NOT crash — a missing config table simply means "no persisted overrides yet". So a
    store-read ``SQLAlchemyError`` is logged and layering is skipped (mirrors the None-backend skip
    at the call site). Never ``create_all`` here — the store stays schema-pure (WR-03/D-14).
    """
    import pydantic
    from sqlalchemy.exc import SQLAlchemyError

    from itrader.config.order import OrderConfig
    from itrader.config.system import SystemSettings
    from itrader.config.universe import UniverseConfig
    from itrader.core.exceptions.base import ConfigurationError

    logger = get_itrader_logger().bind(component="build_live_system")

    # WR-03 degrade-clean contract — each scope is layered under its OWN guard so a bad
    # persisted override (a not-yet-provisioned schema -> SQLAlchemyError; OR a present-but-
    # now-invalid stored value after schema evolution / model-field tightening / a poisoned
    # row -> ConfigurationError / pydantic.ValidationError / ValueError) is LOGGED and SKIPPED
    # rather than crashing build_live_system on boot. Per-scope isolation means one bad scope
    # never aborts the others. NOT a bare Exception — a genuine programming error still
    # surfaces. RTCFG-03 is a best-effort restore; a fresh/un-migrated DB simply has none.
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
    try:
        for row in venue_store.read_all():
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
            "Skipping persisted VENUE-config restart layering — schema unavailable or a "
            "stored override is invalid (%s); boot degrades clean", exc)

    # (portfolio) — each Portfolio's OWN bound store (NOT SystemStore); resolve via the handler.
    try:
        for _pid, portfolio in portfolio_handler._portfolios.items():
            portfolio_cfg = portfolio.state_storage.load_config()
            if portfolio_cfg:
                portfolio.update_config(portfolio_cfg)
    except _degrade_clean as exc:
        logger.warning(
            "Skipping persisted PORTFOLIO-config restart layering — schema unavailable or a "
            "stored override is invalid (%s); boot degrades clean", exc)


def build_live_system(
    spec: Any,
    *,
    status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
    data_plugins: Optional[Dict[str, Any]] = None,
    strategy_catalog: Optional[Dict[str, type]] = None,
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

    D-01: ``strategy_catalog`` is the injected strategy-TYPE allowlist, mirroring
    ``data_plugins`` — both are CODE artifacts the application hands in, as opposed to
    ``spec`` (persisted config). It is the only thing that turns a stored ``strategy_type``
    string into a class, so the app decides WHICH classes are instantiable at boot. The
    ``None`` default keeps every existing caller working: with an empty registry there is
    nothing to instantiate (D-21), and with rows present a missing catalog fails LOUD
    rather than booting a healthy-looking engine that trades nothing (D-19).

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

    # 08-03 (D-03/D-04/D-05): build the live ERROR-route collaborators BEFORE compose so
    # they ride into the ErrorHandler + the injected handler-failure policy via
    # compose_engine (the single mode-agnostic build site) — no post-build monkeypatch.
    #   - alert_sink: the CRITICAL/halt egress (only declared ErrorEvent fields bound;
    #     no connector secret leaks, Pitfall 16 / T-05-01).
    #   - system_store: a freshly-minted SystemStore over the SAME SqlEngine (D-05
    #     NEGATIVE — there is NO existing SystemStore to share and NO second engine to
    #     build), gated on system_db_backend exactly like halt_record_store above; the
    #     import stays LAZY inside the gate (storage.system_store is OKX-inertness _FORBIDDEN).
    #   - error_policy: the live publish-and-continue tripwire, built with the static
    #     D-14 failure-rate settings; halt + error_counter are late-bound below once
    #     SafetyController + the facade exist (D-12 resolves the construction cycle).
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

    ctx = EngineContext(
        bus=global_queue,
        config=_system_config,
        environment=environment,
        feed=feed, store=None,
        sql_engine=system_db_backend,
    )
    engine = compose_engine(
        ctx, exchange_config=None, results_store=None,
        alert_sink=alert_sink, system_store=system_store, error_policy=error_policy,
        strategy_catalog=strategy_catalog,
        # D-27/MPORT-07: LIVE resolves each order's venue account from its
        # portfolio through the injected read-model, so an account's orders can
        # never be submitted through another account's authenticated session.
        # The backtest arm deliberately leaves this False — see compose_engine.
        route_orders_by_account=True)

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
        'paper',
        PaperVenuePlugin(
            execution_handler.exchanges[('simulated', DEFAULT_ACCOUNT_ID)]))
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
            # D-27/MPORT-07: register under the (venue, account_id) PAIR, using
            # the account this bundle was actually built for. Registering under
            # DEFAULT_ACCOUNT_ID here would blackhole every live order for a
            # NAMED account: on_order resolves the portfolio's real account, so
            # the lookup would miss and fail closed — silently, with no test
            # covering it. The `or DEFAULT_ACCOUNT_ID` fallback is the same
            # `spec.account_id or "default"` idiom the shipped venue plugins
            # already use to memoize connectors, so venue and exchange agree on
            # one key. (This is a REGISTRATION-side default for an unnamed
            # account, NOT a resolution-side fallback — on_order must never
            # coerce a None account into the default.)
            execution_handler.exchanges[
                (exchange, venue_spec.account_id or DEFAULT_ACCOUNT_ID)
            ] = bundle.exchange

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
    # RUNTIME-CONFIG PLATFORM (Wave 3 — D-22/D-23/D-25). Construct VenueStore + the
    # engine-thread ConfigRouter over the OWNING module stores per D-21 (system->SystemStore,
    # order->the ORDER store via order_handler.storage, venue->VenueStore, portfolio->each
    # Portfolio's OWN bound state_storage — NOT SystemStore), attach it to the facade so
    # _initialize_live_session threads it into SessionInitializer -> LiveRouteRegistrar (the
    # CONFIG_UPDATE CONTROL route). All storage/venue imports stay LAZY inside the gate
    # (inertness-forbidden at module top). Degrades cleanly to no router / no layering when
    # there is no SQL spine (in-memory fallback) — the CONFIG_UPDATE route stays the empty slot.
    order_handler = engine.order_handler
    if system_store is not None:
        from itrader.core.clock import WallClock
        from itrader.storage.venue_store import VenueStore
        from itrader.trading_system.config_router import ConfigRouter

        venue_store: Optional[Any] = VenueStore(system_db_backend)

        def _venue_kind(venue_name: str) -> bool:
            """(venue_name) -> True when the venue's execution arm is a SimulatedExchange (D-14).

            D-27: the registry is pair-keyed, so this matches every registered
            account on the named venue. The parameter stays a bare VENUE string
            because the question ("is this venue simulated?") is a property of
            the venue, not of one account on it.
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

        # RESTART LAYERING (D-10/D-22): apply persisted overrides on boot from each OWNING
        # store. Base params already resolved at construction (frozen); persisted overrides
        # touch only the mutable sub-models.
        _layer_persisted_overrides(
            _system_config,
            system_store=system_store,
            venue_store=venue_store,
            order_handler=order_handler,
            portfolio_handler=portfolio_handler,
            execution_handler=execution_handler,
        )

        # STRATEGY REHYDRATE (D-01/STRAT-01): the stored roster becomes live instances.
        # THIS EXACT POSITION satisfies four independent constraints at once:
        #  (1) portfolios are already layered ABOVE (_layer_persisted_overrides iterates
        #      portfolio_handler._portfolios), so subscribe_portfolio binds to ids that
        #      already exist and are restart-stable — portfolios-before-strategies holds.
        #  (2) session init BELOW reads the strategy list: wire_universe derives membership
        #      from it via StrategyDerivedSelectionModel, and register_strategy_warmup sizes
        #      the feed ring from it. A strategy registered after either would never enter
        #      the universe and never size the ring — so rehydrate MUST precede them.
        #  (3) NOT inside _initialize_live_session: three integration tests — including a
        #      RESTART test — monkeypatch that method to a no-op, so rehydrate placed there
        #      would be silently lost exactly where it matters most.
        #  (4) the rehydrate collaborator import stays LAZY inside this gate and is never
        #      barrel-exported, keeping the backtest import path SQL-free (GATE-01). The
        #      STORE's own SQL imports moved with it into StrategyRegistryStorageFactory,
        #      where they stay equally lazy inside that factory's 'live' arm.
        # Deliberately NOT wrapped in try/except _degrade_clean: D-19's semantics are finer
        # grained than that pattern. Per-instance failures are ALREADY handled inside
        # rehydrate_strategies (skip + CRITICAL alert + the row left untouched), while an
        # infrastructure failure must fail LOUD — the opposite of degrade-clean. A blanket
        # wrap would convert the loud arm into a silent boot with zero strategies, which is
        # precisely the outcome D-19 rates as worse than not booting.
        from itrader.strategy_handler.registry.rehydrate import rehydrate_strategies

        # DECOMP-01a: the store is READ BACK off the handler that now OWNS it, derived in
        # StrategiesHandler.__init__ from (environment, sql_engine) via
        # StrategyRegistryStorageFactory — no post-construction dep assignment happens
        # here any more. The D-09 ordering constraint that used to justify assigning
        # registry_store BEFORE rehydrate (so a rehydrated strategy's FIRST runtime verb
        # already has a store to persist to — otherwise an enable/disable landing between
        # boot and the next wiring step would apply live and vanish at restart) is now
        # satisfied STRUCTURALLY: the store exists from construction, which is strictly
        # earlier than any point this function could have assigned it.
        #
        # A None store here is the D-21 first-start state (unprovisioned strategy_registry
        # table) or an unwired SQL spine; the factory owns that probe and its WARNING. It
        # is NOT a D-19 infrastructure failure, so skipping rehydrate cannot produce the
        # zero-strategies-while-rows-exist outcome D-19 forbids — a genuine store fault
        # still PROPAGATES loud out of rehydrate_strategies.
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
        # D-19 (RTCFG-06): the durable read-model KV sink for state.status/state.halt_reason
        # at their event source. None on the in-memory fallback (degrade cleanly).
        system_store=system_store,
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
    if provider is not None:
        provider.set_halt_signal(facade._request_connector_halt)
        provider.set_stream_state_listener(
            facade._on_venue_stream_down, facade._on_venue_stream_up)
        if okx_exchange is not None:
            okx_exchange.set_halt_signal(facade._request_connector_halt)
            okx_exchange.set_stream_state_listener(
                facade._on_venue_stream_down, facade._on_venue_stream_up)
            okx_connector.set_halt_signal(facade._request_connector_halt)

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
