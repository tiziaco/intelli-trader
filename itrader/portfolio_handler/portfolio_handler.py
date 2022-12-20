from ..outils.price_parser import PriceParser
from .portfolio import Portfolio

import logging
logger = logging.getLogger()

class PortfolioHandler(object):
    """
    The PortfolioHandler is designed to interact with the
    backtesting or live trading overall event-driven
    architecture. It exposes two methods, on_signal and
    on_fill, which handle how SignalEvent and FillEvent
    objects are dealt with.

    Each PortfolioHandler contains a Portfolio object,
    which stores the actual Position objects.

    The PortfolioHandler takes a handle to a PositionSizer
    object which determines a mechanism, based on the current
    Portfolio, as to how to size a new Order.

    The PortfolioHandler also takes a handle to the
    RiskManager, which is used to modify any generated
    Orders to remain in line with risk parameters.
    """
    def __init__(
        self, initial_cash, time, events_queue,
        price_handler, account_id = '001', portfolio = None
    ):
        
        self.initial_cash = initial_cash
        self.events_queue = events_queue
        self.price_handler = price_handler
        self.current_time = time

        self.account_id = account_id
        self.portfolios = {}
        self._set_initial_portfolios(portfolio)

        self.cash_balances = {}
        self.open_orders = {}
        
        logger.info('POORTFOLIO HANDLER: Default => OK')


    
    def _set_initial_portfolios(self, portfolio):
        """
        Set the appropriate initial portfolios dictionary.

        Returns
        -------
        `dict`
            The empty initial portfolio dictionary.
        """
        if portfolio is None:
            self.create_portfolio('01', self.initial_cash)
        

    def on_fill(self, fill_event):
        """
        This is called by the backtester or live trading architecture
        to take a FillEvent and update the Portfolio object with new
        or modified Positions.

        In a backtesting environment these FillEvents will be simulated
        by a model representing the execution, whereas in live trading
        they will come directly from a brokerage (such as Interactive
        Brokers).
        """
        self._convert_fill_to_portfolio_update(fill_event)


    def _convert_fill_to_portfolio_update(self, fill_event):
            """
            Upon receipt of a FillEvent, the PortfolioHandler converts
            the event into a transaction that gets stored in the Portfolio
            object. This ensures that the broker and the local portfolio
            are "in sync".

            In addition, for backtesting purposes, the portfolio value can
            be reasonably estimated in a realistic manner, simply by
            modifying how the ExecutionHandler object handles slippage,
            transaction costs, liquidity and market impact.
            """

            # Create or modify the position from the fill info
            self.portfolios[fill_event.portfolio_id].transact_asset(
                fill_event.timestamp,
                fill_event.ticker,
                fill_event.action,  
                fill_event.quantity,
                fill_event.price,
                fill_event.commission
            )

    def update_portfolio_value(self):
        """
        Update the portfolio to reflect current market value as
        based on last bid/ask of each ticker.
        """
        # Update portfolio asset values
        for portfolio in self.portfolios:
            for ticker in self.portfolios[portfolio].pos_handler.positions:

                if self.price_handler.istick():
                    bid, ask = self.price_handler.get_best_bid_ask(ticker)
                else:
                    close_price = self.price_handler.get_last_close(ticker)
                    bid = close_price
                    ask = close_price

                mid_price = (bid + ask) / 2
                self.portfolios[portfolio].update_market_value_of_asset(
                    ticker, mid_price, self.current_dt
                )
    


    ### NEW
    def create_portfolio(self, portfolio_id, cash):
            """
            Create a new sub-portfolio with ID 'portfolio_id' and
            an optional name given by 'name'.

            Parameters
            ----------
            portfolio_id : `str`
                The portfolio ID string.
            name : `str`, optional
                The optional name string of the portfolio.
            """
            portfolio_id_str = str(portfolio_id)

            if portfolio_id_str in self.portfolios.keys():
                raise ValueError(
                    "Portfolio with ID '%s' already exists. Cannot create "
                    "second portfolio with the same ID." % portfolio_id_str
                )
            self.portfolios[portfolio_id_str] = Portfolio(
                portfolio_id_str, self.current_time, cash
                )


    def list_all_portfolios(self):
        """
        List all of the sub-portfolios associated with this
        broker account in order of portfolio ID.

        Returns
        -------
        `list`
            The list of portfolios associated with the broker account.
        """
        if self.portfolios == {}:
            return []
        return sorted(
            list(self.portfolios.values()),
            key=lambda port: port.portfolio_id
        )
    
    def get_portfolio_cash_balance(self, portfolio_id):
        """
        Retrieve the cash balance of a sub-portfolio, if
        it exists. Otherwise raise a ValueError.

        Parameters
        ----------
        portfolio_id : `str`
            The portfolio ID string.

        Returns
        -------
        `float`
            The cash balance of the portfolio.
        """
        if portfolio_id not in self.portfolios.keys():
            raise ValueError(
                "Portfolio with ID '%s' does not exist. Cannot "
                "retrieve cash balance for non-existent "
                "portfolio." % portfolio_id
            )
        return self.portfolios[portfolio_id].cash

    def portfolio_info(self):
        """
        Output the portfolio statistics information as a dictionary
        with portfolio id as keys and statistics as items.

        Returns
        -------
        `dict`
            The portfolio statistics.
        """
        info = {}
        for portfolio in self.portfolios.items():
            info[portfolio.portfolio_id] = {
                "total_market_value": portfolio.total_market_value,
                "total_equity": portfolio.total_equity,
                "total_unrealised_pnl": portfolio.total_unrealised_pnl,
                "total_realised_pnl": portfolio.total_realised_pnl,
                "total_pnl": portfolio.total_pnl
            }
        return info


