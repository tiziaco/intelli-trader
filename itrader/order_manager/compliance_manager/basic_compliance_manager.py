from ..order_base import OrderBase

import logging
logger = logging.getLogger('TradingSystem')

class BasicComplianceManager(OrderBase):
    """
    The Compliance class manage the signal event coming from the 
    strategy class.

    It verify that all the entering rules are compliant with the 
    defined conditions. It verifies if a position is already open 
    and if the number of opened positions in a portfolio reached 
    the defined limit
    """
    def __init__(self, long_only = False):
        self.max_position = None
        self.long_only = long_only
        #TODO: allow or not partial buy/sell
        logger.info('   COMPLIANCE MANAGER: Default => OK')


    
    def check_compliance(self, initial_order):
        """
        Check if there's already an opened position in the portfolio
        and if the max. number of positions is reached.

        Parameters
        ----------
        initial_order: `Order object`
            The initial order generated from a signal event
        portfolio_id: `str`
            The portfolio id where to check the compliance
        """
        # if portfolio_id not in self.open_positions:
        #     self.open_positions[portfolio_id] = {}
        portfolio_id = initial_order.portfolio_id
        self.max_position = self.strategies_setting[initial_order.strategy_id]['max_positions']

        if initial_order.ticker in self.open_positions[portfolio_id]:
            if initial_order.direction == self.open_positions[portfolio_id][initial_order.ticker]['action']:
                logger.warning('COMPLIANCE: Position already opened. Order refused')
                return None
            elif initial_order.action == 'ENTRY':
                logger.warning('COMPLIANCE: Position already opened. Order refused')
                return None
        elif (len(self.open_positions[portfolio_id]) >= self.max_position) and (initial_order.action == 'ENTRY'):
            logger.warning('COMPLIANCE: Max. positions reached. Order refused')
            return None
        elif initial_order.action == 'EXIT':
            logger.warning('COMPLIANCE: Order action not valid. No position opened for %s', initial_order.ticker)
            return None
        logger.info('  COMPLIANCE: Order validated')
        return initial_order
    
