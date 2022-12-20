from numpy import sign
from ..outils.price_parser import PriceParser
import logging
logger = logging.getLogger()

class Position(object):
    """
    Handles the accounting of entering a new position in an
    Asset along with subsequent modifications via additional
    trades.

    The approach taken here separates the long and short side
    for accounting purposes. It also includes an unrealised and
    realised running profit & loss of the position.

    Parameters
    ----------
    ticker : `str`
        The Asset symbol string.
    action : `str`
        The market direction of the position e.g. 'BOT' or 'SLD' .
    current_price : `float`
        The initial price of the Position.
    current_time : `pd.Timestamp`
        The time at which the Position was created.
    buy_quantity : `int`
        The amount of the asset bought.
    sell_quantity : `int`
        The amount of the asset sold.
    avg_bought : `float`
        The initial price paid for buying assets.
    avg_sold : `float`
        The initial price paid for selling assets.
    buy_commission : `float`
        The commission spent on buying assets for this position.
    sell_commission : `float`
        The commission spent on selling assets for this position.
    """
    def __init__(
        self,
        ticker,
        action,
        current_price,
        current_time,
        buy_quantity,
        sell_quantity,
        avg_bought,
        avg_sold,
        buy_commission,
        sell_commission,
    ):
        self.ticker = ticker
        self.action = action

        self.current_price = current_price
        self.current_time = current_time 
        self.buy_quantity = buy_quantity
        self.sell_quantity = sell_quantity
        self.avg_bought = avg_bought
        self.avg_sold = avg_sold
        self.buy_commission = buy_commission
        self.sell_commission = sell_commission

        self.entry_date = current_time
        self.exit_date = None
    
    def __repr__(self):
        rep = ('%s, %s, %s'%(self.ticker, self.action, self.net_quantity))
        return rep

    @classmethod
    def open_new_position(cls, time, action, ticker, quantity, price, commission):
        """
        Depending upon whether the action was a buy or sell ("BOT"
        or "SLD") calculate the average bought cost, the total bought
        cost, the average price and the cost basis.

        Finally, calculate the net total with and without commission.
        """

        if action == "BOT":
            buy_quantity = quantity
            sell_quantity = 0
            avg_bought = price
            avg_sold = 0
            buy_commission = commission
            sell_commission = 0.0
        else:  # action == "SLD"
            buy_quantity = 0
            sell_quantity = quantity
            avg_bought = 0
            avg_sold = price
            buy_commission = 0.0
            sell_commission = commission
        
        return cls(
            ticker,
            action,
            price,
            time,
            buy_quantity,
            sell_quantity,
            avg_bought,
            avg_sold,
            buy_commission,
            sell_commission
        )


    @property
    def market_value(self):
        """
        Return the market value (respecting the direction) of the
        Position based on the current price available to the Position.

        Returns
        -------
        `float`
            The current market value of the Position.
        """
        return self.current_price * self.net_quantity

    @property
    def avg_price(self):
        """
        The average price paid for all assets on the long or short side.

        Returns
        -------
        `float`
            The average price on either the long or short side.
        """
        if self.net_quantity == 0:
            return 0.0
        elif self.action =='BOT':
            return (self.avg_bought * self.buy_quantity + self.buy_commission) / self.buy_quantity
        else: # action == "SLD"
            return (self.avg_sold * self.sell_quantity - self.sell_commission) / self.sell_quantity

    @property
    def net_quantity(self):
        """
        The difference in the quantity of assets bought and sold to date.

        Returns
        -------
        `int`
            The net quantity of assets.
        """
        return self.buy_quantity - self.sell_quantity

    @property
    def total_bought(self):
        """
        Calculates the total average cost of assets bought.

        Returns
        -------
        `float`
            The total average cost of assets bought.
        """
        return self.avg_bought * self.buy_quantity

    @property
    def total_sold(self):
        """
        Calculates the total average cost of assets sold.

        Returns
        -------
        `float`
            The total average cost of assets solds.
        """
        return self.avg_sold * self.sell_quantity

    @property
    def net_total(self):
        """
        Calculates the net total average cost of assets
        bought and sold.

        Returns
        -------
        `float`
            The net total average cost of assets bought
            and sold.
        """
        return self.total_sold - self.total_bought

    @property
    def commission(self):
        """
        Calculates the total commission from assets bought and sold.

        Returns
        -------
        `float`
            The total commission from assets bought and sold.
        """
        return self.buy_commission + self.sell_commission

    @property
    def net_incl_commission(self):
        """
        Calculates the net total average cost of assets bought
        and sold including the commission.

        Returns
        -------
        `float`
            The net total average cost of assets bought and
            sold including the commission.
        """
        return self.net_total - self.commission

    @property
    def realised_pnl(self):
        """
        Calculates the profit & loss (P&L) that has been 'realised' via
        two opposing asset transactions in the Position to date.

        Returns
        -------
        `float`
            The calculated realised P&L.
        """
        if self.action == 'BOT':
            if self.sell_quantity == 0:
                return 0.0
            else:
                return (
                    ((self.avg_sold - self.avg_bought) * self.sell_quantity) -
                    ((self.sell_quantity / self.buy_quantity) * self.buy_commission) -
                    self.sell_commission
                )
        elif self.action == 'SLD':
            if self.buy_quantity == 0:
                return 0.0
            else:
                return (
                    ((self.avg_sold - self.avg_bought) * self.buy_quantity) -
                    ((self.buy_quantity / self.sell_quantity) * self.sell_commission) -
                    self.buy_commission
                )
        else:
            return self.net_incl_commission

    @property
    def unrealised_pnl(self):
        """
        Calculates the profit & loss (P&L) that has yet to be 'realised'
        in the remaining non-zero quantity of assets, due to the current
        market price.

        Returns
        -------
        `float`
            The calculated unrealised P&L.
        """
        return (self.current_price - self.avg_price) * self.net_quantity

    @property
    def total_pnl(self):
        """
        Calculates the sum of the unrealised and realised profit & loss (P&L).

        Returns
        -------
        `float`
            The sum of the unrealised and realised P&L.
        """
        return self.realised_pnl + self.unrealised_pnl


    def update_current_price(self, market_price, time=None):
        """
        Updates the Position's awareness of the current market price
        of the Asset, with an optional timestamp.

        Parameters
        ----------
        market_price : `float`
            The current market price.
        time : `pd.Timestamp`, optional
            The optional timestamp of the current market price.
        """

        if market_price <= 0.0:
            raise ValueError(
                'Market price "%s" of asset "%s" must be positive to '
                'update the position.' % (market_price, self.ticker)
            )
        else:
            self.current_price = market_price
            self.current_time = time

    def transact_shares(self, time, ticker, action, quantity, price, commission):
        """
        Calculates the adjustments to the Position that occur
        once new shares are bought and sold.

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

        if self.ticker != ticker:
            raise ValueError(
                'Failed to update Position with asset %s when '
                'carrying out transaction in asset %s. ' % (
                    self.ticker, ticker))

        # Depending upon the direction of the transaction
        # ensure the correct calculation is called
        if action == 'BOT':
            self._transact_buy(
                quantity,
                price,
                commission
            )
        else:
            self._transact_sell(
                quantity, # TEST toltro il -1.0 * all inizio
                price,
                commission
            )

        # Update the current trade information
        self.update_current_price(price, time)
        self.current_time = time

    def _transact_buy(self, quantity, price, commission):
        """
        Handle the accounting for creating a new long leg for the
        Position.

        Parameters
        ----------
        quantity : `int`
            The additional quantity of assets to purchase.
        price : `float`
            The price at which this leg was purchased.
        commission : `float`
            The commission paid to the broker for the purchase.
        """
        self.avg_bought = ((self.avg_bought * self.buy_quantity) + (quantity * price)) / (self.buy_quantity + quantity)
        self.buy_quantity += quantity
        self.buy_commission += commission

    def _transact_sell(self, quantity, price, commission):
        """
        Handle the accounting for creating a new short leg for the
        Position.

        Parameters
        ----------
        quantity : `int`
            The additional quantity of assets to sell.
        price : `float`
            The price at which this leg was sold.
        commission : `float`
            The commission paid to the broker for the sale.
        """
        self.avg_sold = ((self.avg_sold * self.sell_quantity) + (quantity * price)) / (self.sell_quantity + quantity)
        self.sell_quantity += quantity
        self.sell_commission += commission