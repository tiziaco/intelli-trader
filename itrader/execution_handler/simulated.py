from .base import AbstractExecutionHandler
from .fee_model.zero_fee_model import ZeroFeeModel
from .fee_model.percent_fee_model import PercentFeeModel
from ..reporting.engine_logger import EngineLogger
from ..events_handler.event import (FillEvent, EventType)

from itrader.telegram_bot.telegram_bot import TelegramBot

import logging
logger = logging.getLogger()

class ExecutionHandler(AbstractExecutionHandler):
    """
    The simulated execution handler converts all order 
    objects into their equivalent fill objects automatically
    without latency, slippage or fill-ratio issues. 
    
    It allows to cqlculqte the fees with different models.

    This allows a straightforward "first go" test of any strategy,
    before implementation with a more sophisticated execution
    handler.
    """

    def __init__(self, events_queue, engine_logger: EngineLogger, 
        fee_model = 'no_fee', 
        commission_pct = 0.007, tax_pct = 0.0,
        telegram_bot: TelegramBot = None):
        """
        Initialises the handler, setting the event queue
        as well as access to local pricing.

        Parameters:
        events_queue - The Queue of Event objects.
        """
        self.events_queue = events_queue
        self.engine_logger = engine_logger
        self.fee_model = self._initialize_fee_model(fee_model)
        self.commission_pct = commission_pct
        self.tax_pct = tax_pct
        self.telegram_bot = telegram_bot

        logger.info('EXECUTION HANDLER: Simulated broker => OK')


    def execute_order(self, event):
        """
        Converts OrderEvents into FillEvents "naively",
        i.e. without any latency, slippage or fill ratio problems.

        Parameters:
        event - An Event object with order information.
        """
        if event.type == EventType.ORDER:

            # Set the exchange and calculate the trade commission
            exchange = 'Simulated'
            portfolio_id = event.portfolio_id
            commission = self.fee_model.calc_total_commission(event.quantity, event.price)

            # Create the FillEvent and place it in the events queue
            fill_event = FillEvent(
                event.time, event.ticker,
                event.direction,
                event.action, event.quantity,
                exchange, portfolio_id,
                event.price, commission
            )
            self.events_queue.put(fill_event)

            logger.info('EXECUTION HANDLER: Order executed %s %s %s %s %s$', 
                fill_event.direction, fill_event.action, fill_event.ticker, fill_event.quantity, fill_event.price)

            # Record the trade in the SQL database
            self.engine_logger.record_transaction(fill_event)

            # Send telegram message
            if self.telegram_bot is not None:
                text = f'-- Order executed --\n'
                text += f'   {fill_event.ticker} - {fill_event.direction}, {fill_event.action}  \n'
                text += f'   {fill_event.price}$'
                self.telegram_bot.send_message(text=text)

    def _initialize_fee_model(self, fee_model):
        if fee_model == 'percent':
            return PercentFeeModel(self.commission_pct, self.tax_pct)
        elif fee_model == 'no_fee':
            return ZeroFeeModel()
        else:
            logger.warning('EXECUTION HANDLER: fee model %s not supported', fee_model)
            return None