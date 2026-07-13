import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, UTC
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional, Dict, Any, Callable

# D-14 (V17-11): bound on the pause-window protective-order replay queue. During a
# pause/halt, system-generated protective orders (bracket children, OCO/orphan
# cancels) are DEFERRED here and replayed on resume; the bound prevents an unbounded
# backlog if a pause runs long. A realistic reconnect-window generates far fewer than
# this many protective orders, so the cap only guards a pathological stall (oldest
# deferred protective orders are dropped past it — a dropped protective order is the
# same freeze-in-place safety posture as the pre-D-14 blanket suppression).
_DEFERRED_PROTECTIVE_REPLAY_MAX = 1000

from itrader.core.enums import ErrorSeverity, HaltReason, OrderCommand, SystemStatus, VALID_STATUS_TRANSITIONS
from itrader.core.exceptions import ConfigurationError
from itrader.events_handler.full_event_handler import EventHandler
from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.store.csv_store import CsvPriceStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.strategy_handler.storage import SignalStorageFactory
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.reconcile import is_within_single_unit_tolerance
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.trading_system.alert_sink import LogAlertSink
from itrader.universe import Universe

from itrader.logger import get_itrader_logger
from itrader.events_handler.bus import PriorityEventBus
from itrader.events_handler.events import EventType, ErrorEvent, UniversePollEvent

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


@dataclass
class LiveSystemComponents:
    """The pre-built live component graph injected into the facade (RUN-01/D-09).

    ``build_live_system`` owns ALL live wiring and packs the resulting handlers /
    storages / feed / venue bundle into this bundle; ``LiveTradingSystem.__init__``
    is PURE INJECTION — it stores these fields verbatim and holds NO wiring logic
    (the live analog of ``compose_engine -> Engine`` feeding ``BacktestRunner``).
    Fields are loose (``Any``) — the facade module is mypy ``ignore_errors`` (D-live).
    """

    exchange: str
    global_queue: Any
    store: Any
    feed: Any
    screeners_handler: Any
    portfolio_handler: Any
    strategies_handler: Any
    order_handler: Any
    execution_handler: Any
    event_handler: Any
    signal_store: Any
    system_db_backend: Any
    halt_record_store: Any
    order_storage: Any
    venue_bundle: Any
    venue_lifecycle: Any
    okx_connector: Any
    okx_exchange: Any
    okx_data_provider: Any
    venue_account: Any


