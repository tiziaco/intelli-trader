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

    __metaclass__ = ABCMeta

    open_positions = [] # Opened positions in the selected portfolio
    cash = 0            # Cashs available in the selected portfolio

    def __init__(self, events_queue, portfolio_handler):
        self.events_queue = events_queue
        self.portfolio_handler = portfolio_handler


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
