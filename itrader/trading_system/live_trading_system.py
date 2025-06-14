import queue
import threading
import time
from datetime import datetime
from typing import Optional

from itrader.events_handler.full_event_handler import EventHandler
from itrader.price_handler.data_provider import PriceHandler
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.universe.dynamic import DynamicUniverse
from itrader.reporting.statistics import StatisticsReporting

from itrader.logger import get_itrader_logger
from itrader.events_handler.event import EventType


class LiveTradingSystem:
    """
    Encapsulates the settings and components for carrying out live trading.
    Processes events from a global queue in a separate thread instead of 
    using a for-loop like the backtest system.
    """
    
    def __init__(
        self, 
        exchange='binance',
        to_sql=False,
        queue_timeout=1.0,
        max_idle_time=300.0  # 5 minutes max idle time
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
        """
        self.logger = get_itrader_logger().bind(component="LiveTradingSystem")
        self.exchange = exchange
        self.to_sql = to_sql
        self.queue_timeout = queue_timeout
        self.max_idle_time = max_idle_time
        
        # Threading control
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Initialize components
        self.global_queue = queue.Queue()
        self.price_handler = PriceHandler(self.exchange, [], '', '')  # Empty timeframe and start_dt for live trading
        self.universe = DynamicUniverse(self.price_handler, self.global_queue)
        self.strategies_handler = StrategiesHandler(self.global_queue, self.price_handler)
        self.screeners_handler = ScreenersHandler(self.global_queue, self.price_handler)
        self.portfolio_handler = PortfolioHandler(self.global_queue)
        self.order_handler = OrderHandler(self.global_queue, self.portfolio_handler)
        self.execution_handler = ExecutionHandler(self.global_queue)
        self.reporting = StatisticsReporting(
            self.portfolio_handler,
            self.price_handler
        )
        self.event_handler = EventHandler(
            self.strategies_handler,
            self.screeners_handler,
            self.portfolio_handler,
            self.order_handler,
            self.execution_handler,
            self.universe,
            self.global_queue
        )
        
        self.logger.info('Live trading system initialized')
    
    def _initialize_live_session(self):
        """
        Initialize the live trading session by setting up the universe,
        price handler symbols, and other necessary components.
        """
        self.logger.info('Initializing live trading session')
        
        # Initialize universe with strategies and screeners
        self.universe.init_universe(
            self.strategies_handler.get_strategies_universe(),
            self.screeners_handler.get_screeners_universe()
        )
        
        # Set up price handler with symbols and timeframes
        self.price_handler.set_symbols(self.universe.get_full_universe())
        self.price_handler.set_timeframe(
            self.strategies_handler.min_timeframe,
            self.screeners_handler.min_timeframe
        )
        
        self.logger.info('Live trading session initialized')
    
    def _event_processing_loop(self):
        """
        The main event processing loop that runs in a separate thread.
        Continuously processes events from the global queue until stopped.
        """
        self.logger.info('Starting event processing loop')
        last_event_time = datetime.now()
        
        while not self._stop_event.is_set():
            try:
                # Check for events in the queue with timeout
                try:
                    event = self.global_queue.get(timeout=self.queue_timeout)
                    last_event_time = datetime.now()
                    
                    # Process the event through the event handler
                    self.global_queue.put(event)  # Put it back for processing
                    self.event_handler.process_events()
                    
                    # Record portfolio metrics if it's a PING event
                    if event.type == EventType.PING:
                        self.portfolio_handler.record_metrics(event.time)
                    
                    self.global_queue.task_done()
                    
                except queue.Empty:
                    # No events in queue, check if we've been idle too long
                    current_time = datetime.now()
                    idle_time = (current_time - last_event_time).total_seconds()
                    
                    if idle_time > self.max_idle_time:
                        self.logger.warning(f'No events received for {idle_time:.1f} seconds')
                        last_event_time = current_time
                    
                    continue
                    
            except Exception as e:
                self.logger.error(f'Error in event processing loop: {e}')
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
            return
        
        self.logger.info('Starting live trading system')
        
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
            return
        
        self.logger.info('Stopping live trading system')
        
        # Signal the thread to stop
        self._stop_event.set()
        
        # Wait for the thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            
            if self._thread.is_alive():
                self.logger.warning(f'Thread did not stop within {timeout} seconds')
            else:
                self.logger.info('Event processing thread stopped')
        
        self._running = False
        self._thread = None
        
        self.logger.info('Live trading system stopped')
    
    def is_running(self) -> bool:
        """
        Check if the live trading system is currently running.
        
        Returns
        -------
        bool
            True if the system is running, False otherwise
        """
        return self._running and self._thread is not None and self._thread.is_alive()
    
    def get_queue_size(self) -> int:
        """
        Get the current size of the global event queue.
        
        Returns
        -------
        int
            Number of events in the queue
        """
        return self.global_queue.qsize()
    
    def add_event(self, event):
        """
        Add an event to the global queue for processing.
        
        Parameters
        ----------
        event
            The event to add to the queue
        """
        if not self._running:
            self.logger.warning('Cannot add event: Live trading system is not running')
            return
        
        self.global_queue.put(event)
    
    def get_statistics(self):
        """
        Get current trading statistics.
        
        Returns
        -------
        dict or None
            Trading statistics if available
        """
        try:
            self.reporting.calculate_statistics()
            return self.reporting.get_statistics()  # Assuming this method exists
        except Exception as e:
            self.logger.error(f'Error getting statistics: {e}')
            return None
    
    def print_status(self):
        """
        Print the current status of the live trading system.
        """
        status = "RUNNING" if self.is_running() else "STOPPED"
        queue_size = self.get_queue_size()
        
        print(f"Live Trading System Status: {status}")
        print(f"Queue Size: {queue_size}")
        print(f"Exchange: {self.exchange}")
        
        if self.is_running():
            print(f"Thread Name: {self._thread.name}")
            print(f"Thread Alive: {self._thread.is_alive()}")
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
