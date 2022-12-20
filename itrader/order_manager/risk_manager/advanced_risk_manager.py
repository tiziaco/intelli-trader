from ..order_base import OrderBase

#from .base import AbstractRiskManager
from ...outils.price_parser import PriceParser


import logging
logger = logging.getLogger()


class RiskManager(OrderBase):
    """
    This RiskManager class performs different operations on the suggested order:
        - Check if the position is already opened
        - Check available cash
        - Check max position per portfolio
        - Calculate the StopLoss price
        - Calculate the TakeProfit price
    If the order is validated it is sended back to the order manager.

    Parameters
    ----------
    apply_sl : `boolean`
        Specify if apply stop loss
    apply_tp : `boolean`
        Specify if apply take profit
    stop_level : `float`
        Stop level in % (default: 3%)
    """

    def __init__(self, apply_sl=False, apply_tp=False, stop_level=0.03):
        self.apply_sl = apply_sl
        self.apply_tp = apply_tp
        self.stop_level = stop_level  #Stop loss level: 5%
        self.order_id = 0

        logger.info('RISK MANAGER: Advanced Risk Manager => OK')


    def refine_orders(self, sized_order):
        """
        Calculate the StopLoss level annd create a OrderEvent.
        """
        ### Check if the position is already opened
        self._check_open(sized_order)
        
        ### Check if enough cash in the portfolio
        self._check_cash(sized_order)

        ### Check if enough cash in the portfolio
        self._check_max_positions(sized_order)

        ### Calculate SL and TP
        if self.apply_sl:
            self._calculate_sl(sized_order)
        if self.apply_tp:
            self._calculate_tp(sized_order)

        logger.info('  RISK MANAGER: Order VALIDATED')
        return sized_order


    def _calculate_sl(self, sized_order):
        """
        Define stopLoss level at a % of the last close
        """

        last_close = sized_order.price

        if sized_order.action == 'BOT':
            # LONG direction: sl lower
            stop_loss = last_close * (1-self.stop_level)

        elif sized_order.action == 'SLD':
            # SHORT direction: sl higher
            stop_loss = last_close * (1+self.stop_level)
        return stop_loss


    def _calculate_tp(self, sized_order):
        """
        Define stopLoss level at a % of the last close
        """
        last_close = sized_order.price

        if sized_order.action == 'BOT':
            # LONG direction: tp higher
            take_profit = last_close * (1+self.stop_level)

        elif sized_order.action == 'SLD':
            # SHORT direction: tp lower
            take_profit = last_close * (1-self.stop_level)
        return take_profit
    
    def _check_open(self, sized_order):
        """
        Check if the position is already opened. 
        In this case validate and return the object.
        """
        opened_position = self.portfolio_handler.portfolio[0].positions.keys() #TODO da validare
        if sized_order.ticker in opened_position:
            logger.info('  RISK MANAGER: Order VALIDATED')
            return sized_order


    def _check_cash(self):
        """
        Check if enough cash in the selected portfolio.
        If not enough cash the order is refused
        """
        # TODO: mofificare: passa il portfolio_id
        cash = self.portfolio_handler.portfolio[0].cur_cash
        if PriceParser.display(cash) < 30:
            logger.info('  RISK MANAGER: Order REFUSED: Not enough cash to trade')
            return

    def _check_max_positions(self, portfolio):
        """
        Check if too many positions opened. 
        If the limit of the max positions is reached the order is refused.
        """
        if (len(portfolio.positions) >= portfolio.max_position) :
            logger.info('  RISK MANAGER: Order REFUSED: Max positions reached')
            return
        
