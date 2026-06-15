import os
import queue
import sys
import threading
import time
import json
from datetime import datetime, UTC
from decimal import Decimal
from typing import Optional, Dict, Any, Callable

from itrader.core.enums import ErrorSeverity, SystemStatus
from itrader.events_handler.full_event_handler import EventHandler
from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.feed.bar_feed import BacktestBarFeed
from itrader.price_handler.store.csv_store import CsvPriceStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.strategy_handler.storage import SignalStorageFactory
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.universe import Universe, derive_instruments, derive_membership

from itrader.logger import get_itrader_logger
from itrader.events_handler.events import EventType, TimeEvent, OrderEvent, ErrorEvent

# Live system DB URL (D-live deferred). The flat config.py shadow + its ``Config`` class
# (which read SYSTEM_DB_URL from env) were deleted in the M2b config collapse; read the
# env var directly here. A future D-live wiring would source this from Settings.
# WR-10: no hardcoded credential fallback — an unset SYSTEM_DB_URL yields ""
# and the system falls back to in-memory order storage with a loud warning.
_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", "")


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
        self.feed = BacktestBarFeed(self.store, to_timedelta('1d'))
        # Signal-store sink (Plan 05-03, D-07/D-12): no persistent backend in
        # v1.1, so mirror the in-memory order-storage fallback above — captured
        # signals will NOT survive a restart until a persistent backend lands.
        # WR-03: retain the store on self and expose accessors (mirroring the
        # backtest system) — a local variable would leave every captured
        # SignalRecord permanently unreachable (a write-only accumulation).
        self._signal_store = SignalStorageFactory.create('backtest')
        self.strategies_handler = StrategiesHandler(self.global_queue, self.feed, self._signal_store)
        self.screeners_handler = ScreenersHandler(self.global_queue, self.feed)
        self.portfolio_handler = PortfolioHandler(self.global_queue)
        # WR-04: declare the universe attribute as a clean "not yet wired"
        # sentinel here, mirroring Engine.universe: Optional[Universe] = None on
        # the backtest path. It is populated in _initialize_live_session (from
        # start()); without this, any pre-start read raises AttributeError
        # instead of returning None — an attribute-existence trap for D-live.
        self.universe: Optional[Universe] = None
        
        # Create order storage for live trading (PostgreSQL)
        # Note: For now using in-memory until Phase 2 is complete
        if not _SYSTEM_DB_URL:
            # WR-10: fail loudly into the in-memory fallback instead of
            # shipping a default connection string with embedded credentials.
            self.logger.warning(
                "SYSTEM_DB_URL is not set — using in-memory order storage "
                "(orders will NOT survive a restart)"
            )
            order_storage = OrderStorageFactory.create('backtest')
        else:
            try:
                order_storage = OrderStorageFactory.create('live', _SYSTEM_DB_URL)
            except NotImplementedError:
                # Fallback to in-memory during Phase 1
                self.logger.warning("PostgreSQL storage not yet implemented, using in-memory storage")
                order_storage = OrderStorageFactory.create('backtest')
        
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

        self.order_handler = OrderHandler(self.global_queue, self.portfolio_handler, order_storage,
                                          commission_estimator=_estimate_commission)
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
        
        # WR-05: install the documented live error policy (publish-and-continue).
        # The base _on_handler_error re-raises (backtest fail-fast); the live
        # system is documented to override THIS method so _dispatch's existing
        # error routing emits an ErrorEvent and keeps draining instead of
        # aborting. Binding it here (rather than swallowing in the loop) means a
        # failed handler queues an ErrorEvent for the ERROR-route / status
        # consumers instead of becoming an invisible log line + counter.
        self.event_handler._on_handler_error = self._publish_and_continue  # type: ignore[method-assign]

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
    
    def _update_status(self, new_status: SystemStatus, error_msg: Optional[str] = None):
        """Update system status and notify via callback if available."""
        with self._status_lock:
            old_status = self._status
            self._status = new_status
            if error_msg:
                self._last_error = error_msg
        
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
                
                # TODO: Add more specific event type handling if needed like 'ORDER_FILLED' 'ORDER_CREATED' etc...
                if event_type == 'ORDER':
                    self._stats['orders_executed'] += 1
    
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
            self.feed.bind(self.global_queue, universe.members)

            # Plan 06-05: the legacy set_symbols/set_timeframe calls died with
            # the price handler — the Store knows its symbols (store.symbols()).
            # Live symbol/timeframe subscription wiring is owned by D-live.

            self.logger.info('Live trading session initialized')
            
        except Exception as e:
            self.logger.error(f'Failed to initialize live session: {e}')
            self._update_status(SystemStatus.ERROR, str(e))
            raise
    
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
                    self.event_handler._dispatch(event)

                    # Update statistics
                    self._update_stats(event.type.name if hasattr(event, 'type') else 'UNKNOWN')

                    # Record portfolio metrics if it's a TIME event.
                    # CR-02: record_metrics lives on Portfolio, not
                    # PortfolioHandler — iterate the active portfolios exactly
                    # like the backtest path does.
                    if hasattr(event, 'type') and event.type == EventType.TIME:
                        for portfolio in self.portfolio_handler.get_active_portfolios():
                            portfolio.record_metrics(event.time)

                except queue.Empty:
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
            # Initialize the live session
            self._initialize_live_session()
            
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