class LiveTradingSystem:
    """
    Encapsulates the settings and components for carrying out live trading.
    Processes events from a global queue in a separate thread instead of 
    using a for-loop like the backtest system.
    
    Enhanced with web control capabilities for REST API and WebSocket integration.
    """
    
    def __init__(
        self,
        components: "LiveSystemComponents",
        *,
        status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None,
    ):
        """Pure-injection facade constructor (RUN-01/RUN-03/D-09).

        ``build_live_system`` owns ALL live wiring and hands in the pre-built
        ``LiveSystemComponents`` graph; this constructor holds NO wiring logic — it
        stores the injected components and initialises fresh per-instance RUNTIME
        state (status/locks/flags/stats). Mirrors ``compose_engine -> Engine ->
        BacktestRunner`` (the injected engine is the source of truth; the holder is
        thin). ``status_callback`` is the sole surviving loose param; the former
        ``exchange``/``to_sql``/``queue_timeout``/``max_idle_time`` params are SHED
        (``exchange`` now rides on the components; the two loop knobs are injected
        into the ``LiveRunner`` by the factory).

        D-03 boundary honesty: the ~200-line facade is a P7-EXIT gate (P7 owns the
        ~500 lines of safety/reconcile/stream extraction). The interim P6 facade is
        ~600-700 lines and that is CORRECT — RUN-03 acceptance here is STRUCTURAL.

        Parameters
        ----------
        components : LiveSystemComponents
            The pre-built live component graph (handlers/storages/feed/venue bundle).
        status_callback : callable, optional
            Callback to notify status changes to external systems.
        """
        self.logger = get_itrader_logger().bind(component="LiveTradingSystem")
        self.status_callback = status_callback

        # -- Injected component graph (build_live_system owns its construction) --
        self.exchange = components.exchange
        self.global_queue = components.global_queue
        self.store = components.store
        self.feed = components.feed
        self.screeners_handler = components.screeners_handler
        self.portfolio_handler = components.portfolio_handler
        self.strategies_handler = components.strategies_handler
        self.order_handler = components.order_handler
        self.execution_handler = components.execution_handler
        self.event_handler = components.event_handler
        self._signal_store = components.signal_store
        self._system_db_backend: Optional[Any] = components.system_db_backend
        self._halt_record_store: Optional[Any] = components.halt_record_store
        self._order_storage = components.order_storage
        self._venue_bundle: Optional[Any] = components.venue_bundle
        self._venue_lifecycle: Optional[Any] = components.venue_lifecycle
        self._okx_connector: Optional[Any] = components.okx_connector
        self._okx_exchange: Optional[Any] = components.okx_exchange
        self._okx_data_provider: Optional[Any] = components.okx_data_provider
        self._venue_account: Optional[Any] = components.venue_account

        # -- Fresh per-instance RUNTIME state (NOT wiring) ----------------------
        # System status tracking
        self._status = SystemStatus.STOPPED
        self._status_lock = threading.Lock()
        self._last_error = None
        # 05-04 (D-07): machine-readable halt reason surfaced on get_status().
        self._halt_reason: Optional[str] = None
        # 05-08 (D-19): REVERSIBLE pause-on-disconnect state (distinct from HALT).
        self._submission_paused = False
        self._paused_reason: Optional[str] = None
        self._pending_stream_resume = threading.Event()
        # 05.3-08 (D-21 / WR-02): connector-fatal escalation handoff flag.
        self._pending_connector_halt = threading.Event()
        self._pending_connector_halt_reason: Optional[str] = None
        # D-14 (V17-11): bounded pause-window protective-order replay queue.
        self._deferred_protective: "deque[Any]" = deque(
            maxlen=_DEFERRED_PROTECTIVE_REPLAY_MAX)

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
        self._update_status(SystemStatus.STOPPED)

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
        data_provider = overrides.pop('data_provider', None) or {
            'okx': 'okx', 'paper': 'okx'}.get(exchange, 'okx')
        data_plugins = overrides.pop('data_plugins', None)
        spec = SimpleNamespace(
            execution_venue=exchange,
            data_provider=data_provider,
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
        self._update_status(SystemStatus.RUNNING)
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

    def _link_venue_account_to_portfolios(self) -> None:
        """Link the venue-cached account into the active live portfolio (WR-02).

        The ``VenueAccount`` is a FIRST-CLASS KEYED entity — one venue sub-account
        (AccountId), owning that sub-account's balance / available / positions
        cache — NOT a shared singleton. Assigning the SAME ``self._venue_account``
        instance to every active portfolio conflates their buying power and
        positions (``_compare_symbol_drift`` would read one venue truth for all)
        and silently discards each portfolio's prior ``SimulatedAccount`` ledger.

        Real multi-portfolio-live needs a per-portfolio ``VenueAccount`` resolved
        by venue sub-account, with position attribution by clOrdId/tag — a bigger
        design, correctly DEFERRED. Until it exists, FAIL LOUD here on MORE THAN
        ONE active portfolio: refuse to share one venue account across portfolios
        so a second portfolio can never silently mis-attribute buying power /
        positions or have its ``SimulatedAccount`` ledger discarded. A
        ``RuntimeError`` (not a strippable ``assert``) is used so the guard holds
        even under ``python -O``. Zero active portfolios is a benign no-op (a
        system may start before any portfolio is added — nothing to attribute);
        exactly one is the supported single-portfolio-live path (account linked).
        """
        active_portfolios = self.portfolio_handler.get_active_portfolios()
        if len(active_portfolios) > 1:
            raise RuntimeError(
                'Live venue-account wiring supports at most one active portfolio '
                f'(found {len(active_portfolios)}). Sharing one VenueAccount '
                'across portfolios would conflate their buying power / positions '
                'and discard each SimulatedAccount ledger. Multi-portfolio-live '
                'requires a per-portfolio VenueAccount keyed by venue sub-account '
                '(AccountId) with position attribution by clOrdId/tag — deferred '
                'work; wire that before running more than one live portfolio.')
        # Zero -> no-op; exactly one -> link the venue-cached account onto it.
        for portfolio in active_portfolios:
            portfolio.account = self._venue_account

    def _run_session_baseline_guard(self) -> None:
        """Session-start baseline guard (D-04, ARCH-2): HALT on unexplained residual.

        Sequenced AFTER reconciliation and BEFORE the engine thread spawns. The
        reconciler has already SYNCED every EXPLAINABLE delta (adopted external
        fills, re-linked brackets, in-band adjustments); anything LEFT is a
        base-asset residual of UNKNOWN origin — wrong sub-account wiring, a
        crashed-session leftover, a forgotten manual deposit. Per ARCH-2
        sub-decision 3 the engine must NEVER trade on exposure it cannot explain,
        and it must NEVER auto-adopt that exposure. So compare the venue base-asset
        holding against the engine's post-reconcile believed position within the
        per-instrument dust epsilon (F/U-6 — the SAME drift.py band the on-fill
        compare uses, resolved via the handler's instrument precision), and on ANY
        residual mismatch call the LATCHED halt (D-05) so ``start()`` refuses
        RUNNING. Quote-side cash is NOT asserted (deposits are legitimate funding).
        The halt reason is a FIXED literal (never ``str(exc)`` — no venue secret can
        leak, ASVS V7 / T-05.1-10).

        The guard's halt is REAL only because 05.1-05 latched ``HALTED``: a guard
        halt during session init cannot be clobbered back to RUNNING (the processing
        loop's unconditional RUNNING stamp is gated by ``start()``'s ``_is_halted()``
        refusal downstream of this call).
        """
        if self._venue_account is None:
            return
        from itrader import config as _system_config
        symbol = _system_config.stream.okx_stream_symbol
        venue_qty = self._venue_account.positions.get(symbol, Decimal('0'))
        # F/U-6: reuse the per-instrument drift epsilon (the same band the on-fill
        # drift compare keys off the wired instrument's quantity precision).
        precision = self.portfolio_handler._drift_precision(symbol)
        for portfolio in self.portfolio_handler.get_active_portfolios():
            engine_position = portfolio.get_open_position(symbol)
            engine_qty = (
                engine_position.net_quantity if engine_position is not None
                else Decimal('0')
            )
            if is_within_single_unit_tolerance(engine_qty, venue_qty, precision):
                continue  # base-asset balance == believed position — trustworthy.
            # Unexplained base-asset residual: NEVER auto-adopt exposure of unknown
            # origin — latch HALT BEFORE trading (D-04/D-05). start()'s post-guard
            # _is_halted() refusal keeps the engine from spawning the loop.
            self.logger.error(
                'Session-start baseline guard: unexplained base-asset residual — '
                'halting before trading (venue exposure the engine cannot explain)',
                symbol=symbol,
                engine_qty=str(engine_qty),
                venue_qty=str(venue_qty))
            self.halt(HaltReason.BASELINE_RESIDUAL.value)
            return

    def halt(self, reason: str) -> None:
        """Freeze-in-place halt of the whole engine (D-01/D-02/D-06/D-07).

        The conservative money-first response when the engine can no longer trust
        its own state (unexplained drift, unresolved reconciliation, a fatal
        connector error, a disconnect). Sets ``SystemStatus.HALTED`` with a
        machine-readable ``halt_reason`` and SUPPRESSES all NEW order submission
        (the SIGNAL/ORDER routes, gated in ``_dispatch_live``) while BAR/FILL
        streaming, reconciling and persisting CONTINUE to drain. It does NOT
        auto-flatten or auto-cancel: existing positions and resting orders stay
        exactly as they are (the engine just declared its own state untrustworthy,
        so it must not act on it). Idempotent — the first halt wins; a later halt
        with a different reason is a no-op.

        Emits ONE CRITICAL ``ErrorEvent`` so the halt reaches the operator through
        the injected alert sink (D-06); only declared ErrorEvent fields are bound,
        so no connector secret can leak (Pitfall 16, T-05-01).

        Parameters
        ----------
        reason : str
            Machine-readable halt reason (D-07) ∈ {drift,
            reconciliation-unresolved, connector-fatal, paused-on-disconnect}.
        """
        # WR-01 + D-05: atomic check-and-set routed through the SINGLE _update_status
        # seam. _update_status flips the status, sets the halt_reason and records
        # _last_error all under ONE _status_lock acquisition, and returns True ONLY for
        # the winning caller that actually flips a non-HALTED status to HALTED (a
        # re-entrant halt is a same-state no-op -> False). Two concurrent halt() callers
        # can therefore never BOTH pass the guard, both clobber halt_reason and both fire
        # the CRITICAL alert — only the winner reaches the emit below. HALTED is reachable
        # from every non-terminal state in VALID_STATUS_TRANSITIONS, so this flip is never
        # refused. The notify/callback runs OUTSIDE the lock, inside _update_status.
        transitioned = self._update_status(
            SystemStatus.HALTED,
            error_msg=f'halt: {reason}',
            halt_reason=reason,
        )
        if not transitioned:
            return  # already halted — first reason wins (idempotent).
        # Winner only past here. Emit the SINGLE CRITICAL alert.
        # D-06: CRITICAL egress — routed through the EventHandler's ERROR route to
        # the injected alert sink. Only declared ErrorEvent fields are bound.
        self.global_queue.put(ErrorEvent(
            time=datetime.now(UTC),
            source='live_trading_system',
            error_type='EngineHalted',
            error_message=(
                f'Engine halted (reason={reason}) — new order submission frozen '
                'in place; streaming/reconciling/persisting continue, no '
                'auto-flatten/auto-cancel'),
            operation='halt',
            severity=ErrorSeverity.CRITICAL,
        ))
        # 05.2-06 (D-10 / ARCH-4 Layer 2): persist a DURABLE halt record so the HALTED
        # latch survives a process restart — a supervised auto-restart builds a FRESH
        # engine (in-process _status STOPPED) that would otherwise silently clear a
        # breaker halt whose cause is not re-detectable at start(). Reached ONLY by the
        # winning transition above, so a re-entrant (idempotent) halt never double-writes.
        # Bind ONLY the machine-readable reason literal + timestamp (V7 secret-scrub,
        # T-05.2-18; mirrors the ErrorEvent field-bind discipline) — never str(exc) or a
        # connector payload. Guarded on the store being present (in-memory fallback ->
        # no durable record, degrade cleanly).
        if self._halt_record_store is not None:
            self._halt_record_store.record_halt(reason, datetime.now(UTC))

    def _is_halted(self) -> bool:
        """Whether the engine is in the freeze-in-place HALTED state (D-02)."""
        with self._status_lock:
            return self._status == SystemStatus.HALTED

    def reset_halt(self) -> bool:
        """Operator-only clear of the latched HALTED state (D-05, F/U-9).

        ``HALTED`` has NO legal exit in ``VALID_STATUS_TRANSITIONS`` — it is a latched
        safety state. This method is the SOLE sanctioned exit, deliberately OUTSIDE the
        transition table (a ``force=True`` write through the single ``_update_status``
        seam) that returns the engine to ``STOPPED``. It does NOT re-open the trading
        gate itself: verify-then-trust means a subsequent ``start()`` re-runs
        reconciliation + the session-start baseline guard from a clean STOPPED baseline,
        so the halt cause is re-checked, never implicitly assumed resolved. Clearing the
        halt also clears the machine-readable ``halt_reason`` (handled in
        ``_update_status`` when leaving HALTED). A no-op returning ``False`` when the
        engine is not currently HALTED.

        Returns
        -------
        bool
            ``True`` if a latched HALTED was cleared; ``False`` if the engine was not
            HALTED (no-op).
        """
        if not self._is_halted():
            self.logger.warning('reset_halt() ignored — engine is not HALTED')
            return False
        # force=True is the ONLY sanctioned bypass of the latch table (the HALTED exit).
        cleared = self._update_status(
            SystemStatus.STOPPED,
            error_msg='HALTED cleared by operator reset_halt()',
            force=True,
        )
        if cleared:
            # 05.2-06 (D-10): resolve the DURABLE halt record too, so the durable latch
            # does not re-refuse the next start() (F/U-9 verify-then-trust: that next
            # start() still re-runs reconciliation + the baseline guard from a clean
            # STOPPED baseline, so the halt cause is re-checked, never assumed resolved).
            # Guarded on the store being present (in-memory fallback -> no-op).
            if self._halt_record_store is not None:
                self._halt_record_store.resolve_all()
            self.logger.warning(
                'HALTED cleared by operator reset_halt() — engine returned to STOPPED; '
                'a subsequent start() will re-run reconciliation + the baseline guard '
                'before trading (verify-then-trust)')
        return cleared

    def _is_submission_paused(self) -> bool:
        """Whether NEW order submission is reversibly paused on a disconnect (D-19)."""
        with self._status_lock:
            return self._submission_paused

    def pause_submission(self, reason: str) -> None:
        """Reversibly pause NEW order submission on a venue-stream disconnect (D-19).

        Distinct from ``halt()``: this is a REVERSIBLE quiesce — streaming, reconciling
        and persisting continue, existing positions/orders are untouched, and
        ``resume_submission()`` (after reconnect + a fresh REST balance/position
        snapshot) clears it. A
        terminal HALT supersedes a pause, so this is a no-op while HALTED. Idempotent
        (a second pause with a new reason keeps the first). Thread-safe (a locked flag
        flip) so the connector-loop reconnect callback can call it without blocking I/O.

        Parameters
        ----------
        reason : str
            Machine-readable pause reason (D-07), e.g. ``'paused-on-disconnect'``.
        """
        with self._status_lock:
            if self._status == SystemStatus.HALTED:
                return
            if self._submission_paused:
                return
            self._submission_paused = True
            self._paused_reason = reason
        self.logger.warning(
            'Order submission paused (reason=%s) — new SIGNAL/ORDER suppressed until '
            'reconnect + a fresh REST balance/position snapshot; positions/orders '
            'untouched', reason)

    def resume_submission(self) -> None:
        """Clear the reversible pause after reconnect + a fresh REST snapshot (D-19).

        D-14: once the pause flag is cleared, DRAIN the protective-order replay queue —
        each deferred protective order (bracket child / OCO / orphan cancel) is
        re-dispatched through ``_dispatch_live``. The pause flag is cleared FIRST
        (below), so the re-dispatch proceeds to ``_dispatch`` and is NOT re-suppressed
        (Assumption A4 — the drain runs after the flag clears).
        """
        with self._status_lock:
            if not self._submission_paused:
                return
            self._submission_paused = False
            self._paused_reason = None
        self.logger.info(
            'Order submission resumed — venue stream reconnected + fresh REST '
            'balance/position snapshot complete')
        # D-14: replay the protective orders deferred during the pause window.
        self._replay_deferred_protective()

    def _replay_deferred_protective(self) -> None:
        """Replay pause-deferred protective orders through the live gate on resume (D-14).

        Snapshots the replay queue into a local batch and CLEARS it before re-dispatching,
        so a re-dispatch that finds the engine HALTED (and re-defers) appends to the now-empty
        queue rather than spinning this drain forever. Each protective order is re-dispatched
        through ``_dispatch_live``; with the pause flag already cleared it passes the gate to
        ``_dispatch`` (Assumption A4). Bracket children / OCO cancels reach the venue so the
        just-filled position is no longer left naked.
        """
        if not self._deferred_protective:
            return
        batch = list(self._deferred_protective)
        self._deferred_protective.clear()
        self.logger.info(
            'Replaying %d deferred protective order(s) on resume (D-14)', len(batch))
        for deferred in batch:
            self._dispatch_live(deferred)

    def _on_venue_stream_down(self, stream_name: str) -> None:
        """Connector-loop callback (D-19): pause NEW submission on a sustained disconnect.

        Thread-safe (a locked flag flip) — does NO blocking venue I/O on the connector
        loop (Pitfall 9). Fires once per sustained disconnect (past the debounce).
        """
        self.logger.warning(
            'Venue %s stream disconnected — pausing new order submission', stream_name)
        self.pause_submission('paused-on-disconnect')

    def _on_venue_stream_up(self, stream_name: str) -> None:
        """Connector-loop callback (D-19): REQUEST an engine-thread resume on reconnect.

        Only SETS a thread-safe flag — it must not perform the fresh REST snapshot /
        reconcile here (a ``connector.call`` on the connector loop would deadlock,
        Pitfall 9). The engine loop drains the flag via ``_maybe_resume_after_reconnect``.
        """
        self.logger.info(
            'Venue %s stream reconnected — requesting engine-thread resume', stream_name)
        self._pending_stream_resume.set()

    def _maybe_resume_after_reconnect(self) -> None:
        """Engine-thread resume after a venue stream reconnected (D-19).

        Runs on the engine (queue-draining) thread: take a fresh REST balance/position
        SNAPSHOT (don't trade when you can't see the venue) THEN clear the pause. The
        connector-loop reconnect callback only sets the flag; all blocking venue I/O
        happens HERE, off the connector loop (Pitfall 9). A failed snapshot leaves the
        pause in place (retried on the next set) — never resume blind.

        WR-04: resume does a fresh REST balance/position snapshot, NOT the full
        two-sided ``VenueReconciler.reconcile()``. A blind mid-session reconcile would
        spuriously HALT: ``VenueReconciler._halt_on_orphan_positions`` treats any venue
        position whose symbol has no ACTIVE order in the rehydrated working set as an
        unexplained orphan and halts — correct at startup (pre-RUNNING), but mid-session
        the engine legitimately holds positions from filled (now-terminal, non-bracket)
        orders. Re-running ``_adopt_fill_deltas`` against a store whose ``filled_quantity``
        momentarily lags an in-flight live fill also risks a double-adopt. The full
        two-sided reconcile is therefore a startup-before-RUNNING contract only.
        """
        if not self._pending_stream_resume.is_set():
            return
        self._pending_stream_resume.clear()
        if not self._is_submission_paused():
            return
        try:
            # D-25 (WR-01): re-fetch fills that settled while the fill stream was down,
            # BEFORE the fresh REST snapshot — so the snapshot's balance/position picture
            # already reflects the recovered trade. Engine thread here (safe to block; the
            # bounded fetch_my_trades page bridges through the connector). Each trade routes
            # through _handle_trade and is deduped by the D-08 {symbol}:{trade_id} guard, so
            # a later reconcile never double-settles it. Guard-claused on _okx_exchange
            # (mirrors the _venue_account guard); a catch-up failure is caught by the same
            # except below (stay paused, never resume blind). NOTE: no distinct attempt==1
            # live-path call site exists — every reconnect funnels through _mark_stream_down
            # → on_stream_up → _pending_stream_resume → this drain (see okx.py supervisor).
            if self._okx_exchange is not None:
                self._okx_exchange.catch_up_missed_fills()
            if self._venue_account is not None:
                # WR-04: fresh REST balance/position snapshot before resuming (engine
                # thread — safe to block); NOT a full two-sided reconcile (see docstring).
                self._venue_account.snapshot()
        except Exception as e:
            self.logger.error(
                'Resume missed-fill catch-up / REST snapshot failed — staying paused: %s', e)
            self._pending_stream_resume.set()  # retry on the next engine iteration
            return
        # D-28 (WR-03): resume NEW submission ONLY when EVERY wired venue stream arm
        # is healthy. A single arm's reconnect (candle stream up while the fill stream
        # is still down, OR the exchange's own orders-stream up while its fills-stream
        # is still down) previously resumed submission while the engine was still blind
        # to fills. Leave the pause in place — do NOT re-set _pending_stream_resume: the
        # still-down arm's next up-event re-fires it, so there is no engine-thread spin.
        # (The D-25 catch-up + snapshot above ran regardless — recovering fills while
        # staying paused is correct.)
        if not self._all_venue_streams_healthy():
            self.logger.info(
                'Reconnect handled but venue streams not all healthy — staying paused '
                '(resume gated until every wired arm reports up, D-28/WR-03)')
            return
        self.resume_submission()

    def _all_venue_streams_healthy(self) -> bool:
        """True unless a WIRED venue arm reports its stream set down (D-28 / WR-03).

        The compound resume gate: resume NEW submission only when EVERY wired arm —
        the exchange arm (fills+orders) AND the data-provider arm (candles) — reports
        its own ``_streams_down`` empty. Each arm OWNS its health state; the engine only
        READS a public per-arm predicate, adding NO engine-side aggregate stream set and
        NO namespaced stream names. A None (unwired) arm never blocks (absent ⇒ healthy),
        so non-OKX runs resume unconditionally.
        """
        if (self._okx_exchange is not None
                and not self._okx_exchange.is_streaming_healthy()):
            return False
        if (self._okx_data_provider is not None
                and not self._okx_data_provider.is_streaming_healthy()):
            return False
        return True

    def _request_connector_halt(self, reason: str) -> None:
        """Connector-loop callback (D-21/WR-02): REQUEST an engine-thread durable halt.

        Injected as the OKX stream arms' halt signal (``set_halt_signal``). Fired from the
        connector ASYNCIO LOOP thread on a fatal connector error / exhausted retry ceiling /
        the unclassified catch-all. It ONLY flips a thread-safe flag — it must NOT drive the
        blocking ``halt()`` here (its durable ``record_halt`` SQL write would stall every
        stream sharing the loop, Pitfall 9). The engine loop drains the flag via
        ``_maybe_halt_after_connector_fatal`` and runs the blocking halt off the loop.
        Mirrors ``_on_venue_stream_up`` (the reconnect-resume flag handoff).

        Parameters
        ----------
        reason : str
            Machine-readable halt reason (the arms pass the fixed ``'connector-fatal'``).
        """
        self._pending_connector_halt_reason = reason
        self._pending_connector_halt.set()

    def _maybe_halt_after_connector_fatal(self) -> None:
        """Engine-thread durable halt after a connector-fatal escalation (D-21/WR-02).

        Runs on the engine (queue-draining) thread. When the connector-loop escalation has
        flagged a fatal, this drains the flag and runs the blocking ``halt()`` HERE — the
        durable ``record_halt`` write + status flip + CRITICAL alert all off the connector
        asyncio loop (Pitfall 9). ``halt()`` is winner-only/idempotent, so two flagged
        escalations (e.g. both stream arms fail) still write the durable record exactly once
        (D-10 latch ordering preserved). The V7 secret scrub is preserved end-to-end — only
        the fixed ``'connector-fatal'`` reason literal crosses the handoff, never ``str(exc)``.
        Mirrors ``_maybe_resume_after_reconnect`` (the reconnect-resume drain).
        """
        if not self._pending_connector_halt.is_set():
            return
        self._pending_connector_halt.clear()
        reason = self._pending_connector_halt_reason or 'connector-fatal'
        self._pending_connector_halt_reason = None
        self.halt(reason)

    def _dispatch_live(self, event) -> None:
        """Dispatch one event through the live halt/pause gate (D-02/D-19).

        The freeze-in-place gate: while HALTED (terminal) OR paused-on-disconnect
        (reversible), NEW order submission (the SIGNAL and ORDER routes) is gated, while
        BAR/FILL/ERROR streaming + reconciling + persisting continue to drain normally
        (so the venue stays mirrored and the halt itself — a CRITICAL ErrorEvent — is
        still consumed). Otherwise → a transparent pass-through.

        D-14 (V17-11): the gate no longer blanket-suppresses SIGNAL+ORDER. It branches by
        order KIND so risk-REDUCING commands are not silently dropped during the pause:
        (a) a CANCEL command ALWAYS passes through (a cancel only reduces risk);
        (b) a system-generated PROTECTIVE order (a bracket child — ``parent_order_id`` set)
            is DEFERRED onto the replay queue and replayed on resume (never left naked);
        (c) a fresh ENTRY order (NEW, no parent) and any SIGNAL stay SUPPRESSED — opening
            new risk while blind to the venue is exactly what the pause exists to prevent.
        """
        if (self._is_halted() or self._is_submission_paused()) and getattr(
                event, 'type', None) in (EventType.SIGNAL, EventType.ORDER):
            event_type = getattr(getattr(event, 'type', None), 'name', 'UNKNOWN')
            command = getattr(event, 'command', None)
            parent = getattr(event, 'parent_order_id', None)
            # (a) CANCEL always passes — a cancel only reduces risk (D-14).
            if command is OrderCommand.CANCEL:
                self.logger.info(
                    'CANCEL dispatched during pause/halt (D-14) — cancels always pass the '
                    'gate (risk-reducing)', event_type=event_type)
                self.event_handler._dispatch(event)
                return
            # (b) a PROTECTIVE order (bracket child — parent set) is deferred for replay
            # on resume, not dropped (D-14) — the just-filled position stays protected.
            if getattr(event, 'type', None) is EventType.ORDER and parent is not None:
                self._deferred_protective.append(event)
                self.logger.warning(
                    'Protective order deferred during pause/halt (D-14) — replays on resume',
                    event_type=event_type)
                return
            # (c) fresh ENTRY order + SIGNAL stay suppressed (don't open new risk blind).
            self.logger.warning(
                'New order submission suppressed (freeze-in-place / paused-on-disconnect)',
                event_type=event_type)
            return
        self.event_handler._dispatch(event)

    def _update_status(
        self,
        new_status: SystemStatus,
        error_msg: Optional[str] = None,
        halt_reason: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        """The SINGLE enforced status-mutation seam (D-05 / V17-03).

        This is the ONE point that writes ``self._status`` for a lifecycle transition
        (``__init__`` sets the initial STOPPED at construction; ``reset_halt`` is the
        one sanctioned off-table exit, routed here with ``force=True``). It enforces
        ``VALID_STATUS_TRANSITIONS``: a transition not in the current state's legal set
        is REFUSED (log-and-refuse, status left unchanged) rather than raised — the live
        event loop follows publish-and-continue (D-17), so an illegal transition must
        never abort it. ``HALTED`` has NO legal exit in the table, so once the reconciler
        or baseline guard halts the engine, no lifecycle transition (including the
        processing loop's RUNNING stamp) can clobber it — only ``reset_halt`` may.

        A same-state call is an idempotent no-op (returns ``False`` without notifying).

        Parameters
        ----------
        new_status : SystemStatus
            The target lifecycle state.
        error_msg : str, optional
            Recorded as ``self._last_error`` on a successful transition.
        halt_reason : str, optional
            The machine-readable halt reason (D-07), set ATOMICALLY with the flip under
            the same ``_status_lock`` acquisition. ``halt()`` routes its reason through
            here so the reason and the HALTED flip share one lock (WR-01 atomic
            check-and-set) — two concurrent ``halt()`` callers can never both win.
        force : bool
            Bypass the transition-table check. RESERVED for ``reset_halt``'s sanctioned
            HALTED exit only — do NOT use elsewhere (it defeats the latch).

        Returns
        -------
        bool
            ``True`` iff the status actually changed (the winning caller); ``False`` on a
            same-state no-op or a refused illegal transition.
        """
        with self._status_lock:
            old_status = self._status
            if new_status == old_status:
                return False  # idempotent no-op — already in this state.
            if not force and new_status not in VALID_STATUS_TRANSITIONS[old_status]:
                # F/U-8: log-and-refuse (never raise from the live loop). The message
                # binds only fixed enum literals — no connector context — so no secret
                # can leak on a halt-adjacent refusal (T-05.1-10, ASVS V7).
                self.logger.warning(
                    'Refused illegal status transition %s -> %s (D-05 latch); '
                    'status unchanged', old_status.value, new_status.value)
                return False
            self._status = new_status
            if error_msg:
                self._last_error = error_msg
            if new_status == SystemStatus.HALTED:
                if halt_reason is not None:
                    self._halt_reason = halt_reason
            else:
                # Leaving HALTED (only possible via reset_halt's forced exit) clears the
                # machine-readable reason so get_status() no longer surfaces a stale one.
                self._halt_reason = None

        self._notify_status_change(old_status, new_status, error_msg)
        return True

    def _notify_status_change(
        self,
        old_status: SystemStatus,
        new_status: SystemStatus,
        error_msg: Optional[str],
    ) -> None:
        """Log + fire the status callback OUTSIDE ``_status_lock`` (WR-01).

        Split out of ``_update_status`` so ``halt()`` can flip the status UNDER the
        lock (atomic check-and-set) and still reuse the exact notification path once,
        for the winning caller only — the callback/log must never run holding the lock.
        """
        self.logger.info(f'Status changed from {old_status.value} to {new_status.value}')

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
            # LAZY imports (mirror the donor's lazy live imports) so the backtest
            # import path never pulls these onto its graph — the recurring inertness
            # gate (tests/integration/test_okx_inertness.py).
            from itrader import config as _system_config
            from itrader.core.clock import BacktestClock
            from itrader.trading_system.compose import Engine
            from itrader.trading_system.session_initializer import SessionInitializer
            from itrader.trading_system.simulation.time_generator import TimeGenerator
            from itrader.universe.universe_handler import UniverseHandlerConfig

            # INTERIM Engine holder (behavior-preserving): the facade still wires its
            # own handlers directly this plan, so it assembles the compose ``Engine``
            # holder from them for ``SessionInitializer`` / ``wire_universe``. ``clock``
            # + ``time_generator`` are inert placeholders the live path never reads (only
            # the handlers + feed + queue are consumed); 06-06's ``build_live_system``
            # replaces this with the real ``compose_engine`` ``Engine``.
            engine = Engine(
                global_queue=self.global_queue,
                clock=BacktestClock(),
                store=self.store,
                feed=self.feed,
                strategies_handler=self.strategies_handler,
                screeners_handler=self.screeners_handler,
                portfolio_handler=self.portfolio_handler,
                execution_handler=self.execution_handler,
                order_handler=self.order_handler,
                event_handler=self.event_handler,
                time_generator=TimeGenerator())

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
            # first-class UniverseHandler -> LiveRouteRegistrar). The freeze-gate is the
            # interim callable repointed to SafetyController in P7 (D-04 body untouched).
            initializer = SessionInitializer(
                engine,
                universe_config=universe_config,
                venue_exchange=venue_exchange,
                data_provider=self._okx_data_provider,
                freeze_gate=lambda: self._is_halted() or self._is_submission_paused(),
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
            self._update_status(SystemStatus.ERROR, str(e))
            raise
    
    def start(self):
        """
        Start the live trading system by initializing the session
        and starting the event processing thread.
        """
        if self._running:
            self.logger.warning('Live trading system is already running')
            return False
        
        self.logger.info('Starting live trading system')
        self._update_status(SystemStatus.STARTING)
        
        try:
            # 05.3-08 (D-20 / WR-01): the DURABLE halt refusal gate runs FIRST — right
            # after STARTING and BEFORE any session init / OKX connect / feed warmup /
            # stream spawn / VenueAccount.snapshot() / VenueReconciler.reconcile(). A
            # supervised auto-restart builds a FRESH engine whose in-process _status is
            # STOPPED, so the in-process _is_halted() check further below would silently
            # clear a breaker halt whose cause is not re-detectable at start(). Refuse
            # RUNNING while an unresolved durable record exists (runs for EVERY venue,
            # outside the OKX branch) and RE-LATCH this fresh instance in-process from the
            # persisted reason via _update_status (NOT halt() — halt() would write a SECOND
            # durable record) so get_status() reflects it and reset_halt() can clear both
            # the in-process and durable latches. Placed at the TOP so a durably-HALTED
            # engine stays INERT: zero venue I/O, no state-mutating reconcile, no second
            # durable record (WR-01 — the old late position ran the whole OKX handshake +
            # reconcile before refusing). The `not self._is_halted()` conjunct is KEPT (a
            # reconcile/guard halt raised DURING this run is handled by the D-05 check
            # below, no double-refuse); guarded on the store being present (in-memory
            # fallback -> skip). Sits before the D-17 error-policy bind so a refused start
            # does not even install the live handler policy.
            if (self._halt_record_store is not None
                    and not self._is_halted()
                    and self._halt_record_store.has_unresolved()):
                durable_record = self._halt_record_store.get_unresolved()
                durable_reason = (
                    durable_record.reason if durable_record is not None
                    else 'durable-halt')
                self.logger.error(
                    'start() refused RUNNING: an unresolved DURABLE halt record latches '
                    'across the restart (reason=%s) — a supervised auto-restart cannot '
                    'silently clear a breaker halt (T-05.2-17); resolve the cause then '
                    'call reset_halt()', durable_reason)
                self._update_status(
                    SystemStatus.HALTED,
                    error_msg=f'durable halt latched on restart: {durable_reason}',
                    halt_reason=durable_reason)
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

            # 05-04 (D-14): with the connector live, seed the VenueAccount cache
            # from a REST snapshot then start its push stream BEFORE RUNNING, and
            # link the venue-cached account into every active live portfolio so the
            # engine-thread drift compare reads venue truth. Gated to the OKX arm
            # (the only venue with a VenueAccount); lazy inside the okx branch, so
            # no inertness impact. The venue owns balance/positions in live — the
            # engine caches, it does not recompute (Pitfall 10, D-14).
            # 05.3-09 (D-23): UNGATE the durable PORTFOLIO-ledger rehydrate from the
            # OKX arm — it runs whenever the store exposes rehydrate() (the durable
            # Postgres spine present), REGARDLESS of exchange, so a durable
            # paper/simulated engine restores its persisted cash + realized-PnL on
            # restart instead of coming up with construction-time initial cash. It is
            # sequenced FIRST (before the okx block's snapshot()/link/reconcile) so a
            # paper/simulated account restores while its portfolio still holds the
            # SimulatedAccount — before any VenueAccount swap (whose restore_cash is a
            # no-op, which is why link-before-rehydrate left the SimulatedAccount
            # restore dead on the paper path). Semantics = RESTORE not reconcile: the
            # SimulatedAccount ledger is sole truth and the restored (cash, positions)
            # pair's consistency is guaranteed by D-19's atomic fill-path write; the
            # venue reconcile/snapshot below is NOT invoked on the paper path. Guarded
            # on the store exposing rehydrate() (the CachedSql live store; not the
            # in-memory fallback) so an unconfigured ITRADER_DATABASE_* env degrades
            # cleanly; rehydrate() is additionally per-portfolio getattr-guarded (the
            # in-memory backtest backend is a clean skip → oracle-dark).
            # D-22 (WR-05): pass the order-mirror seed sink so the SAME single
            # transactions.venue_trade_id history pass restart-seeds the
            # ReconcileManager dedup ring SYMMETRICALLY with the portfolio ledger's
            # _settled_venue_trade_ids — a re-delivered pre-restart trade cannot
            # double-settle on EITHER arm.
            if hasattr(self._order_storage, 'rehydrate'):
                self.portfolio_handler.rehydrate(
                    self.order_handler.order_manager.seed_applied_trades)

            if self._venue_account is not None:
                self._venue_account.snapshot()
                self._venue_account.start_streaming()
                self._link_venue_account_to_portfolios()

                # 05-07 (RECON-05, D-03/D-05): two-sided restart reconcile on the
                # ENGINE thread BEFORE RUNNING. The working set was rehydrated from the
                # store (INTENT truth) above; reconcile against the venue REST snapshot,
                # adopt in-band deltas as reconciling FillEvents (idempotent fill
                # path), halt on unexplained venue positions, and re-link brackets.
                # Lazy-imported inside the OKX arm so the backtest import path stays
                # SQL/async/connector-free (inertness gate). Stays okx-only (the venue
                # reconcile never runs on the paper/simulated path — D-23 RESTORE-only)
                # and guarded on the store exposing rehydrate() so an unconfigured
                # ITRADER_DATABASE_* env degrades cleanly.
                if hasattr(self._order_storage, 'rehydrate'):
                    from itrader.portfolio_handler.reconcile.venue_reconciler import (
                        VenueReconciler,
                    )
                    reconciler = VenueReconciler(
                        store=self._order_storage,
                        venue_account=self._venue_account,
                        connector=self._okx_connector,
                        global_queue=self.global_queue,
                        halt_signal=self.halt,
                        exchange=self._okx_exchange,
                    )
                    reconciler.reconcile()

                # D-04 (V17-04, ARCH-2 guard arm): session-start baseline guard,
                # sequenced strictly AFTER reconcile() and BEFORE the thread spawn.
                # Reconcile syncs the explainable; this guard HALTs on the residue —
                # any unexplained base-asset holding the engine cannot account for.
                # Runs even when the store has no rehydrate() (the reconcile block
                # above is store-gated; the guard is not — a fresh session with a
                # venue holding the engine never opened must still halt). On a clean
                # fresh session (engine flat, venue flat) it is a benign no-op.
                self._run_session_baseline_guard()

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
            # reset_halt() re-runs the verify-then-trust sequence. _update_status already
            # refuses HALTED->RUNNING as a second line of defence; this check keeps
            # start() from even spawning the loop and returns False so the caller sees the
            # refusal. The stop() teardown in the caller's finally is safe (no thread).
            if self._is_halted():
                self.logger.error(
                    'start() refused RUNNING: engine HALTED during session init '
                    '(reason=%s) — the reconciler/baseline guard declared venue state '
                    'untrustworthy; not spawning the processing thread',
                    self._halt_reason)
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
            self._update_status(SystemStatus.ERROR, str(e))
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
            self._update_status(SystemStatus.STOPPING)

            # RUN-02 (D-05/D-06): delegate the drain-loop + poll-timer teardown to the
            # injected LiveRunner — it sets the shared _stop_event, joins the drain thread,
            # then stops the composed WorkerSupervisor. Replaces the facade-owned
            # _thread/_poll_timer_thread join bookkeeping.
            if self._live_runner is not None:
                self._live_runner.stop(timeout=timeout)

            self._running = False
            self._update_status(SystemStatus.STOPPED)

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
        with self._status_lock, self._stats_lock:
            uptime = None
            if self._stats['uptime_start'] and self._status == SystemStatus.RUNNING:
                start_time = datetime.fromisoformat(self._stats['uptime_start'])
                # WR-05: uptime_start is now stored tz-aware (datetime.now(UTC)),
                # so the comparand must also be tz-aware or this subtraction
                # raises "can't subtract offset-naive and offset-aware datetimes".
                uptime = (datetime.now(UTC) - start_time).total_seconds()
            
            return {
                'status': self._status.value,
                # 05-04 (D-07): the machine-readable halt reason (None unless HALTED).
                'halt_reason': self._halt_reason,
                # 05-08 (D-19): the reversible pause-on-disconnect state, surfaced
                # DISTINCTLY from the terminal halt (paused != HALTED).
                'paused': self._submission_paused,
                'paused_reason': self._paused_reason,
                'is_running': self.is_running(),
                'exchange': self.exchange,
                'queue_size': self.get_queue_size(),
                'thread_alive': (
                    self._live_runner._thread.is_alive()
                    if self._live_runner is not None and self._live_runner._thread
                    else False),
                'thread_name': (
                    self._live_runner._thread.name
                    if self._live_runner is not None and self._live_runner._thread
                    else None),
                'last_error': self._last_error,
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
    store = CsvPriceStore()
    # Phase 3 (FEED-05): LiveBarFeed is the live driver — LAZY-imported here so the
    # BACKTEST import path never pulls live_bar_feed (inertness gate).
    from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
    feed = LiveBarFeed(provider=None, base_timeframe=to_timedelta('1d'))
    screeners_handler = ScreenersHandler(global_queue, feed)

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
        order_storage = OrderStorageFactory.create('backtest')
        signal_store = SignalStorageFactory.create_in_memory()
        system_db_backend: Optional[Any] = None
    else:
        # CR-01/RECON-04: honor the unified ITRADER_DATABASE_* Postgres surface — one
        # SqlEngine drives the whole v1.6 operational store (same source Alembic uses).
        from itrader.config.sql import SqlDriver, SqlSettings
        from itrader.storage import SqlEngine
        from itrader.order_handler.storage.cached_sql_storage import (
            CachedSqlOrderStorage,
        )
        from itrader.order_handler.storage.sql_storage import SqlOrderStorage

        backend = SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
        # D-10: store-first working set (persist-then-acknowledge) via the CachedSql
        # wrapper over the untouched SqlOrderStorage; rehydrate() rebuilds it on restart.
        order_storage = CachedSqlOrderStorage(SqlOrderStorage(backend))
        system_db_backend = backend
        # D-11: signal store live-driven on the async/best-effort path over the SAME spine.
        signal_store = SignalStorageFactory.create('live', sql_engine=backend)

    # 05.2-05 (D-07): durable portfolio ledger when the Postgres spine is present.
    if system_db_backend is not None:
        portfolio_handler = PortfolioHandler(
            global_queue, environment='live', sql_engine=system_db_backend)
    else:
        portfolio_handler = PortfolioHandler(global_queue)

    # 05.2-06 (D-10 / ARCH-4 Layer 2): durable halt-record store over the shared spine
    # (survives a process restart) — None on the in-memory fallback (degrade cleanly).
    if system_db_backend is not None:
        from itrader.storage.halt_record_store import HaltRecordStore
        halt_record_store: Optional[Any] = HaltRecordStore(system_db_backend)
    else:
        halt_record_store = None

    # Execution handler BEFORE the order handler (admission commission estimator, D-04).
    execution_handler = ExecutionHandler(global_queue)
    simulated_exchange = execution_handler.exchanges.get('simulated')

    def _estimate_commission(quantity: Decimal, price: Decimal) -> Decimal:
        if not isinstance(simulated_exchange, SimulatedExchange):
            return Decimal("0")
        return simulated_exchange.fee_model.calculate_fee(
            quantity, price, side="buy", order_type="market")

    # Plan 02-03 (D-09/D-14): thread the portfolio's margin settings into the order
    # domain (mirrors compose_engine). SHORT-01/D-07: thread the shorts-enabling flags.
    _trading_rules = portfolio_handler.config_data.trading_rules
    strategies_handler = StrategiesHandler(
        global_queue, feed, signal_store,
        allow_short_selling=_trading_rules.allow_short_selling,
        enable_margin=_trading_rules.enable_margin)

    order_handler = OrderHandler(
        global_queue, portfolio_handler, order_storage,
        commission_estimator=_estimate_commission,
        enable_margin=_trading_rules.enable_margin,
        portfolio_max_leverage=_trading_rules.max_leverage)
    # LIQ-03 (04-03): live-parity injection of the SAME order_storage into the portfolio
    # handler so a BAR-route liquidation registers its Order in the shared mirror.
    portfolio_handler.set_order_storage(order_storage)

    event_handler = EventHandler(
        strategies_handler,
        screeners_handler,
        portfolio_handler,
        order_handler,
        execution_handler,
        feed.generate_bar_event,
        global_queue,
    )

    # ------------------------------------------------------------------
    # Venue wiring (Plan 02-05, D-04 / CONN-04 — relocated P5 D-06 assemble_venue call).
    # The whole OKX/paper venue stack is LAZY-imported here so the BACKTEST import path
    # stays async/ccxt/credential-free (the hot-path inertness gate).
    okx_connector: Optional[Any] = None
    okx_exchange: Optional[Any] = None
    okx_data_provider: Optional[Any] = None
    venue_account: Optional[Any] = None
    venue_bundle: Optional[Any] = None
    venue_lifecycle: Optional[Any] = None

    from itrader import config as _system_config
    from itrader.connectors.provider import ConnectorProvider
    from itrader.trading_system.engine_context import EngineContext
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

    # (2) D-23: the infra ctx wires live onto the PriorityEventBus (not the raw queue).
    ctx = EngineContext(
        bus=global_queue,
        config=_system_config,
        environment='live',
        sql_engine=system_db_backend,
    )
    venue_spec = SimpleNamespace(
        execution_venue=exchange,
        # D-21: production paper re-points to the OKX live data feed (the offline replay
        # feed left production for tests/). A TEST fixture injects a 'replay' plugin via
        # data_plugins and passes data_provider='replay' explicitly; production never does.
        data_provider=(getattr(spec, 'data_provider', None) or {
            'okx': 'okx', 'paper': 'okx'}.get(exchange, 'okx')),
        account_id=getattr(spec, 'account_id', None),
    )

    # (3) Delegate venue assembly (registry membership replaces the venue-string branch).
    provider: Optional[Any] = None
    if exchange in exec_registry:
        bundle, venue_lifecycle = assemble_venue(
            ctx, venue_spec, connectors, exec_registry, data_registry)
        venue_bundle = bundle
        provider = venue_lifecycle.provider

        # bundle.connector is the STREAMING-venue discriminator (okx present, paper None).
        # A paper (connector=None) bundle has no streaming okx exchange/account; its data
        # provider is still wired to the feed below (the injected TEST 'replay' provider in
        # tests, or the OKX data provider in production paper — D-21).
        okx_connector = bundle.connector
        if bundle.connector is not None:
            okx_exchange = bundle.exchange
            execution_handler.exchanges[exchange] = bundle.exchange
            venue_account = bundle.account_factory()
            okx_data_provider = provider

        # (4) UNIFORM provider->feed wiring (D-10) that needs NO facade method.
        feed.set_provider(provider)
        provider.set_bar_sink(feed.update)
        provider.set_global_queue(global_queue)

    # Construct the facade via PURE INJECTION (RUN-03/D-09).
    components = LiveSystemComponents(
        exchange=exchange,
        global_queue=global_queue,
        store=store,
        feed=feed,
        screeners_handler=screeners_handler,
        portfolio_handler=portfolio_handler,
        strategies_handler=strategies_handler,
        order_handler=order_handler,
        execution_handler=execution_handler,
        event_handler=event_handler,
        signal_store=signal_store,
        system_db_backend=system_db_backend,
        halt_record_store=halt_record_store,
        order_storage=order_storage,
        venue_bundle=venue_bundle,
        venue_lifecycle=venue_lifecycle,
        okx_connector=okx_connector,
        okx_exchange=okx_exchange,
        okx_data_provider=okx_data_provider,
        venue_account=venue_account,
    )
    facade = LiveTradingSystem(components, status_callback=status_callback)

    # Facade-dependent wiring (references the constructed facade's own gate methods).
    # The provider halt-signal + stream-state listeners for a registered venue, and the
    # streaming-venue exchange/connector halt signals (bundle.connector present).
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
    # 05-04 (D-01/D-02): engine-thread drift-halt signal -> freeze-in-place halt.
    portfolio_handler.set_halt_signal(facade.halt)

    # RUN-02 (D-05/D-06/D-07/D-08): the live runtime engine. LiveRunner OWNS the drain
    # loop; it COMPOSES the WorkerSupervisor (poll timer, D-05) and takes the minimal
    # ErrorPolicy (D-07) + a dispatch-gate callback bound to the facade's untouched
    # _dispatch_live (D-08) + the D-04-frozen per-tick hook callables. The facade's
    # error-policy install happens in start() (daemon/live path only, D-17).
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
        dispatch_gate=facade._dispatch_live,
        update_stats=facade._update_stats,
        record_bar_metrics=facade._record_bar_metrics,
        resume_after_reconnect=facade._maybe_resume_after_reconnect,
        halt_after_connector_fatal=facade._maybe_halt_after_connector_fatal,
        queue_timeout=_LIVE_QUEUE_TIMEOUT,
        max_idle_time=_LIVE_MAX_IDLE_TIME,
        on_loop_start=facade._on_loop_start,
        on_loop_error=facade._on_loop_error,
    )
    facade._live_runner = live_runner
    facade._error_policy = error_policy

    logger.info('Live trading system built', exchange=exchange)
    return facade
