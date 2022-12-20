from .base import AbstractRiskManager
from ...instances.event import OrderEvent
import logging
logger = logging.getLogger()

class ExampleRiskManager(AbstractRiskManager):
    def refine_orders(self, portfolio, sized_order):
        """
        This ExampleRiskManager object simply lets the
        sized order through, creates the corresponding
        OrderEvent object and adds it to a list.
        """
        order_event = OrderEvent(
            sized_order.ticker,
            sized_order.action,
            sized_order.quantity
        )
        logger.info('  RISK MANAGER: OK Proceed')
        return [order_event]
