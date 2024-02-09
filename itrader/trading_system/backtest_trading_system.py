from __future__ import print_function
import os
from datetime import datetime, timedelta
import threading

import queue
import pandas as pd
from itrader.events_handler.event import EventType

from itrader.engine.event_driven import EventEngine
from itrader.price_handler.CCXT_data_provider import CCXT_data_provider
from itrader.universe.dynamic import DynamicUniverse
from itrader.strategy.strategies_handler import StrategiesHandler
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.trading_system.simulation.ping_generator import PingGenerator
from itrader.reporting.statistics import StatisticsReporting
from itrader.telegram_bot.telegram_bot import TelegramBot



from sqlalchemy import create_engine
from sqlalchemy_utils import database_exists, create_database

import logging


### Set up logging system
# Remove old log file
if os.path.exists('info.log'):
    os.remove('info.log')
    print('.log file removed')
    

logger = logging.getLogger('TradingSystem')
logger.setLevel(logging.DEBUG)  # Overall minimum logging level

stream_handler = logging.StreamHandler()  # Configure the logging messages displayed in the Terminal
formatter = logging.Formatter('%(levelname)s | %(message)s') # %(asctime)s 
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.DEBUG)  # Minimum logging level for the StreamHandler

# file_handler = logging.FileHandler('info.log')  # Configure the logging messages written to a file
# file_handler.setFormatter(formatter)
# file_handler.setLevel(logging.DEBUG)  # Minimum logging level for the FileHandler

logger.addHandler(stream_handler)
#logger.addHandler(file_handler)



