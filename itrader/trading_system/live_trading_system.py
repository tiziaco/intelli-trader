import os
import queue
import sys
import threading
from collections import deque
from datetime import datetime, UTC
from decimal import Decimal
from typing import Optional, Dict, Any, Callable

# D-14 (V17-11): bound on the pause-window protective-order replay queue. During a
# pause/halt, system-generated protective orders (bracket children, OCO/orphan
# cancels) are DEFERRED here and replayed on resume; the bound prevents an unbounded
# backlog if a pause runs long. A realistic reconnect-window generates far fewer than
# this many protective orders, so the cap only guards a pathological stall (oldest
# deferred protective orders are dropped past it — a dropped protective order is the
# same freeze-in-place safety posture as the pre-D-14 blanket suppression).
_DEFERRED_PROTECTIVE_REPLAY_MAX = 1000

from dataclasses import dataclass

from itrader.core.enums import ErrorSeverity, OrderCommand, SystemStatus, VALID_STATUS_TRANSITIONS
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
from itrader.universe import Universe, derive_instruments, derive_membership

from itrader.logger import get_itrader_logger
from itrader.events_handler.events import EventType, ErrorEvent

# Live operational store credential surface (D-live wiring completed). The live order +
# signal store is selected by ENV-PRESENCE of a Postgres credential on the unified
# ``ITRADER_DATABASE_*`` surface — ``ITRADER_DATABASE_PASSWORD`` (component-var arm) or the
# ``ITRADER_DATABASE_URL`` verbatim escape hatch — and built from the unified ``SqlSettings``
# Postgres arm, the SAME credential source Alembic ``migrations/env.py`` uses (one canonical
# source; no separate legacy env-var seam). WR-10: no hardcoded credential fallback — an
# unconfigured env falls back to in-memory order + signal storage with a loud warning. The
# presence check reads ``os.getenv`` inside ``__init__`` (below) so it honors per-construction
# env; it MUST gate BEFORE constructing ``SqlSettings(driver=POSTGRESQL_PSYCOPG2)``, which
# RAISES ``ValidationError`` (``_require_pg_credentials``) when no credential is present.

# WR-03: the SINGLE wiring source for the live OKX subscription. The OKX data
# provider stamps this symbol/timeframe into every ClosedBar (the feed's ring key),
# the feed warms up on the same pair, and universe membership is checked against it —
# so the OkxDataProvider constructor args and the feed.warmup() args can never drift
# into a ring-key vs membership mismatch (which would otherwise surface only as a
# MissingPriceDataError at first window()). A future D-live wiring sources these from
# Settings; today they are the one shared constant.
# BTC/USDC (not BTC/USDT): the OKX EEA entity restricts USDT spot pairs under MiCA —
# an order on BTC/USDT returns sCode 51155 "local compliance restrictions". Hardcoded
# for now; the pair becomes configurable via the universe subsystem in the next phase.
_OKX_STREAM_SYMBOL = "BTC/USDC"
_OKX_STREAM_TIMEFRAME = "1d"

# D-18 (structural half — SINGLE SOURCE OF TRUTH for the paper/backtest parity anchor):
# the canonical golden window + symbol. BOTH the paper replay store (constructed
# EXPLICITLY from these in the paper arm of __init__ below) AND the backtest comparand
# (test_paper_parity.py imports these) derive from THESE literals, so paper/backtest
# parity can never silently desync. They previously agreed only because the CsvPriceStore
# class defaults happened to equal the test's own literals (WR-02 coincidental parity) —
# the replay store window is now wired from this shared constant, not the class default.
PAPER_PARITY_START_DATE = "2018-01-01"
PAPER_PARITY_END_DATE = "2026-06-03"
PAPER_PARITY_SYMBOL = "BTCUSD"

# Phase 4 (D-02/D-09): the SINGLE wiring source for the paper replay subscription.
# The ReplayDataProvider stamps this symbol/timeframe into every replayed ClosedBar
# (the feed's ring key), and run_paper_replay() queries newest_bar() on the same
# symbol for the bar-open stamp. The paper ticker MUST be the universe-member form
# "BTCUSD" (what the strategy's window() queries), NOT the OKX venue form "BTC/USDT":
# a mismatch surfaces only as a MissingPriceDataError at the first window() call
# (LiveBarFeed._find_ring). This is the symbol-form trap the OKX arm guards against
# with its wiring-time membership assertion. Sourced from the D-18 parity symbol above.
_PAPER_STREAM_SYMBOL = PAPER_PARITY_SYMBOL
_PAPER_STREAM_TIMEFRAME = "1d"

# WR-02 (assertion half, now backed by the D-18 structural wiring): run_paper_replay
# asserts the replay store's effective window/symbol equals these — a defense that the
# CsvPriceStore honored the window it was EXPLICITLY constructed with (below), no longer
# a coincidental-class-default check. Aliased to the single-source constants above.
_PAPER_EXPECTED_START = PAPER_PARITY_START_DATE
_PAPER_EXPECTED_END = PAPER_PARITY_END_DATE


# SystemStatus now lives in its canonical home ``core/enums/system.py`` and is
# imported above; the ``SystemStatus.X`` usages below resolve unchanged.


@dataclass(frozen=True)
class _LiveWarmupConsumer:
    """D-13 raw-bar consumer: sizes ``LiveBarFeed.cache_capacity()`` at wiring time.

    A minimal frozen ``RawBarConsumer`` (``cache_registration.RawBarConsumer``
    Protocol — a read-only ``required_history_depth``) registered on the LIVE feed
    so the ring + warmup derive to the max strategy warmup (100 for SMA_MACD), not
    the newest-bar floor (1). Without it the indicators never warm and
    ``calculate_signals`` short-circuits to zero trades — the single most likely
    correctness failure of the live path (RESEARCH Pitfall 1).
    """

    required_history_depth: int


