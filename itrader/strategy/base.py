from abc import ABCMeta, abstractmethod
import re
import datetime # DONT DELETE: Used with eval


class AbstractStrategy(object):
    """
    AbstractStrategy is an abstract base class providing an interface for
    all subsequent (inherited) strategy handling objects.

    The goal of a (derived) Strategy object is to generate Signal
    objects for particular symbols based on the inputs of ticks
    generated from a PriceHandler (derived) object.

    This is designed to work both with historic and live data as
    the Strategy object is agnostic to data location.
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def calculate_signals(self, event):
        """
        Provides the mechanisms to calculate the list of signals.
        """
        raise NotImplementedError("Should implement calculate_signals()")

    @staticmethod
    def cross_up(bar, indicator, lockback):
        # print('Close: %s', bar['Close'].values)
        # print('Ind: %s', indicator[-2])
        return ((bar['Close'].values > indicator[lockback]) & (bar['Open'].values < indicator[lockback]))

    @staticmethod
    def cross_down(bar, indicator, lockback):
        return ((bar['Close'].values < indicator[lockback]) & (bar['Open'].values > indicator[lockback]))
    
    @staticmethod
    def _get_delta(timeframe):
        # Splitting text and number in string
        temp = re.compile("([0-9]+)([a-zA-Z]+)")
        res = temp.match(timeframe).groups()
        if res[1] == 'd':
            delta = eval(f'datetime.timedelta(days={res[0]})')
        elif res[1] == 'h':
            delta = eval(f'datetime.timedelta(hours={res[0]})')
        elif res[1] == 'm':
            delta = eval(f'datetime.timedelta(minutes={res[0]})')
        else:
            print('WARNING: timeframe not suppoerted') #TODO implementare log ERROR
        return delta


class Strategies(AbstractStrategy):
    """
    Strategies is a collection of strategy
    """
    def __init__(self, *strategies):
        self._lst_strategies = strategies

    def calculate_signals(self, event):
        for strategy in self._lst_strategies:
            strategy.calculate_signals(event)
