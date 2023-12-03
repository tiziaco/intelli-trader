from .order_base import OrderBase

import logging
logger = logging.getLogger('TradingSystem')

class Compliance(OrderBase):
    """
    The Compliance class manage the signal event coming from the 
    strategy class.

    It verify that all the entering rules are compliant with the 
    defined conditions. It verifies if a position is already open 
    and if the number of opened positions in a portfolio reached 
    the defined limit
    """
    def __init__(self, max_position = 1):
        self.max_position = max_position
        #TODO: check if position already opened
        #TODO: allow or not partial buy/sell
        logger.info('   COMPLIANCE MANAGER: Default => OK')

    def check_compliance(self, initial_order, portfolio_id='01'):
        """
        Check if there's already an opened position in the portfolio
        and if the max. number of positions is reached.

        Parameters
        ----------
        initial_order : `Order object`
            The initial order generated from a signal event
        portfolio_id : `str`
            The portfolio id where to check the compliance
        """
        # Check direction
        if bool(self.open_positions[portfolio_id]):
            # Check if the dictionary is full
            if (initial_order.ticker in self.open_positions[portfolio_id].keys()):
                if (initial_order.action == self.open_positions[portfolio_id][initial_order.ticker]['action']):
                    logger.info('  COMPLIANCE: position already opened')
                    #print('first check OK')
                    return None

            # Check max position
            if len(self.open_positions[portfolio_id].keys()) >= self.max_position:
                if (initial_order.ticker in self.open_positions[portfolio_id].keys()):
                    if (initial_order.action != self.open_positions[portfolio_id][initial_order.ticker]['action']):
                        #print('seconf check OK')
                        return initial_order
                else:
                    logger.info('  COMPLIANCE: max positions reached. Order refused')
                    return None
            else:
                return initial_order
        else:
            return initial_order
    
    def check_compliance_NEW(self, initial_order, portfolio_id='01'):
        """
        #TODO: da testare
        """
        # if portfolio_id not in self.open_positions:
        #     self.open_positions[portfolio_id] = {}

        if initial_order.ticker in self.open_positions[portfolio_id]:
            if initial_order.action == self.open_positions[portfolio_id][initial_order.ticker]['action']:
                logger.warning('COMPLIANCE: Position already opened. Order refused')
                return None
        elif len(self.open_positions[portfolio_id]) >= self.max_position:
            logger.warning('COMPLIANCE: Max. positions reached. Order refused')
            return None
        return initial_order
    
    def _check_open_positions(self, initial_order, portfolio_id='01'):
        if initial_order.action == self.open_positions[portfolio_id][initial_order.ticker]['action']:
            logger.info('  COMPLIANCE: position already opened')
            return None
