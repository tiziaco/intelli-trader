from abc import ABCMeta, abstractmethod
import re
import datetime # DONT DELETE: Used with eval

from itrader.instances.event import SignalEvent

import logging
logger = logging.getLogger('TradingSystem')

class BaseStrategy(object):
    """
    AbstractStrategy is an abstract base class providing an interface for
    all subsequent (inherited) strategy handling objects.

    The goal of a (derived) Strategy object is to generate Signal
    objects for particular symbols based on the inputs of ticks
    generated from a PriceHandler (derived) object.

    This is designed to work both with historic and live data as
    the Strategy object is agnostic to data location.
    """

    global_queue = None
    strategy_setting = None

    def _send_signal(self, ticker: str, signal: tuple, event, strategy_id: str):
        """
        Add the signal generated from the strategy to the global queue of the trading system
        """
        if signal is None:
            return
        _signal = SignalEvent(
                        time=event.time,
                        ticker=ticker, 
                        direction=signal[0],
                        action=signal[1],
                        price=event.bars[ticker]['close'],
                        strategy_id=strategy_id                 
                    )
        self.global_queue.put(_signal)
        logger.info('STRATEGY - New signal => %s - %s %s, %s, %s $', _signal.strategy_id,
                     _signal.direction, _signal.action, _signal.ticker, _signal.price)

    @staticmethod
    def cross_up(present_val, past_val, limit) -> bool:
        return ((present_val > limit) & (past_val <= limit))
        
    @staticmethod
    def cross_down(present_val, past_val, limit) -> bool:
        return ((present_val < limit) & (past_val >= limit))

    @staticmethod
    def price_cross_up(bar, indicator, lockback)  -> bool:
        # print('Close: %s', bar['Close'].values)
        # print('Ind: %s', indicator[-2])
        return ((bar['Close'].values > indicator[lockback]) & (bar['Open'].values < indicator[lockback]))

    @staticmethod
    def price_cross_down(bar, indicator, lockback) -> bool:
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