class TradingSystem(object):
    """
    Enscapsulates the settings and components for
    carrying out either a backtest or live trading session.
    """
    def __init__(
        self, exchange='binance', universe = 'static',
        init_cash = None, 
        start_date=None, end_date='', 
        session_type='backtest',
        price_handler=None,
        engine_logger='internal',
        stats_report=None,
        benchmark=None,
        to_sql = False,
        telegram_bot = None
    ):
        """
        Set up the backtest variables according to
        what has been passed in.
        """
        self.config = None  #TODO: in futuro vedi se ho bisogno di un setting file generale
        self.session_type = session_type
        self.exchange = exchange
        self.uni_type = universe

        self.init_cash = init_cash
        self.start_date = start_date
        self.end_date = ''
        self.to_sql = to_sql

        self.global_queue = None
        self.engine_queue = None
        self.price_handler = price_handler
        self.universe = None
        self.strategies_handler = None
        self.screeners_handler = None
        self.engine = None
        self.ping = None
        self.reporting = None
        self.telegram_bot: TelegramBot = telegram_bot

        self._system_thread = None
        self._streaming_thread = None
        self._is_running = False
        self.continue_live = True
        self.engine_logger = engine_logger

        self.stats_report = stats_report
        self.benchmark = benchmark
        
        self._initialize_trading_system()
        self.cur_time = None

    def add_strategy(self, strategy, strategy_setting):
            """
            Add a strategy module to the list of strategies of the trading system

            Parameters
            ----------
            strategy : `object`
                Strategy instance.
            strategy_setting: `dict`
                Dictionary with all strategy setting and portfolio id
                where to execute the transactions of the strategy.
            """
            # NEW
            strategy.global_queue = self.global_queue

            self.strategies_handler._add_strategy(strategy, strategy_setting)
            self.engine.order_handler.set_strategy_setting(strategy.strategy_id, strategy.tf_delta, strategy_setting)

    def add_screener(self, screener):
        """
        Add a screener module to the list of strategies of the trading system

        Parameters
        ----------
        screener : `object`
            Svreener instance.
        screener_setting: `dict`
            Dictionary with all strategy setting and portfolio id
            where to execute the transactions of the strategy.
        """
        self.screeners_handler._add_screener(screener)


    def _initialize_trading_system(self):
        """
        Initialises the necessary modules used
        within the session.
        """
        # Define the global queue
        if self.global_queue is None:
            self.global_queue = queue.Queue()
        
        # Define the engine queue
        if self.engine_queue is None:
            self.engine_queue = queue.Queue()

        # Define  price handler
        if self.price_handler is None:
            self.price_handler = CCXT_data_provider(self.exchange, start_dt= self.start_date, 
                                                    end_dt='', global_queue=self.global_queue)

        # Define trading engine module
        self.engine = EventEngine(self.price_handler, self.global_queue, self.session_type, self.exchange, self.init_cash,
                                  to_sql=self.to_sql, telegram_bot = self.telegram_bot)

        # Define the Universe module
        self.universe = DynamicUniverse(self.price_handler, self.global_queue, self.uni_type)

        # Define the strategies module
        self.strategies_handler = StrategiesHandler(self.global_queue, self.price_handler)

        # Define the screeners handler
        self.screeners_handler = ScreenersHandler(self.global_queue, self.price_handler, self.telegram_bot)

        # Define ping generator
        self.ping = PingGenerator()

        # Statistical reporting module
        self.reporting = StatisticsReporting(self.engine.engine_logger)
        #self.reporting.prices = self.price_handler.prices

    def _process_ping(self):
        """
        When a ping is generated from the ping simulator or the live
        price streamer, execute it.
        """

        while not self.global_queue.empty() :
            
            try:
                event = self.global_queue.get(False)
                time = event.time
            except queue.Empty:
                event = None
            if event.type == EventType.PING:
                self.universe.generate_bars(event)
            elif event.type == EventType.BAR:
                logger.info('UNIVERSE - New bar %s', event.time)
                self.engine.portfolio_handler.update_portfolio_value(event)
                self.engine.order_handler.check_pending_orders(event)
                #self.engine.order_handler.check_max_duration(event)
                self.engine._process_signal() # Process eventual stop or limit order signal
                if self.uni_type == 'dynamic':
                    self.screeners_handler.apply_screeners(event)
                    # TEMPORARY: al momento non considera lo screener
                    self.strategies_handler.assign_symbol(self.screeners_handler.get_proposed_symbols())
                    ###
                    self.universe.assign_assets(self._get_assets())
                    event = self.universe.update_bars(event)

                self.strategies_handler.calculate_signals(event)
            elif event.type == EventType.SIGNAL:
                self.engine.engine_queue.put(event)
                self.engine._process_signal()
            else:
                raise NotImplemented('Unsupported event type %s' % event.type)
            #self.engine.portfolio_handler.record_portfolios_metrics(time)

    def _run_backtest(self):
        """
        Carries out an for-loop that polls the
        events queue and directs each event to either the
        strategy component of the execution handler. The
        loop continue until the ping series is completed
        """

        logger.info('    RUNNING BACKTEST   ')

        for ping_event in self.ping:
            self.global_queue.put(ping_event)
            self._process_ping()
            self.engine.portfolio_handler.record_portfolios_metrics(ping_event.time)
            
        logger.info('    BACKTEST COMPLETED   ')
    
    def _run_live_session(self):
        logger.info('TRADING SYSTEM: Live session started')

        while self._is_running:
            if not self.global_queue.empty():
                time = self.global_queue.queue[0].time
                self._process_ping()
                self.engine.portfolio_handler.record_portfolios_metrics(time)
    
    def stop_live_session(self):
        self.price_handler.live_data.stop_streaming()
        self._is_running = False

        # Send confirmation message
        text = f' -- System --\n    System stopped'
        self.telegram_bot.send_message(text = text)

        logger.info('TRADING SYSTEM: Live session ended')
    
    def _get_traded_symbols(self):
        sym1 = self.strategies_handler.get_traded_symbols()
        sym2 = self.screeners_handler.get_screener_universe()
        return (sym1+sym2)
    
    def _get_assets(self):
        """
        Return a list of string with the tickers traded from the 
        strategies and the opened positions in the portfolio
        """
        sym1 = self.engine._get_opened_positions()
        sym2 = self.strategies_handler.get_traded_symbols()
        unique_assetts = list(set(sym1+sym2))
        return unique_assetts
    
    def _initialise_backtest_session(self):
        """
        Load the data in the price handler and define the pings vector
        for the for-loop iteration.
        """
        logger.info('TRADING SYSTEM: Initialising backtest session')

        self.universe.assign_assets(self.strategies_handler.get_traded_symbols())
        self.price_handler.set_symbols(self._get_traded_symbols())
        self.price_handler.set_timeframe(self.strategies_handler.min_timeframe[1])
        self.price_handler.download_data()
        self.ping.set_dates(next(iter(self.price_handler.prices.items()))[1].index)
        self.reporting.prices = self.price_handler.prices
    
    def _initialise_live_session(self):
        """
        Start streaming the data from a websocket and proces the data 
        at every closed timeframe.
        """
        logger.info('TRADING SYSTEM: Initialising live session')

        self.universe.assign_assets(self.strategies_handler.get_traded_symbols())
        self.price_handler.set_symbols(self.strategies_handler.get_traded_symbols())
        self.price_handler.set_timeframe(self.strategies_handler.min_timeframe[1])
        #self.price_handler.live_data.bar_length = self.strategies_handler.min_timeframe[1]

        # Download the last N bars
        start_dt = pd.to_datetime(datetime.utcnow()) - self.strategies_handler.min_timeframe[0]*2200 
        self.price_handler.start_date = start_dt.strftime("%Y-%m-%d %H:%M")
        self.price_handler.download_data()

        


    def start(self, print_summary=False):
        """
        Runs either a backtest or live session, and outputs performance when complete.
        """
        if self.session_type == 'backtest':
            self._initialise_backtest_session()
            self._run_backtest()

            if print_summary:
                self.reporting.calculate_statistics()
                self.reporting.print_summary()

        elif self.session_type == 'live':
            self._initialise_live_session()
            self._system_thread = threading.Thread(target=self._run_live_session)
            self._streaming_thread = threading.Thread(target=self.price_handler.live_data.stream_data)

            # Send confirmation message
            text = f' -- System --\n    System started'
            self.telegram_bot.send_message(text = text)

            # Start the engine and live data stream threads
            self._is_running = True
            self._system_thread.start()
            self._streaming_thread.start()
            
        else:
            logger.warning('Session type %s not supported', self.session_type)

        # Close the logger file
        #file_handler.close()
        # Close the SQL connection
        #self.sql_engine.dispose() # Close all checked in sessions
