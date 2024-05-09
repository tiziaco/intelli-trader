from .base import AbstractStatistics

import os
from datetime import datetime

import pandas as pd
import numpy as np

import itrader.reporting.performance as perf
import itrader.reporting.plots as plots


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
		self, engine_logger, sql_engine=None, 
		periods=355, to_sql=False
	):
		"""
		Takes in a portfolio handler.
		"""
		#self.sql_engine = sql_engine
		#self.meta = sqlalchemy.MetaData(self.engine)
		self.engine_logger = engine_logger
		self.periods = periods
		self.prices = None
		self.transaction = None
		self.positions = None
		self.portfolio_metrics = None
		self.statistics={}
		self.log_scale = False
		self.to_sql = to_sql #TODO da finire



	def _prepare_data(self):
		"""
		Convert and format the data for the statistic calculations.
		Not used in Live trading
		"""
		# Create transactions DataFrame
		self.transaction = pd.DataFrame(self.engine_logger.transactions).set_index('transaction_id')

		# Create positions DataFrame
		self.positions = pd.DataFrame(self.engine_logger.closed_positions).set_index('position_id')
		# Calculate the return and duration for each position
		self.positions['trade_return'] = (self.positions.total_sold / self.positions.total_bought)-1
		self.positions['duration'] = self.positions['exit_date'] - self.positions['entry_date']

		# Create portfolio metrics dictionary
		port_metrics = self.engine_logger.portfolio_metrics
		self.portfolio_metrics = pd.concat({k: pd.DataFrame(v) for k, v in port_metrics.items()}, axis=1).T
		self.portfolio_metrics.index.set_names(['date','portfolio_id'], inplace=True)

	
	def _equity_statistics(self, portfolio_id):
		### Equity statistics

		# Slice the portfolio_metrics DataFrame according to the portfolio_id
		df = self.portfolio_metrics.loc[:,portfolio_id,:]

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

	def _trade_statistics(self, portfolio_id):
		### Trades statistics

		# Slice the portfolio_metrics DataFrame according to the portfolio_id
		df = self.positions[self.positions.portfolio_id == portfolio_id]

		# Calculate the return for each trade
		# df['trade_return'] = (df.total_sold / df.total_bought)-1

		trade_statistics={}
		if df is not None:
			trade_statistics={
				'trades' : df.shape[0],
				'win_pct' : df[df["trade_return"] > 0].shape[0] / float(df.shape[0]),
				'long_trades' : len(df[(df['action'] == 'BOT')]),
				'long_win_pct' : perf.long_trades_win_pct(df),
				'short_trades' : len(df[(df['action'] == 'SLD')]),
				'short_win_pct': perf.short_trades_win_pct(df),
				'profict_factor': perf.calculate_profict_factor(df),
				'avg_trd_pct' : np.mean(df["trade_return"]),
				'avg_win_pct' : np.mean(df[df["trade_return"] > 0]["trade_return"]),
				'avg_loss_pct' : np.mean(df[df["trade_return"] <= 0]["trade_return"]),
				'max_win_pct' : np.max(df["trade_return"]),
				'max_loss_pct' : np.min(df["trade_return"])}
		#TODO aggiungere stats separate per long e short
		return trade_statistics
	
	def _temporal_statistics(self, portfolio_id):
		### Temporal statistics

		# Slice the portfolio_metrics DataFrame according to the portfolio_id
		df = self.portfolio_metrics.loc[:,portfolio_id,:]

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


	def calculate_statistics(self):
		"""
		Return a dict with all important statistics. Runned at the
		end of the backtest in 'trading_session.py'
		"""
		self._prepare_data()

		for portfolio_id in self.positions.portfolio_id.unique():

			### Equity statistics
			self.statistics.setdefault(portfolio_id,{})['equity_stats'] = self._equity_statistics(portfolio_id)

			### Trades statistics
			self.statistics[portfolio_id]['trade_stats'] = self._trade_statistics(portfolio_id)
			
			### Temporal statistics
			self.statistics[portfolio_id]['temporal_stats'] = self._temporal_statistics(portfolio_id)
		
		
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
		#self._to_sql(strategy)
	
	def print_summary(self, portfolio_id = '01'):
		"""
		Print a summury with the main statistics of the backtest.
		"""
		self.calculate_statistics()
		statistics = self.statistics[portfolio_id]
		positions = self.positions[self.positions.portfolio_id == portfolio_id]
		start_dt = list(self.prices.values())[0].index[0].strftime('%Y/%m/%d, %H:%M')
		end_dt = list(self.prices.values())[0].index[-1].strftime('%Y/%m/%d, %H:%M')
		
		print("---------------------------------------------------------")
		print("                 STRATEGY STATISTICS")
		print("---------------------------------------------------------")
		print('Start date: %s', start_dt)
		print('End date: %s', (end_dt))
		print("Bars: %s",(len(list(self.prices.values())[0])))
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
		
	def plot_charts(self, portfolio_id = '01'):
		# Filter data
		df = self.portfolio_metrics.loc[:,portfolio_id,:]
		positions = self.positions[self.positions.portfolio_id == portfolio_id]
		# Preprocess the equity line adding returns, cum_returns and drawdown
		df['returns'] = df['total_equity'].pct_change().fillna(0.0)
		df['cum_returns'] = np.exp(np.log(1 + df['returns']).cumsum())
		df['drawdowns'] = perf.calculate_drawdowns(df['cum_returns'])

		eq_line = plots.line_equity(df['cum_returns'])
		dd_line = plots.line_drwdwn(df['drawdowns'])
		profit_loss = plots.profit_loss_scatter(positions, list(self.prices.values())[0].index)

		return plots.sub_plots3(eq_line, dd_line, profit_loss)
	
	def plot_signals(self, ticker, portfolio_id = '01'):
		transactions = self.transaction[(self.transaction.portfolio_id == portfolio_id) &
										 (self.transaction.ticker == ticker)]
		return plots.signals_plot(self.prices[ticker], transactions)
	
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

