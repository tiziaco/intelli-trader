from abc import ABC
from typing import Any

import pickle


class AbstractStatistics(ABC):
    """
    Statistics is an abstract class providing an interface for
    all inherited statistic classes (live, historic, custom, etc).

    The goal of a Statistics object is to keep a record of useful
    information about one or many trading strategies as the strategy
    is running. This is done by hooking into the main event loop and
    essentially updating the object according to portfolio performance
    over time.

    Real ABC (D-07): the dead ``__metaclass__ = ABCMeta`` Py2 no-op is removed.
    The interface methods are intentionally NOT marked ``@abstractmethod`` —
    the concrete reporters (``StatisticsReporting``, ``EngineLogger``) implement
    only a subset, and reconciling the compute/presentation split is the
    deferred reporting rework (M5b #38). Minimal conformance only.
    """

    def print_summary(self, statistics: dict[str, Any]) -> None:
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
        

    def update(self) -> None:
        """
        Update all the statistics according to values of the portfolio
        and open positions. This should be called from within the
        event loop.
        """
        raise NotImplementedError("Should implement update()")

    def get_results(self) -> dict[str, Any]:
        """
        Return a dict containing all statistics.
        """
        raise NotImplementedError("Should implement get_results()")

    def plot_results(self) -> None:
        """
        Plot all statistics collected up until 'now'
        """
        raise NotImplementedError("Should implement plot_results()")

    def save(self, filename: str) -> None:
        """
        Save statistics results to filename
        """
        raise NotImplementedError("Should implement save()")

    @classmethod
    def load(cls, filename: str) -> Any:
        with open(filename, 'rb') as fd:
            stats = pickle.load(fd)
        return stats


def load(filename: str) -> Any:
    return AbstractStatistics.load(filename)
