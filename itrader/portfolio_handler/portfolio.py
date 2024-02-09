from ..outils.price_parser import PriceParser
from itrader.portfolio_handler.position_handler import PositionHandler

import logging
logger = logging.getLogger('TradingSystem')

class Portfolio(object):
    """
    Represents a portfolio of assets. It contains a cash
    account with the ability to subscribe and withdraw funds.
    It also contains a list of positions in assets, encapsulated
    by a PositionHandler instance.

    Parameters
    ----------
    user_id: str
        An identifier for the user owner of the portfolio.
    name: str
        The human-readable name of the portfolio.
    cash : float
        Starting cash of the portfolio.
    time : datetime
        Portfolio creation datetime. 
    """

    def __init__(self, user_id, name, cash, time):
        """
        Initialise the Portfolio object with a PositionHandler,
        along with cash balance.
        """
        self.user_id = user_id
        self.portfolio_id = '123' #TODO: da generare automaticamente
        self.name = name
        self.cash = cash
        self.creation_time = time
        self.current_time = time
        self.transactions = {}
        self.pos_handler = PositionHandler()

    @property
    def total_market_value(self):
        """
        Obtain the total market value of the portfolio excluding cash.
        """
        return self.pos_handler.total_market_value()

    @property
    def total_equity(self):
        """
        Obtain the total market value of the portfolio including cash.
        """
        return self.total_market_value + self.cash

    @property
    def total_unrealised_pnl(self):
        """
        Calculate the sum of all the positions' unrealised P&Ls.
        """
        return self.pos_handler.total_unrealised_pnl()

    @property
    def total_realised_pnl(self):
        """
        Calculate the sum of all the positions' realised P&Ls.
        """
        return self.pos_handler.total_realised_pnl()

    @property
    def total_pnl(self):
        """
        Calculate the sum of all the positions' total P&Ls.
        """
        return self.pos_handler.total_pnl()

    def process_transaction(self, transaction):
        """
        Adjusts positions to account for a transaction.

        Parameters
        ----------
        time : `pd.Timestamp`
            The transaction time
        ticker : `str`
            The ticker of the transacted asset
        action : `str`
            The market direction of the position e.g. 'BOT' or 'SLD'
        quantity : `float`
            The amount of the transacted asset
        price : `float`
            The asset price at the moment of the transaction
        commission : `float`
            The commission spent on transacting the asset
        """
        self.current_time = time

        txn_share_cost = round(price * quantity,2)
        txn_total_cost = round(txn_share_cost + commission,2)

        last_close = None

        if ticker not in self.portfolio_to_dict().keys():
            self.pos_handler._add_position(
                time, ticker, action, quantity,
                price, commission)
            self.cash -= txn_total_cost
        else:
            last_close = self.pos_handler._modify_position(
                time, ticker, action, quantity,
                price, commission)
            #print(txn_total_cost)

            # Update the cash in the portfolio after a transaction
            if last_close is not None:
                # The position has been closed
                if last_close.action == 'BOT':
                    self.cash += round(last_close.total_bought + last_close.realised_pnl,2)
                elif last_close.action == 'SLD':
                    self.cash += round(last_close.total_sold + last_close.realised_pnl,2)
                return last_close
            else:
                # The position is still open
                pos = self.pos_handler.positions[ticker]
                if pos.action != action :
                    # Partial exit of the position.
                    # TODO: da verificare
                    self.cash += pos.realised_pnl 
                else:
                    # Increase the position
                    self.cash -= txn_total_cost
                return None


    def update_market_value_of_asset(self, ticker, current_price, current_dt):
        """
        Updates the value of all positions that are currently open.
        """
        if ticker not in self.pos_handler.positions:
            return
        else:
            if current_price < 0:
                raise ValueError(
                    'Current trade price of %s is negative for '
                    'asset %s. Cannot update position.' % (
                        current_price, ticker
                    )
                )

        self.pos_handler.positions[ticker].update_current_price(
                current_price, current_dt
            )

    def to_dict(self):
        """
        Output the portfolio holdings information as a dictionary
        with Assets as keys and sub-dictionaries as values.
        This excludes cash.

        Returns
        -------
        `dict`
            The portfolio holdings.
        """
        holdings = {}
        for ticker, pos in self.pos_handler.positions.items():
            holdings[ticker] = {
                'action': pos.action,
                "quantity": pos.net_quantity,
                'avg_price': pos.avg_price,
                "market_value": pos.market_value,
                "unrealised_pnl": pos.unrealised_pnl,
                "realised_pnl": pos.realised_pnl,
                "total_pnl": pos.total_pnl
            }
        return holdings
    
    def closed_position_to_dict(self):
        """
        Output the clodsed positions of the portfolio as a dictionary
        with Assets as keys and position informations as values.

        Returns
        -------
        `dict`
            The closed positions.
        """
        closed = {}
        for pos in self.pos_handler.closed_positions:
            closed[pos.ticker] = {
                'entry_date': pos.entry_date,
                'exit_date': pos.exit_date,
                'action': pos.action,
                "buy_quantity": pos.buy_quantity,
                "sell_quantity": pos.sell_quantity,
                "avg_bought": pos.avg_bought,
                "avg_sold": pos.avg_sold,
                "unrealised_pnl": pos.unrealised_pnl,
                "realised_pnl": pos.realised_pnl,
                "total_pnl": pos.total_pnl
            }
        return closed
