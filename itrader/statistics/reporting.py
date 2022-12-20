from .base import AbstractStatistics
from ..outils.price_parser import PriceParser

import os
from datetime import datetime

import pandas as pd
import numpy as np

import qstrader.statistics.performance as perf
from qstrader.compliance import SqlCompliance


import sqlalchemy 
from sqlalchemy import Column, Integer, Text
from sqlalchemy.dialects.postgresql import JSON


class StatisticsReporting(AbstractStatistics):
    """
    Displays a Matplotlib-generated 'one-pager' as often
    found in institutional strategy performance reports.

    Includes an equity curve, drawdown curve, monthly
    returns heatmap, yearly returns summary, strategy-
    level statistics and trade-level statistics.

    Also includes an optional annualised rolling Sharpe
    ratio chart.
    """
    def __init__(
        self, engine, config, portfolio_handler,
        benchmark=None, periods=252, to_sql=False
    ):
        """
        Takes in a portfolio handler.
        """
        self.engine = engine
        self.config = config
        self.meta = sqlalchemy.MetaData(self.engine)
        self.portfolio_handler = portfolio_handler
        self.price_handler = portfolio_handler.price_handler
        self.benchmark = benchmark
        self.periods = periods # TODO: usato in rolling sharpe. da cambiare
        self.report={'Date':['positions', 'invested', 'equity','realised_pnl', 'cash']}
        self.statistics={}
        self.equity_benchmark = {'Date':['equity']}
        self.log_scale = False
        self.to_sql = to_sql #TODO da finire



    def update(self, timestamp):
        """
        Update equity curve, benchmark equity curve and cash that must be 
        tracked over time.
        """
        """
        self.equity[timestamp] = PriceParser.display(
            self.portfolio_handler.portfolio.equity)
        self.cash[timestamp] = PriceParser.display(
            self.portfolio_handler.portfolio.cur_cash)"""
        
        # Calculate the invested amount at the current timestamp
        invested=0
        for ticker in self.portfolio_handler.portfolio.positions.keys():
            pos = self.portfolio_handler.portfolio.positions[ticker]
            invested += PriceParser.display(pos.init_price) * pos.quantity
        
        # Save the data in the "report" dictionary
        tmp=[
            len(self.portfolio_handler.portfolio.positions), invested,
            PriceParser.display(self.portfolio_handler.portfolio.equity),
            PriceParser.display(self.portfolio_handler.portfolio.realised_pnl),
            PriceParser.display(self.portfolio_handler.portfolio.cur_cash)
            ]
        
        if self.to_sql:
            # Store the data in the "portfolio" SQL db
            SqlCompliance.record_portfolio(timestamp, tmp)
        else:
            # Store the data in the "report" dictionary
            self.report[timestamp] = tmp
        
        # Calculate the equiy line for the benchmark
        if self.benchmark is not None:
            self.equity_benchmark[timestamp] = PriceParser.display(
                self.price_handler.get_last_close(self.benchmark)
            )


    def _prepare_data(self, mydict):
        """
        Convert and format the data for the statistic calculations.
        Not used in Live trading
        Parameters:
        dict - Dictionary with the equity line.

        Returns:
        df - Pandas DataFrame with returns, cum_returns and drawdowns.
        """
        df=pd.DataFrame(mydict).T
        df.columns = df.iloc[0]
        df = df.iloc[1:]
        df['returns'] = df['equity'].pct_change().fillna(0.0)
        df['cum_returns'] = np.exp(np.log(1 + df['returns']).cumsum())
        df['drawdowns'] = perf.calculate_drawdowns(df['cum_returns'])
        return df
    
    def _equity_statistics(self, df):
        ### Equity statistics
        #TODO aggiungere volatility
        # max drawdown, max drawdown duration
        max_dd, dd_dur = perf.calculate_max_drawdowns(df[['drawdowns']])

        statistics = {}
        statistics['tot_ret'] = df['cum_returns'][-1] - 1.0
        statistics['sharpe'] = perf.create_sharpe_ratio(df['returns'], self.periods)
        statistics['sortino'] = perf.create_sortino_ratio(df['returns'], self.periods)
        statistics['cagr'] = perf.create_cagr(df['cum_returns'], self.periods)
        statistics['rsq'] = perf.rsquared(range(df['cum_returns'].shape[0]), df['cum_returns'])
        statistics['max_drawdown_pct'] = max_dd
        statistics['max_drawdown_duration'] = dd_dur
        return statistics

    def _trade_statistics(self):
        ### Trades statistics
        #TODO aggiungere stats separate per long e short
        pos = self._get_positions()
        trade_statistics={}
        if pos is not None:
            trade_statistics={
                'trades' : pos.shape[0],
                'win_pct' : pos[pos["trade_pct"] > 0].shape[0] / float(pos.shape[0]),
                'avg_trd_pct' : np.mean(pos["trade_pct"]),
                'avg_win_pct' : np.mean(pos[pos["trade_pct"] > 0]["trade_pct"]),
                'avg_loss_pct' : np.mean(pos[pos["trade_pct"] <= 0]["trade_pct"]),
                'max_win_pct' : np.max(pos["trade_pct"]),
                'max_loss_pct' : np.min(pos["trade_pct"])}
        return trade_statistics
    
    def _temporal_statistics(self, df):
        ### Temporal statistics
        mly_ret = perf.aggregate_returns(df['returns'], 'monthly')
        yly_ret = perf.aggregate_returns(df['returns'], 'yearly')
        temporal_statistics={
            'mly_pct' : mly_ret[mly_ret >= 0].shape[0] / float(mly_ret.shape[0]),
            'mly_avg_win_pct' : np.mean(mly_ret[mly_ret >= 0]),
            'mly_avg_loss_pct' : np.mean(mly_ret[mly_ret < 0]),
            'mly_max_win_pct' : np.max(mly_ret),
            'mly_max_loss_pct' : np.min(mly_ret),
            'yly_pct' : yly_ret[yly_ret >= 0].shape[0] / float(yly_ret.shape[0]),
            'yly_max_win_pct' : np.max(yly_ret),
            'yly_max_loss_pct' : np.min(yly_ret)}
        if temporal_statistics['mly_avg_win_pct'] is np.nan:
            temporal_statistics['mly_avg_win_pct'] = 0
        return temporal_statistics


    def get_results(self):
        """
        Return a dict with all important statistics. Runned at the
        end of the backtest in 'trading_session.py'
        """
               
        ### Equity statistics
        # Strategy stats
        strategy = self._prepare_data(self.report)
        self.statistics['equity_stats'] = self._equity_statistics(strategy)

        # Benchmark stats
        if self.benchmark is not None:
            bck = self._prepare_data(self.equity_benchmark)
            self.statistics['equity_bck_stats'] = self._equity_statistics(bck)
        else: bck=None

        ### Trades statistics
        self.statistics['trade_stats'] = self._trade_statistics()
        
        ### Temporal statistics
        self.statistics['temporal_stats'] = self._temporal_statistics(strategy)
        
        
         ### Rolling statistics
         #TODO da finire
        """
        # Rolling Annualised Sharpe
        rolling = df['returns'].rolling(window=self.periods)
        rolling_sharpe_s = np.sqrt(self.periods) * (
            rolling.mean() / rolling.std()
        )
        """

        ### Export the data
        self._to_sql(strategy, bck)
        

    
    def _to_sql(self, strategy, bck):

        ### Backtest Performance statistics (sharpe, drawdown, trades, win trades, etc...)
        # Delete previous performance table
        query = f'DROP TABLE IF EXISTS performance;'
        result = self.engine.execute(query)

        # Create table if it doesn't exist
        stats_table=sqlalchemy.Table("performance", self.meta,  
                Column('strategy', Text), #TODO: da integrare per ottimizazione
                Column('statistics', JSON))
        self.meta.create_all()

        # Store statistics
        statement = stats_table.insert().values(
            strategy="backtest",
            statistics=self.statistics
            )
        self.engine.execute(statement)

        ### Portfolio equity, cash, drawdowns, cum returns, invested, realised_pnl
        strategy.to_sql('strategy', self.engine, index = True, if_exists='replace')

        ### Benchmark equity, cumilative returns, drawdowns
        if bck is not None:
            bck.to_sql('benchmark', self.engine, index = True, if_exists='replace')

        ### Closed positions history
        df=self._get_positions()
        df.to_sql('positions', self.engine, index = True, if_exists='replace')



    def _get_positions(self):
        """
        Retrieve the list of closed Positions objects from the portfolio
        and reformat into a pandas dataframe to be returned
        """
        def x(p):
            return PriceParser.display(p)

        pos = self.portfolio_handler.portfolio.closed_positions
        a = []
        for p in pos:
            a.append(p.__dict__)
        if len(a) == 0:
            # There are no closed positions
            return None
        else:
            df = pd.DataFrame(a)
            df['avg_bot'] = df['avg_bot'].apply(x)
            df['avg_price'] = df['avg_price'].apply(x)
            df['avg_sld'] = df['avg_sld'].apply(x)
            df['cost_basis'] = df['cost_basis'].apply(x)
            df['init_commission'] = df['init_commission'].apply(x)
            df['init_price'] = df['init_price'].apply(x)
            df['market_value'] = df['market_value'].apply(x)
            df['net'] = df['net'].apply(x)
            df['net_incl_comm'] = df['net_incl_comm'].apply(x)
            df['net_total'] = df['net_total'].apply(x)
            df['realised_pnl'] = df['realised_pnl'].apply(x)
            df['total_bot'] = df['total_bot'].apply(x)
            df['total_commission'] = df['total_commission'].apply(x)
            df['total_sld'] = df['total_sld'].apply(x)
            df['unrealised_pnl'] = df['unrealised_pnl'].apply(x)
            df['trade_pct'] = (df['avg_sld'] / df['avg_bot'] - 1.0)
            return df

