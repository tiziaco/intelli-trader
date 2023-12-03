from .base import AbstractStatistics

import os
from datetime import datetime

import pandas as pd
import numpy as np


from sqlalchemy import MetaData, Table, Column, DateTime
from sqlalchemy.dialects.postgresql import JSON

import logging
logger = logging.getLogger('TradingSystem')


class EngineLogger(AbstractStatistics):
    """
    The EngineLogger class keep track of the useful 
    information about the trading system.

    At the end of evry main loop of the engine it register 
    the datas about each portfolio. It also records transactions
    and closed positions when the execution handler generate fill
    events.

    Includes an equity curve, drawdown curve, monthly
    returns heatmap, yearly returns summary, strategy-
    level statistics and trade-level statistics.
    """
    def __init__(
        self, sql_engine = None, to_sql = False
    ):
        """
        Parameters
        ----------
        sql_engine: `object`
            The sql Postgres engine from the trading system engine
        
        to_sql: `boolean`
            Register or not the information in the SQL database
        """
        
        self.to_sql = to_sql
        self.sql_engine = sql_engine
        self.meta = None
        self._portfolio_table = None
        self.initialise_sql_tables()

        self.transaction_id = 0
        self.position_id = 0

        self.closed_positions = []
        self.transactions = []
        self.portfolio_metrics = {}
    
    def initialise_sql_tables(self):
        if self.sql_engine is not None:
            self.meta = MetaData(bind=self.sql_engine)
            # Create the performance table
            self._portfolio_table = Table("portfolios", self.meta,
                                Column('date', DateTime),
                                Column('metrics', JSON))
            self.meta.create_all(bind=self.sql_engine, checkfirst=True)


    def record_position(self, portfolio_id: str, last_close):
        """
        Record all details about the a closed position into the trade log 
        table in the SQL db or internal memory during a backtest.

        Parameters
        ----------
        portfolio_id: `str`
            ID of the portfolio where the position is closed
        last_close: `Position`
            Position object from the portfolio handler
        """
        closed_position = {
                'position_id' : self._position_id(),
                'portfolio_id': portfolio_id,
                'ticker': last_close.ticker,
                'action': last_close.action,
                'entry_date': last_close.entry_date,
                'exit_date': last_close.exit_date,
                'avg_price': last_close.avg_price,
                'avg_bought': last_close.avg_bought,
                'avg_sold': last_close.avg_sold,
                'buy_quantity': last_close.buy_quantity,
                'sell_quantity': last_close.sell_quantity,
                'total_bought': last_close.total_bought,
                'total_sold': last_close.total_sold,
                'tot_commissions': last_close.commission,
                'realised_pnl': last_close.realised_pnl
            }

        # Record the closed position in the SQL db or internal memory
        if self.to_sql:
            df = pd.DataFrame(closed_position, index=[0])
            df.to_sql('closed_positions', self.sql_engine, index = False, if_exists='append')
        else:
            self.closed_positions.append(closed_position)
    
    def record_transaction(self, fill):
        """
        Record all details about the FillEvent into the trade log 
        table in the SQL db or internal memory during a backtest.

        Parameters
        ----------
        fill: `FillEvent`
            FillEvent object from the execution handler
        """
        transaction = {
                'transaction_id': self._transaction_id(),
                'date':fill.time, #.strftime('%Y-%m-%d %H:%M:%S')
                'portfolio_id': fill.portfolio_id,
                'exchange': fill.exchange, 
                'ticker': fill.ticker,
                'direction': fill.direction,
                'action': fill.action, 
                'quantity': fill.quantity, 
                'price': round(fill.price, 4),
                'commission': round(fill.commission, 4)
            }

        # Record transaction details in the SQL db or internal memory
        if self.to_sql:
            df = pd.DataFrame(transaction, index=[0])
            df.to_sql('trades', self.sql_engine, index = False, if_exists='append')
        else:
            self.transactions.append(transaction)


    def record_portfolios_metrics(self, time: pd.Timestamp, portfolio_info: dict):
        """
        Record the equity curve, invested amount, available and the 
        realised pnl at a defined timestamp.

        Parameters
        ----------
        time: `TimeStamp`
            Time of the event when storing the data

        portfolio_info: `dict`
            Dictionary containing the portfolio metrics (market value, available cash, tot equity, etc...)
            for every portfolio
        """

        if self.to_sql:
            # Store the metrics in the SQL db
            with self.sql_engine.begin() as connection:
                statement = self._portfolio_table.insert().values(
                    date = time,
                    metrics = portfolio_info
                )
                connection.execute(statement)
        else:
            # Store the metrics in the internal dictionary
            self.portfolio_metrics[time] = portfolio_info
    
    def delete_all_tables(self):
        """
        Delete all the tables in the system database.
        """
        # Reflect the existing tables from the database
        self.meta.reflect()

        # Drop all tables
        self.meta.drop_all()

        # Create new empty portfolio mertrics table
        self.initialise_sql_tables()

        logger.info('   ENGINE LOGGER: Sql tables deleted')
    
    def _transaction_id(self): 
        """
        Generate a transaction ID
        """
        self.transaction_id += 1
        return self.transaction_id
    
    def _position_id(self):
        """
        Generate a position ID
        """
        self.position_id += 1
        return self.position_id

