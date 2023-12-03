import re
import datetime # DONT DELETE: Used with eval

import logging
logger = logging.getLogger('TradingSystem')

class BaseScreener(object):
    """
    AbstractScreener is an abstract base class providing an interface for
    all subsequent (inherited) screener handling objects.

    The goal of a (derived) Screener object is to analyse the market and
    propose the most suitable instument to be traded.

    This is designed to work both with historic and live data as
    the Screener object is agnostic to data location.
    """

    @staticmethod
    def cross_up(present_val, past_val, limit):
        return ((present_val > limit) & (past_val <= limit))
        
    @staticmethod
    def cross_down(present_val, past_val, limit):
        return ((present_val < limit) & (past_val >= limit))

    @staticmethod
    def price_cross_up(bar, indicator, lockback):
        # print('Close: %s', bar['Close'].values)
        # print('Ind: %s', indicator[-2])
        return ((bar['Close'].values > indicator[lockback]) & (bar['Open'].values < indicator[lockback]))

    @staticmethod
    def price_cross_down(bar, indicator, lockback):
        return ((bar['Close'].values < indicator[lockback]) & (bar['Open'].values > indicator[lockback]))
    
    @staticmethod
    def _get_delta(timeframe):
        """
        Transform the str timeframe in a `timedelta` object.

        Parameters
        ----------
        timeframe: `str`
            Timeframe of the strategy

        Returns
        -------
        delta: `TimeDelta object`
            The time delta corresponding to the timeframe.
        """
        
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
            logger.error('WARNING: timeframe not suppoerted')
        return delta
