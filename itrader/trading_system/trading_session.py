from __future__ import print_function
import os
from datetime import datetime
from .compat import queue
from .event import EventType
from .price_handler.yahoo_daily_csv_bar import YahooDailyCsvBarPriceHandler
from .price_parser import PriceParser
from .position_sizer.fixed import FixedPositionSizer
from .risk_manager.advanced_risk_manager import StopLossRiskManager
from .portfolio_handler import PortfolioHandler
from .compliance.SqlCompliance import SqlCompliance
from .execution_handler.ib_simulated import IBSimulatedExecutionHandler
from .statistics.reporting import StatisticsReporting

from sqlalchemy import create_engine
from sqlalchemy_utils import database_exists, create_database

import logging
import sys
""" Non funziona con jupyter notebook
logging.basicConfig(format='%(levelname)s | %(message)s',
                    level=logging.DEBUG, stream=sys.stdout)
"""

### Set up logging system
# Remove old log file
if os.path.exists('info.log'):
    os.remove('info.log')
else:
    print("The file does not exist")

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)  # Overall minimum logging level

stream_handler = logging.StreamHandler()  # Configure the logging messages displayed in the Terminal
formatter = logging.Formatter('%(levelname)s | %(message)s') # %(asctime)s 
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.INFO)  # Minimum logging level for the StreamHandler

file_handler = logging.FileHandler('info.log')  # Configure the logging messages written to a file
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)  # Minimum logging level for the FileHandler

logger.addHandler(stream_handler)
logger.addHandler(file_handler)



class TradingSession(object):
    """
    Enscapsulates the settings and components for
    carrying out either a backtest or live trading session.
    """
    def __init__(
        self, config, strategy, tickers,
        cash, start_date, end_date, 
        session_type="backtest", events_queue=None, end_session_time=None,
        price_handler=None, portfolio_handler=None,
        compliance=None, position_sizer=None,
        execution_handler=None, risk_manager=None,
        order_handler = None,
        statistics=None, sentiment_handler=None,
        benchmark=None, stop_loss = False, take_profit = False
    ):
        """
        Set up the backtest variables according to
        what has been passed in.
        """
        self.config = config
        self.strategy = strategy
        self.tickers = tickers
        self.cash = PriceParser.parse(cash)
        self.start_date = start_date
        self.end_date = end_date
        self.events_queue = events_queue
        self.price_handler = price_handler
        self.portfolio_handler = portfolio_handler
        self.compliance = compliance
        self.execution_handler = execution_handler
        self.position_sizer = position_sizer
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.risk_manager = risk_manager
        self.order_handler = order_handler
        self.statistics = statistics
        self.sentiment_handler = sentiment_handler
        self.benchmark = benchmark
        self.session_type = session_type
        self.engine = self._create_engine()
        self._config_session()
        self.cur_time = None

        if self.session_type == "live":
            if self.end_session_time is None:
                raise Exception("Must specify an end_session_time when live trading")

    def _create_engine(self):
        engine = create_engine('postgresql+psycopg2://postgres:1234@localhost:5432/out/backtest_res')
        if not database_exists(engine.url):
            create_database(engine.url)
        return engine

    def _config_session(self):
        """
        Initialises the necessary classes used
        within the session.
        """
        # Define queue
        if self.events_queue is None:
            self.events_queue = queue.Queue()
        
        # Define default price handler
        if self.price_handler is None and self.session_type == "backtest":
            self.price_handler = YahooDailyCsvBarPriceHandler(
                self.config.CSV_DATA_DIR, self.events_queue,
                self.tickers, start_date=self.start_date,
                end_date=self.end_date)
        else:
            self.price_handler.events_queue = self.events_queue
        
        # Define default price handler
        if self.position_sizer is None:
            self.position_sizer = FixedPositionSizer()

        # Define risk manager
        if self.risk_manager is None:
            self.risk_manager = StopLossRiskManager(
                order_type='mkt',
                apply_sl = self.stop_loss,
                apply_tp = self.take_profit
            )
            

        if self.portfolio_handler is None:
            self.portfolio_handler = PortfolioHandler(
                self.cash,
                self.events_queue,
                self.price_handler,
                self.position_sizer,
                self.risk_manager
            )
            # Assign EventsQueue and Portfolio to the strategy
            self.strategy.events_queue = self.events_queue
            self.strategy.portfolio = self.portfolio_handler.portfolio
            self.strategy.price_handler = self.price_handler

        if self.compliance is None:
            self.compliance = SqlCompliance(self.config, self.engine)

        if self.execution_handler is None:
            self.execution_handler = IBSimulatedExecutionHandler(
                self.events_queue,
                self.price_handler,
                self.compliance
            )

        if self.statistics is None:
            self.statistics = StatisticsReporting(
                self.engine, self.config,
                self.portfolio_handler,
                self.benchmark
            )


    def _continue_loop_condition(self):
        if self.session_type == "backtest":
            return self.price_handler.continue_backtest
        else:
            return datetime.now() < self.end_session_time

    def _run_session(self):
        """
        Carries out an infinite while loop that polls the
        events queue and directs each event to either the
        strategy component of the execution handler. The
        loop continue until the event queue has been
        emptied.
        """

        if self.session_type == "backtest":
            logger.info('    RUNNING BACKTEST   ')
        else:
            logger.info('    RUNNING LIVE SESSION   ')

        while self._continue_loop_condition():
            try:
                event = self.events_queue.get(False)
            except queue.Empty:
                self.price_handler.stream_next()
            else:
                if event is not None:
                    if (
                        event.type == EventType.TICK or
                        event.type == EventType.BAR
                    ):
                        self.cur_time = event.time
                        self.portfolio_handler.update_portfolio_value() # Modif: invertito con la riga sottostante
                        self.portfolio_handler.order_handler.check_pending_orders(self.price_handler)
                        self.strategy.calculate_signals(event) #, self.events_queue, self.portfolio_handler.portfolio
                        self.statistics.update(event.time) #self.portfolio_handler
                    elif event.type == EventType.SENTIMENT:
                        self.strategy.calculate_signals(event)
                    elif event.type == EventType.SIGNAL:
                        self.portfolio_handler.on_signal(event)
                    elif event.type == EventType.ORDER:
                        self.execution_handler.execute_order(event)
                    elif event.type == EventType.FILL:
                        self.portfolio_handler.on_fill(event)
                    else:
                        raise NotImplemented("Unsupported event.type '%s'" % event.type)


    def start_trading(self, testing=False):
        """
        Runs either a backtest or live session, and outputs performance when complete.
        """
        self._run_session()
        self.statistics.get_results()

        # Save statistics in a sql db
        #self.statistics.to_sql(self.engine)

        # Close the logger file
        file_handler.close()
        # Close the SQL connection
        self.engine.dispose() # Close all checked in sessions

        if not testing:
            self.statistics.print_summary(self.statistics.statistics)
        return 
