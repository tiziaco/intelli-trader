import re
import datetime # DONT DELETE: Used with eval
import pytz
from datetime import datetime, timedelta

from itrader.instances.event import SignalEvent

import logging
logger = logging.getLogger('TradingSystem')


class StrategiesHandler(object):
    """
    Manage all the strategies of the trading system.
    """

    def __init__(self, global_queue, price_handler):
        """
        Parameters
        ----------
        events_queue: `Queue object`
            The events queue of the trading system
        """
        self.global_queue = global_queue
        self.price_handler = price_handler
        self.min_timeframe = None # Tuple (timedelta, timeframe)
        self.strategies = []

        logger.info('STRATEGIES HANDLER: Default => OK')

    def calculate_signals(self, event):
        """
        Calculate the signal for every strategy to be traded.

        Before generating the signal check if the actual time 
        is a multiple of the strategy's timeframe.

        Also, it get the prices data from the PriceHandler and 
        resample them according to the strategy's timeframe.

        Parameters
        ----------
        event: `BarEvent object`
            The bar event of the trading system
        """
        for strategy in self.strategies:
            # Check if the strategy's timeframe is a multiple of the bar event time
            if not self._check_timeframe(event.time, strategy.tf_delta):
                continue

            # Calculate the signal for each ticker or pair traded from the strategy
            for ticker in strategy.tickers:

                # Get the data checking if i am trading a single ticker or a pair
                if isinstance(ticker, str):
                    data = self.price_handler.get_and_resample_bars(event.time, ticker, strategy.tf_delta, strategy.max_window)
                elif isinstance(ticker, tuple):
                    data = {}
                    for sym in ticker:
                        data[sym] = self.price_handler.get_and_resample_bars(event.time, sym, strategy.tf_delta, strategy.max_window)

                signal = strategy.calculate_signal(data, event, ticker)
                self._send_signal(ticker, signal, event, strategy.strategy_id)


    def assign_symbol(self, signals):
        """
        Take the proposed symbols from the screener and assign it to the strategy.
        If a proposed symbol is not in the strategy universe, remove it.

        Parameters
        ----------
        signals: `list of str`
            List of the proposed symbol from the screener
        """
        traded = self.strategies[0].tickers
        max_pos = self.strategies[0].strategy_setting['max_positions']
        
        # TEMPORARY:
        first_key = list(signals.keys())[0]
        proposed = signals[first_key]

        # Remove the symbols from the traded ones if not proposed by the screener
        new_traded = [elem for elem in traded if elem in proposed]

        # Remove the already traded symbols from the proposed ones
        new_proposed = [elem for elem in proposed if elem not in traded]

        # Assign the symbols to be traded to the strategy
        new_traded.extend(new_proposed[0:(max_pos-len(new_traded))])
        self.strategies[0].tickers = new_traded

        if new_traded:
            logger.info('STRATEGY HANDLER: new symbols for %s : %s', self.strategies[0].__str__(), str(new_traded))



    def _send_signal(self, ticker, signal, event, strategy_id):
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
    
    def get_traded_symbols(self):
        """
        Return a list with all the coins traded from the differents strategies.

        Returns
        -------
        traded_tickers: `list`
            List of strings with the traded symbols
        """
        traded_tickers = []
        for strategy in self.strategies:
            # Check if the strategy is trading pairs
            if strategy.tickers and isinstance(strategy.tickers[0], tuple):
                traded_tickers += [value for tuple in strategy.tickers for value in tuple]
            else:
                traded_tickers += strategy.tickers
                
        return list(set(traded_tickers))

    
    def _add_strategy(self, strategy, strategy_setting):
        """
        Add a new strategy in the list of strategies to trade.
        At the same time, calculate the minimum timeframe among 
        the different strategies to be traded. 
        This timeframe will be used from the price handler to 
        download historical prices

        Parameters
        ----------
        strategy: `Strategy object`
            Strategy to be executed by the trading system
        """
        # Add the strategy in the strategies list
        strategy.strategy_setting = strategy_setting
        self.strategies.append(strategy)

        # Find the minimum timeframe. Used later when loading the bars
        self._get_min_timeframe()

        logger.info('STRATEGY HANDLER: New strategy added')
        logger.info('   %s', strategy.strategy_id)
    
    def _check_timeframe(self, time, tf_delta):
        """
        Check if the time of the BarEvent is a multiple of the
        strategy's timeframe.
        In that case return True end go on calculating the signals.

        Parameters
        ----------
        time: `timestamp`
            Event time
        tf_delta: `timedelta object`
            Timeframe of the strategy
        """
        # Calculate the number of seconds in the timestamp
        time = time.astimezone(pytz.utc)
        seconds = (time - time.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()

        # Check if the number of seconds is a multiple of the delta
        if seconds % tf_delta.total_seconds() == 0:
            # The timestamp IS a multiple of the timeframe
            return True
        else:
            # The timestamp IS NOT a multiple of the timeframe
            return False

    
    def _get_min_timeframe(self):
        """
        Extrapolate the lowest timefrime among the different 
        strategies to be traded.
        The timeframe is stored as a `timedelta` object.
        """
        tf = []
        for strategy in self.strategies:
            tf += [(strategy.tf_delta, strategy.timeframe)]
        self.min_timeframe = min(tf)
