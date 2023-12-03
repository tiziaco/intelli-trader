from collections import OrderedDict
from ..outils.price_parser import PriceParser
from itrader.instances.position import Position

import logging
logger = logging.getLogger('TradingSystem')

class PositionHandler(object):
    """
    A class that keeps track of, and updates, the current
    list of Position instances stored in a Portfolio entity.
    """

    def __init__(self):
        """
        Initialise the PositionHandler object to generate
        an ordered dictionary containing the current positions.
        """
        self.positions = OrderedDict()
        self.closed_positions = []
        self.last_close = None

    def _add_position(
        self, time, ticker, action,
        quantity, price, commission
    ):
        """
        Adds a new Position object to the Portfolio. This
        requires getting the best bid/ask price from the
        price handler in order to calculate a reasonable
        "market value".

        Once the Position is added, the Portfolio values
        are updated.
        """

        position = Position.open_new_position(
            time, action, ticker, 
            quantity, price, commission
        )
        self.positions[ticker] = position

        logger.info('  New position added: %s %s %s %s$',
            ticker, action, quantity, price) #PriceParser.display(price)


    def _modify_position(
        self, time, ticker, action,
        quantity, price, commission
    ):
        """
        Modifies or close a current Position object to the Portfolio.
        This requires getting the best bid/ask price from the
        price handler in order to calculate a reasonable
        "market value".

        Once the Position is modified, the Portfolio values
        are updated.
        """
        self.positions[ticker].transact_shares(
            time, ticker, action, quantity, price, commission
        )

        if round(self.positions[ticker].net_quantity, 3) == 0:
            self.positions[ticker].exit_date = time
            #self.closed_positions.append(self.positions[ticker]) #ora salvo in reporting
            #self.last_close = self.positions[ticker]
            last_close = self.positions[ticker]
            logger.info('  Position closed: %s %s %s %s$',
                ticker, action, quantity, price)
            del self.positions[ticker]
            return last_close
        else:
            logger.info('  Position partially closed: %s %s %s %s$',
                ticker, action, quantity, price)
            return None


    def transact_position(self, time, action, ticker,
        quantity, price, commission
    ):
        """
        WARNING: non utilizzata. da rimuovere in futuro

        Handles any new position or modification to
        a current position, by calling the respective
        _add_position and _modify_position methods.

        Hence, this single method will be called by the
        PortfolioHandler to update the Portfolio itself.
        """

        if ticker not in self.positions:
            self._add_position(
                time, ticker, action, quantity,
                price, commission)
        else:
            self._modify_position(
                time, ticker, action, quantity,
                price, commission)


    
    ### Calculated properties 
    def total_market_value(self):
        """
        Calculate the sum of all the positions' market values.
        """
        return sum(
            pos.market_value
            for ticker, pos in self.positions.items()
        )

    def total_unrealised_pnl(self):
        """
        Calculate the sum of all the positions' unrealised P&Ls.
        """
        return sum(
            pos.unrealised_pnl
            for ticker, pos in self.positions.items()
        )

    def total_realised_pnl(self):
        """
        Calculate the sum of all the positions' realised P&Ls.
        """
        return sum(
            pos.realised_pnl
            for ticker, pos in self.positions.items()
        )

    def total_pnl(self):
        """
        Calculate the sum of all the positions' P&Ls.
        """
        return sum(
            pos.total_pnl
            for ticker, pos in self.positions.items()
        )
    
    def positions_info(self):
        """
        Return a dictionary with the main info about every
        open position in the portfolio.

        Return
        ------
        pos_info: `dict`
        """
        pos_info = {}
        for ticker, position in self.positions.items():
            pos_info[ticker] = {
                'action' : position.action,
                'quantity' : abs(round(position.net_quantity, 5)),
                'unrealised_pnl' : position.unrealised_pnl,
                'entry_time' : position.entry_date
                }
        return pos_info

