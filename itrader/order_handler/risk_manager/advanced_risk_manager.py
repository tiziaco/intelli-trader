import sys
from ..order_base import OrderBase
from .sltp_models.sltp_models import FixedPercentage
from .sltp_models.sltp_models import Proportional
from .sltp_models.sltp_models import ATRsltp

#from .base import AbstractRiskManager
from ...outils.price_parser import PriceParser


import logging
logger = logging.getLogger('TradingSystem')


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

    def __init__(self, price_handler):
        self.price_handler = price_handler
        self.apply_sl = None
        self.apply_tp = None
        self.sltp_models = self._initialise_sltp_models()
        self.order_id = 0

        logger.info('   RISK MANAGER: Advanced Risk Manager => OK')


    def refine_orders(self, sized_order):
        """
        Calculate the StopLoss level annd create a OrderEvent.
        """
        
        ### Check if enough cash in the portfolio
        # if self._check_cash(sized_order):
        #     return None
        self.apply_sl = self.strategies_setting[sized_order.strategy_id]['apply_sl']
        self.apply_tp = self.strategies_setting[sized_order.strategy_id]['apply_tp']
        

        ### Calculate SL and TP
        if sized_order.action == 'ENTRY':
            if self.apply_sl:
                sl_setting = self.strategies_setting[sized_order.strategy_id]['sl_setting']
                # Get bars prices when the sltp model is ATR or probabilistic
                bars = None
                if sl_setting['sl_model'] == 'ATR':
                    # Load 100 bars
                    start_dt = (sized_order.time - self.strategies_setting[sized_order.strategy_id]['tf_delta'] * 100)
                    bars = self.price_handler.get_bars(sized_order.ticker, start_dt, sized_order.time)
                sized_order = self.sltp_models[sl_setting['sl_model']].calculate_sl(sized_order, sl_setting, bars)
            if self.apply_tp:
                tp_setting = self.strategies_setting[sized_order.strategy_id]['tp_setting']
                bars = None
                if tp_setting['tp_model'] == 'ATR':
                    # Load 100 bars
                    start_dt = (sized_order.time - self.strategies_setting[sized_order.strategy_id]['tf_delta'] * 100)
                    bars = self.price_handler.get_bars(sized_order.ticker, start_dt, sized_order.time)
                sized_order = self.sltp_models[tp_setting['tp_model']].calculate_tp(sized_order, tp_setting, bars)

        logger.info('  RISK MANAGER: Order validated')
        return sized_order


    def _check_cash(self, sized_order):
        """
        Check if enough cash in the selected portfolio.
        If not enough cash the order is refused
        """
        cash = self.cash[sized_order.portfolio_id]
        if cash < 30:#PriceParser.display
            logger.info('  RISK MANAGER: Order REFUSED: Not enough cash to trade')
            return False

    def _initialise_sltp_models(self):
        """
        Instanciate all the stop loss and take profit models
        in a dictionary.
        """
        sltp_models = {
            'fixed': FixedPercentage(),
            'proportional': Proportional(),
            'ATR': ATRsltp(),
            'probabilistic': None
        }
        return sltp_models
        
