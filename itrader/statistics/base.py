from abc import ABCMeta, abstractmethod

import pickle


class AbstractStatistics(object):
    """
    Statistics is an abstract class providing an interface for
    all inherited statistic classes (live, historic, custom, etc).

    The goal of a Statistics object is to keep a record of useful
    information about one or many trading strategies as the strategy
    is running. This is done by hooking into the main event loop and
    essentially updating the object according to portfolio performance
    over time.

    Ideally, Statistics should be subclassed according to the strategies
    and timeframes-traded by the user. Different trading strategies
    may require different metrics or frequencies-of-metrics to be updated,
    however the example given is suitable for longer timeframes.
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def print_summary(self, statistics):
        """
        Print a summury with the main statistics of the backtest.
        """
        print("---------------------------------------------------------")
        print("Backtest complete.")
        print("---------------------------------------------------------")
        print("Return: %0.2f%%" % (statistics['equity_stats']['tot_ret']*100))
        print("Trades: %s (%0.2f%%)" % (statistics['trade_stats']['trades'], statistics['trade_stats']['win_pct']*100))
        print("Sharpe Ratio: %0.2f" % statistics['equity_stats']['sharpe'])
        print("Max Drawdown: %0.2f%%" % (
                statistics['equity_stats']['max_drawdown_pct']*100.0))
        

    @abstractmethod
    def update(self):
        """
        Update all the statistics according to values of the portfolio
        and open positions. This should be called from within the
        event loop.
        """
        raise NotImplementedError("Should implement update()")

    @abstractmethod
    def get_results(self):
        """
        Return a dict containing all statistics.
        """
        raise NotImplementedError("Should implement get_results()")

    @abstractmethod
    def plot_results(self):
        """
        Plot all statistics collected up until 'now'
        """
        raise NotImplementedError("Should implement plot_results()")

    @abstractmethod
    def save(self, filename):
        """
        Save statistics results to filename
        """
        raise NotImplementedError("Should implement save()")

    @classmethod
    def load(cls, filename):
        with open(filename, 'rb') as fd:
            stats = pickle.load(fd)
        return stats


def load(filename):
    return AbstractStatistics.load(filename)
