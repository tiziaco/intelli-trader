"""Bar feed package (M5-05, D-16) — the runtime market-data read model.

Re-exports the ``BarFeed`` ABC and the backtest implementation. The
bar-timing contract (rules 1-7) lives in the ``bar_feed`` module docstring —
the single written home of the engine's look-ahead invariant (M5-01).
"""

from .bar_feed import BacktestBarFeed
from .base import BarFeed

__all__ = [
    'BarFeed',
    'BacktestBarFeed',
]
