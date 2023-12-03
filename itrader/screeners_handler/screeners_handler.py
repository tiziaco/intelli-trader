import re
import datetime # DONT DELETE: Used with eval
import pytz

from itrader.telegram_bot.telegram_bot import TelegramBot

import logging
logger = logging.getLogger('TradingSystem')


class ScreenersHandler(object):
    """
    Manage all the screeners of the trading system.
    """

    def __init__(self, global_queue, price_handler, telegram_bot: TelegramBot = None):
        """
        Parameters
        ----------
        events_queue: `Queue object`
            The events queue of the trading system
        """
        self.global_queue = global_queue
        self.price_handler = price_handler
        self.telegram_bot = telegram_bot

        self.min_timeframe = None # Tuple (timedelta, timeframe)
        self.symbols = None
        self.screeners = []
        self.last_results = {}
        self.results = {}

        logger.info('STRATEGIES HANDLER: Default => OK')

    def apply_screeners(self, event):
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
        for screener in self.screeners:
            
            # Check if the screener's timeframe is a multiple of the bar event time
            if not self._check_timeframe(event.time, screener.frequency):
                continue

            # Calculate the signal for each ticker traded from the strategy
            proposed = screener.apply_screener(
                self.price_handler.get_megaframe(event.time, screener.tf_delta, screener.max_window),
                event.time
            )
            self.last_results = {event.time : proposed}
            self.results[event.time] = proposed

            # Send telegram message
            if self.telegram_bot is not None and proposed:
                text = f'-- Screener allert --\n'
                text += f'   {screener.screener_id}\n'
                text += f'   {proposed}'
                self.telegram_bot.send_message(text=text)


            logger.info('SCREENER HANDLER: Screener updated - %s', screener.__str__())
            # Print the new proposed symbols
            if proposed:
                logger.info('   Proposed symbols: ' + str(proposed))

            # Update symbols in the universe


    def _add_screener(self, screener):
        """
        Add a new screener in the list of screeners.
        At the same time, calculate the minimum timeframe among 
        the different screeners to be applied. 
        This timeframe will be used from the price handler to 
        download historical prices.

        Parameters
        ----------
        screener: `Screener object`
            Screener to be applied to the system's assets
        """
        # Add the strategy in the strategies list
        self.screeners.append(screener)

        # Find the minimum timeframe. Used later when loading the bars
        self._get_min_timeframe()

        logger.info('SCREENER HANDLER: New screener added')
        logger.info('   %s', screener.screener_id)
    
    def _check_timeframe(self, time, tf_delta):
        """
        Check if the time of the BarEvent is a multiple of the
        screener's timeframe.
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

    def get_proposed_symbols(self):
        """
        Return a dictionary with a list of symbols proposed from  
        every screener at the last update. 

        Returns
        -------
        proposed_tickers: `dict`
            Dictionary of list with the proposed tickers per screener
            {screener_id: [last_proposed]}
        """
        proposed_tickers = {}
        for screener in self.screeners:
            proposed_tickers[screener.__str__()] = screener.last_proposed
        return proposed_tickers
    
    def get_screener_universe(self):
        """
        Return the list with the universe to be screened
        """
        screener_universe = []
        for screener in self.screeners:
            screener_universe += screener.tickers
        return screener_universe
    
    def _get_min_timeframe(self):
        """
        Extrapolate the lowest timefrime among the different 
        screeners to be traded.

        The timeframe is stored as a `timedelta` object.
        """
        tf = []
        for screener in self.screeners:
            tf += [(screener.tf_delta, screener.timeframe)]
        self.min_timeframe = min(tf)
