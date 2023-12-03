import queue
import logging
from datetime import datetime

from itrader.instances.event import EventType
from itrader.order_manager.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.execution_handler.simulated import ExecutionHandler
from itrader.reporting.engine_logger import EngineLogger

from sqlalchemy import create_engine
from sqlalchemy_utils import database_exists, create_database

# logger = logging.getLogger('TradingSystem')

## FOR TESTING
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Overall minimum logging level

stream_handler = logging.StreamHandler()  # Configure the logging messages displayed in the Terminal
formatter = logging.Formatter('%(levelname)s | %(message)s') # %(asctime)s 
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.INFO)  # Minimum logging level for the StreamHandler

logger.addHandler(stream_handler)

class EventEngine(object):
    """
    Encapsulates all components associated with the engine of the
    trading system. This includes the order handler (with its risk manager 
    and position sizer), the portfolio handler and the execution handler
    (with its transaction cost model).

    It process the signal coming from the strategy handler.

    Parameters
    ----------
    price_handler : `PriceHandler`
        The data handler instance used for all market data.
    global_queue : `Queue`
        The global events queue of the trading system.
    exchange : `str`
        The exchange where to execute real orders.
    init_cash : `int`
        Initial cash for the simulated portfolio
    max_positions : `int`
        Max number of positions that can be opened 
    order_type : `str`, default 'market'
        Order type for the otder handler ('market' or 'limit')
    fee_model : `str`, default = 'noo_fee'
        How to calculate the fee ('noo_fee', 'percent')
    submit_orders : `Boolean`, optional
        Whether to actually submit live orders. Defaults to no submission.
    """

    def __init__(
        self,
        #universe,
        price_handler,
        global_queue,
        session_type,
        exchange,
        init_cash,
        engine_queue = None,
        order_type = 'market',
        fee_model = 'no_fee',
        submit_orders = False,
        to_sql = False,
        telegram_bot = None
        #**kwargs
    ):
        #self.universe = universe
        self.price_handler = price_handler
        self.global_queue = global_queue
        self.session_type = session_type
        self.init_cash = init_cash
        self.order_type = order_type
        self.fee_model = fee_model
        self.submit_orders = submit_orders

        self.engine_queue = engine_queue
        self.telegram_bot = telegram_bot
        self.exchange = None
        self.testnet = True
        self.engine_logger = None
        self.order_handler = None
        self.portfolio_handler = None
        self.execution_handler = None

        self.sql_engine = self._create_sql_engine()
        self.to_sql = to_sql

        self._initialize_engine(exchange)

    def _create_sql_engine(self):
        """
        Create the engine istance to connect to the SQL database.
        This database will contains informations about the trading 
        system like: transactions, closed positions and portfolio equity.

        Return
        ------
        engine: `Engine` object
            The sql engine object
        """
        engine = create_engine('postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_data')
        if not database_exists(engine.url):
            create_database(engine.url)
        return engine

    def _initialize_engine(self, exchange):
        """
        TODO : da finire.
        Initialise the various components for the engine of the
        trading system. This includes the portfolio, order and
        execution handler.
        """

        # Initialise the engine queue
        if self.engine_queue is None:
            self.engine_queue = queue.Queue()

        # Initialize the exchange for live session
        # if self.session_type == 'live':
        #     exchange_class = getattr(ccxt, exchange)()
        #     self.exchange = exchange_class({
        #         'apiKey': 'YOUR_API_KEY',
        #         'secret': 'YOUR_SECRET'
        #         })
        #     if self.testnet:
        #         self.exchange.set_sandbox_mode(True)

        # Initialise the engine logger
        self.engine_logger = EngineLogger(self.sql_engine, self.to_sql)

        # Initialise the Portfolio handler
        time = datetime.now()
        self.portfolio_handler = PortfolioHandler(self.init_cash , time, self.engine_queue, self.price_handler, self.engine_logger)

        # Initialise the Order handler
        self.order_handler = OrderHandler(self.engine_queue, self.portfolio_handler, self.price_handler, self.order_type)

        # Initialise the Execution handler
        self.execution_handler = ExecutionHandler(self.engine_queue, self.engine_logger, self.fee_model, 
                                                  telegram_bot = self.telegram_bot)
    
    def _process_signal(self):
        """
        Process the Signal event generated by the Strategy module.
        First it get the signal from the engine queue and then it process
        it trough the Order handler, execution and portfolio handler.
        """

        while not self.engine_queue.empty() :
            try:
                event = self.engine_queue.get(False)
            except queue.Empty:
                event = None
            if event.type == EventType.SIGNAL:
                self.order_handler.on_signal(event)
            elif event.type == EventType.ORDER:
                self.execution_handler.execute_order(event)
            elif event.type == EventType.FILL:
                self.portfolio_handler.on_fill(event)
                self.order_handler._delete_pending_orders(event)
            else:
                raise NotImplemented('ENGINE: Unsupported event type %s' % event.type)
    
    def _get_opened_positions(self):
        """
        Return a list of string with the ticker of every opened position.
        Used in universe.assign_asset()
        """
        opened = []
        positions_dict = self.portfolio_handler.get_positions_info()

        for id, portfolio in positions_dict.items():
            opened += list(portfolio.keys())
        return opened
    
            
    