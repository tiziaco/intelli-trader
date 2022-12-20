from ..outils.price_parser import PriceParser
from itrader.portfolio_handler.position_handler import PositionHandler

import logging
logger = logging.getLogger()

class Portfolio(object):
    """
    Represents a portfolio of assets. It contains a cash
    account with the ability to subscribe and withdraw funds.
    It also contains a list of positions in assets, encapsulated
    by a PositionHandler instance.

    Parameters
    ----------
    portfolio_id: str, optional
        An identifier for the portfolio.
    start_dt : datetime
        Portfolio creation datetime. 
    starting_cash : float, optional
        Starting cash of the portfolio. Defaults to 100,000 USD.
    name: str, optional
        The human-readable name of the portfolio.
    """

    def __init__(self, portfolio_id, start_dt, starting_cash, name = None):
        """
        Initialise the Portfolio object with a PositionHandler,
        along with cash balance.
        """
        self.portfolio_id = portfolio_id
        self.start_dt = start_dt
        self.current_time = start_dt
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.name = name

        self.pos_handler = PositionHandler()

        logger.info('PORTFOLIO: New portfolio added - ID:%s, User: %s, Cash: %s $',
            self.portfolio_id , self.portfolio_id)

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

    def transact_asset(self, time, ticker, action, quantity, price, commission):
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
        if time < self.current_time:
            raise ValueError(
                'Transaction datetime (%s) is earlier than '
                'current portfolio datetime (%s). Cannot '
                'transact assets.' % (time, self.current_time)
            )
        self.current_time = time

        txn_share_cost = price * quantity
        txn_total_cost = txn_share_cost + commission

        # self.pos_handler.transact_position(time, action, ticker,
        #     quantity, price, commission)
        
        # self.cash -= txn_total_cost

        if ticker not in self.portfolio_to_dict().keys():
            self.pos_handler._add_position(
                time, ticker, action, quantity,
                price, commission)
            self.cash -= txn_total_cost
        else:
            self.pos_handler._modify_position(
                time, ticker, action, quantity,
                price, commission)

            if ticker not in self.portfolio_to_dict().keys():
                # The position has been closed
                self.cash += txn_total_cost
            else:
                # The position is still open
                pos = self.pos_handler.positions[ticker]
                if pos.action != action :
                    self.cash += txn_total_cost
                else:
                    self.cash -= txn_total_cost


    def update_market_value_of_asset(self, ticker, current_price, current_dt):
        """
        Updates the value of all positions that are currently open.
        """
        if ticker not in self.pos_handler.positions:
            return
        else:
            if current_price < 0.0:
                raise ValueError(
                    'Current trade price of %s is negative for '
                    'asset %s. Cannot update position.' % (
                        current_price, ticker
                    )
                )

        self.pos_handler.positions[ticker].update_current_price(
                current_price, current_dt
            )

    def portfolio_to_dict(self):
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
