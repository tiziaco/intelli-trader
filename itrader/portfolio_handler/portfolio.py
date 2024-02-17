import numpy as np
from datetime import datetime

from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.position import Position, PositionSide

from itrader import logger, idgen

TOLERANCE = 1e-3

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

    def __init__(self, user_id: int, name: str, cash: float, time: datetime):
        """
        Initialise the Portfolio object with a PositionHandler,
        along with cash balance.
        """
        self.user_id = user_id
        self.portfolio_id = idgen.generate_portfolio_id()
        self.name = name
        self.cash = cash
        self.creation_time = time
        self.current_time = time
        self.transactions = {}
        self.positions = {}
        self.closed_positions = []
        self.transaction_history = []

    @property
    def total_market_value(self):
        """
        Obtain the total market value of the portfolio excluding cash.
        """
        return sum(
            pos.market_value
            for ticker, pos in self.positions.items()
        )

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
        return sum(
            pos.unrealised_pnl
            for ticker, pos in self.positions.items()
        )

    @property
    def total_realised_pnl(self):
        """
        Calculate the sum of all the positions' realised P&Ls.
        """
        return sum(
            pos.realised_pnl
            for ticker, pos in self.positions.items()
        )

    @property
    def total_pnl(self):
        """
        Calculate the sum of all the positions' total P&Ls.
        """
        return sum(
            pos.total_pnl
            for ticker, pos in self.positions.items()
        )

    def process_transaction(self, transaction: Transaction):
        time = transaction.time
        ticker = transaction.ticker
        price = transaction.price

        # Retrieve open position for the asset's ticker
        open_position: Position = self.positions.get(ticker)

        if open_position:
            # Update existing position for buy transaction
            open_position.update_current_price_time(price, time)
            transaction_cost = self.calculate_transaction_cost(transaction, open_position)
            open_position.update_position(transaction)
            transaction.position_id = open_position.id
            # Check if position should be closed
            if np.isclose(open_position.net_quantity, 0, atol=TOLERANCE):
                open_position.close_position(price, time)
                self.closed_positions.append(open_position)
                del self.positions[ticker]
        else:
            # Create a new long position for the trading pair
            open_position = Position.open_position(transaction)
            transaction_cost = self.calculate_transaction_cost(transaction, None)
            transaction.position_id = open_position.id
            self.positions[ticker] = open_position

        # Calculate transaction cost
        # transaction_cost = self.calculate_transaction_cost(transaction, open_position)
        # Update portfolio cash
        self.cash += transaction_cost

    @staticmethod
    def calculate_transaction_cost(transaction: Transaction, open_position: Position) -> float:
        if not open_position:
            price = transaction.price
            quantity = transaction.quantity
            commission = transaction.commission
            transaction_cost = -round((price * quantity) + commission, 2)
        else:
            if (open_position.side == PositionSide.LONG and transaction.type == TransactionType.BUY) | \
                (open_position.side == PositionSide.SHORT and transaction.type == TransactionType.SELL):
                price = transaction.price
                quantity = transaction.quantity
                commission = transaction.commission
                transaction_cost = -round((price * quantity) + commission, 2)
            else:
                avg_price = open_position.avg_price
                quantity = transaction.quantity
                # Calculate the total cost including commissions
                total_cost_incl_commission = open_position.net_incl_commission
                # Calculate the realized profit or loss
                realized_pnl = open_position.realised_pnl
                # Deduct the realized profit or loss from the total cost
                transaction_cost = total_cost_incl_commission - realized_pnl + avg_price * quantity
        return transaction_cost

    def update_market_value_of_asset(self, ticker, current_price, current_dt):
        """
        Updates the value of all positions that are currently open.
        """
        if ticker not in self.positions:
            return
        self.positions[ticker].update_current_price_time(
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
        for ticker, pos in self.positions.items():
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
        for pos in self.closed_positions:
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
