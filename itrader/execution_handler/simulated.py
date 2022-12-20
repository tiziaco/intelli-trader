from .base import AbstractExecutionHandler
from .fee_model.percent_fee_model import PercentFeeModel
from ..instances.event import (FillEvent, EventType)
from ..outils.price_parser import PriceParser

import logging
logger = logging.getLogger()

class ExecutionHandler(AbstractExecutionHandler):
    """
    The simulated execution handler for Interactive Brokers
    converts all order objects into their equivalent fill
    objects automatically without latency, slippage or
    fill-ratio issues.

    This allows a straightforward "first go" test of any strategy,
    before implementation with a more sophisticated execution
    handler.
    """

    def __init__(self, events_queue, commission_pct = 0.007, compliance=None):
        """
        Initialises the handler, setting the event queue
        as well as access to local pricing.

        Parameters:
        events_queue - The Queue of Event objects.
        """
        self.events_queue = events_queue
        #self.price_handler = price_handler
        self.fee_model = PercentFeeModel(commission_pct)
        self.compliance = compliance
        logger.info('BROKER: Simulated => OK')


    def execute_order(self, event):
        """
        Converts OrderEvents into FillEvents "naively",
        i.e. without any latency, slippage or fill ratio problems.

        Parameters:
        event - An Event object with order information.
        """
        if event.type == EventType.ORDER:
            # Obtain values from the OrderEvent
            timestamp = event.time
            ticker = event.ticker
            action = event.action
            quantity = event.quantity
            fill_price = event.price

            """# Obtain the fill price
            if self.price_handler.istick():
                bid, ask = self.price_handler.get_best_bid_ask(ticker)
                if event.action == "BOT":
                    fill_price = ask
                else:
                    fill_price = bid
            else:
                close_price = self.price_handler.get_last_close(ticker)
                fill_price = close_price"""

            # Set a dummy exchange and calculate trade commission
            exchange = "Simulated"
            portfolio_id = '01' # TODO: da automatizzare
            commission = self.fee_model.calc_total_commission(quantity, fill_price)

            # Create the FillEvent and place on the events queue
            fill_event = FillEvent(
                timestamp, ticker,
                action, quantity,
                exchange, portfolio_id,
                fill_price, commission
            )
            self.events_queue.put(fill_event)

            # Record the trade in the SQL database
            if self.compliance is not None:
                self.compliance.record_trade(fill_event)
