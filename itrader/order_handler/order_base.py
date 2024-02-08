from abc import ABCMeta, abstractmethod


class OrderBase(object):
    """
    The OrderBase abstract class it is the blue print of 
    the order hundler subclasses (position sizer and risk
    manager). 
    It imports the instances necessary for this module like:
        - Portfolio handler
        - Events queue
    """
    open_positions = {}     # Opened positions in each portfolio
    cash = {}               # Cash available in each portfolio
    strategies_setting = {}
    
    #__metaclass__ = ABCMeta

    def __init__(self, events_queue, portfolio_handler):
        self.events_queue = events_queue
        self.portfolio_handler = portfolio_handler
    
    def set_strategy_setting(self, strategy_id, tf_delta, strategy_setting):
        """
        Add the strategy seting for a defined strategy id in the 
        global strategies_setting dictionary.

        Parameters
        ----------
        strategy_id: `str`
            Strategy ID of the corresponding setting
        strategy_setting: `dict`
            Dictionary with all strategy setting and portfolio id
            where to execute the transactions of the strategy.
        """
        strategy_setting['tf_delta'] = tf_delta
        OrderBase.strategies_setting[strategy_id] = strategy_setting

    def _update_portfolio_data(self):
        # Initialize portfolio data
        OrderBase.open_positions = self.portfolio_handler.get_positions_info()
        OrderBase.cash = self.portfolio_handler.get_all_cash()
    
    def open_pos(self):
        return self.open_positions


    @abstractmethod
    def size_order(self, initial_order):
        """
        This TestPositionSizer object simply modifies
        the quantity to be 100 of any share transacted.
        """
        raise NotImplementedError("Position sizer not implemented")
    

    @abstractmethod
    def refine_order(self, **kwargs):
        """
        This TestPositionSizer object simply modifies
        the quantity to be 100 of any share transacted.
        """
        raise NotImplementedError("Risk manager sizer not implemented")