class LiveTradingSystem:
    """
    Encapsulates the settings and components for carrying out live trading.
    Processes events from a global queue in a separate thread instead of 
    using a for-loop like the backtest system.
    
    Enhanced with web control capabilities for REST API and WebSocket integration.
    """
    
    def __init__(
        self, 
        exchange='binance',
        to_sql=False,
        queue_timeout=1.0,
        max_idle_time=300.0,  # 5 minutes max idle time
        status_callback: Optional[Callable[[SystemStatus, Dict[str, Any]], None]] = None
    ):
        """
        Set up the live trading system variables.
        
        Parameters
        ----------
        exchange : str
            The exchange to connect to
        to_sql : bool
            Whether to store data to SQL
        queue_timeout : float
            Timeout for queue operations in seconds
        max_idle_time : float
            Maximum idle time before logging a warning (seconds)
        status_callback : callable, optional
            Callback function to notify status changes to external systems
        """
        self.logger = get_itrader_logger().bind(component="LiveTradingSystem")
        self.exchange = exchange
        self.to_sql = to_sql
        self.queue_timeout = queue_timeout
        self.max_idle_time = max_idle_time
        self.status_callback = status_callback
        
        # System status tracking
        self._status = SystemStatus.STOPPED
        self._status_lock = threading.Lock()
        self._last_error = None
        # 05-04 (D-07): machine-readable halt reason surfaced on get_status() when
        # the engine is HALTED. reason ∈ {drift, reconciliation-unresolved,
        # connector-fatal, paused-on-disconnect}. None until the first halt.
        self._halt_reason: Optional[str] = None
        # 05-08 (D-19): REVERSIBLE pause-on-disconnect state — distinct from the
        # terminal HALT. A sustained venue-stream disconnect quiesces NEW order
        # submission (don't trade when you can't see the venue) while streaming /
        # reconciling / persisting continue and existing positions/orders stay
        # untouched; a reconnect + a fresh REST snapshot/reconcile resumes it.
        # _pending_stream_resume is SET by the connector-loop reconnect callback and
        # DRAINED on the ENGINE thread (Pitfall 9 — no blocking venue I/O on the loop).
        self._submission_paused = False
        self._paused_reason: Optional[str] = None
        self._pending_stream_resume = threading.Event()
        # 05.3-08 (D-21 / WR-02): connector-fatal escalation handoff. A fatal connector
        # error / exhausted retry ceiling / unclassified catch-all escalates from the
        # connector ASYNCIO LOOP thread. Doing the blocking durable record_halt SQL write
        # there stalls every stream sharing the loop (Pitfall 9). The loop-thread callback
        # (_request_connector_halt) only SETS this flag; the ENGINE thread drains it via
        # _maybe_halt_after_connector_fatal and runs the blocking halt() (durable write +
        # status flip + CRITICAL alert), winner-only. Mirrors the pause/resume flag pattern.
        self._pending_connector_halt = threading.Event()
        self._pending_connector_halt_reason: Optional[str] = None
        # D-14 (V17-11): pause-window protective-order replay queue. While submission
        # is paused/halted, system-generated PROTECTIVE orders (bracket children,
        # OCO/orphan cancels — a just-filled entry's stop/take-profit) are DEFERRED here
        # instead of being blanket-dropped, and REPLAYED through _dispatch_live on
        # resume so the position is never left naked. Bounded engine-internal state — NOT
        # a new EventType. Fresh ENTRY orders are still suppressed (never deferred), and a
        # CANCEL command is dispatched immediately (a cancel only reduces risk).
        self._deferred_protective: "deque[Any]" = deque(
            maxlen=_DEFERRED_PROTECTIVE_REPLAY_MAX)
        
        # Threading control
        self._running = False
        self._thread: Optional[threading.Thread] = None
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
        
        # Initialize components — mirrors the backtest Store+Feed wiring shape
        # (Plan 06-05, Pitfall 8). Minimal conformance only: a real live feed
        # (streaming Store/Feed implementations) is owned by D-live; this keeps
        # the module importing and constructing on the same seams.
        self.global_queue = queue.Queue()
        self.store = CsvPriceStore()
        # Phase 3 (FEED-05): LiveBarFeed replaces the BacktestBarFeed placeholder as
        # the live driver — the bar's arrival IS the event, so it takes over
        # TimeGenerator's driver role. LAZY-imported here (mirrors the lazy OKX/SQL
        # imports below) so the BACKTEST import path never pulls live_bar_feed — the
        # recurring milestone inertness gate (tests/integration/test_okx_inertness.py).
        # Constructed provider-less and UNCONDITIONALLY (constructible for every venue);
        # the real OKX provider is injected into the okx arm below via
        # self.feed.set_provider(...). The self.feed.generate_bar_event reference in the
        # EventHandler route literal stays a valid callable because LiveBarFeed defines
        # its OWN concrete dormant no-op generate_bar_event (D-05).
        from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
        self.feed = LiveBarFeed(provider=None, base_timeframe=to_timedelta('1d'))
        # Signal-store sink (Plan 05-03 / 05-06, D-11): the live signal store is
        # wired TOGETHER with the order working set in the ITRADER_DATABASE_*-gated
        # store block below — both share ONE SqlBackend (sync-durable orders on the D-10
        # path, the advisory signal store on the D-11 async/best-effort path). WR-03:
        # retain the store on self and expose accessors (mirroring the backtest
        # system) — a local variable would leave every captured SignalRecord
        # permanently unreachable (a write-only accumulation).
        self.screeners_handler = ScreenersHandler(self.global_queue, self.feed)
        # 05.2-05 (D-07): the PortfolioHandler is constructed AFTER the operational
        # store block below (which sets self._system_db_backend) so it can inject the
        # SAME shared SqlBackend on the durable 'live' arm — see the durable-portfolio
        # wiring right after the store block. Declared here as a forward attribute so
        # nothing between reads it before construction.
        self.portfolio_handler: PortfolioHandler
        # WR-04: declare the universe attribute as a clean "not yet wired"
        # sentinel here, mirroring Engine.universe: Optional[Universe] = None on
        # the backtest path. It is populated in _initialize_live_session (from
        # start()); without this, any pre-start read raises AttributeError
        # instead of returning None — an attribute-existence trap for D-live.
        self.universe: Optional[Universe] = None
        
        # ------------------------------------------------------------------
        # v1.6 operational store live-drive (05-06, RECON-04, D-10/D-11).
        #
        # Complete the deferred v1.6 D-01/RETAIN-03 wiring: drive the operational
        # store off the real feed, SPLIT by durability. The SYNC-DURABLE working set
        # (order lifecycle — create/terminalize) persists store-first via
        # ``CachedSqlOrderStorage`` so it survives a crash for a correct two-sided
        # restart (D-10). The DERIVED / advisory state (the signal store) is
        # live-driven on the async/best-effort path (D-11 — signals are audit records,
        # NOT the restart working set). Both share ONE ``SqlBackend`` built here.
        #
        # All SQL imports stay LAZY inside the Postgres arm (mirrors the OKX
        # lazy imports below) so the BACKTEST import path stays SQLAlchemy-free — the
        # recurring milestone inertness gate (tests/integration/test_okx_inertness.py).
        #
        # Read the credential presence at __init__ time INSIDE the method (not module
        # scope) so it honors per-construction env. CRITICAL: this env-presence check
        # MUST gate BEFORE constructing SqlSettings — a bare
        # SqlSettings(driver=POSTGRESQL_PSYCOPG2) with no password/url RAISES
        # ValidationError via _require_pg_credentials, so construct-and-catch is NOT
        # valid control flow here.
        pg_password = os.getenv("ITRADER_DATABASE_PASSWORD", "")
        pg_url = os.getenv("ITRADER_DATABASE_URL", "")
        if not (pg_password or pg_url):
            # WR-10: fail loudly into the in-memory fallback instead of shipping a
            # default connection string with embedded credentials. Both the order
            # working set and the signal store fall back to in-memory — captured
            # orders/signals will NOT survive a restart.
            self.logger.warning(
                "No Postgres credential in env (ITRADER_DATABASE_PASSWORD / "
                "ITRADER_DATABASE_URL unset) — using in-memory order + signal storage "
                "(orders/signals will NOT survive a restart)"
            )
            order_storage = OrderStorageFactory.create('backtest')
            # create_in_memory() (not create('backtest')) — the stale unconditional
            # backtest signal wiring is gone; the live-driven store is on the D-11 arm above.
            self._signal_store = SignalStorageFactory.create_in_memory()
            # No SQL spine on the in-memory fallback — nothing to dispose at stop().
            self._system_db_backend: Optional[Any] = None
        else:
            # CR-01/RECON-04: a Postgres credential is present on the unified
            # ITRADER_DATABASE_* surface — honor it. Build ONE Postgres ``SqlBackend``
            # from the unified ``SqlSettings`` Postgres arm (the SAME surface Alembic
            # migrations/env.py uses) and drive the whole v1.6 operational store off it.
            # The SQL imports stay LAZY inside this arm so the backtest import path
            # remains SQLAlchemy-free (GATE-01 inertness).
            from itrader.config.sql import SqlDriver, SqlSettings
            from itrader.storage import SqlBackend
            from itrader.order_handler.storage.cached_sql_storage import (
                CachedSqlOrderStorage,
            )
            from itrader.order_handler.storage.sql_storage import SqlOrderStorage

            # Mirror migrations/env.py:76 — no explicit url=; let pydantic-settings source
            # ITRADER_DATABASE_* (component vars, default port 5544) or the
            # ITRADER_DATABASE_URL verbatim escape hatch from env.
            backend = SqlBackend(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
            # Sync-durable working set (D-10): order create/terminalize persists
            # store-first (persist-then-acknowledge, Pitfall 8) via the CachedSql
            # wrapper composing the untouched Phase-3 ``SqlOrderStorage`` — its
            # ``rehydrate()`` rebuilds the open set on restart. Constructed EXPLICITLY
            # here (rather than via ``OrderStorageFactory.create('live')``) so the
            # store-first working-set wrapper is visible at the composition root.
            order_storage = CachedSqlOrderStorage(SqlOrderStorage(backend))
            # Retain the shared spine so stop() can dispose its connection pool (Pitfall 4 —
            # an undisposed engine leaks a socket / ResourceWarning under filterwarnings=error).
            self._system_db_backend = backend
            # Async/best-effort derived state (D-11): the signal store is live-driven
            # (``CachedSqlSignalStorage`` over the SAME spine, via the factory's 'live'
            # arm). Signals are advisory audit records, NOT the restart working set, and
            # are persisted on the engine (queue-draining) thread — never inside a
            # connector asyncio coroutine (Pitfall 9) — so a write can never stall the
            # loop. Keep-only-measured: no async buffering is built unless a live stall
            # is profiled (D-10).
            self._signal_store = SignalStorageFactory.create('live', backend=backend)

        # 05.2-05 (D-07): durable portfolio ledger wiring. When the Postgres spine
        # is present, construct the PortfolioHandler on the 'live' arm with the SAME
        # shared SqlBackend so each Portfolio threads it into its state storage —
        # the engine's own durable ledger becomes the source of portfolio truth
        # (rehydrate restores positions+cash on restart). No spine -> 'backtest'
        # in-memory (degrades cleanly, mirroring the order/signal fallback above).
        if self._system_db_backend is not None:
            self.portfolio_handler = PortfolioHandler(
                self.global_queue, environment='live',
                backend=self._system_db_backend)
        else:
            self.portfolio_handler = PortfolioHandler(self.global_queue)

        # 05.2-06 (D-10 / ARCH-4 Layer 2): durable halt-record store — the HALTED
        # latch that survives a process restart. Built over the SAME shared Postgres
        # spine when present (so a breaker halt persisted by halt() latches across a
        # supervised auto-restart), else None (in-memory fallback -> no durable record,
        # degrade cleanly like the order/signal/portfolio stores above). The SQL import
        # stays LAZY inside the spine-present arm so the backtest import path remains
        # SQLAlchemy-free (GATE-01 inertness). Offline tests inject an in-memory double
        # via attribute assignment.
        if self._system_db_backend is not None:
            from itrader.storage.halt_record_store import HaltRecordStore
            self._halt_record_store: Optional[Any] = HaltRecordStore(
                self._system_db_backend)
        else:
            self._halt_record_store = None

        # Execution handler constructed BEFORE the order handler so the
        # admission gate's commission estimator can adapt the simulated
        # exchange's fee model (Plan 05-06, D-04 — mode-agnostic wiring).
        self.execution_handler = ExecutionHandler(self.global_queue)

        # Commission estimator for the admission cash-reservation gate
        # (Plan 05-06, D-04): (quantity, price) -> Decimal adapter over the
        # simulated exchange's fee model; fee_model read at call time.
        simulated_exchange = self.execution_handler.exchanges.get('simulated')

        def _estimate_commission(quantity: Decimal, price: Decimal) -> Decimal:
            if not isinstance(simulated_exchange, SimulatedExchange):
                return Decimal("0")
            return simulated_exchange.fee_model.calculate_fee(
                quantity, price, side="buy", order_type="market")

        # Plan 02-03 (D-09/D-14): thread the portfolio's margin settings into the
        # order domain (mirrors compose_engine). With the default PortfolioConfig
        # (enable_margin=False / max_leverage=1) the order domain stays on the spot
        # byte-exact arm. The Universe is injected later via set_universe.
        _trading_rules = self.portfolio_handler.config_data.trading_rules

        # SHORT-01/D-07: thread the two shorts-enabling flags from trading_rules
        # into the registration gate (mirrors compose_engine). Constructed AFTER
        # the _trading_rules binding so the flags are available; both default off
        # → SMA_MACD (LONG_ONLY) stays admitted, oracle byte-exact.
        self.strategies_handler = StrategiesHandler(
            self.global_queue, self.feed, self._signal_store,
            allow_short_selling=_trading_rules.allow_short_selling,
            enable_margin=_trading_rules.enable_margin)

        self.order_handler = OrderHandler(self.global_queue, self.portfolio_handler, order_storage,
                                          commission_estimator=_estimate_commission,
                                          enable_margin=_trading_rules.enable_margin,
                                          portfolio_max_leverage=_trading_rules.max_leverage)
        # LIQ-03 (04-03): live-parity injection of the SAME order_storage into the
        # portfolio handler so a BAR-route liquidation forced-close registers its
        # real Order in the shared mirror the ReconcileManager reads (mirrors the
        # compose.py backtest wiring). Oracle-dark on the spot path.
        self.portfolio_handler.set_order_storage(order_storage)
        # 05-07 (RECON-05): retain the order working set so the two-sided restart
        # VenueReconciler can rehydrate it (INTENT truth) and reconcile against the
        # venue REST snapshot before RUNNING. Only the CachedSql* live store exposes
        # rehydrate(); the in-memory fallback does not, so the reconcile is guarded on
        # hasattr(rehydrate) at start().
        self._order_storage = order_storage
        # The TIME route's BarEvent source is the feed-owned factory
        # (Plan 07-02, D-20) — mirrors the backtest wiring shape; a real
        # live feed is owned by D-live.
        self.event_handler = EventHandler(
            self.strategies_handler,
            self.screeners_handler,
            self.portfolio_handler,
            self.order_handler,
            self.execution_handler,
            self.feed.generate_bar_event,
            self.global_queue
        )

        # ------------------------------------------------------------------
        # OKX live venue wiring (Plan 02-05, D-04 / CONN-04 — composition root).
        #
        # This is the ONLY place the concrete OkxConnector is constructed; the
        # three arms type against the LiveConnector Protocol and receive the
        # SESSION injected, never the concretion. The whole OKX stack is
        # LAZY-imported inside __init__ (mirrors the lazy SQL import above,
        # lines 141-150) so the BACKTEST import path stays async/ccxt/credential-
        # free — the hot-path inertness gate is proven by
        # tests/integration/test_okx_inertness.py.
        #
        # Stream startup (OkxExchange.connect() / OkxDataProvider.start_stream())
        # is a Phase 4/5 live-wiring step (02-03 SUMMARY boundary): this plan
        # constructs the connector, registers the 'okx' venue, and injects the
        # session into each arm. connector.disconnect() is wired into stop().
        # CR-02: the OKX arms are wired ONLY when the requested venue is OKX. For
        # any other venue (the default 'binance') the entire OKX stack stays
        # untouched — OkxSettings() (which hard-requires the OKX_API_* env triple)
        # is never constructed and the ccxt.pro/connector modules are never
        # imported — so constructing a LiveTradingSystem for a non-OKX venue needs
        # no OKX credentials and performs no OKX network I/O. The blocking network
        # connect (build client + load_markets) is DEFERRED out of the constructor
        # into start() so __init__ never performs blocking I/O and a connect
        # failure surfaces as SystemStatus.ERROR instead of raising out of a
        # constructor.
        self._okx_connector: Optional[Any] = None
        self._okx_exchange: Optional[Any] = None
        self._okx_data_provider: Optional[Any] = None
        self._venue_account: Optional[Any] = None
        # Phase 4 (D-02): paper venue sentinel — None for any non-paper venue so
        # run_paper_replay() can fail loudly if invoked on a mis-wired system.
        self._replay_provider: Optional[Any] = None
        if self.exchange == 'okx':
            from itrader.connectors import OkxConnector
            from itrader.config.okx_settings import OkxSettings
            from itrader.execution_handler.exchanges.okx import OkxExchange
            from itrader.price_handler.providers.okx_provider import OkxDataProvider
            from itrader.portfolio_handler.account import VenueAccount

            # Constructed ONCE (D-04). connect() is deferred to start() (CR-02).
            self._okx_connector = OkxConnector(OkxSettings())

            # Order arm: register under 'okx' — ExecutionHandler.on_order already
            # routes by event.exchange, and init_exchanges is UNCHANGED (the backtest
            # path stays OKX-free). Only THIS root imports the OkxConnector concretion.
            self._okx_exchange = OkxExchange(self.global_queue, self._okx_connector)
            self.execution_handler.exchanges['okx'] = self._okx_exchange

            # Data arm + venue account: injected the SAME session Protocol (D-04).
            # symbol/timeframe are the wiring defaults; Phase 3 (LiveBarFeed) owns the
            # real subscription config.
            self._okx_data_provider = OkxDataProvider(
                self._okx_connector, symbol=_OKX_STREAM_SYMBOL,
                timeframe=_OKX_STREAM_TIMEFRAME)
            # D-03 (V17-04, quote-wiring arm): thread the WIRED pair's real quote +
            # spot market-type into the VenueAccount so the settlement currency is the
            # traded pair's quote (USDC for BTC/USDC — never the USDT default) AND the
            # per-symbol position truth is DERIVED from total[BASE] (OKX spot reports
            # no position rows). Both are taken from the single wiring input
            # (_OKX_STREAM_SYMBOL): quote = right leg, symbol drives the base read.
            self._venue_account = VenueAccount(
                self._okx_connector,
                quote_currency=_OKX_STREAM_SYMBOL.split('/')[1],
                market_type='spot',
                symbol=_OKX_STREAM_SYMBOL,
            )

            # Phase 3 (D-01/D-13 provider->feed seam, FEED-05): inject the real OKX
            # provider into the LIVE feed via the PUBLIC setter — it assigns
            # self._provider, the PRIVATE attribute that warmup()/gap-backfill read.
            # A bare self.feed.provider = ... would create a dead attribute and leave
            # self._provider None -> AttributeError at warmup. Injection MUST precede
            # any warmup/start_stream call.
            self.feed.set_provider(self._okx_data_provider)
            # Wire the provider's confirm-gated closed-bar sink to the feed's
            # monotonic-guard ingest so every ClosedBar drives feed.update() -> BarEvent.
            self._okx_data_provider.set_bar_sink(self.feed.update)

            # 05-08 (RES-01/D-19/D-20): wire the reconnect-supervisor seams on BOTH
            # venue stream arms. A fatal connector error or an exhausted retry ceiling
            # escalates to the freeze-in-place halt (reason='connector-fatal', HALTED +
            # CRITICAL alert); a sustained disconnect pauses NEW submission and a
            # reconnect resumes it only after a fresh REST balance/position snapshot
            # (engine thread) — NOT a full two-sided reconcile (WR-04, see below).
            # The pause/resume callbacks fire from the connector loop thread, so they
            # only flip thread-safe flags — no blocking venue I/O there (Pitfall 9).
            #
            # 05.3-08 (D-21 / WR-02): the halt signal is _request_connector_halt (a
            # thread-safe FLAG setter), NOT halt() directly. halt() does a BLOCKING durable
            # record_halt SQL write; running it inline on the connector asyncio loop would
            # stall every stream sharing the loop (Pitfall 9). The engine thread drains the
            # flag via _maybe_halt_after_connector_fatal and runs the blocking halt off the
            # loop (winner-only, D-10 latch, V7 scrub preserved). Mirrors the pause/resume
            # flag handoff above.
            self._okx_exchange.set_halt_signal(self._request_connector_halt)
            self._okx_exchange.set_stream_state_listener(
                self._on_venue_stream_down, self._on_venue_stream_up)
            # 05.3-11 (D-26 / WR-02): arm the CONNECTOR's halt signal too. Without this
            # OkxConnector._on_task_done's `if self._halt_signal is not None:` guard is
            # always False, so a task dying OUTSIDE the exchange/provider stream supervisors
            # (a supervisor bug, or any coroutine not itself wrapped) would log-and-vanish
            # with no halt. Same flag-only callback the exchange/provider arms pass
            # (_request_connector_halt) — fail-safe: an unexpected dead task escalates to
            # an engine halt, never silently.
            self._okx_connector.set_halt_signal(self._request_connector_halt)
            self._okx_data_provider.set_halt_signal(self._request_connector_halt)
            self._okx_data_provider.set_stream_state_listener(
                self._on_venue_stream_down, self._on_venue_stream_up)

        elif self.exchange == 'paper':
            # ------------------------------------------------------------------
            # Paper venue wiring (Phase 4, D-02/D-04/D-05/D-06/D-09 — composition
            # root). The paper path REUSES the already-constructed 'simulated'
            # SimulatedExchange AS-IS (fetched at line 198): it already implements
            # AbstractExchange, holds no Account (D-06 — fills flow FillEvent ->
            # PortfolioHandler.on_fill), and ExecutionHandler already routes on_order
            # by event.exchange and fans on_market_data over self.exchanges.items(),
            # so the LiveBarFeed BarEvents reach it unchanged (D-04). There is NO new
            # exchange/adapter class and NO cost-model extraction: with one shared
            # fill-pricing implementation (the simulated exchange's, UNTOUCHED) there
            # is nothing to drift, so PAPER-02 is satisfied-by-reuse (D-05).
            #
            # The genuinely new surface is the OFFLINE, SYNCHRONOUS replay data arm:
            # a ReplayDataProvider replaying the golden CsvPriceStore as Decimal-edge
            # ClosedBar dicts through the SAME Phase-3 feed seam the OKX arm uses. The
            # import is LAZY inside this arm (mirrors the OKX/LiveBarFeed lazy imports)
            # so the BACKTEST import path never pulls it — the inertness gate (D-12).
            from itrader.price_handler.providers.replay_provider import ReplayDataProvider

            # D-18 (structural half): construct the replay store EXPLICITLY from the
            # shared parity window (PAPER_PARITY_START_DATE/END) instead of relying on
            # the CsvPriceStore class defaults happening to equal the parity window. The
            # paper store and the backtest comparand (test_paper_parity.py) now read ONE
            # source, so they can never silently desync (WR-02 coincidental parity gone).
            self._replay_provider = ReplayDataProvider(
                store=CsvPriceStore(
                    start_date=PAPER_PARITY_START_DATE, end_date=PAPER_PARITY_END_DATE),
                symbol=_PAPER_STREAM_SYMBOL, timeframe=_PAPER_STREAM_TIMEFRAME)
            # Inject the replay provider into the LIVE feed via the PUBLIC setter — it
            # assigns self._provider (the private attr warmup()/gap-backfill read); a
            # bare self.feed.provider = ... would leave self._provider None. Then wire
            # its sink to feed.update so each replayed ClosedBar drives
            # feed.update() -> BarEvent onto the queue (the real D-02 seam).
            self.feed.set_provider(self._replay_provider)
            self._replay_provider.set_bar_sink(self.feed.update)

        # D-17 (error-policy split, WR-04): the live publish-and-continue policy is NO
        # LONGER installed here. It is bound in start() — the daemon/live path ONLY — so
        # run_paper_replay() (which never calls start()) keeps the base fail-fast re-raise
        # (EventHandler._on_handler_error). A deterministic replay must abort LOUDLY on a
        # handler failure so the parity gate can never false-green on a swallowed error
        # (T-05-28); a live session, by contrast, can't abort on one handler error.

        # 05-04 (D-06): construct the pluggable CRITICAL/halt alert sink at the
        # composition root and inject it into the event handler, so a CRITICAL
        # ErrorEvent (a halt) reaches the operator egress. The sink binds ONLY the
        # declared ErrorEvent fields — no raw connector context — so no secret can
        # leak (Pitfall 16, T-05-01). This is the live-path wiring of the seam
        # 05-01 landed (the attribute defaults to None on the backtest path).
        self.event_handler._alert_sink = LogAlertSink()

        # 05-04 (D-01/D-02): wire the engine-thread drift-halt signal to the
        # freeze-in-place halt entrypoint so an unexplained beyond-band per-symbol
        # drift compare (PortfolioHandler, engine thread) halts the WHOLE engine.
        # Wired for every live venue; the compare only runs for a live
        # VenueAccount portfolio, so a non-OKX venue never triggers it.
        self.portfolio_handler.set_halt_signal(self.halt)

        self.logger.info('Live trading system initialized')
        self._update_status(SystemStatus.STOPPED)

    def _publish_and_continue(self, event, handler) -> None:
        """Live handler-failure policy (WR-05): publish an ErrorEvent, keep draining.

        Overrides the base EventHandler._on_handler_error (fail-fast re-raise).
        Invoked from EventHandler._dispatch when a handler raises; emits an
        ErrorEvent onto the queue (consumed by the ERROR route) and returns so
        the loop continues. Reads the active exception via sys.exc_info().
        """
        # IN-01: sys and ErrorEvent are now module-level imports (top of file).
        # The deferred-import rationale (keep the events package out of the
        # dispatcher's import graph) does not apply to THIS module — it already
        # imports EventType/TimeEvent/OrderEvent from the same package at module
        # scope, so re-importing on every handler failure on the hot error path
        # bought nothing.
        exc = sys.exc_info()[1]
        handler_name = getattr(handler, '__qualname__', repr(handler))
        self.logger.error(
            f'Handler {handler_name} failed on {getattr(event, "type", "UNKNOWN")}: {exc}'
        )
        with self._stats_lock:
            self._stats['errors_count'] += 1
        # WR-06: the ERROR route is TERMINAL. If the FAILING event is itself an
        # ErrorEvent, publishing a fresh ErrorEvent would route it straight back to
        # the same failing ERROR-route consumer (_log_error_event) — an unbounded
        # error->error feedback loop flooding the engine-thread queue (and, when the
        # failure repeats on the re-consumed event, livelocking a single
        # process_events() drain forever). The failure is already logged once above;
        # stop here rather than republish.
        if getattr(event, 'type', None) is EventType.ERROR:
            return
        self.global_queue.put(ErrorEvent(
            # WR-05: prefer the event's own business time; fall back to a
            # tz-aware UTC wall clock (never naive) to stay consistent with the
            # datetime.now(UTC) convention used by the portfolio handler.
            time=getattr(event, 'time', datetime.now(UTC)),
            source='live_trading_system',
            error_type=type(exc).__name__ if exc is not None else 'UnknownError',
            error_message=str(exc) if exc is not None else 'unknown handler failure',
            operation=handler_name,
            severity=ErrorSeverity.ERROR,
        ))
    
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
        symbol = _OKX_STREAM_SYMBOL
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
            self.halt('baseline-residual')
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
        ``run_paper_replay`` direct ``record_metrics`` per bar is the reference).

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
        """
        Initialize the live trading session by deriving membership and
        binding the feed's BarEvent factory.
        """
        self.logger.info('Initializing live trading session')

        try:
            # Membership derived at wiring time (M5-08, D-20) — mirrors
            # the backtest wiring shape (A4 minimal shim; D-live owns
            # real behavior).
            membership = derive_membership(
                self.strategies_handler.strategies,
                self.screeners_handler.get_screeners_universe()
            )
            # INST-02/INST-03 (D-08): mirror the backtest_runner Universe
            # construction/injection so the live path is Universe-aware and
            # consistent. price_data empty (declared symbols win; live venue
            # fetch is D-live). This module is mypy-deferred (ignore_errors) and
            # NOT exercised by the backtest byte-exact/determinism gates.
            instruments = derive_instruments(
                self.strategies_handler.strategies,
                self.screeners_handler.get_screeners_universe(),
                price_data={}
            )
            universe = Universe(members=membership, instrument_map=instruments)
            self.universe = universe
            simulated_exchange = self.execution_handler.exchanges.get('simulated')
            if isinstance(simulated_exchange, SimulatedExchange):
                simulated_exchange.set_universe(universe)
            # Plan 02-03 (Pitfall 1): mirror the exchange injection into the ORDER
            # domain so the admission leverage cap (D-04) can read
            # Instrument.max_leverage — same Trap-4 ordering as backtest_runner.
            self.order_handler.set_universe(universe)
            # Plan 02-05 (D-13): mirror the injection into the PORTFOLIO domain so
            # the maintenance_margin/margin_ratio read-model resolves each open
            # position's Instrument.maintenance_margin_rate — same Trap-4 ordering
            # as backtest_runner.
            self.portfolio_handler.set_universe(universe)
            # Phase 3 (D-13): register the raw-bar consumer sized to the max strategy
            # warmup so cache_capacity() derives to 100 (SMA_MACD) on the LIVE feed.
            # Without this the ring + warmup collapse to the newest-bar floor (1),
            # indicators never warm, and the oracle produces zero trades (Pitfall 1).
            self.feed.register_raw_bar_consumer(_LiveWarmupConsumer(
                required_history_depth=max(
                    (s.warmup for s in self.strategies_handler.strategies),
                    default=1)))
            self.feed.bind(self.global_queue, universe.members)

            # WR-03: the LIVE feed keys its ring on the streamed symbol string
            # (_OKX_STREAM_SYMBOL, stamped by the provider into ClosedBar['symbol']),
            # while window() is queried with the ticker drawn from universe.members.
            # If the two forms diverge (e.g. 'BTC/USDT' vs 'BTCUSD'), _find_ring raises
            # MissingPriceDataError only at the FIRST window() call — deep on the live
            # path. Assert the streamed symbol is a member at WIRING time so a ring-key
            # vs membership format mismatch fails loudly at startup instead. Guarded on
            # a non-empty membership: an empty universe (no strategy declared an
            # instrument) streams nothing and has no ticker to mismatch.
            if (self.exchange == 'okx' and universe.members
                    and _OKX_STREAM_SYMBOL not in universe.members):
                raise ConfigurationError(
                    config_key="okx_stream_symbol",
                    config_value=_OKX_STREAM_SYMBOL,
                    reason=(
                        f"streamed symbol is not a member of the universe "
                        f"{universe.members!r}; the feed ring key and the strategy's "
                        "window() ticker would mismatch (MissingPriceDataError at first "
                        "window()). Align the subscription symbol with the universe."))

            # Plan 06-05: the legacy set_symbols/set_timeframe calls died with
            # the price handler — the Store knows its symbols (store.symbols()).
            # Live symbol/timeframe subscription wiring is owned by D-live.

            self.logger.info('Live trading session initialized')
            
        except Exception as e:
            self.logger.error(f'Failed to initialize live session: {e}')
            self._update_status(SystemStatus.ERROR, str(e))
            raise
    
    def run_paper_replay(self) -> None:
        """Drive the golden dataset E2E through the live-paper mechanism, synchronously.

        The OFFLINE, single-thread paper driver (D-03): it replays the golden bars
        one-by-one through the real Phase-3 live seam (replay provider -> feed.update
        -> BarEvent -> queue) using the EXACT per-tick + run-end discipline of the
        backtest runner (backtest_runner._run_backtest) — but BAR-driven, not
        TimeGenerator-driven. There is NO daemon thread and NO start()/stop() call:
        this is the deterministic, CI-runnable path the 04-04 parity gate diffs
        against a fresh backtest.

        Determinism is by construction (D-09): the seeded random.Random already lives
        in the shared ExecutionHandler (config.performance.rng_seed=42) injected into
        the reused SimulatedExchange — identical to backtest — and every bar's time is
        the venue/CSV bar-open stamp the feed built (feed.newest_bar(...).time), never
        wall-clock.
        """
        if self._replay_provider is None:
            raise ConfigurationError(
                config_key="exchange",
                config_value=self.exchange,
                reason=(
                    "run_paper_replay() requires the paper venue (the replay provider "
                    "is not wired) — construct LiveTradingSystem(exchange='paper')."))

        # WR-02 (assertion half, no structural refactor): assert the replay store's
        # effective window/symbol equals the canonical golden window the backtest in
        # test_paper_parity.py is constructed with. The two paths are wired from
        # different sources (test literals vs CsvPriceStore class defaults) and only
        # happen to agree today — so a future default change or window drift fails
        # loudly HERE with a clear ConfigurationError instead of surfacing as a
        # confusing count-equality diff deep in the parity test.
        _store = self._replay_provider._store
        if (_store.start_date != _PAPER_EXPECTED_START
                or _store.end_date != _PAPER_EXPECTED_END
                or self._replay_provider._symbol != _PAPER_STREAM_SYMBOL):
            raise ConfigurationError(
                config_key="paper_replay_window",
                config_value=(
                    f"({_store.start_date}, {_store.end_date}, "
                    f"{self._replay_provider._symbol})"),
                reason=(
                    f"replay store window/symbol drifted from the backtest parity "
                    f"window: expected ({_PAPER_EXPECTED_START}, {_PAPER_EXPECTED_END}, "
                    f"{_PAPER_STREAM_SYMBOL}) but got ({_store.start_date}, "
                    f"{_store.end_date}, {self._replay_provider._symbol}). Align the "
                    "replay store window/symbol with the parity backtest."))

        # Step 1 — session init (ORDER-SENSITIVE): derive membership/instruments,
        # inject the Universe into the 'simulated' exchange + order/portfolio handlers,
        # register the _LiveWarmupConsumer that sizes cache_capacity() to the max
        # strategy warmup (100 for SMA_MACD — WITHOUT it the ring collapses to 1 and
        # the run yields zero trades, Pitfall 1), and bind(global_queue, members). The
        # OKX symbol-membership assertion inside is gated to exchange=='okx', so paper
        # skips it.
        self._initialize_live_session()

        # Step 2 — synchronous per-bar drive (mirror backtest_runner._run_backtest
        # 145-158, BAR-driven): per bar, in this order,
        #   (a) replay_bar -> registered sink self.feed.update -> BarEvent on queue,
        #   (b) process_events() drains BAR -> SIGNAL -> ORDER -> FILL in-thread,
        #   (c) a DIRECT record_metrics per active portfolio using the feed's own
        #       bar-open stamp (Trap 4 — backtest calls record_metrics directly, never
        #       via an event reroute). bar_time is tz-aware UTC bar-open (D-09).
        for cb in self._replay_provider.iter_closed_bars():
            self._replay_provider.replay_bar(cb)
            self.event_handler.process_events()
            newest = self.feed.newest_bar(_PAPER_STREAM_SYMBOL)
            if newest is None:
                continue
            # WR-03: only record when the feed's newest-DELIVERED bar IS the bar
            # replayed THIS iteration. If the LiveBarFeed monotonic guard dropped
            # this bar (stale/duplicate/off-grid/revision), newest holds the PREVIOUS
            # bar's stamp — recording it would re-stamp an already-recorded timestamp
            # (a duplicate/stale equity point). Compare the feed stamp against the
            # replayed bar-open (cb["ts"], epoch-ms) and skip on mismatch. On the
            # contiguous golden dataset no bar is ever dropped, so newest always
            # equals the replayed bar and every bar records exactly once (byte-exact).
            if int(newest.time.timestamp() * 1000) != cb["ts"]:
                continue
            bar_time = newest.time
            for portfolio in self.portfolio_handler.get_active_portfolios():
                portfolio.record_metrics(bar_time)

        # Step 3 — run-end time-in-force sweep (byte-exact parity with
        # backtest_runner 159-169): expire every still-resting order, then ONE final
        # process_events() drain clears them through the exchange. No record_metrics
        # after the sweep — the last per-bar record_metrics was the final equity point.
        self.order_handler.expire_all_resting()
        self.event_handler.process_events()

    def _event_processing_loop(self):
        """
        The main event processing loop that runs in a separate thread.
        Continuously processes events from the global queue until stopped.
        """
        self.logger.info('Starting event processing loop')
        self._update_status(SystemStatus.RUNNING)
        
        with self._stats_lock:
            self._stats['uptime_start'] = datetime.now(UTC).isoformat()
        
        last_event_time = datetime.now(UTC)

        while not self._stop_event.is_set():
            try:
                # Check for events in the queue with timeout
                try:
                    event = self.global_queue.get(timeout=self.queue_timeout)
                    last_event_time = datetime.now(UTC)

                    # WR-09: dispatch the dequeued event DIRECTLY through the
                    # event handler's routing. The previous get -> put-back ->
                    # process_events() pattern re-appended the event behind
                    # anything already queued, breaking the single-FIFO-queue
                    # ordering contract (e.g. a BAR processed before its PING).
                    # The task_done() bookkeeping is dropped with it: nothing
                    # joins this queue, and the put-back/internal gets left
                    # unfinished_tasks permanently drifting.
                    # 05-04 (D-02): route through the freeze-in-place halt gate so
                    # a HALTED engine suppresses NEW order submission (SIGNAL/ORDER)
                    # while BAR/FILL/ERROR streaming + reconciling + persisting
                    # continue to drain.
                    self._dispatch_live(event)

                    # Update statistics
                    self._update_stats(event.type.name if hasattr(event, 'type') else 'UNKNOWN')

                    # 05-06 (D-16 / WR-01): record the per-bar equity curve keyed on
                    # EventType.BAR (the async/best-effort path). LiveBarFeed emits only
                    # BarEvent, so the old TIME key never fired live — see
                    # _record_bar_metrics. record_metrics lives on Portfolio, not
                    # PortfolioHandler, so the helper iterates the active portfolios.
                    self._record_bar_metrics(event)

                    # 05-08 (D-19): resume submission on the ENGINE thread once a venue
                    # stream reconnected — a fresh REST balance/position snapshot then clears the
                    # pause. The connector-loop reconnect callback only flagged it here;
                    # the blocking snapshot runs on this thread (Pitfall 9).
                    self._maybe_resume_after_reconnect()

                    # 05.3-08 (D-21 / WR-02): drain a pending connector-fatal escalation on
                    # the ENGINE thread — the blocking durable record_halt write runs here,
                    # never on the connector asyncio loop (Pitfall 9). Flag-only on the loop.
                    self._maybe_halt_after_connector_fatal()

                except queue.Empty:
                    # 05-08 (D-19): drain a pending resume even when the queue is idle —
                    # a reconnect during a quiet spell must still resume submission.
                    self._maybe_resume_after_reconnect()

                    # 05.3-08 (D-21 / WR-02): drain a pending connector-fatal even when the
                    # queue is idle — a fatal during a quiet spell must still halt (off-loop).
                    self._maybe_halt_after_connector_fatal()

                    # No events in queue, check if we've been idle too long
                    current_time = datetime.now(UTC)
                    idle_time = (current_time - last_event_time).total_seconds()

                    if idle_time > self.max_idle_time:
                        self.logger.warning(f'No events received for {idle_time:.1f} seconds')
                        last_event_time = current_time

                    continue
                    
            except Exception as e:
                self.logger.error(f'Error in event processing loop: {e}')
                with self._stats_lock:
                    self._stats['errors_count'] += 1
                # Continue processing even if there's an error
                continue
        
        self.logger.info('Event processing loop stopped')
    
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
            # hardening); the deterministic run_paper_replay() driver never reaches this
            # bind, so it keeps the base fail-fast re-raise so a handler failure aborts
            # the replay loudly and the parity gate can't false-green (T-05-28).
            self.event_handler._on_handler_error = self._publish_and_continue  # type: ignore[method-assign]

            # Initialize the live session
            self._initialize_live_session()

            # CR-02: perform the OKX connector's network connect HERE (build client
            # + load_markets on the daemon-thread loop), deferred out of __init__ so
            # construction stays I/O-free. A failure propagates to the except below,
            # which sets SystemStatus.ERROR and returns False — never an unhandled
            # raise. Only wired when the requested venue is OKX (connector is None
            # otherwise). stop() tears the connector down unconditionally (CR-01).
            if self._okx_connector is not None:
                self._okx_connector.connect()

            # Phase 3 (FEED-05, RESEARCH Thread hand-off): warm the LIVE feed BEFORE
            # the socket goes live so every update() stays on the one thread until the
            # stream starts (single-writer ring/guard). Gated to the OKX arm — a
            # non-OKX venue has no provider, so the None provider is never dereferenced
            # (mirrors the CR-02 venue-guard). Warmup MUST precede start_stream.
            if self.exchange == 'okx' and self._okx_data_provider is not None:
                self.feed.warmup(_OKX_STREAM_SYMBOL, _OKX_STREAM_TIMEFRAME)
                self._okx_data_provider.start_stream()

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
            if self.exchange == 'okx' and self._okx_exchange is not None:
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

            if self.exchange == 'okx' and self._venue_account is not None:
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

            # Reset the stop event and start the processing thread
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._event_processing_loop,
                name='LiveTradingSystem-EventProcessor',
                daemon=True
            )
            
            self._running = True
            self._thread.start()
            
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
        connector = getattr(self, '_okx_connector', None)
        try:
            if not self._running:
                self.logger.warning('Live trading system is not running')
                return True

            self.logger.info('Stopping live trading system')
            self._update_status(SystemStatus.STOPPING)

            # Signal the thread to stop
            self._stop_event.set()

            # Wait for the thread to finish
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout)

                if self._thread.is_alive():
                    self.logger.warning(f'Thread did not stop within {timeout} seconds')
                    self._update_status(SystemStatus.ERROR, 'Failed to stop gracefully')
                    return False
                else:
                    self.logger.info('Event processing thread stopped')

            self._running = False
            self._thread = None
            self._update_status(SystemStatus.STOPPED)

            self.logger.info('Live trading system stopped')
            return True
        finally:
            # Plan 02-05 (D-04 shutdown): tear down the OKX connector — cancel every
            # spawned stream task and close the ccxt/native sessions so no leaked
            # socket / ResourceWarning survives across runs.
            if connector is not None:
                try:
                    connector.disconnect()
                except Exception as e:
                    self.logger.error(f'Error disconnecting OKX connector: {e}')
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
        return self._running and self._thread is not None and self._thread.is_alive()
    
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
                'thread_alive': self._thread.is_alive() if self._thread else False,
                'thread_name': self._thread.name if self._thread else None,
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

        D-18 (V17-16, HIGH — ASVS V4/V5): ``add_event`` is the engine's PUBLIC external/web
        surface. A raw ``OrderEvent`` here would reach the execution queue with NO validation,
        sizing, cash reservation or order-mirror engagement — an external caller could inject
        an arbitrary order that bypasses every admission control (elevation-of-privilege /
        input-validation defect). Raw ``EventType.ORDER`` injection is therefore REFUSED.

        The sanctioned external-order path is SIGNAL-form entry: submit a ``SignalEvent`` (or
        call the order domain directly), which routes through ``OrderHandler.on_signal`` ->
        ``AdmissionManager`` so validation + sizing + reservation + mirror engage before any
        ``OrderEvent`` is emitted. The internal order flow is UNAFFECTED — handlers emit
        ``OrderEvent``s by putting them on ``global_queue`` directly, never through ``add_event``.

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

        # D-18: reject raw ORDER injection. Only ORDER events are blocked (a narrow gate);
        # every non-ORDER event (the sanctioned SIGNAL-form entry included) enqueues normally.
        if getattr(event, 'type', None) is EventType.ORDER:
            self.logger.warning(
                'Rejected raw ORDER injection via add_event (D-18/V17-16) — external orders '
                'must route through the admission pipeline (signal-form entry), not the '
                'live queue directly')
            return False

        try:
            self.global_queue.put(event)
            return True
        except Exception as e:
            self.logger.error(f'Failed to add event to queue: {e}')
            return False
    

    
    def get_statistics(self):
        """
        Get current trading statistics.
        
        Returns
        -------
        dict or None
            Trading statistics if available
        """
        # The legacy StatisticsReporting subsystem was deleted with the M5-07
        # reporting rework (plan 07-03); live-mode statistics are D-live scope
        # and gain no metrics printout here (A4 — keep the module importing).
        self.logger.warning('Live statistics unavailable: legacy reporting deleted (D-live scope)')
        return None
    
    def print_status(self):
        """
        Print the current status of the live trading system.
        """
        status_info = self.get_status()
        
        print(f"Live Trading System Status: {status_info['status'].upper()}")
        print(f"Queue Size: {status_info['queue_size']}")
        print(f"Exchange: {status_info['exchange']}")
        print(f"Events Processed: {status_info['statistics']['events_processed']}")
        print(f"Orders Executed: {status_info['statistics']['orders_executed']}")
        print(f"Errors Count: {status_info['statistics']['errors_count']}")
        
        if status_info['is_running']:
            print(f"Thread Name: {status_info['thread_name']}")
            print(f"Thread Alive: {status_info['thread_alive']}")
            if status_info['statistics']['uptime_seconds']:
                print(f"Uptime: {status_info['statistics']['uptime_seconds']:.1f} seconds")
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
