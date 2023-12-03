from itrader.universe.universe import Universe
from ..instances.event import BarEvent

import logging
logger = logging.getLogger('TradingSystem')

class DynamicUniverse(Universe):
    """
    An Asset Universe that allows additions of assets
    beyond a certain datetime.

    TODO: This does not currently support removal of assets
    or sequences of additions/removals.

    Parameters
    ----------
    assets : `list[str]`
        List of assets and their entry date.
    """

    def __init__(self, price_handler, global_queue = None, uni_type = 'static'):
        self.uni_type = uni_type
        self.price_handler = price_handler
        self.global_queue = global_queue
        self.assets = []
        self.last_bar = None
        

        logger.info('UNIVERSE: %s => OK', self.uni_type)

    def get_assets(self):
        """
        Obtain the list of assets in the Universe at a particular
        point in time. This will always return a static list
        independent of the timestamp provided.

        Returns
        -------
        `list[str]`
            The list of Asset tickers in the Universe.
        """
        logger.info('UNIVERSE: list of assets updated')
        return self.assets

    def assign_assets(self, tickers):
        """
        Assign tradeable assets to the universe

        Parameters
        ----------
        assets: `list[str]`
            List of tradeable assets.
        """
        self.assets = tickers
    
    def generate_bars(self, ping_event):
        """
        Generate a bar event with the last price data of all the 
        traded symbol from the different strategies.

        Parameters
        ----------
        ping_event: `Ping event object`
            Ping object with the last closed bar time.
        """
        bar_event = BarEvent(ping_event.time)

        for ticker in self.assets:
            if ticker in self.price_handler.prices.keys():
                bar = self.price_handler.get_bar(ticker, ping_event.time)
                bar_event.bars[ticker] = {
                    'open' : bar.open,
                    'high' : bar.high,
                    'low' : bar.low,
                    'close' : bar.close,
                    'volume' : bar.volume
                }
                self.last_bar = bar_event
            else:
                logger.warning('UNIVERSE: ticker %s not present in the price handler', ticker)
        if self.global_queue is not None:
            self.global_queue.put(bar_event)
        else:
            return bar_event
    
    def update_bars(self, bar_event):
        bar_tickers = bar_event.bars.keys()

        missing_ticker = [string for string in self.assets if string not in bar_tickers]

        # Check if i have missing ticker
        if not missing_ticker:
            return bar_event
        
        # Update the bars
        for ticker in missing_ticker:
            if ticker in self.price_handler.prices.keys():
                bar = self.price_handler.get_bar(ticker, bar_event.time)
                bar_event.bars[ticker] = {
                    'open' : bar.open,
                    'high' : bar.high,
                    'low' : bar.low,
                    'close' : bar.close,
                    'volume' : bar.volume
                }
                self.last_bar = bar_event
            else:
                logger.warning('UNIVERSE: ticker %s not present in the price handler', ticker)
        return bar_event

