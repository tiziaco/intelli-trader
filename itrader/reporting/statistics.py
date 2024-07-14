from .base import AbstractStatistics

import os
from datetime import datetime

import pandas as pd
import numpy as np

import itrader.reporting.performance as perf
import itrader.reporting.plots as plots
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.price_handler.data_provider import PriceHandler


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
	def __init__(self,
			portfolio_handler: PortfolioHandler, 
			price_handler: PriceHandler, 
			periods=355, to_sql=False
	):
		"""
		Takes in a portfolio handler.
		"""
		self.portfolio_handler = portfolio_handler
		self.price_handler = price_handler
		self.periods = periods
		# self.transaction = None
		# self.positions = None
		# self.portfolio_metrics = None
		self.statistics={}
		self.log_scale = False



	def _prepare_data(self, portfolio: Portfolio):
		"""
		Convert and format the data for the statistic calculations.
		Not used in Live trading
		"""
		# Create transactions DataFrame
		transactions_list = [t.to_dict() for t in portfolio.transactions]
		transactions = pd.DataFrame(transactions_list).set_index('transaction_id')

		# Create positions DataFrame
		positions_list = [t.to_dict() for t in portfolio.closed_positions]
		positions = pd.DataFrame(positions_list) #.set_index('position_id')
		# Calculate the return and duration for each position
		positions['trade_return'] = (positions.total_sold / positions.total_bought) - 1
		positions['duration'] = positions['exit_date'] - positions['entry_date']

		# Create portfolio metrics dictionary
		# equity_metrics = portfolio.metrics
		equity_metrics = pd.DataFrame.from_dict(portfolio.metrics, orient='index')
		# equity_metrics.index.set_names(['date','portfolio_id'], inplace=True)

		return transactions, positions, equity_metrics

	
	def _equity_statistics(self, equity_metrics: pd.DataFrame):
		### Equity statistics

		df = equity_metrics

		# Preprocess the equity line adding returns, cum_returns and drawdown
		df['returns'] = df['total_equity'].pct_change().fillna(0.0)
		df['cum_returns'] = np.exp(np.log(1 + df['returns']).cumsum())
		df['drawdowns'] = perf.calculate_drawdowns(df['cum_returns'])

		max_dd, dd_dur = perf.calculate_max_drawdowns(df[['drawdowns']])

		statistics = {}
		statistics['tot_ret'] = df['cum_returns'][-1] - 1.0
		statistics['sharpe'] = perf.create_sharpe_ratio(df['returns'], self.periods)
		statistics['sortino'] = perf.create_sortino_ratio(df['returns'], self.periods)
		statistics['cagr'] = perf.create_cagr(df['cum_returns'], self.periods)
		statistics['rsq'] = perf.rsquared(range(df['cum_returns'].shape[0]), df['cum_returns'])
		statistics['max_drawdown_pct'] = max_dd
		statistics['max_drawdown_duration'] = dd_dur
		#TODO aggiungere volatility
		return statistics

	def _trade_statistics(self, positions: pd.DataFrame):
		### Trades statistics

		df = positions

		# Calculate the return for each trade
		# df['trade_return'] = (df.total_sold / df.total_bought)-1

		trade_statistics={}
		if df is not None:
			trade_statistics={
				'trades' : df.shape[0],
				'win_pct' : df[df["trade_return"] > 0].shape[0] / float(df.shape[0]),
				'long_trades' : len(df[(df['side'] == 'LONG')]),
				'long_win_pct' : perf.long_trades_win_pct(df),
				'short_trades' : len(df[(df['side'] == 'SHORT')]),
				'short_win_pct': perf.short_trades_win_pct(df),
				'profict_factor': perf.calculate_profict_factor(df),
				'avg_trd_pct' : np.mean(df["trade_return"]),
				'avg_win_pct' : np.mean(df[df["trade_return"] > 0]["trade_return"]),
				'avg_loss_pct' : np.mean(df[df["trade_return"] <= 0]["trade_return"]),
				'max_win_pct' : np.max(df["trade_return"]),
				'max_loss_pct' : np.min(df["trade_return"])}
		#TODO aggiungere stats separate per long e short
		return trade_statistics
	
	def _temporal_statistics(self, equity_metrics: pd.DataFrame):
		### Temporal statistics

		# Slice the portfolio_metrics DataFrame according to the portfolio_id
		df = equity_metrics

		# Preprocess the equity line adding returns
		df['returns'] = df['total_equity'].pct_change().fillna(0.0)
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


	def calculate_statistics(self, positions, equity_metrics):
		"""
		Return a dict with all important statistics. Runned at the
		end of the backtest in 'trading_session.py'
		"""
		

		statistics={}
		### Equity statistics
		statistics['equity_stats'] = self._equity_statistics(equity_metrics)

		### Trades statistics
		statistics['trade_stats'] = self._trade_statistics(positions)
		
		### Temporal statistics
		statistics['temporal_stats'] = self._temporal_statistics(equity_metrics)
		
		 ### Rolling statistics
		 #TODO da finire
		"""
		# Rolling Annualised Sharpe
		rolling = df['returns'].rolling(window=self.periods)
		rolling_sharpe_s = np.sqrt(self.periods) * (
			rolling.mean() / rolling.std()
		)
		"""

		return statistics
	
	def print_summary(self, portfolio_id: int = 1):
		"""
		Print a summury with the main statistics of the backtest.
		"""
		portfolio = self.portfolio_handler.get_portfolio(portfolio_id)
		transactions, positions, equity_metrics = self._prepare_data(portfolio)
		statistics = self.calculate_statistics(positions, equity_metrics)

		start_dt = list(self.price_handler.prices.values())[0].index[0].strftime('%Y/%m/%d, %H:%M')
		end_dt = list(self.price_handler.prices.values())[0].index[-1].strftime('%Y/%m/%d, %H:%M')
		
		print("---------------------------------------------------------")
		print("                 STRATEGY STATISTICS")
		print("---------------------------------------------------------")
		print('Start date: %s', start_dt)
		print('End date: %s', (end_dt))
		print("Bars: %s",(len(list(self.price_handler.prices.values())[0])))
		print('')
		print("Return: %0.2f%%" % (statistics['equity_stats']['tot_ret']*100))
		print("Sharpe Ratio: %0.2f" % statistics['equity_stats']['sharpe'])
		print("Sortino Ratio: %0.2f" % statistics['equity_stats']['sortino'])
		print("CAGR: %0.2f" % statistics['equity_stats']['cagr'])
		print("Max Drawdown: %0.2f%%" % (statistics['equity_stats']['max_drawdown_pct']*100))
		print("Max Drawdown Duration: %s " % (statistics['equity_stats']['max_drawdown_duration']))
		print('')
		print("Trades: %s (%0.2f%%)" % (statistics['trade_stats']['trades'], statistics['trade_stats']['win_pct']*100))
		print("Profict factor: %s" % round(statistics['trade_stats']['profict_factor'],2))
		print("Long trades: %s (%0.2f%%)" % (statistics['trade_stats']['long_trades'], statistics['trade_stats']['long_win_pct']*100))
		print("Short trades: %s (%0.2f%%)" % (statistics['trade_stats']['short_trades'], statistics['trade_stats']['short_win_pct']*100))
		print("Best Trade: %0.2f%%" % (statistics['trade_stats']['max_win_pct']*100))
		print("Worst Trade %0.2f%%"  % (statistics['trade_stats']['max_loss_pct']*100))
		print("Avg. Trade: %0.2f%%" % (statistics['trade_stats']['avg_trd_pct']*100))
		print("Avg. Win: %0.2f%%" % (statistics['trade_stats']['avg_win_pct']*100))
		print("Avg. Loss: %0.2f%%" % (statistics['trade_stats']['avg_loss_pct']*100))
		print("Avg. duration: %s" % np.mean(positions.duration))
		print("Max. duration: %s" % max(positions.duration))
		
	def plot_charts(self, portfolio_id = 1):
		portfolio = self.portfolio_handler.get_portfolio(portfolio_id)
		transactions, positions, equity_metrics = self._prepare_data(portfolio)

		# Preprocess the equity line adding returns, cum_returns and drawdown
		equity_metrics['returns'] = equity_metrics['total_equity'].pct_change().fillna(0.0)
		equity_metrics['cum_returns'] = np.exp(np.log(1 + equity_metrics['returns']).cumsum())
		equity_metrics['drawdowns'] = perf.calculate_drawdowns(equity_metrics['cum_returns'])

		eq_line = plots.line_equity(equity_metrics['cum_returns'])
		dd_line = plots.line_drwdwn(equity_metrics['drawdowns'])
		profit_loss = plots.profit_loss_scatter(positions, list(self.price_handler.prices.values())[0].index)

		return plots.sub_plots3(eq_line, dd_line, profit_loss)
	
	def plot_signals(self, ticker, portfolio_id = 1):
		portfolio = self.portfolio_handler.get_portfolio(portfolio_id)
		transactions, positions, equity_metrics = self._prepare_data(portfolio)
		transactions = transactions[transactions.ticker == ticker]
		return plots.signals_plot(self.price_handler.get_bars(ticker), transactions)
	
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

