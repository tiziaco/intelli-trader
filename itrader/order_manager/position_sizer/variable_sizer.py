from ..order_base import OrderBase

#from .base import AbstractPositionSizer

from ...outils.price_parser import PriceParser

import logging
logger = logging.getLogger()

class DynamicSizer(OrderBase):
    """
    Size the order according to the cash available in the
    portfolio and the number of positions already opened.

    By default, it assaign 80% of the available cash at 
    each order.

    Parameters
    ----------
    integer_size : `boolean`
        Specify if only int size should be calculated
    max_allocation : `float`
        Allocation percentage (default: 80%)

    """
    def __init__(self, integer_size=True, max_allocation = 0.8, max_positions = 1):
        self.integer_size = integer_size #define only integer sizes
        self.max_allocation = max_allocation
        self.max_positions = max_positions # TODO: da parametrizzare secondo il portfolio

        logger.info('POSITION SIZER: Dynamic Sizer => OK')
    

    def size_order(self, initial_order):
        """
        Calculate the size of the order (80% of the available cash).
        """
        
        ticker = initial_order.ticker
        #opened_position = self.portfolio_handler.portfolio[0].positions.keys() #TODO da validare

        if ticker in self.open_positions:
            # The position is already open, assign 100% of the quantity
            quantity = self.portfolio_handler.portfolio[0].positions[ticker].quantity
        else:
            # New position, assign 80% of the cash
            cash = self.cash
            last_price = initial_order.price

            available_pos = (self.max_positions-len(self.open_positions))
            quantity = (cash * (self.max_allocation * (1 / available_pos))) / last_price

            if self.integer_size:
                quantity = int(quantity)
        
        # Assign the calculated size to the ordr event
        initial_order.quantity = quantity
        return initial_order
